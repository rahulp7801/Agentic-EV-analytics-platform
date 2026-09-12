"""Capture read-only venue evidence and publish explicitly unverified price comparisons."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx

from sportsbet.config import settings
from sportsbet.dashboard import publish_snapshot
from sportsbet.ingestion.archive import write_archive
from sportsbet.ingestion.kalshi import KalshiReader
from sportsbet.ingestion.kalshi_history import SERIES as KALSHI_PROP_SERIES
from sportsbet.ingestion.prizepicks import capture as capture_projections
from sportsbet.ledger import Ledger
from sportsbet.scan import SPORT_KEYS, timestamp
from sportsbet.quant.vig import american_to_raw_prob
from sportsbet.arbitrage.kalshi_fees import fee_terms, taker_buy_cost, taker_depth_cost

DEFAULT_GAME_LIMIT=20
MAX_GAME_LIMIT=40
PROP_PAGE_LIMIT=1000
MAX_PROP_PAGES=3
PROP_FEE_CONCURRENCY=8


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def prop_fee_context(series: dict, series_changes: dict, event: str,
        event_changes: dict, received_at: datetime) -> dict:
    """Retain only fields needed to reproduce a prop fee decision plus source hashes."""
    if (not isinstance(series,dict) or not isinstance(series_changes,dict)
            or not isinstance(series_changes.get('series_fee_change_arr'),list)
            or not isinstance(event_changes,dict)
            or not isinstance(event_changes.get('event_fee_changes'),list)):
        raise ValueError('Invalid prop fee evidence')
    series_fields={key:series[key] for key in ('ticker','fee_type','fee_multiplier','last_updated_ts')}
    scheduled=[{key:item.get(key) for key in ('series_ticker','fee_type','fee_multiplier','scheduled_ts')}
        for item in series_changes['series_fee_change_arr']]
    overrides=[{key:item.get(key) for key in ('event_ticker','series_ticker','fee_type_override',
        'fee_multiplier_override','scheduled_ts')} for item in event_changes['event_fee_changes']]
    return dict(status='observed',received_at=received_at.isoformat(),series=series_fields,
        series_changes={'series_fee_change_arr':scheduled},
        event_changes={'event_fee_changes':overrides,'cursor':event_changes.get('cursor')},
        series_sha256=digest(series),series_changes_sha256=digest(series_changes),
        event_changes_sha256=digest(event_changes),event_ticker=event)


async def kalshi_prop_fee_contexts(reader: KalshiReader, supported: dict,
        linked_games: dict) -> tuple[dict, list[dict]]:
    """Capture public fee terms before quotes without making fee availability a price gate."""
    contexts={};failures=[];semaphore=asyncio.Semaphore(PROP_FEE_CONCURRENCY)
    for series in supported:
        events=sorted(event for event in linked_games if event.startswith(series+'-'))
        if not events:
            continue
        try:
            series_data,series_changes=await asyncio.gather(
                reader.series(series),reader.series_fee_changes(series))
        except Exception as exc:
            failures.append(dict(stage='prop_fees',series=series,error_type=type(exc).__name__))
            continue

        async def capture(event: str):
            async with semaphore:
                changes=await reader.event_fee_changes(event)
                return prop_fee_context(series_data,series_changes,event,changes,
                    datetime.now(timezone.utc))

        results=await asyncio.gather(*(capture(event) for event in events),return_exceptions=True)
        for event,result in zip(events,results):
            if isinstance(result,Exception):
                failures.append(dict(stage='prop_fees',series=series,event_ticker=event,
                    error_type=type(result).__name__))
            else:
                contexts[event]=result
    return contexts,failures


async def sportsbooks(sport: str, daily_credit_limit: int) -> dict:
    if not settings.odds_api_key:
        raise ValueError('Provider not configured')
    if not Ledger().reserve_api_credits(1, daily_credit_limit):
        return dict(status='budget_exhausted', events=[])
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.get(f'https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/odds',
            params=dict(apiKey=settings.odds_api_key, regions='us', markets='h2h', oddsFormat='american'))
        if response.status_code != 200:
            raise RuntimeError(f'Quote provider HTTP {response.status_code}')
    return dict(status='observed', received_at=datetime.now(timezone.utc).isoformat(),
        events=response.json(), response_sha256=hashlib.sha256(response.content).hexdigest())


async def discover_kalshi_games(reader: KalshiReader, sport: str, now: datetime):
    """Bound discovery to three 500-record pages; never assume provider sort order."""
    series='KXNFLGAME' if sport=='nfl' else 'KXNBAGAME'
    pages=[];failures=[];eligible={};conflicts=set();seen_cursors=set();cursor=None
    for _ in range(3):
        try:
            page=await reader.milestones(sport,now,limit=500,cursor=cursor)
            pages.append(page)
            if not isinstance(page.get('milestones'),list):raise ValueError('Invalid discovery page')
        except Exception as exc:
            failures.append(dict(stage='discovery',error_type=type(exc).__name__))
            break
        for milestone in page['milestones']:
            try:
                details=milestone.get('details',{})
                event=details.get('main_game_event_ticker','')
                if details.get('league')!=sport.upper() or not event.startswith(series+'-'):continue
                start=timestamp(milestone['start_date'])
                if not now<start<=now+timedelta(days=7):continue
                identity=(start,details['home_team_id'],details['away_team_id'])
                if not all(identity[1:]) or identity[1]==identity[2]:raise ValueError('Invalid teams')
                if event in conflicts:continue
                if event in eligible:
                    prior=eligible[event]
                    if identity!=(timestamp(prior['start_date']),prior['details']['home_team_id'],prior['details']['away_team_id']):
                        del eligible[event]
                        conflicts.add(event)
                        raise ValueError('Conflicting milestone identity')
                else:eligible[event]=milestone
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                failures.append(dict(stage='milestone',error_type=type(exc).__name__))
        cursor=page.get('cursor')
        if cursor is not None and not isinstance(cursor,str):
            failures.append(dict(stage='discovery',error_type='InvalidCursor'))
            break
        if not cursor:break
        if cursor in seen_cursors:
            failures.append(dict(stage='discovery',error_type='InvalidCursor'))
            break
        seen_cursors.add(cursor)
    ordered=sorted(eligible.values(),key=lambda m:(timestamp(m['start_date']),m['details']['main_game_event_ticker']))
    return ordered,pages,failures,not cursor and not failures


async def kalshi_prop_inventory(reader: KalshiReader, sport: str, games: list[dict]) -> dict:
    """Retain compact top-of-book props linked to exact structured game milestones.

    Full market pages are hashed but not retained in the periodic dashboard snapshot.
    List-market top-of-book fields avoid one order-book request per prop. They are
    screening evidence only until player identity and settlement rules are matched.
    """
    if sport not in KALSHI_PROP_SERIES or not isinstance(games,list):
        raise ValueError('Invalid Kalshi prop inventory request')
    supported=KALSHI_PROP_SERIES[sport]
    linked_games={};conflicts=set();failures=[]
    for game in games:
        try:
            game_id=game['id']
            related=game['related_event_tickers']
            if (not isinstance(game_id,str) or not game_id or not isinstance(related,list)
                    or game['details']['league']!=sport.upper()):
                raise ValueError
        except (KeyError,ValueError,TypeError):
            failures.append(dict(stage='prop_link',error_type='InvalidMilestone'))
            continue
        for event in related:
            if not isinstance(event,str):
                failures.append(dict(stage='prop_link',error_type='InvalidEvent'))
                continue
            series=event.split('-',1)[0]
            if series not in supported:
                continue
            if event in conflicts:
                continue
            if event in linked_games and linked_games[event]['id']!=game_id:
                del linked_games[event]
                conflicts.add(event)
                failures.append(dict(stage='prop_link',error_type='ConflictingEvent'))
            else:
                linked_games[event]=game

    fee_contexts,fee_failures=await kalshi_prop_fee_contexts(reader,supported,linked_games)
    results={}
    all_markets=set();all_events=set();linked_markets=set();linked_events=set();quotes=[]
    for series in supported:
        cursor=None;seen_cursors=set();pages=[];tickers=set();events=set();linked=set();linked_event_set=set()
        status='observed';complete=False
        try:
            for _ in range(MAX_PROP_PAGES):
                request_started=datetime.now(timezone.utc)
                page=await reader.markets(series,limit=PROP_PAGE_LIMIT,cursor=cursor)
                received_at=datetime.now(timezone.utc)
                if not isinstance(page,dict) or not isinstance(page.get('markets'),list):
                    raise ValueError('Invalid market page')
                page_cursor=page.get('cursor')
                if page_cursor is not None and not isinstance(page_cursor,str):
                    raise ValueError('Invalid market cursor')
                pages.append(page)
                page_sha256=digest(page)
                for market in page['markets']:
                    event=market['event_ticker'];ticker=market['ticker']
                    if (not isinstance(event,str) or not isinstance(ticker,str)
                            or not event.startswith(series+'-') or not ticker.startswith(event+'-')
                            or market.get('status')!='active' or market.get('market_type')!='binary'
                            or Decimal(market['notional_value_dollars'])!=1 or ticker in tickers):
                        raise ValueError('Invalid prop market identity')
                    tickers.add(ticker);events.add(event)
                    if event in linked_games:
                        linked.add(ticker);linked_event_set.add(event)
                        quotes.append(kalshi_prop_quote(market,series,supported[series],linked_games[event],
                            request_started,received_at,page_sha256))
                cursor=page_cursor
                if not cursor:
                    complete=True
                    break
                if cursor in seen_cursors:
                    raise ValueError('Repeated market cursor')
                seen_cursors.add(cursor)
            if not complete:
                status='partial'
                failures.append(dict(stage='prop_discovery',series=series,error_type='PageLimitExceeded'))
        except (KeyError,ValueError,TypeError,ArithmeticError) as exc:
            status='invalid'
            failures.append(dict(stage='prop_discovery',series=series,error_type=type(exc).__name__))
        except Exception as exc:
            status='unavailable'
            failures.append(dict(stage='prop_discovery',series=series,error_type=type(exc).__name__))
        all_markets.update(tickers);all_events.update(events)
        linked_markets.update(linked);linked_events.update(linked_event_set)
        results[series]=dict(status=status,complete=complete,pages=len(pages),open_markets=len(tickers),
            open_events=len(events),linked_markets=len(linked),linked_events=len(linked_event_set),
            response_sha256=digest(pages) if pages else None)
    target_records={}
    if quotes:
        try:
            request_started=datetime.now(timezone.utc)
            target_page=await reader.targets(sorted({quote['player_target_id'] for quote in quotes}))
            received_at=datetime.now(timezone.utc)
            targets=target_page['structured_targets']
            if not isinstance(targets,list) or target_page.get('cursor') or len({target['id'] for target in targets})!=len(targets):
                raise ValueError('Invalid structured target page')
            by_id={str(UUID(target['id'])):target for target in targets}
            expected={quote['player_target_id'] for quote in quotes}
            if set(by_id)!=expected:
                raise ValueError('Incomplete structured target page')
            page_sha256=digest(target_page)
            teams_by_player={}
            for quote in quotes:
                teams_by_player.setdefault(quote['player_target_id'],set()).add(quote['team_target_id'])
            for target_id,target in by_id.items():
                name=target['name'].strip()
                team_id=str(UUID(target['details']['team_id']))
                kind='football' if sport=='nfl' else 'basketball'
                if (target.get('type')!=kind+'_player' or target['details'].get('league')!=sport.upper()
                        or not name or teams_by_player[target_id]!={team_id}):
                    raise ValueError('Structured target does not match prop')
                target_records[target_id]=dict(player_name=name,team_target_id=team_id,
                    target_sha256=digest(target),
                    target_page_sha256=page_sha256,target_request_started_at=request_started.isoformat(),
                    target_received_at=received_at.isoformat())
        except (KeyError,ValueError,TypeError,AttributeError) as exc:
            failures.append(dict(stage='prop_targets',error_type=type(exc).__name__))
        except Exception as exc:
            failures.append(dict(stage='prop_targets',error_type=type(exc).__name__))
    coverage=dict(series_expected=len(supported),series_observed=sum(r['status']=='observed' for r in results.values()),
        open_markets=len(all_markets),open_events=len(all_events),linked_markets=len(linked_markets),
        linked_events=len(linked_events),structured_quote_markets=len(quotes),
        two_sided_quote_markets=sum(bool(q['yes_ask'] and q['no_ask']) for q in quotes),
        player_resolved_quote_markets=sum(quote['player_target_id'] in target_records for quote in quotes),
        fee_contexts_expected=len(linked_games),fee_contexts_observed=len(fee_contexts),
        discovery_complete=not failures and all(r['complete'] for r in results.values()))
    return dict(status='degraded' if failures else 'observed',series=results,quotes=quotes,targets=target_records,
        fee_contexts=fee_contexts,coverage=coverage,failures=failures,fee_failures=fee_failures,
        partial_coverage=not coverage['discovery_complete'],
        scope='Open-market top-of-book observations linked by Kalshi structured milestone, player and team IDs. Kalshi player names are resolved in one bulk structured-target read. Public series and event fee terms are captured independently; missing fee evidence does not discard prices. Full pages are hashed but omitted. One displayed level is not a fill; cross-provider settlement equivalence remains unverified, and no profit is inferred.')


def kalshi_prop_quote(market: dict, series: str, prop_type: str, game: dict,
        request_started: datetime, received_at: datetime, page_sha256: str) -> dict:
    """Normalize one structured prop and verify the listed asks against bid complements."""
    kind='football' if game['details']['league']=='NFL' else 'basketball'
    player_key=kind+'_player';team_key=kind+'_team'
    custom=market['custom_strike']
    player_id=str(UUID(custom[player_key]));team_id=str(UUID(custom[team_key]))
    team_ids={str(UUID(game['details'][side+'_team_id'])) for side in ('home','away')}
    line=Decimal(str(market['floor_strike']))
    occurrence=timestamp(market['occurrence_datetime'])
    if (series not in KALSHI_PROP_SERIES[game['details']['league'].lower()]
            or market.get('primary_participant_key')!=player_key or team_id not in team_ids
            or market.get('strike_type')!='greater' or not line.is_finite() or line<0
            or request_started.utcoffset() is None or received_at.utcoffset() is None
            or not request_started<=received_at or len(page_sha256)!=64):
        raise ValueError('Invalid structured prop evidence')

    def ask(side: str) -> dict | None:
        if side=='yes':
            bid_key,size_key,ask_key='no_bid_dollars','yes_ask_size_fp','yes_ask_dollars'
        else:
            bid_key,size_key,ask_key='yes_bid_dollars','yes_bid_size_fp','no_ask_dollars'
        if not all(isinstance(market.get(key),str) for key in (bid_key,size_key,ask_key)):
            raise ValueError('Expected fixed-point quote strings')
        bid,size,reported=map(Decimal,(market[bid_key],market[size_key],market[ask_key]))
        if not all(value.is_finite() for value in (bid,size,reported)):
            raise ValueError('Invalid prop quote')
        if bid==0 and size==0 and reported in (0,1):
            return None
        cost=1-bid
        if not 0<bid<1 or size<=0 or reported!=cost:
            raise ValueError('Inconsistent prop top of book')
        return dict(cost=str(cost),displayed_size=str(size))

    yes_ask,no_ask=ask('yes'),ask('no')
    if yes_ask and no_ask and Decimal(yes_ask['cost'])+Decimal(no_ask['cost'])<1:
        raise ValueError('Crossed prop top of book')
    rules=dict(primary=market.get('rules_primary'),secondary=market.get('rules_secondary'))
    if not all(isinstance(value,str) and value.strip() for value in rules.values()):
        raise ValueError('Missing prop settlement rules')
    result=dict(ticker=market['ticker'],event_ticker=market['event_ticker'],series_ticker=series,
        milestone_id=game['id'],scheduled_game_start_time=timestamp(game['start_date']).isoformat(),
        market_occurrence_time=occurrence.isoformat(),
        prop_type=prop_type,player_target_id=player_id,team_target_id=team_id,
        strike_type='greater',line=str(line),yes_ask=yes_ask,no_ask=no_ask,
        request_started_at=request_started.isoformat(),received_at=received_at.isoformat(),
        market_sha256=digest(market),source_page_sha256=page_sha256,rules_sha256=digest(rules),
        settlement_equivalent=False,execution_ready=False)
    waiver=market.get('fee_waiver_expiration_time')
    if waiver is not None:
        result['fee_waiver_expiration_time']=timestamp(waiver).isoformat()
    return result


async def kalshi_games(sport: str, now: datetime, limit: int) -> dict:
    if sport not in ('nfl','nba') or now.utcoffset() is None or type(limit) is not int or not 1<=limit<=MAX_GAME_LIMIT:
        raise ValueError('Invalid Kalshi collection request')
    series = 'KXNFLGAME' if sport == 'nfl' else 'KXNBAGAME'
    async with KalshiReader() as reader:
        # Missing fee data must not discard otherwise valid price observations.
        try:
            series_data,series_changes=await asyncio.gather(reader.series(series),reader.series_fee_changes(series))
        except Exception:
            series_data=series_changes=None
        eligible,pages,failures,discovery_complete=await discover_kalshi_games(reader,sport,now)
        prop_inventory=await kalshi_prop_inventory(reader,sport,eligible[:limit])
        failures.extend(prop_inventory['failures'])
        games = []
        targets = {}
        failed_games=set();omitted_markets=0
        for milestone in eligible[:limit]:
            details = milestone['details']
            identity=details['main_game_event_ticker']
            try:
                event = await reader.event(identity)
                if event['event']['event_ticker']!=identity or event['event']['series_ticker']!=series:
                    raise ValueError('Returned event identity mismatch')
                active=[m for m in event['markets'] if m['status']=='active']
                if any(m['event_ticker']!=identity for m in active) or len({m['ticker'] for m in active})!=len(active):
                    raise ValueError('Invalid event markets')
                for side in ('home', 'away'):
                    target_id = details[side+'_team_id']
                    if target_id not in targets:
                        targets[target_id] = await reader.target(target_id)
            except Exception as exc:
                failures.append(dict(stage='event',event_ticker=identity,error_type=type(exc).__name__))
                failed_games.add(identity)
                continue
            fee_context={'status':'unavailable'}
            if series_data is not None and series_changes is not None:
                try:
                    changes=await reader.event_fee_changes(details['main_game_event_ticker'])
                    fee_context=dict(status='observed',series=series_data,series_changes=series_changes,
                        event_changes=changes,received_at=datetime.now(timezone.utc).isoformat())
                except Exception:
                    pass
            snapshots=[]
            omitted_markets+=max(0,len(active)-3)
            for market in active[:3]:
                try:
                    snapshot=await reader.snapshot(market['ticker'])
                    if snapshot['market'].get('event_ticker')!=identity:
                        raise ValueError('Snapshot event identity mismatch')
                    if snapshot['market'].get('status')!='active':continue
                    snapshots.append(snapshot)
                except Exception as exc:
                    failures.append(dict(stage='market',event_ticker=identity,market_ticker=market['ticker'],error_type=type(exc).__name__))
                    failed_games.add(identity)
            games.append(dict(milestone=milestone, event=event, snapshots=snapshots,fee_context=fee_context))
    teams = None
    try:
        path = 'football/nfl' if sport=='nfl' else 'basketball/nba'
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(f'https://site.api.espn.com/apis/site/v2/sports/{path}/teams')
            response.raise_for_status()
            teams = response.json()
    except (httpx.HTTPError, ValueError):
        pass  # Same-contract observations remain valid; cross-venue identity stays unmatched.
    prop_coverage=prop_inventory['coverage']
    return dict(status='degraded' if failures else 'observed', games=games, targets=targets,
        discovery_pages=pages,team_directory=teams,failures=failures,
        prop_inventory=prop_inventory,
        partial_coverage=not discovery_complete or len(eligible)>limit or bool(failed_games) or bool(omitted_markets)
            or prop_inventory['partial_coverage'],
        coverage=dict(discovery_complete=discovery_complete,discovered_games=len(eligible),
            attempted_games=min(limit,len(eligible)),observed_games=len(games),failed_games=len(failed_games),
            quoted_games=sum(bool(game['snapshots']) for game in games),omitted_markets=omitted_markets,
            prop_discovery_complete=prop_coverage['discovery_complete'],
            prop_series_observed=prop_coverage['series_observed'],prop_series_expected=prop_coverage['series_expected'],
            prop_open_markets=prop_coverage['open_markets'],prop_open_events=prop_coverage['open_events'],
            prop_linked_markets=prop_coverage['linked_markets'],prop_linked_events=prop_coverage['linked_events'],
            prop_structured_quote_markets=prop_coverage['structured_quote_markets'],
            prop_two_sided_quote_markets=prop_coverage['two_sided_quote_markets'],
            prop_player_resolved_quote_markets=prop_coverage['player_resolved_quote_markets'],
            prop_fee_contexts_expected=prop_coverage['fee_contexts_expected'],
            prop_fee_contexts_observed=prop_coverage['fee_contexts_observed'],
            prop_fee_failures=len(prop_inventory['fee_failures'])))


def book_quotes(event: dict, now: datetime) -> list[dict]:
    """Only full-game two-team h2h quotes with actual provider timing."""
    if not event.get('id') or not now < timestamp(event['commence_time']) <= now+timedelta(days=7):
        return []
    teams = {event['home_team'], event['away_team']}
    quotes = []
    for book in event.get('bookmakers', []):
        for market in book.get('markets', []):
            if market.get('key') != 'h2h' or {o.get('name') for o in market.get('outcomes', [])} != teams:
                continue
            try:
                observed = timestamp(market.get('last_update') or book['last_update'])
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if not -1 <= (now-observed).total_seconds() <= 300:
                continue
            for outcome in market['outcomes']:
                price = outcome.get('price')
                if type(price) is int and abs(price) >= 100:
                    quotes.append(dict(team=outcome['name'], book=book['key'], price=price,
                        cost=str(american_to_raw_prob(price)), observed_at=observed.isoformat()))
    return quotes


def kalshi_team_aliases(source: dict, sport: str) -> dict[str,list[str]]:
    """Return only exact captured team names, including one unambiguous ESPN alias."""
    directory={}
    sports=(source.get('team_directory') or {}).get('sports') or [{}]
    for league in sports[0].get('leagues',[]):
        if league.get('abbreviation','').upper()!=sport.upper():
            continue
        for item in league.get('teams',[]):
            team=item['team']
            directory.setdefault(team['abbreviation'],set()).add(team['displayName'])
    aliases={}
    for target_id,target in source.get('targets',{}).items():
        names={target.get('name'),target.get('details',{}).get('team_name')}
        official=directory.get(target.get('details',{}).get('abbreviation'),set())
        if len(official)==1:
            names.update(official)
        aliases[target_id]=sorted(name for name in names if isinstance(name,str) and name.strip())
    return aliases


def kalshi_prop_handoff(source: dict, sport: str, captured_at: str) -> dict:
    """Build the private worker handoff without exposing full game/order-book payloads."""
    inventory=source.get('prop_inventory')
    if not isinstance(inventory,dict):
        return dict(schema_version=1,sport=sport,captured_at=captured_at,status='unavailable',
            evidence=None,evidence_sha256=None,execution_ready=False)
    aliases=kalshi_team_aliases(source,sport)
    games=[]
    for item in source.get('games',[]):
        milestone=item['milestone'];details=milestone['details']
        home_id,away_id=details['home_team_id'],details['away_team_id']
        if home_id not in aliases or away_id not in aliases:
            continue
        games.append(dict(milestone_id=milestone['id'],scheduled_game_start_time=timestamp(
            milestone['start_date']).isoformat(),main_game_event_ticker=details['main_game_event_ticker'],
            home_team_id=home_id,away_team_id=away_id,home_team_aliases=aliases[home_id],
            away_team_aliases=aliases[away_id]))
    quote_games={quote.get('milestone_id') for quote in inventory.get('quotes',[])}
    context_games={game['milestone_id'] for game in games}
    incomplete=inventory.get('partial_coverage',True) or not quote_games<=context_games
    evidence=dict(quotes=inventory.get('quotes',[]),player_targets=inventory.get('targets',{}),
        fee_contexts=inventory.get('fee_contexts',{}),games=games,coverage=inventory.get('coverage',{}),
        partial_coverage=incomplete)
    status='degraded' if incomplete else inventory.get('status','unavailable')
    return dict(schema_version=2,sport=sport,captured_at=captured_at,status=status,
        evidence=evidence,evidence_sha256=digest(evidence),execution_ready=False)


def comparisons(evidence: dict) -> list[dict]:
    """Binary win-only algebra, deliberately blocked pending full settlement review."""
    version=evidence.get('schema_version',1)
    if type(version) is not int or version not in (1,2):
        raise ValueError('Unsupported market evidence version')
    now = timestamp(evidence['captured_at'])
    rows = []
    events = evidence['sources'].get('sportsbook', {}).get('events', [])
    books = {}
    for event in events:
        quotes = book_quotes(event, now)
        if not quotes:
            continue
        books[event['id']] = (event, quotes)
        pair = [min((q for q in quotes if q['team']==team), key=lambda q:Decimal(q['cost']), default=None)
                for team in (event['home_team'],event['away_team'])]
        if all(pair):
            rows.append(price_row('sportsbooks', event['id'], event['home_team']+' / '+event['away_team'], pair,
                ['Settlement rules and account limits unverified; tie/void states excluded.']))
    kalshi = evidence['sources'].get('kalshi', {})
    aliases=kalshi_team_aliases(kalshi,evidence['sport'])
    for game in kalshi.get('games', []):
        milestone = game['milestone']
        details = milestone['details']
        # Exact provider names only. Never infer identity from ticker suffixes or fuzzy text.
        def names(side):
            return set(aliases.get(details[side+'_team_id'],[]))
        matched = [(e,q) for e,q in books.values() if e['home_team'] in names('home') and e['away_team'] in names('away')
            and timestamp(e['commence_time']) == timestamp(milestone['start_date'])]
        for snap in game['snapshots']:
            market = snap['market']
            if market.get('notional_value_dollars') != '1.0000':
                continue
            base_reasons = ['Fees unverified; displayed depth does not establish a fill.']
            fee_scenarios=None
            sized_orders={}
            try:
                context=game['fee_context']
                if market.get('status')!='active' or market.get('market_type')!='binary':
                    raise ValueError('Fee scenario requires an active binary market')
                if market.get('fee_waiver_expiration_time') and timestamp(market['fee_waiver_expiration_time'])>now:
                    raise ValueError('Active market fee waiver requires separate review')
                if timestamp(context['received_at'])>timestamp(snap['received_at']):
                    raise ValueError('Fee context was unavailable at the quote observation')
                if context['series']['ticker']!=game['event']['event']['series_ticker']:
                    raise ValueError('Series fee identity mismatch')
                if market['event_ticker']!=details['main_game_event_ticker']:
                    raise ValueError('Market fee identity mismatch')
                _,multiplier=fee_terms(context,market['event_ticker'],now)
                fee_scenarios={side:{label:taker_buy_cost(Decimal(snap[side+'_asks'][0][0]),Decimal(1),multiplier,precision)
                    for label,precision in (('direct',Decimal('.0001')),('non_direct',Decimal('.01')))}
                    for side in ('yes','no') if snap[side+'_asks'] and Decimal(snap[side+'_asks'][0][1])>=1}
                for count in ((1,10,100) if version==2 else ()):
                    sized_orders[count]={}
                    for side in ('yes','no'):
                        try:
                            sized_orders[count][side]={label:taker_depth_cost(snap[side+'_asks'],Decimal(count),multiplier,precision)
                                for label,precision in (('direct',Decimal('.0001')),('non_direct',Decimal('.01')))}
                        except (ValueError,ArithmeticError):
                            pass  # Insufficient or invalid depth cannot support this requested size.
            except (KeyError,ValueError,TypeError,ArithmeticError):
                pass
            if snap['same_contract_pair']:
                legs = [dict(book='kalshi', team=side.upper(), cost=snap[side+'_asks'][0][0],
                    displayed_size=snap[side+'_asks'][0][1], observed_at=snap['received_at']) for side in ('yes','no')]
                row=price_row('kalshi_pair', market['ticker'], market['title'], legs, base_reasons)
                if fee_scenarios and set(fee_scenarios)=={'yes','no'}:
                    row['exchange_fee_scenarios']=fee_cost_scenarios(fee_scenarios)
                if sized_orders:
                    row['depth_fee_scenarios']=depth_cost_scenarios(sized_orders,('yes','no'))
                rows.append(row)
            if len(matched) != 1:
                continue
            event, quotes = matched[0]
            target = market.get('custom_strike', {}).get('football_team' if evidence['sport']=='nfl' else 'basketball_team')
            if target not in (details['home_team_id'], details['away_team_id']):
                continue
            team = event['home_team'] if target==details['home_team_id'] else event['away_team']
            for side in ('yes','no'):
                opposite = [q for q in quotes if (q['team'] != team if side=='yes' else q['team']==team)]
                if not opposite or not snap[side+'_asks']:
                    continue
                quote = min(opposite,key=lambda q:Decimal(q['cost']))
                legs = [dict(book='kalshi', team=side.upper()+' '+team, cost=snap[side+'_asks'][0][0],
                    displayed_size=snap[side+'_asks'][0][1], observed_at=snap['received_at']), quote]
                row=price_row('kalshi_sportsbook', market['ticker']+':'+side, milestone['title'], legs,
                    base_reasons+['Team/time match only. Tie, postponement, cancellation and account limits need review.'])
                if fee_scenarios and side in fee_scenarios:
                    row['exchange_fee_scenarios']=fee_cost_scenarios({side:fee_scenarios[side]},Decimal(quote['cost']))
                if sized_orders:
                    row['depth_fee_scenarios']=depth_cost_scenarios(sized_orders,(side,),Decimal(quote['cost']))
                rows.append(row)
    return sorted(rows, key=lambda r:Decimal(r['gross_gap_to_one_dollar']), reverse=True)


def fee_cost_scenarios(legs: dict, other_principal: Decimal=Decimal(0)) -> dict:
    return dict(legs=legs,
        combined_cost={label:str(other_principal+sum((Decimal(leg[label]['total_cost']) for leg in legs.values()),Decimal(0)))
            for label in ('direct','non_direct')},
        schedule_ref='https://kalshi.com/docs/kalshi-fee-schedule.pdf',schedule_effective_date='2026-07-07',
        scope='One contract per Kalshi leg, one taker fill per leg, zero prior fee accumulator; July 7, 2026 quadratic formula with captured fee multipliers. Excludes sportsbook/FCM, funding and exceptional settlement charges. Not a fill or profit bound.')


def depth_cost_scenarios(orders: dict, sides: tuple, sportsbook_per_unit: Decimal=Decimal(0)) -> dict:
    cases=[]
    for count,available in orders.items():
        if not all(side in available for side in sides):
            continue
        legs={side:available[side] for side in sides}
        cases.append(dict(contracts_per_kalshi_leg=count,legs=legs,
            combined_cost={label:str(sportsbook_per_unit*count+sum(
                (Decimal(leg[label]['total_cost']) for leg in legs.values()),Decimal(0)))
                for label in ('direct','non_direct')}))
    return dict(cases=cases,
        scope='Hypothetical orders consuming displayed price levels, one taker fill per level and separate fee accumulators per leg. Only sizes covered by captured Kalshi depth are shown. Actual fill fragmentation, quote changes, sportsbook limits, FCM/funding and exceptional settlement charges are not modeled. Not a fill or profit bound.')


def price_row(kind, identity, title, legs, reasons):
    times = [timestamp(leg['observed_at']) for leg in legs]
    if (max(times)-min(times)).total_seconds() > 30:
        reasons = reasons+['Quote observations are more than 30 seconds apart.']
    cost = sum((Decimal(leg['cost']) for leg in legs), Decimal(0))
    return dict(kind=kind, identity=identity, title=title, legs=legs, gross_cost=str(cost),
        gross_gap_to_one_dollar=str(1-cost), status='unverified', reasons=reasons,
        fee_adjusted_profit=None, realized_profit=None, execution_ready=False)


async def run(sport: str, daily_credit_limit: int, game_limit: int, publish: bool, provider: str='all'):
    if sport not in ('nba','nfl') or provider not in ('all','sportsbook','kalshi','prizepicks') or type(game_limit) is not int or not 1<=game_limit<=MAX_GAME_LIMIT or daily_credit_limit<1:
        raise ValueError('Invalid market collection request')
    now = datetime.now(timezone.utc)
    collectors={'sportsbook':lambda:sportsbooks(sport,daily_credit_limit),
        'kalshi':lambda:kalshi_games(sport,now,game_limit),'prizepicks':lambda:capture_projections(sport)}
    selected=list(collectors) if provider=='all' else [provider]
    sources = {name:dict(status='not_requested',partial_coverage=True) for name in collectors if name not in selected}
    # Independent source failures are retained; a blocked endpoint is not an empty successful scan.
    results = await asyncio.gather(*(collectors[name]() for name in selected),return_exceptions=True)
    for name, result in zip(selected,results):
        sources[name] = dict(status='unavailable', error_type=type(result).__name__) if isinstance(result,Exception) else result
        if name=='prizepicks' and not isinstance(result,Exception):
            sources[name]['status']='observed'
    evidence = dict(schema_version=2, sport=sport, captured_at=datetime.now(timezone.utc).isoformat(), sources=sources)
    rows = comparisons(evidence)
    summary = dict(schema_version=2, sport=sport, captured_at=evidence['captured_at'], evidence_sha256=digest(evidence),
        sources={name:dict(status=source['status'], count=len(source.get('events',source.get('games',source.get('projections',[])))),
            partial_coverage=source.get('partial_coverage',True),**({'coverage':source['coverage']} if 'coverage' in source else {})) for name,source in sources.items()},
        comparisons=rows, execution_ready=False, realized_profit=None,
        scope='Observed prices only. Gross gaps exclude fees and full settlement states; they are not verified arbitrage or backtest returns.')
    archive = write_archive(dict(evidence=evidence, summary=summary),directory=Path('.local/market-watch'))
    if publish:
        if 'kalshi' in selected:
            publish_snapshot('kalshi-props:'+sport,kalshi_prop_handoff(sources['kalshi'],sport,evidence['captured_at']))
        publish_snapshot('markets:'+sport,summary)
    return summary, archive


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=['nba','nfl','both'], default='both')
    parser.add_argument('--daily-credit-limit', type=int, default=25)
    parser.add_argument('--game-limit', type=int, choices=range(1,MAX_GAME_LIMIT+1), default=DEFAULT_GAME_LIMIT)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--provider',choices=['all','sportsbook','kalshi','prizepicks'],default='all',
        help='Collect one provider independently; others are explicitly marked not_requested')
    parser.add_argument('--replay', type=Path, help='Recompute comparisons from an immutable capture; no network or publishing')
    args=parser.parse_args()
    if args.replay:
        if args.publish:
            parser.error('Replay cannot publish historical prices as current observations')
        archived=json.loads(args.replay.read_text(encoding='utf-8'))
        if digest(archived['evidence']) != archived['summary']['evidence_sha256']:
            raise SystemExit('Capture integrity check failed')
        rows=comparisons(archived['evidence'])
        matches=rows==archived['summary']['comparisons']
        print(json.dumps(dict(mode='observation_replay', comparisons=len(rows),
            matches_archived_comparisons=matches,
            positive_gross_gaps=sum(Decimal(r['gross_gap_to_one_dollar'])>0 for r in rows),
            realized_profit=None, execution_ready=False)))
        if not matches:
            raise SystemExit(2)
        return
    failed=False
    for sport in (['nfl','nba'] if args.sport=='both' else [args.sport]):
        try:
            summary,_ = asyncio.run(run(sport,args.daily_credit_limit,args.game_limit,args.publish,args.provider))
            unavailable=not summary['sources'] or any(source['status'] not in ('observed','not_requested')
                for source in summary['sources'].values())
            failed=failed or unavailable
            print(json.dumps(dict(sport=sport,status='degraded' if unavailable else 'observed',
                sources=summary['sources'],comparisons=len(summary['comparisons']),execution_ready=False)))
        except Exception as exc:
            failed=True
            # A failed league must not suppress the other league; never expose exception text.
            print(json.dumps(dict(sport=sport,status='failed',error_type=type(exc).__name__,execution_ready=False)))
    if failed:
        raise SystemExit(2)


if __name__=='__main__':
    main()
