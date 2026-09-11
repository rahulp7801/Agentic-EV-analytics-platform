"""Capture read-only venue evidence and publish explicitly unverified price comparisons."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from sportsbet.config import settings
from sportsbet.dashboard import publish_snapshot
from sportsbet.ingestion.archive import write_archive
from sportsbet.ingestion.kalshi import KalshiReader
from sportsbet.ingestion.prizepicks import capture as capture_projections
from sportsbet.ledger import Ledger
from sportsbet.scan import SPORT_KEYS, timestamp
from sportsbet.quant.vig import american_to_raw_prob
from sportsbet.arbitrage.kalshi_fees import fee_terms, taker_buy_cost


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


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


async def kalshi_games(sport: str, now: datetime, limit: int) -> dict:
    series = 'KXNFLGAME' if sport == 'nfl' else 'KXNBAGAME'
    async with KalshiReader() as reader:
        # Missing fee data must not discard otherwise valid price observations.
        try:
            series_data,series_changes=await asyncio.gather(reader.series(series),reader.series_fee_changes(series))
        except Exception:
            series_data=series_changes=None
        page = await reader.milestones(sport, now)
        eligible = [m for m in page['milestones'] if now < timestamp(m['start_date']) <= now+timedelta(days=7)
            and m.get('details', {}).get('league') == sport.upper()
            and m.get('details', {}).get('main_game_event_ticker', '').startswith(series+'-')]
        eligible.sort(key=lambda m: m['start_date'])
        games = []
        targets = {}
        for milestone in eligible[:limit]:
            details = milestone['details']
            event = await reader.event(details['main_game_event_ticker'])
            fee_context={'status':'unavailable'}
            if series_data is not None and series_changes is not None:
                try:
                    changes=await reader.event_fee_changes(details['main_game_event_ticker'])
                    fee_context=dict(status='observed',series=series_data,series_changes=series_changes,
                        event_changes=changes,received_at=datetime.now(timezone.utc).isoformat())
                except Exception:
                    pass
            for side in ('home', 'away'):
                target_id = details[side+'_team_id']
                if target_id not in targets:
                    targets[target_id] = await reader.target(target_id)
            snapshots = [await reader.snapshot(m['ticker']) for m in event['markets'][:3] if m['status']=='active']
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
    return dict(status='observed', games=games, targets=targets, discovery_page=page, team_directory=teams,
        partial_coverage=bool(page.get('cursor')) or len(eligible)>limit,
        eligible_on_page=len(eligible), sampled_games=len(games))


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


def comparisons(evidence: dict) -> list[dict]:
    """Binary win-only algebra, deliberately blocked pending full settlement review."""
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
    directory = {}
    for league in (kalshi.get('team_directory') or {}).get('sports', [{}])[0].get('leagues', []):
        if league.get('abbreviation', '').upper() != evidence['sport'].upper():
            continue
        for item in league.get('teams', []):
            team = item['team']
            directory.setdefault(team['abbreviation'], set()).add(team['displayName'])
    for game in kalshi.get('games', []):
        milestone = game['milestone']
        details = milestone['details']
        # Exact provider names only. Never infer identity from ticker suffixes or fuzzy text.
        def names(side):
            target = kalshi['targets'][details[side+'_team_id']]
            aliases = {target['name'], target.get('details', {}).get('team_name')}
            # Exact same-league abbreviation in a captured team directory; no fuzzy matching.
            official = directory.get(target.get('details', {}).get('abbreviation'), set())
            return aliases | official if len(official)==1 else aliases
        matched = [(e,q) for e,q in books.values() if e['home_team'] in names('home') and e['away_team'] in names('away')
            and timestamp(e['commence_time']) == timestamp(milestone['start_date'])]
        for snap in game['snapshots']:
            market = snap['market']
            if market.get('notional_value_dollars') != '1.0000':
                continue
            base_reasons = ['Fees unverified; displayed depth does not establish a fill.']
            fee_scenarios=None
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
            except (KeyError,ValueError,TypeError,ArithmeticError):
                pass
            if snap['same_contract_pair']:
                legs = [dict(book='kalshi', team=side.upper(), cost=snap[side+'_asks'][0][0],
                    displayed_size=snap[side+'_asks'][0][1], observed_at=snap['received_at']) for side in ('yes','no')]
                row=price_row('kalshi_pair', market['ticker'], market['title'], legs, base_reasons)
                if fee_scenarios and set(fee_scenarios)=={'yes','no'}:
                    row['exchange_fee_scenarios']=fee_cost_scenarios(fee_scenarios)
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
                rows.append(row)
    return sorted(rows, key=lambda r:Decimal(r['gross_gap_to_one_dollar']), reverse=True)


def fee_cost_scenarios(legs: dict, other_principal: Decimal=Decimal(0)) -> dict:
    return dict(legs=legs,
        combined_cost={label:str(other_principal+sum((Decimal(leg[label]['total_cost']) for leg in legs.values()),Decimal(0)))
            for label in ('direct','non_direct')},
        schedule_ref='https://kalshi.com/docs/kalshi-fee-schedule.pdf',schedule_effective_date='2026-07-07',
        scope='One contract per Kalshi leg, one taker fill per leg, zero prior fee accumulator; July 7, 2026 quadratic formula with captured fee multipliers. Excludes sportsbook/FCM, funding and exceptional settlement charges. Not a fill or profit bound.')


def price_row(kind, identity, title, legs, reasons):
    times = [timestamp(leg['observed_at']) for leg in legs]
    if (max(times)-min(times)).total_seconds() > 30:
        reasons = reasons+['Quote observations are more than 30 seconds apart.']
    cost = sum((Decimal(leg['cost']) for leg in legs), Decimal(0))
    return dict(kind=kind, identity=identity, title=title, legs=legs, gross_cost=str(cost),
        gross_gap_to_one_dollar=str(1-cost), status='unverified', reasons=reasons,
        fee_adjusted_profit=None, realized_profit=None, execution_ready=False)


async def run(sport: str, daily_credit_limit: int, game_limit: int, publish: bool, provider: str='all'):
    if sport not in ('nba','nfl') or provider not in ('all','sportsbook','kalshi','prizepicks') or not 1<=game_limit<=10 or daily_credit_limit<1:
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
    evidence = dict(schema_version=1, sport=sport, captured_at=datetime.now(timezone.utc).isoformat(), sources=sources)
    rows = comparisons(evidence)
    summary = dict(schema_version=1, sport=sport, captured_at=evidence['captured_at'], evidence_sha256=digest(evidence),
        sources={name:dict(status=source['status'], count=len(source.get('events',source.get('games',source.get('projections',[])))),
            partial_coverage=source.get('partial_coverage',True)) for name,source in sources.items()},
        comparisons=rows, execution_ready=False, realized_profit=None,
        scope='Observed prices only. Gross gaps exclude fees and full settlement states; they are not verified arbitrage or backtest returns.')
    archive = write_archive(dict(evidence=evidence, summary=summary),directory=Path('.local/market-watch'))
    if publish:
        publish_snapshot('markets:'+sport,summary)
    return summary, archive


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=['nba','nfl','both'], default='both')
    parser.add_argument('--daily-credit-limit', type=int, default=25)
    parser.add_argument('--game-limit', type=int, choices=range(1,11), default=5)
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
        print(json.dumps(dict(mode='observation_replay', comparisons=len(rows),
            matches_archived_comparisons=rows==archived['summary']['comparisons'],
            positive_gross_gaps=sum(Decimal(r['gross_gap_to_one_dollar'])>0 for r in rows),
            realized_profit=None, execution_ready=False)))
        return
    for sport in (['nfl','nba'] if args.sport=='both' else [args.sport]):
        try:
            summary,_ = asyncio.run(run(sport,args.daily_credit_limit,args.game_limit,args.publish,args.provider))
            print(json.dumps(dict(sport=sport,sources=summary['sources'],comparisons=len(summary['comparisons']),execution_ready=False)))
        except Exception as exc:
            raise SystemExit(f'Market observation failed ({type(exc).__name__})') from None


if __name__=='__main__':
    main()
