"""Archive bounded public Kalshi prop history; no fills, fees or athlete outcomes inferred."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from sportsbet.ingestion.archive import write_archive
from sportsbet.ingestion.kalshi import KalshiReader, ticker_path

SERIES = {
    'nfl': {'KXNFLPASSYDS': 'pass_yds', 'KXNFLRSHYDS': 'rush_yds', 'KXNFLRECYDS': 'rec_yds', 'KXNFLREC': 'receptions'},
    'nba': {'KXNBAPTS': 'points', 'KXNBAREB': 'rebounds', 'KXNBAAST': 'assists'},
}
EASTERN = ZoneInfo('America/New_York')
SCOPE = ('Explicitly selected settled contracts, not a complete market universe. '
    'One-minute bid/ask closes relative to the archived scheduled game start; actual start and '
    'quote update time are unverified. Metadata may contain later corrections. '
    'Settlement is the contract result, not the player stat. No depth, fees, fills, CLV or ROI inferred.')


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('Timestamp requires timezone')
    return result


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_request(sport: str, day: date, tickers: list[str]) -> None:
    if sport not in SERIES or not 1 <= len(tickers) <= 20 or len(set(tickers)) != len(tickers):
        raise ValueError('Request 1..20 distinct supported prop tickers')
    for ticker in tickers:
        if ticker_path(ticker).split('-', 1)[0] not in SERIES[sport]:
            raise ValueError('Unsupported prop series for this sport')


def linked_game(market: dict, pages: list[dict], sport: str, day: date) -> dict:
    matches = {}
    for page in pages:
        for game in page['milestones']:
            if market['event_ticker'] not in game.get('related_event_tickers', []):
                continue
            game_id = str(UUID(game['id']))
            if game_id in matches and matches[game_id] != game:
                raise ValueError('Conflicting milestone')
            matches[game_id] = game
    game, = matches.values()
    kind = 'football' if sport == 'nfl' else 'basketball'
    details = game['details']
    if (game['type'] != kind+'_game' or details['league'] != sport.upper()
            or timestamp(game['start_date']).astimezone(EASTERN).date() != day):
        raise ValueError('Game identity mismatch')
    teams = {str(UUID(details[k])) for k in ('home_team_id', 'away_team_id')}
    if len(teams) != 2 or str(UUID(market['custom_strike'][kind+'_team'])) not in teams:
        raise ValueError('Game team mismatch')
    return game


def selected_market(evidence: dict, ticker: str) -> tuple[dict, bool]:
    matches = []
    requested = set(evidence['request']['tickers'])
    for page in evidence['market_pages']:
        if page['body'].get('cursor'):
            raise ValueError('Incomplete market lookup')
        for market in page['body']['markets']:
            if market['ticker'] not in requested:
                raise ValueError('Unexpected market identity')
            if market['ticker'] == ticker:
                matches.append((market, page['historical']))
    (market, historical), = matches
    series = ticker.split('-', 1)[0]
    if not market['event_ticker'].startswith(series+'-') or not ticker.startswith(market['event_ticker']+'-'):
        raise ValueError('Market event identity mismatch')
    return market, historical


def latest_quote(body: dict, ticker: str, historical: bool, cutoff: int, opened: datetime) -> dict | None:
    if body['ticker'] != ticker:
        raise ValueError('Candle identity mismatch')
    field = 'close' if historical else 'close_dollars'
    latest = None
    previous = -1
    for bar in body['candlesticks']:
        end = bar['end_period_ts']
        if (type(end) is not int or end % 60 or end <= previous
                or not cutoff-3600 <= end <= cutoff or end < opened.timestamp()):
            raise ValueError('Invalid candle timestamp')
        previous = end
        raw_bid, raw_ask = bar['yes_bid'].get(field), bar['yes_ask'].get(field)
        # A later null bar invalidates an older quote; never carry forward trade prices.
        latest = None
        if raw_bid is None or raw_ask is None:
            continue
        if not isinstance(raw_bid, str) or not isinstance(raw_ask, str):
            raise ValueError('Expected fixed-point dollar strings')
        bid, ask = Decimal(raw_bid), Decimal(raw_ask)
        if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask < 1:
            raise ValueError('Invalid bid/ask')
        if cutoff-end <= 60:
            latest = dict(candle_end_ts=end, yes_bid_dollars=str(bid), yes_ask_dollars=str(ask),
                cutoff_age_seconds=cutoff-end)
    return latest


def normalize(evidence: dict) -> dict:
    request = evidence['request']
    sport, day, tickers = request['sport'], date.fromisoformat(request['date']), request['tickers']
    validate_request(sport, day, tickers)
    rows, exclusions = [], []
    discovery_complete = (bool(evidence['milestone_pages'])
        and not evidence['milestone_pages'][-1].get('cursor') and not evidence.get('discovery_error'))
    for ticker in tickers:
        observation = evidence['observations'].get(ticker, {})
        reason = None
        try:
            if not discovery_complete:
                reason = 'incomplete_game_discovery'
            else:
                market, historical = selected_market(evidence, ticker)
                game = linked_game(market, evidence['milestone_pages'], sport, day)
                start, opened = timestamp(game['start_date']), timestamp(market['open_time'])
                cutoff = int((start-timedelta(minutes=15)).timestamp())
                if (market['status'] not in ('settled', 'finalized') or market['market_type'] != 'binary'
                        or Decimal(market['notional_value_dollars']) != 1
                        or timestamp(market['settlement_ts']) > timestamp(evidence['received_at'])
                        or timestamp(market['settlement_ts']) <= start):
                    raise ValueError('Invalid settled contract')
                if opened.timestamp() > cutoff or timestamp(market['close_time']).timestamp() <= cutoff:
                    reason = 'not_open_at_pregame_cutoff'
                elif observation.get('error_type'):
                    reason = 'provider_read_failed'
                else:
                    kind = 'football' if sport == 'nfl' else 'basketball'
                    player_id = str(UUID(market['custom_strike'][kind+'_player']))
                    target = observation['target']
                    if (target['id'] != player_id or target['type'] != kind+'_player'
                            or target['details']['league'] != sport.upper() or not target['name'].strip()):
                        raise ValueError('Player identity mismatch')
                    quote = latest_quote(observation['candles'], ticker, historical, cutoff, opened)
                    if quote is None:
                        reason = 'missing_or_stale_bid_ask'
                    else:
                        settlement = Decimal(market['settlement_value_dollars'])
                        if (not settlement.is_finite() or not 0 <= settlement <= 1
                                or market.get('result') not in ('yes', 'no')
                                or settlement != (1 if market['result'] == 'yes' else 0)):
                            raise ValueError('Invalid settlement value')
                        rows.append(dict(ticker=ticker, event_ticker=market['event_ticker'], sport=sport,
                            prop_type=SERIES[sport][ticker.split('-', 1)[0]], player_id=player_id,
                            player_name=target['name'], milestone_id=game['id'],
                            scheduled_game_start_time=start.isoformat(), cutoff_ts=cutoff,
                            historical_endpoint=historical, strike_type=market.get('strike_type'),
                            floor_strike=market.get('floor_strike'), result=market.get('result'),
                            settlement_value_dollars=str(settlement), settlement_time=market['settlement_ts'],
                            **quote, executable_depth=None, fee_adjusted_profit=None, execution_ready=False))
        except (KeyError, ValueError, TypeError, ArithmeticError):
            reason = 'invalid_or_incomplete_evidence'
        if reason:
            exclusions.append(dict(ticker=ticker, reason=reason))
    return dict(kind='kalshi_historical_props', schema_version=1, request=request,
        source_sha256=digest(evidence), records=rows, exclusions=exclusions,
        status='complete' if rows and not exclusions else 'incomplete',
        record_count=len(rows), requested_count=len(tickers), scope=SCOPE, roi=None, clv=None)


async def collect(reader: KalshiReader, sport: str, day: date, tickers: list[str]) -> dict:
    validate_request(sport, day, tickers)
    if day >= datetime.now(EASTERN).date():
        raise ValueError('Only past Eastern calendar dates are supported')
    evidence = dict(request=dict(sport=sport, date=str(day), tickers=tickers),
        request_started_at=datetime.now(timezone.utc).isoformat(),
        milestone_pages=[], market_pages=[], observations={})
    try:
        cursor = None
        for _ in range(3):
            page = await reader.milestones(sport, datetime.combine(day, time(), EASTERN), limit=500, cursor=cursor)
            evidence['milestone_pages'].append(page)
            cursor = page.get('cursor')
            if not cursor:
                break
        for historical in (False, True):
            page = await reader.settled_markets(tickers, historical=historical)
            evidence['market_pages'].append(dict(historical=historical, body=page))
    except Exception as exc:
        evidence['discovery_error'] = type(exc).__name__
    if not evidence.get('discovery_error') and not evidence['milestone_pages'][-1].get('cursor'):
        for ticker in tickers:
            observation = evidence['observations'][ticker] = {}
            try:
                market, historical = selected_market(evidence, ticker)
                game = linked_game(market, evidence['milestone_pages'], sport, day)
                cutoff = int((timestamp(game['start_date'])-timedelta(minutes=15)).timestamp())
                if (timestamp(market['open_time']).timestamp() > cutoff
                        or timestamp(market['close_time']).timestamp() <= cutoff):
                    continue
                kind = 'football' if sport == 'nfl' else 'basketball'
                observation['target'] = await reader.target(market['custom_strike'][kind+'_player'])
                observation['candles'] = await reader.minute_candles(ticker, historical=historical,
                    start_ts=cutoff-3600, end_ts=cutoff)
            except Exception as exc:
                observation['error_type'] = type(exc).__name__
    evidence['received_at'] = datetime.now(timezone.utc).isoformat()
    return dict(evidence=evidence, dataset=normalize(evidence))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=SERIES)
    parser.add_argument('--date', type=date.fromisoformat)
    parser.add_argument('--ticker', action='append', default=[])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    try:
        if args.replay:
            if args.sport or args.date or args.ticker or args.output:
                parser.error('--replay cannot be combined with collection options')
            archive = json.loads(args.replay.read_text(encoding='utf-8'))
            dataset = normalize(archive['evidence'])
            matches = dataset == archive['dataset']
            print(json.dumps(dict(matches=matches, record_count=dataset['record_count'], status=dataset['status'])))
            raise SystemExit(0 if matches else 2)
        if not args.sport or not args.date or not args.ticker:
            parser.error('collection requires --sport, --date and --ticker')

        async def run():
            async with KalshiReader() as reader:
                return await collect(reader, args.sport, args.date, args.ticker)

        archive = asyncio.run(run())
        path = write_archive(archive, args.output, directory=Path('.local/kalshi-history'))
        dataset = archive['dataset']
        print(json.dumps(dict(archive=str(path), status=dataset['status'],
            record_count=dataset['record_count'], exclusions=dataset['exclusions'])))
        raise SystemExit(0 if dataset['status'] == 'complete' else 2)
    except Exception as exc:
        raise SystemExit(f'Kalshi history failed ({type(exc).__name__})') from None


if __name__ == '__main__':
    main()
