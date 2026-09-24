"""Scheduled NFL/NBA prop evaluation. External data stays outside graph logic."""
from __future__ import annotations
import argparse
import asyncio
import json
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import isfinite
from zoneinfo import ZoneInfo
import httpx
import structlog
from sportsbet.config import settings
from sportsbet.dashboard import publish_snapshot, load_snapshot
from sportsbet.db.connection import create_async_pool
from sportsbet.graph.graph import create_graph
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, parse_event_quotes, write_player_prop_snapshots
from sportsbet.ledger import Ledger
from sportsbet.model_contract import MODEL_VERSION
from sportsbet.prop.agents import make_prop_quant_agent
from sportsbet.prop.availability import (blocks_unadjusted_teammate_context,
                                         fetch_event_availability, player_availability, nfl_roster_history_bindings)
from sportsbet.prop.injury_context import historical_availability_splits, relevant_availability_reports
from sportsbet.prop.ngs_evidence import load_ngs_evidence
from sportsbet.arbitrage.ev import compute_expected_return, quote_terms
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.prop.cross_venue import PROP_MARKETS, screen as screen_cross_venue, screen_sportsbooks
from sportsbet.prop.probability import outcome_interval_for_side
from sportsbet.picks import LOCK_BEFORE_START, build_pick_board
from sportsbet.provider_cache import CachedResponse, ProviderResponseCache
from sportsbet.quant.shadow_inputs import normalize_source_timestamps
from sportsbet.quant.vig import american_to_raw_prob
from sportsbet.quant.market_baseline import paired_market_baseline
from sportsbet.quant.history_shadow import VERSION as SHADOW_VERSION, POLICY as SHADOW_POLICY, load_histories, shadow_record

log = structlog.get_logger()

MARKETS = PROP_MARKETS
SPORT_KEYS = {'nba':'basketball_nba','nfl':'americanfootball_nfl','cfb':'americanfootball_ncaaf'}
MODEL_SPORTS = frozenset({'nba','nfl','cfb'})
MAX_MODEL_CONCURRENCY = 8
FORECAST_HORIZON_HOURS = 48
RECOMMENDATION_POLICY_VERSION = 'confidence-floor-v2'
PROVIDER_CACHE_TTL = timedelta(minutes=5)
# Leave a full scheduler hour to capture before the immutable board locks.
PRELOCK_QUOTE_WINDOW = LOCK_BEFORE_START + timedelta(hours=1)
PRIORITY_NEAR_PASS_FLOOR = -0.03
MAX_PRIORITY_SIGNALS = 5000
PRIOR_EVENT_EVIDENCE_QUERY = '''SELECT snapshot_key,jsonb_build_object(
    'generated_at',payload->'generated_at','games',payload->'games',
    'signal_count',CASE WHEN jsonb_typeof(payload->'signals')='array'
        THEN jsonb_array_length(payload->'signals') ELSE -1 END,
    'signals',COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'sport',signal->'sport','game_id',signal->'game_id','sample_size',signal->'sample_size',
        'true_prob',signal->'true_prob','implied_prob',signal->'implied_prob','ev_pct',signal->'ev_pct',
        'push_probability',signal->'push_probability','confidence_interval',signal->'confidence_interval',
        'gate_reason',signal->'gate_reason','sportsbook',signal->'sportsbook',
        'american_odds',signal->'american_odds','availability',jsonb_build_object(
            'status',signal#>'{availability,status}',
            'roster_confirmed',signal#>'{availability,roster_confirmed}')))
      FROM jsonb_array_elements(CASE WHEN jsonb_typeof(payload->'signals')='array'
        AND jsonb_array_length(payload->'signals')<=$2 THEN payload->'signals' ELSE '[]'::jsonb END) signal),
      '[]'::jsonb)) AS payload
FROM dashboard_snapshots WHERE snapshot_key=ANY($1::text[])'''


class ProviderRefreshInProgress(RuntimeError):
    pass


def recommendation_quality(signal):
    """Rank supported uncertainty margins before allocating correlated risk."""
    if not signal or not signal.confidence_interval:
        return Decimal('-Infinity'), 0
    lower,upper=signal.confidence_interval
    if (not all(value.is_finite() for value in (lower,upper,signal.true_probability,signal.push_probability,
            signal.implied_probability)) or not 0<=lower<=signal.true_probability<=upper<=1-signal.push_probability):
        return Decimal('-Infinity'),0
    margin=signal.confidence_interval[0]-signal.implied_probability
    return (margin, signal.sample_size or 0) if margin.is_finite() else (Decimal('-Infinity'),0)


def _prior_event_evidence(snapshot: object,sport: str,event_id: str,
                          now: datetime | None = None) -> tuple[tuple[float, int] | None,str | None]:
    quality=None
    attempt=None
    try:
        if not isinstance(snapshot,dict):
            return None,None
        if now is not None:
            try:
                generated=timestamp(snapshot['generated_at'])
                games=snapshot.get('games')
                age=now-generated
                if (timedelta(minutes=-1)<=age<=timedelta(hours=FORECAST_HORIZON_HOURS)
                        and isinstance(games,list) and len(games)==1 and isinstance(games[0],dict)
                        and games[0].get('game_id')==event_id and games[0].get('sport')==sport):
                    attempt=generated.isoformat()
            except (KeyError,ValueError,TypeError,AttributeError):
                pass
        signals=snapshot.get('signals')
        signal_count=snapshot.get('signal_count',len(signals) if isinstance(signals,list) else -1)
        if (isinstance(signal_count,bool) or not isinstance(signal_count,int)
                or signal_count<0 or signal_count>MAX_PRIORITY_SIGNALS
                or not isinstance(signals,list) or len(signals)!=signal_count):
            return None,attempt
        best=None
        for signal in signals:
            if not isinstance(signal,dict) or signal.get('sport')!=sport or signal.get('game_id')!=event_id:
                continue
            availability=signal.get('availability')
            interval=signal.get('confidence_interval')
            sample=signal.get('sample_size')
            if (not isinstance(availability,dict) or availability.get('status')!='observed'
                    or availability.get('roster_confirmed') is not True
                    or signal.get('gate_reason') not in ('accepted','edge_not_confident','edge_review_limit','stale_quote')
                    or not isinstance(signal.get('sportsbook'),str) or not signal['sportsbook']
                    or isinstance(signal.get('american_odds'),bool)
                    or not isinstance(signal.get('american_odds'),int) or abs(signal['american_odds'])<100
                    or isinstance(sample,bool) or not isinstance(sample,int) or sample<20
                    or not isinstance(interval,list) or len(interval)!=2):
                continue
            values=tuple(float(signal[key]) for key in ('true_prob','implied_prob','ev_pct','push_probability'))
            lower,upper=(float(value) for value in interval)
            probability,implied,edge,push=values
            if (not all(isfinite(value) for value in (*values,lower,upper))
                    or not 0<=implied<=1 or not 0<=push<1
                    or not 0<=lower<=probability<=upper<=1-push
                    or probability<=implied or edge<=0
                    or abs(edge-(probability-implied))>1e-6):
                continue
            margin=lower-implied
            if margin<PRIORITY_NEAR_PASS_FLOOR:
                continue
            candidate=(margin,sample)
            if best is None or candidate>best:
                best=candidate
        quality=best
    except Exception:
        pass
    return quality,attempt


def prior_event_evidence(sport: str, event_id: str, now: datetime | None = None) -> tuple[tuple[float, int] | None,str | None]:
    """Read prior ranking and cadence evidence from one validated snapshot."""
    try:
        return _prior_event_evidence(load_snapshot(f'signals:{sport}:{event_id}'),sport,event_id,now)
    except Exception:
        return None,None


async def prior_event_evidence_batch(pool,sport: str,event_ids: list[str],now: datetime):
    """Project and load only fields used for refresh priority, in one database read."""
    evidence={event_id:(None,None) for event_id in event_ids}
    if not event_ids:
        return evidence
    keys=[f'signals:{sport}:{event_id}' for event_id in event_ids]
    try:
        async with pool.acquire() as conn:
            rows=await conn.fetch(PRIOR_EVENT_EVIDENCE_QUERY,keys,MAX_PRIORITY_SIGNALS)
    except Exception:
        return evidence
    identities={key:event_id for key,event_id in zip(keys,event_ids,strict=True)}
    for row in rows:
        try:
            event_id=identities.get(row['snapshot_key'])
            payload=row['payload']
            if event_id is None:
                continue
            if isinstance(payload,str):
                payload=json.loads(payload)
            evidence[event_id]=_prior_event_evidence(payload,sport,event_id,now)
        except (KeyError,TypeError,json.JSONDecodeError):
            continue
    return evidence


def prior_event_quality(sport: str, event_id: str) -> tuple[float, int] | None:
    """Use a bounded prior near-miss only to choose which event gets refreshed first."""
    return prior_event_evidence(sport,event_id)[0]


def prior_quality_sort(quality: tuple[float, int] | None) -> tuple[bool, float, int]:
    if quality is None:
        return True,0,0
    return False,-quality[0],-quality[1]

def timestamp(value: str) -> datetime:
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('Provider timestamp has no timezone')
    return result

def prop_credit_holdback(sports: list[str], limit: int) -> int:
    """Protect one pre-lock and one final-hour check when the budget supports them."""
    width=max(len(MARKETS[sport]) for sport in sports)
    return 2*width if limit>=3*width else 0


def event_credit_holdback(event: dict, reserved: int, now: datetime) -> int:
    """Release one check before the board lock, retaining one for the final hour."""
    remaining=timestamp(event['commence_time'])-now
    if remaining<=LOCK_BEFORE_START:
        return 0
    if remaining<=PRELOCK_QUOTE_WINDOW:
        return reserved//2
    return reserved


def next_quote_check(event: dict, attempted_at: str | None, now: datetime) -> datetime:
    """Cadence controls collection only, never extends quote eligibility."""
    start=timestamp(event['commence_time'])
    try:
        last=timestamp(attempted_at)
        if last>now: return now
    except (ValueError,TypeError,AttributeError):
        return now
    remaining=start-now
    boundaries=[start-boundary for boundary in (timedelta(hours=6),PRELOCK_QUOTE_WINDOW,LOCK_BEFORE_START)]
    if any(last<boundary<=now for boundary in boundaries):
        return now
    interval=timedelta(hours=12) if remaining>timedelta(hours=6) else (
        timedelta(hours=2) if remaining>timedelta(hours=1) else timedelta(minutes=15))
    transitions=[boundary for boundary in boundaries if boundary>now]
    return min([last+interval]+transitions)

def quotes_from_event(event: dict, sport: str) -> list[PlayerPropSnapshotCreate]:
    return parse_event_quotes(event, sport, set(MARKETS[sport]))


def validate_provider_event(event: object, discovered: dict | None = None) -> dict:
    if not isinstance(event, dict):
        raise ValueError('Invalid provider event')
    try:
        identity = (event['id'], event['home_team'], event['away_team'])
        start = timestamp(event['commence_time'])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('Invalid provider event') from None
    if (not all(isinstance(value, str) and 0 < len(value) <= 100 for value in identity)
            or identity[1] == identity[2]):
        raise ValueError('Invalid provider event identity')
    if discovered is not None and (identity != (discovered.get('id'), discovered.get('home_team'),
            discovered.get('away_team')) or start != timestamp(discovered['commence_time'])):
        raise ValueError('Quote response does not match the discovered event')
    return event


def validate_event_listing(payload: object) -> list[dict]:
    if not isinstance(payload, list) or len(payload) > 1000:
        raise ValueError('Invalid provider event list')
    events = [validate_provider_event(event) for event in payload]
    if len({event['id'] for event in events}) != len(events):
        raise ValueError('Duplicate provider event identity')
    return events


def cache_key(kind: str, sport: str, event_id: str | None = None) -> str:
    suffix = ':' + event_id.lower() if event_id else ''
    key = f'odds:{kind}:{sport}{suffix}'
    if len(key) > 255 or any(character not in 'abcdefghijklmnopqrstuvwxyz0123456789:_-' for character in key):
        raise ValueError('Invalid provider cache key')
    return key


def unprocessed_cached_event(cache: ProviderResponseCache, event: dict, sport: str,
                             now: datetime) -> tuple[CachedResponse, dict] | None:
    cached = cache.load(cache_key('event', sport, event['id']), 'the_odds_api', sport, now)
    if not cached:
        return None
    try:
        quoted = validate_provider_event(cached.payload, event)
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    try:
        prior = load_snapshot(f'signals:{sport}:{event["id"]}') or {}
        if timestamp(prior['generated_at']) >= cached.captured_at:
            return None
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    return cached, quoted


async def discover_events(client: httpx.AsyncClient, cache: ProviderResponseCache,
                          sport: str, owner: str, now: datetime) -> list[dict]:
    key = cache_key('events', sport)
    cached = cache.load(key, 'the_odds_api', sport, now)
    if cached:
        try:
            return validate_event_listing(cached.payload)
        except ValueError:
            pass
    if not cache.claim(key, 'the_odds_api', sport, owner, now):
        raise ProviderRefreshInProgress('Event discovery refresh already in progress')
    try:
        response = await client.get(f'/sports/{SPORT_KEYS[sport]}/events',
            params={'apiKey': settings.odds_api_key})
        if response.status_code != 200:
            raise RuntimeError(f'Event provider HTTP {response.status_code}')
        events = validate_event_listing(response.json())
        captured = datetime.now(timezone.utc)
        cache.store(key, 'the_odds_api', sport, owner, events, captured,
            captured + PROVIDER_CACHE_TTL)
        return events
    except Exception:
        cache.release(key, 'the_odds_api', sport, owner)
        raise

def quote_coverage(quotes: list[PlayerPropSnapshotCreate]) -> dict:
    selections={(q.player_name,q.prop_type,q.line,q.side) for q in quotes}
    return dict(quotes=len(quotes),source_committed_quotes=sum(
        quote.source_provider=='the_odds_api' and bool(quote.source_sha256)
        and bool(quote.source_record_sha256) for quote in quotes),
        selections=len(selections),unique_players=len({selection[0] for selection in selections}))

async def evaluate_event(pool, event: dict, sport: str, ledger: Ledger, scan_id: str,
                         availability: dict | None = None) -> dict:
    start=timestamp(event['commence_time'])
    game_date=start.astimezone(ZoneInfo('America/New_York')).date()
    boundary=10 if sport=='nba' else 8 if sport=='cfb' else 9
    season=game_date.year if game_date.month >= boundary else game_date.year-1
    graph=create_graph(nba_quant_node=make_nba_quant_agent(pool),prop_quant_node=make_prop_quant_agent(pool),
        prop_arbitrage_node=make_prop_arbitrage_agent(sport=sport),
        nba_context_producer_node=(make_nba_context_signals_producer(pool,target_date=game_date)
            if sport=='nba' else None))
    quotes=quotes_from_event(event,sport)
    await write_player_prop_snapshots(pool,quotes)
    export=[]
    audited=[]
    counts=Counter()
    # A separate model evaluation per line; prices are compared only for identical outcomes.
    selections=sorted({(q.player_name,q.prop_type,q.line,q.side) for q in quotes})
    player_ids={}
    table='nba_player_gamelogs' if sport=='nba' else 'cfb_player_gamelogs' if sport=='cfb' else 'player_stats'
    identity_column='athlete_id' if sport=='cfb' else 'player_id'
    quoted_players=sorted({selection[0] for selection in selections})
    normalized_players=sorted({player.lower() for player in quoted_players})
    bindings=nfl_roster_history_bindings(availability,event,datetime.now(timezone.utc)) if sport=='nfl' else {}
    history_ids=sorted({bindings[player]['history_player_id'] for player in quoted_players if player in bindings})
    identity_evidence={}
    if normalized_players:
        async with pool.acquire() as conn:
            rows=await conn.fetch(f'''SELECT LOWER(player_name) AS normalized_name,
                {identity_column}::text AS player_id FROM {table}
                WHERE LOWER(player_name)=ANY($1::text[]) OR {identity_column}::text=ANY($2::text[])
                GROUP BY LOWER(player_name),{identity_column}''',normalized_players,history_ids)
        identities={name: set() for name in normalized_players}
        observed_ids=set()
        for row in rows:
            name=row['normalized_name'];identity=row['player_id']
            if isinstance(identity,str) and identity:
                observed_ids.add(identity)
                if name in identities:
                    identities[name].add(identity)
        for player in quoted_players:
            matches=identities[player.lower()]
            binding=bindings.get(player)
            verified_id=binding['history_player_id'] if binding else None
            if verified_id and verified_id in observed_ids:
                if not matches or matches=={verified_id}:
                    player_ids[player]=verified_id
                    identity_evidence[player]=binding
            elif len(matches)==1 and verified_id is None:
                player_ids[player]=next(iter(matches))
        # Distinct quoted names cannot acquire separate risk slots for one athlete.
        repeated=Counter(player_ids.values())
        for player,identity in list(player_ids.items()):
            if repeated[identity]>1:
                del player_ids[player]
                identity_evidence.pop(player,None)
    prepared=[]
    selection_time=datetime.now(timezone.utc)
    for player,market,line,side in selections:
        candidates=[q for q in quotes if (q.player_name,q.prop_type,q.line,q.side)==(player,market,line,side)]
        fresh=[q for q in candidates if -60 <= (selection_time-q.snapped_at).total_seconds() <= 300]
        quote=min(fresh or candidates,key=lambda q:american_to_raw_prob(q.price))
        if player not in player_ids:
            counts['unknown_or_ambiguous_player'] += 1
            continue  # Unknown/ambiguous identity cannot borrow another player's history.
        prepared.append((player,market,line,side,quote,player_ids[player]))

    limiter=asyncio.Semaphore(MAX_MODEL_CONCURRENCY)
    async def model(selection):
        player,market,line,side,quote,player_id=selection
        async with limiter:
            try:
                state=await graph.ainvoke(dict(session_id=scan_id,request_type='nba_prop_analysis' if sport=='nba' else 'prop_analysis',
                game_id=event['id'],home_team=event['home_team'],away_team=event['away_team'],season=season-2,week=1,
                receiver_gsis_id=player_id,player_name=player,sport=sport,prop_type=MARKETS[sport][market],
                prop_line=line,prop_side=side.lower(),as_of_date=game_date,last_n_games=40,player_prop_snapshots=[quote]))
            except Exception as exc:
                log.warning('selection_model_failed',sport=sport,error_type=type(exc).__name__)
                state={'error':'model_evaluation_failed'}
        return selection,state

    async def capture_shadow_history():
        if not settings.history_shadow_enabled:
            return {},None
        try:
            async with asyncio.timeout(5):
                rows=await load_histories(pool,sport,season,game_date,
                    {(selection[5],MARKETS[sport][selection[1]]) for selection in prepared})
            return normalize_source_timestamps(rows),None
        except Exception as exc:
            log.warning('shadow_history_unavailable',sport=sport,error_type=type(exc).__name__)
            return {},'history_read_failed'

    # Read once alongside the existing model work, with a bounded research budget.
    async def capture_role_history():
        if not settings.role_history_shadow_enabled or sport!='nfl':return {},None
        try:
            from sportsbet.quant.nfl_role_shadow import load_inputs
            async with asyncio.timeout(5):
                return await load_inputs(pool,sport,season,game_date,{s[5] for s in prepared}),None
        except Exception as exc:
            log.warning('role_history_unavailable',error_type=type(exc).__name__)
            return {},'history_read_failed'
    modeled,(shadow_histories,shadow_unavailable),(role_inputs,role_unavailable)=await asyncio.gather(
        asyncio.gather(*(model(selection) for selection in prepared)),capture_shadow_history(),capture_role_history())
    failures=sum(bool(state.get('error')) for _,state in modeled)
    if failures and failures==len(modeled):
        raise RuntimeError('Model evaluation failed')
    if failures:
        counts['model_evaluation_failed']=failures
        modeled=[item for item in modeled if not item[1].get('error')]
    # Successful selections retain every gate. A failed neighbor cannot erase
    # them; requested-versus-estimated counts publish honest partial coverage.
    # Alphabetical/line order must not consume a player's risk slot ahead of a
    # stronger qualified estimate. Keep all forecasts; retain every existing gate.
    modeled.sort(key=lambda candidate:recommendation_quality(candidate[1].get('ev_signal')),reverse=True)
    shadow_counts=Counter();role_counts=Counter()
    explained_contexts=set()
    ngs_contexts={}
    for selection,state in modeled:
        player,market,line,side,quote,player_id=selection
        prop=state.get('nba_prop_result' if sport=='nba' else 'prop_result')
        if not prop or prop.true_probability is None:
            counts['missing_model_estimate'] += 1
            continue
        counts['evaluated_selections'] += 1
        probability=prop.true_probability if side=='Over' else 1-prop.true_probability-prop.push_probability
        model_interval=outcome_interval_for_side(
            prop.confidence_interval,prop.push_probability,side.lower())
        signal=state.get('ev_signal')
        accepted=False
        reason=state.get('gate_reason') or 'no_positive_edge'
        now=datetime.now(timezone.utc)
        availability_evidence, availability_reason=player_availability(availability,player,now,
            player_id=player_id if sport=='nfl' else None)
        relevant_reports=[]
        if sport in ('nba','nfl') and availability_evidence['status']=='observed':
            relevant_reports=relevant_availability_reports(availability,
                availability_evidence['team'],availability_evidence.get('roster_player_name',player),sport)
            availability_evidence['teammates']=relevant_reports
            if availability_reason in (None,'teammate_availability_unmodeled'):
                availability_reason=('teammate_availability_unmodeled'
                    if any(blocks_unadjusted_teammate_context(report) for report in relevant_reports)
                    else None)
        # The sorted first selection is the same strongest per-player exposure
        # the public desk can surface. Avoid multiplying up to eight split
        # queries across every alternate threshold for that player.
        context_key=player
        if sport in ('nba','nfl') and availability_evidence['status']=='observed' and context_key not in explained_contexts:
            explained_contexts.add(context_key)
            splits=await historical_availability_splits(pool,context=availability,
                subject_team=availability_evidence['team'],subject_player=availability_evidence.get('roster_player_name',player),
                sport=sport,player_id=player_id,season=season-2,cutoff=game_date,
                prop_type=MARKETS[sport][market],line=float(line),direction=side.lower())
            if splits:
                availability_evidence['context_splits']=splits
        ngs_evidence=None
        if sport=='nfl' and availability_evidence['status']=='observed':
            ngs_key=(player_id,MARKETS[sport][market])
            if ngs_key not in ngs_contexts:
                try:
                    ngs_contexts[ngs_key]=await load_ngs_evidence(pool,
                        player_gsis_id=player_id,season=season,game_date=game_date,
                        team=availability_evidence.get('team',''),prop_type=MARKETS[sport][market])
                except Exception as exc:
                    log.warning('ngs_evidence_unavailable',error_type=type(exc).__name__)
                    ngs_contexts[ngs_key]=None
            ngs_evidence=ngs_contexts[ngs_key]
        if signal:
            if now >= start: reason='game_started'
            elif not -60 <= (now-quote.snapped_at).total_seconds() <= 300: reason='stale_quote'
            elif recommendation_quality(signal)[0]<=0: reason='edge_not_confident'
            elif availability_reason: reason=availability_reason
            else: accepted,reason=ledger.reserve(signal,float(line))
        payload=dict(game_id=event['id'],player=player,player_id=player_id,sport=sport,
            game_date=game_date.isoformat(),home_team=event['home_team'],away_team=event['away_team'],
            prop_type=MARKETS[sport][market],direction=side.lower(),line=float(line),
            sportsbook=quote.sportsbook,american_odds=quote.price,model_probability=float(probability),
            push_probability=float(prop.push_probability),model_sample_size=prop.sample_size,
            model_mean_stat=float(prop.mean_stat) if prop.mean_stat is not None else None,
            model_confidence_interval=[float(x) for x in model_interval] if model_interval else None,
            captured_at=now.isoformat(),game_start_time=start.isoformat(),
            quote_time=quote.snapped_at.isoformat(),model_generated_at=now.isoformat(),
            quote_source_provider=quote.source_provider,quote_source_sha256=quote.source_sha256,
            quote_source_record_sha256=quote.source_record_sha256,accepted=accepted,gate_reason=reason,
            stake_fraction=float(signal.kelly_fraction) if accepted else 0,model_version=MODEL_VERSION,
            recommendation_policy_version=RECOMMENDATION_POLICY_VERSION,
            **paired_market_baseline(quote, quotes))
        if player in identity_evidence:
            payload['player_identity_evidence']=identity_evidence[player]
        counts[reason] += 1
        # Publish every measured forecast, including non-recommended estimates.
        # Availability screens eligibility; v4 remains an unchanged historical baseline.
        if prop:
            implied,payout=quote_terms(quote.price,american_to_raw_prob(quote.price))
            trade_plan=list(signal.trade_plan) if signal else [
                f'Historical baseline: {prop.sample_size} prior games before {game_date.isoformat()}; '
                f'{side.lower()} probability {float(probability):.1%}.',
                f'Observed price {quote.price:+d}; break-even {float(implied):.1%}. '
                'This estimate did not pass the model edge and uncertainty gates.',
                'No validated injury or teammate probability adjustment is applied.']
            if signal:
                mean=f'{float(prop.mean_stat):.1f}' if prop.mean_stat is not None else 'unavailable'
                uncertainty=(f'{float(model_interval[0]):.1%} to {float(model_interval[1]):.1%}'
                    if model_interval else 'unavailable')
                # A thesis must not suggest staking a pick that eligibility blocks.
                trade_plan[1]=(f'Historical sample: {prop.sample_size} games, mean {mean}; '
                    f'95% probability interval {uncertainty}. Approved research stake at capture: '
                    f'{float(signal.kelly_fraction) if accepted else 0:.1%} of bankroll.')
            if availability_evidence['status']=='observed':
                split_count=len(availability_evidence.get('context_splits',[]))
                trade_plan[-1]=(f"Availability: {availability_evidence['subject_status']}; "
                    f"{len(relevant_reports)} relevant current report{'s' if len(relevant_reports) != 1 else ''}; "
                    f"{split_count} exact historical on/off comparison{'s' if split_count != 1 else ''} retained. "
                    'Current reports screen eligibility; descriptive splits do not change the probability.')
            public_signal=dict(player=player,sport=sport,
                game_id=event['id'],prop_type=MARKETS[sport][market],direction=side.lower(),line=float(line),
                team='',opponent='',home_team=event['home_team'],away_team=event['away_team'],
                true_prob=float(probability),implied_prob=float(implied),ev_pct=float(probability-implied),
                expected_return=float(compute_expected_return(probability,payout,prop.push_probability)),push_probability=float(prop.push_probability),
                kelly_fraction=float(signal.kelly_fraction) if accepted and signal else 0,gated=not accepted,gate_reason=reason,
                sportsbook=quote.sportsbook,american_odds=quote.price,snapped_at=quote.snapped_at.isoformat(),
                game_start_time=start.isoformat(),sample_size=prop.sample_size,mean_stat=float(prop.mean_stat) if prop.mean_stat is not None else None,
                confidence_interval=[float(x) for x in model_interval] if model_interval else None,
                model_version=MODEL_VERSION,strength='unrated',trade_plan=trade_plan,injury_flags={},market_type=market,
                availability=availability_evidence,forecast_cutoff=game_date.isoformat(),
                **({'next_gen_stats':ngs_evidence} if ngs_evidence else {}))
            payload.update(availability=availability_evidence,trade_plan=trade_plan,
                           forecast_cutoff=game_date.isoformat(),
                           **({'next_gen_stats':ngs_evidence} if ngs_evidence else {}))
        if settings.history_shadow_enabled:
            try:
                payload['history_shadow']=shadow_record(payload,
                    shadow_histories.get((player_id,MARKETS[sport][market]),[]),
                    unavailable=shadow_unavailable)
            except Exception as exc:
                log.warning('shadow_evaluation_failed',sport=sport,error_type=type(exc).__name__)
                payload['history_shadow']={'model_version':SHADOW_VERSION,'policy_version':SHADOW_POLICY,
                    'status':'unavailable','reason':'shadow_evaluation_failed'}
            shadow_counts[payload['history_shadow'].get('reason','predicted')]+=1
        if settings.role_history_shadow_enabled and sport=='nfl':
            from sportsbet.quant.nfl_role_shadow import shadow_record as role_record,VERSION as ROLE_VERSION,POLICY as ROLE_POLICY
            try:
                payload['role_history_shadow']=role_record(payload,role_inputs.get(player_id,{}),unavailable=role_unavailable)
            except Exception as exc:
                log.warning('role_shadow_evaluation_failed',error_type=type(exc).__name__)
                payload['role_history_shadow']=dict(model_version=ROLE_VERSION,policy_version=ROLE_POLICY,
                    status='unavailable',reason='shadow_evaluation_failed')
            role_counts[payload['role_history_shadow'].get('reason','predicted')]+=1
        audited.append((payload,public_signal))
    prediction_ids=ledger.record_many(scan_id,[payload for payload,_ in audited])
    for prediction_id,(_,public_signal) in zip(prediction_ids,audited,strict=True):
        if public_signal is not None:
            export.append(dict(id=prediction_id,prediction_id=prediction_id,**public_signal))
    estimates=counts['evaluated_selections']
    model_status=('no_quotes' if not selections else 'unavailable' if not prepared or not estimates
        else 'complete' if len(prepared)==len(selections) and estimates==len(prepared) else 'partial')
    return dict(generated_at=datetime.now(timezone.utc).isoformat(),signals=export,
        coverage=quote_coverage(quotes)|dict(resolved_players=len(player_ids),model_requests=len(prepared),
            model_estimates=estimates,model_status=model_status,
            model_concurrency_limit=MAX_MODEL_CONCURRENCY,counts=dict(counts),
            history_shadow=dict(enabled=settings.history_shadow_enabled,inference_counts=dict(shadow_counts)),
            role_history_shadow=dict(enabled=settings.role_history_shadow_enabled and sport=='nfl',inference_counts=dict(role_counts))),games=[dict(game_id=event['id'],
        home_team=event['home_team'],away_team=event['away_team'],date=game_date.strftime('%Y%m%d'),sport=sport)])

async def run(sports: list[str], daily_credit_limit: int, event_ids: frozenset[str] | None = None):
    if not sports or len(sports)!=len(set(sports)) or any(s not in MODEL_SPORTS for s in sports) or daily_credit_limit<1:
        raise ValueError('Invalid scan scope or budget')
    if event_ids is not None and (len(sports)!=1 or not event_ids or len(event_ids)>10
            or any(not isinstance(value,str) or not value or len(value)>100 for value in event_ids)):
        raise ValueError('Invalid targeted scan')
    if not settings.odds_api_key or not settings.analytics_database_url:
        raise ValueError('Worker credentials are not configured')
    ledger=Ledger()
    cache=ProviderResponseCache()
    pool=await create_async_pool()
    scan_id=uuid.uuid4().hex
    now=datetime.now(timezone.utc)
    reports={}
    queues={}
    screens={sport:[] for sport in sports}
    held=prop_credit_holdback(sports,daily_credit_limit)
    try:
        async with httpx.AsyncClient(base_url='https://api.the-odds-api.com/v4',timeout=20,follow_redirects=False) as client:
            for sport in sports:
                previous=load_snapshot('scan:'+sport) or {}
                report=dict(scan_id=scan_id,sport=sport,started_at=now.isoformat(),finished_at=None,status='running',
                    eligible_events=None,attempted_events=0,completed_events=0,budget_skipped_events=0,budget_reasons={},
                    cadence_deferred_events=0,cache_hits=0,coalesced_events=0,next_refresh_at=None,
                    failures=[],coverage={},attempts=previous.get('attempts',{}),
                    model_complete_events=0,model_partial_events=0,model_unavailable_events=0,
                    events=[],execution_ready=False)
                reports[sport]=report
                publish_snapshot('scan:'+sport,report)
                try:
                    discovered=await discover_events(client,cache,sport,scan_id,now)
                    events=[e for e in discovered if now < timestamp(e['commence_time']) <= now+timedelta(hours=FORECAST_HORIZON_HOURS)]
                    active_ids={event['id'] for event in events}
                    report['attempts']={identity:attempt for identity,attempt in report['attempts'].items()
                        if identity in active_ids}
                    evidence=await prior_event_evidence_batch(pool,sport,[event['id'] for event in events],now)
                    for identity,(_,attempt) in evidence.items():
                        if identity not in report['attempts'] and attempt is not None:
                            report['attempts'][identity]=attempt
                    if event_ids is not None:
                        if missing:=event_ids-active_ids:
                            raise ValueError(f'Targeted events are unavailable or outside the pregame horizon: {len(missing)}')
                        events=[event for event in events if event['id'] in event_ids]
                    report['eligible_events']=len(events)
                    report['events']=[dict(game_id=e['id'],home_team=e['home_team'],
                        away_team=e['away_team'],game_start_time=e['commence_time'],state='waiting_quotes')
                        for e in events]
                    priorities={event['id']:evidence[event['id']][0] for event in events}
                    queues[sport]=sorted(events,key=lambda e:(timestamp(e['commence_time'])>now+LOCK_BEFORE_START,
                        timestamp(e['commence_time'])>now+PRELOCK_QUOTE_WINDOW,
                        *prior_quality_sort(priorities[e['id']]),
                        report['attempts'].get(e['id'],''),timestamp(e['commence_time']),e['id']))
                except Exception as exc:
                    report['failures'].append(dict(stage='event_discovery',error_type=type(exc).__name__))
                    queues[sport]=[]
            # Alternate leagues, starting with the least recently attempted league.
            # Within each league, rotate past previous attempts before spending again.
            order=sorted(sports,key=lambda s:max(reports[s]['attempts'].values(),default=''))
            pending=[(sport,queues[sport][i]) for i in range(max(map(len,queues.values()),default=0))
                     for sport in order if i<len(queues[sport])]
            for sport,event in pending:
                report=reports[sport]
                event_state=next(item for item in report['events'] if item['game_id']==event['id'])
                quote_key=cache_key('event',sport,event['id'])
                cached=unprocessed_cached_event(cache,event,sport,datetime.now(timezone.utc))
                cache_owned=False
                quoted=None
                if cached:
                    if cache.claim(quote_key,'the_odds_api',sport,scan_id,datetime.now(timezone.utc)):
                        cache_owned=True
                        quoted=cached[1]
                        event_state['cache']='hit'
                        report['cache_hits']=report.get('cache_hits',0)+1
                    else:
                        event_state['state']='provider_busy'
                        report['coalesced_events']=report.get('coalesced_events',0)+1
                        continue
                check=next_quote_check(event,report['attempts'].get(event['id']),datetime.now(timezone.utc))
                if quoted is None and event_ids is None and check>datetime.now(timezone.utc):
                    event_state.update(state='scheduled',next_refresh_at=check.isoformat())
                    report['cadence_deferred_events']+=1
                    if not report['next_refresh_at'] or check<timestamp(report['next_refresh_at']):
                        report['next_refresh_at']=check.isoformat()
                    continue
                if quoted is None:
                    if not cache.claim(quote_key,'the_odds_api',sport,scan_id,datetime.now(timezone.utc)):
                        event_state['state']='provider_busy'
                        report['coalesced_events']=report.get('coalesced_events',0)+1
                        continue
                    cache_owned=True
                    reserved,budget_reason=ledger.reserve_api_credits_with_reason(
                        len(MARKETS[sport]),daily_credit_limit,
                        holdback=event_credit_holdback(event,held,datetime.now(timezone.utc)))
                    if not reserved:
                        cache.release(quote_key,'the_odds_api',sport,scan_id)
                        cache_owned=False
                        event_state.update(state='api_budget',budget_reason=budget_reason)
                        report['budget_skipped_events']+=1
                        report['budget_reasons'][budget_reason]=report['budget_reasons'].get(budget_reason,0)+1
                        continue
                    report['attempted_events']+=1
                event_state['state']='evaluating'
                if quoted is None:
                    report['attempts'][event['id']]=datetime.now(timezone.utc).isoformat()
                    # Persist before I/O so interrupted runs don't repeatedly consume the same game's budget.
                    publish_snapshot('scan:'+sport,report)
                try:
                    if quoted is None:
                        response=await client.get(f'/sports/{SPORT_KEYS[sport]}/events/{event["id"]}/odds',params={
                            'apiKey':settings.odds_api_key,'regions':'us','markets':','.join(MARKETS[sport]),'oddsFormat':'american'})
                        if response.status_code!=200: raise RuntimeError(f'Quote provider returned HTTP {response.status_code}')
                        quoted=validate_provider_event(response.json(),event)
                        captured=datetime.now(timezone.utc)
                        # Retain the paid response before downstream work so a crashed model can resume it.
                        cache.store(quote_key,'the_odds_api',sport,scan_id,quoted,captured,
                            captured+PROVIDER_CACHE_TTL,release=False)
                    quotes=quotes_from_event(quoted,sport)
                    sportsbook_screen=screen_sportsbooks(quoted,sport,quotes,datetime.now(timezone.utc))
                    screened=screen_cross_venue(quoted,sport,quotes,
                        load_snapshot('kalshi-props:'+sport),datetime.now(timezone.utc))
                    report['coverage'][event['id']]=quote_coverage(quotes)|dict(
                        model_status='pending',cross_venue=screened['coverage'])
                    publish_snapshot('scan:'+sport,report)
                    screens[sport].append(dict(status=screened['status'],
                        coverage=screened['coverage'],
                        comparisons=sportsbook_screen['comparisons']+screened['comparisons']))
                    availability=await fetch_event_availability(quoted,sport,
                        player_names={quote.player_name for quote in quotes})
                    result=await asyncio.wait_for(evaluate_event(pool,quoted,sport,ledger,scan_id,availability),timeout=120)
                    result['cross_venue']=screened
                    result['sportsbook_arb']=sportsbook_screen
                    publish_snapshot(f'signals:{sport}:{event["id"]}',result)
                    cache.release(quote_key,'the_odds_api',sport,scan_id)
                    cache_owned=False
                    report['completed_events']+=1
                    report['coverage'][event['id']]=result['coverage']|{'cross_venue':screened['coverage']}
                    event_state['state']='evaluated'
                except Exception as exc:
                    if cache_owned:
                        cache.release(quote_key,'the_odds_api',sport,scan_id)
                    event_state['state']='failed'
                    report['failures'].append(dict(stage='event_evaluation',event_id=event['id'],error_type=type(exc).__name__))
            for sport,report in reports.items():
                model_statuses=Counter(item.get('model_status') for item in report['coverage'].values())
                report['model_complete_events']=model_statuses['complete']
                report['model_partial_events']=model_statuses['partial']
                report['model_unavailable_events']=model_statuses['unavailable']
                model_incomplete=report['model_partial_events'] or report['model_unavailable_events']
                report['status']='degraded' if report['failures'] or report['budget_skipped_events'] or model_incomplete else (
                    'scheduled' if report['cadence_deferred_events'] or report['coalesced_events'] else 'complete')
                report['finished_at']=datetime.now(timezone.utc).isoformat()
                publish_snapshot('scan:'+sport,report)
                comparisons=[row for screen in screens[sport] for row in screen['comparisons']]
                cross_venue=[screen['coverage'] for screen in screens[sport]
                    if isinstance(screen.get('coverage'),dict)]
                side_funnel=Counter()
                for coverage in cross_venue:
                    if isinstance(coverage.get('side_funnel'),dict):
                        side_funnel.update(coverage['side_funnel'])
                observed=sum(screen['status']=='observed' for screen in screens[sport])
                screen_status='observed' if (report['status']=='complete' and (
                    report['eligible_events']==0 or observed==report['eligible_events'])) else 'degraded'
                publish_snapshot('prop-screens:'+sport,dict(schema_version=1,scan_id=scan_id,sport=sport,
                    generated_at=report['finished_at'],status=screen_status,
                    coverage=dict(events=len(screens[sport]),observed_events=observed,
                        unavailable_events=sum(screen['status']=='unavailable' for screen in screens[sport]),
                        positive_gross_gaps=len(comparisons),
                        sportsbook_gaps=sum(row['kind']=='sportsbook_sportsbook_prop' for row in comparisons),
                        kalshi_sportsbook_gaps=sum(row['kind']=='kalshi_sportsbook_prop' for row in comparisons),
                        kalshi_quotes=sum(coverage.get('kalshi_quotes',0) for coverage in cross_venue),
                        kalshi_exact_markets=sum(coverage.get('exact_markets',0) for coverage in cross_venue),
                        kalshi_paired_sides=side_funnel['paired'],
                        kalshi_missing_ask_sides=side_funnel['missing_kalshi_ask'],
                        kalshi_missing_sportsbook_sides=side_funnel['missing_sportsbook_side'],
                        kalshi_observation_skew_sides=side_funnel['observation_skew'],
                        kalshi_rule_terms_classified=sum(row.get('settlement_review',{}).get(
                            'kalshi',{}).get('classified') is True for row in comparisons),
                        kalshi_fee_modeled=sum('exchange_fee_scenarios' in row for row in comparisons),
                        kalshi_direct_cost_below_one=sum(Decimal(row['exchange_fee_scenarios']['combined_cost']['direct'])<1
                            for row in comparisons if 'exchange_fee_scenarios' in row),
                        kalshi_non_direct_cost_below_one=sum(Decimal(row['exchange_fee_scenarios']['combined_cost']['non_direct'])<1
                            for row in comparisons if 'exchange_fee_scenarios' in row)),
                    comparisons=comparisons,execution_ready=False))
        publish_snapshot('metrics:all',ledger.report(model_version=MODEL_VERSION))
        publish_snapshot('metrics:recommendations',ledger.report(True,model_version=MODEL_VERSION))
        prediction_rows=ledger.predictions()
        for sport in sports:
            publish_snapshot(f'metrics:all:{sport}',ledger.report(model_version=MODEL_VERSION,sport=sport))
            publish_snapshot(f'metrics:recommendations:{sport}',
                ledger.report(True,model_version=MODEL_VERSION,sport=sport))
            publish_snapshot(f'picks:{sport}',build_pick_board(prediction_rows,sport))
            from sportsbet.quant.history_shadow_audit import publish_history_shadow
            publish_history_shadow(prediction_rows,sport,publish_snapshot)
            from sportsbet.quant.nfl_role_shadow_audit import publish_role_history_shadow
            publish_role_history_shadow(prediction_rows,sport,publish_snapshot)
        return reports
    finally:
        cache.close()
        await pool.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport',choices=['nba','nfl','cfb','both','all'],default='both')
    parser.add_argument('--daily-credit-limit',type=int,default=25)
    parser.add_argument('--event-id',action='append',default=[],help='Refresh only this discovered pregame event; repeat at most ten times')
    args=parser.parse_args()
    try:
        sports=['nfl','nba'] if args.sport=='both' else ['nfl','nba','cfb'] if args.sport=='all' else [args.sport]
        reports=asyncio.run(run(sports,args.daily_credit_limit,
            frozenset(args.event_id) if args.event_id else None))
        print(json.dumps({s:{k:v for k,v in r.items() if k not in ('attempts','coverage')} for s,r in reports.items()}))
        if not reports or any(r['status'] not in ('complete','scheduled') for r in reports.values()):
            raise SystemExit(2)
    except Exception as exc:
        raise SystemExit(f'Market update failed ({type(exc).__name__})') from None

if __name__=='__main__': main()
