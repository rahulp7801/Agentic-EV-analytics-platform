"""Scheduled NFL/NBA prop evaluation. External data stays outside graph logic."""
from __future__ import annotations
import argparse
import asyncio
import json
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import httpx
from sportsbet.config import settings
from sportsbet.dashboard import publish_snapshot, load_snapshot
from sportsbet.db.connection import create_async_pool
from sportsbet.graph.graph import create_graph
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, parse_event_quotes, write_player_prop_snapshots
from sportsbet.ledger import Ledger
from sportsbet.model_contract import MODEL_VERSION
from sportsbet.prop.agents import make_prop_quant_agent
from sportsbet.prop.availability import fetch_event_availability, player_availability
from sportsbet.prop.injury_context import historical_availability_splits
from sportsbet.arbitrage.ev import compute_expected_return, quote_terms
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.prop.cross_venue import PROP_MARKETS, screen as screen_cross_venue, screen_sportsbooks
from sportsbet.prop.probability import outcome_interval_for_side
from sportsbet.quant.vig import american_to_raw_prob

MARKETS = PROP_MARKETS
SPORT_KEYS = {'nba':'basketball_nba','nfl':'americanfootball_nfl'}
MAX_MODEL_CONCURRENCY = 8
FORECAST_HORIZON_HOURS = 48
RECOMMENDATION_POLICY_VERSION = 'lower-bound-margin-v1'


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

def timestamp(value: str) -> datetime:
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('Provider timestamp has no timezone')
    return result

def prop_credit_holdback(sports: list[str], limit: int) -> int:
    """Protect two full pregame checks when the configured budget supports them."""
    width=max(len(MARKETS[sport]) for sport in sports)
    return 2*width if limit>=3*width else 0

def next_quote_check(event: dict, attempted_at: str | None, now: datetime) -> datetime:
    """Cadence controls collection only, never extends quote eligibility."""
    start=timestamp(event['commence_time'])
    try:
        last=timestamp(attempted_at)
        if last>now: return now
    except (ValueError,TypeError,AttributeError):
        return now
    remaining=start-now
    boundaries=[start-boundary for boundary in (timedelta(hours=6),timedelta(hours=1))]
    if any(last<boundary<=now for boundary in boundaries):
        return now
    interval=timedelta(hours=12) if remaining>timedelta(hours=6) else (
        timedelta(hours=2) if remaining>timedelta(hours=1) else timedelta(minutes=15))
    transitions=[boundary for boundary in boundaries if boundary>now]
    return min([last+interval]+transitions)

def quotes_from_event(event: dict, sport: str) -> list[PlayerPropSnapshotCreate]:
    return parse_event_quotes(event, sport, set(MARKETS[sport]))

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
    season=game_date.year if game_date.month >= (10 if sport=='nba' else 9) else game_date.year-1
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
    table='nba_player_gamelogs' if sport=='nba' else 'player_stats'
    for player in sorted({selection[0] for selection in selections}):
        async with pool.acquire() as conn:
            players=await conn.fetch(
                f'SELECT DISTINCT player_id FROM {table} WHERE LOWER(player_name)=LOWER($1)',player)
        if len(players)==1:
            player_ids[player]=str(players[0]['player_id'])
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
            state=await graph.ainvoke(dict(session_id=scan_id,request_type='nba_prop_analysis' if sport=='nba' else 'prop_analysis',
            game_id=event['id'],home_team=event['home_team'],away_team=event['away_team'],season=season-2,week=1,
            receiver_gsis_id=player_id,player_name=player,sport=sport,prop_type=MARKETS[sport][market],
            prop_line=line,prop_side=side.lower(),as_of_date=game_date,last_n_games=40,player_prop_snapshots=[quote]))
        return selection,state

    modeled=await asyncio.gather(*(model(selection) for selection in prepared))
    if any(state.get('error') for _,state in modeled):
        raise RuntimeError('Model evaluation failed')
    # Alphabetical/line order must not consume a player's risk slot ahead of a
    # stronger qualified estimate. Keep all forecasts; retain every existing gate.
    modeled.sort(key=lambda candidate:recommendation_quality(candidate[1].get('ev_signal')),reverse=True)
    explained_contexts=set()
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
        # The sorted first selection is the same strongest per-player exposure
        # the public desk can surface. Avoid multiplying up to eight split
        # queries across every alternate threshold for that player.
        context_key=player
        if availability_evidence['status']=='observed' and context_key not in explained_contexts:
            explained_contexts.add(context_key)
            splits=await historical_availability_splits(pool,context=availability,
                subject_team=availability_evidence['team'],subject_player=availability_evidence.get('roster_player_name',player),
                sport=sport,player_id=player_id,season=season-2,cutoff=game_date,
                prop_type=MARKETS[sport][market],line=float(line),direction=side.lower())
            if splits:
                availability_evidence['context_splits']=splits
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
            model_confidence_interval=[float(x) for x in model_interval] if model_interval else None,
            captured_at=now.isoformat(),game_start_time=start.isoformat(),
            quote_time=quote.snapped_at.isoformat(),model_generated_at=now.isoformat(),
            quote_source_provider=quote.source_provider,quote_source_sha256=quote.source_sha256,
            quote_source_record_sha256=quote.source_record_sha256,accepted=accepted,gate_reason=reason,
            stake_fraction=float(signal.kelly_fraction) if accepted else 0,model_version=MODEL_VERSION,
            recommendation_policy_version=RECOMMENDATION_POLICY_VERSION)
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
                availability=availability_evidence,forecast_cutoff=game_date.isoformat())
            payload.update(availability=availability_evidence,trade_plan=trade_plan,
                           forecast_cutoff=game_date.isoformat())
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
            model_concurrency_limit=MAX_MODEL_CONCURRENCY,counts=dict(counts)),games=[dict(game_id=event['id'],
        home_team=event['home_team'],away_team=event['away_team'],date=game_date.strftime('%Y%m%d'),sport=sport)])

async def run(sports: list[str], daily_credit_limit: int):
    if not sports or len(sports)!=len(set(sports)) or any(s not in SPORT_KEYS for s in sports) or daily_credit_limit<1:
        raise ValueError('Invalid scan scope or budget')
    if not settings.odds_api_key or not settings.analytics_database_url:
        raise ValueError('Worker credentials are not configured')
    ledger=Ledger()
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
                    eligible_events=None,attempted_events=0,completed_events=0,budget_skipped_events=0,
                    cadence_deferred_events=0,next_refresh_at=None,
                    failures=[],coverage={},attempts=previous.get('attempts',{}),
                    model_complete_events=0,model_partial_events=0,model_unavailable_events=0,
                    events=[],execution_ready=False)
                reports[sport]=report
                publish_snapshot('scan:'+sport,report)
                try:
                    response=await client.get(f'/sports/{SPORT_KEYS[sport]}/events',params={'apiKey':settings.odds_api_key})
                    if response.status_code!=200: raise RuntimeError(f'Event provider HTTP {response.status_code}')
                    events=[e for e in response.json() if now < timestamp(e['commence_time']) <= now+timedelta(hours=FORECAST_HORIZON_HOURS)]
                    if len({e['id'] for e in events})!=len(events):
                        raise ValueError('Duplicate provider event identity')
                    report['eligible_events']=len(events)
                    report['events']=[dict(game_id=e['id'],home_team=e['home_team'],
                        away_team=e['away_team'],game_start_time=e['commence_time'],state='waiting_quotes')
                        for e in events]
                    report['attempts']={e['id']:report['attempts'][e['id']] for e in events if e['id'] in report['attempts']}
                    queues[sport]=sorted(events,key=lambda e:(timestamp(e['commence_time'])>now+timedelta(hours=1),
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
                check=next_quote_check(event,report['attempts'].get(event['id']),datetime.now(timezone.utc))
                if check>datetime.now(timezone.utc):
                    event_state.update(state='scheduled',next_refresh_at=check.isoformat())
                    report['cadence_deferred_events']+=1
                    if not report['next_refresh_at'] or check<timestamp(report['next_refresh_at']):
                        report['next_refresh_at']=check.isoformat()
                    continue
                close=timestamp(event['commence_time'])-datetime.now(timezone.utc)<=timedelta(hours=1)
                if not ledger.reserve_api_credits(len(MARKETS[sport]),daily_credit_limit,holdback=0 if close else held):
                    event_state['state']='api_budget'
                    report['budget_skipped_events']+=1
                    continue
                report['attempted_events']+=1
                event_state['state']='evaluating'
                report['attempts'][event['id']]=datetime.now(timezone.utc).isoformat()
                # Persist before I/O so interrupted runs don't repeatedly consume the same game's budget.
                publish_snapshot('scan:'+sport,report)
                try:
                    response=await client.get(f'/sports/{SPORT_KEYS[sport]}/events/{event["id"]}/odds',params={
                        'apiKey':settings.odds_api_key,'regions':'us','markets':','.join(MARKETS[sport]),'oddsFormat':'american'})
                    if response.status_code!=200: raise RuntimeError(f'Quote provider returned HTTP {response.status_code}')
                    quoted=response.json()
                    if quoted.get('id')!=event['id'] or any(quoted.get(k)!=event.get(k) for k in ('home_team','away_team')) or timestamp(quoted['commence_time'])!=timestamp(event['commence_time']):
                        raise ValueError('Quote response does not match the discovered event')
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
                    report['completed_events']+=1
                    report['coverage'][event['id']]=result['coverage']|{'cross_venue':screened['coverage']}
                    event_state['state']='evaluated'
                except Exception as exc:
                    event_state['state']='failed'
                    report['failures'].append(dict(stage='event_evaluation',event_id=event['id'],error_type=type(exc).__name__))
            for sport,report in reports.items():
                model_statuses=Counter(item.get('model_status') for item in report['coverage'].values())
                report['model_complete_events']=model_statuses['complete']
                report['model_partial_events']=model_statuses['partial']
                report['model_unavailable_events']=model_statuses['unavailable']
                model_incomplete=report['model_partial_events'] or report['model_unavailable_events']
                report['status']='degraded' if report['failures'] or report['budget_skipped_events'] or model_incomplete else (
                    'scheduled' if report['cadence_deferred_events'] else 'complete')
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
        for sport in sports:
            publish_snapshot(f'metrics:all:{sport}',ledger.report(model_version=MODEL_VERSION,sport=sport))
            publish_snapshot(f'metrics:recommendations:{sport}',
                ledger.report(True,model_version=MODEL_VERSION,sport=sport))
        return reports
    finally:
        await pool.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport',choices=['nba','nfl','both'],default='both')
    parser.add_argument('--daily-credit-limit',type=int,default=25)
    args=parser.parse_args()
    try:
        reports=asyncio.run(run(['nfl','nba'] if args.sport=='both' else [args.sport],args.daily_credit_limit))
        print(json.dumps({s:{k:v for k,v in r.items() if k not in ('attempts','coverage')} for s,r in reports.items()}))
        if not reports or any(r['status'] not in ('complete','scheduled') for r in reports.values()):
            raise SystemExit(2)
    except Exception as exc:
        raise SystemExit(f'Market update failed ({type(exc).__name__})') from None

if __name__=='__main__': main()
