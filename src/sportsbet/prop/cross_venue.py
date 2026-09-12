"""Fail-closed screening of exact sportsbook and Kalshi player-prop quotes."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal

from sportsbet.arbitrage.kalshi_fees import fee_terms, taker_buy_cost
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.quant.vig import american_to_raw_prob


PROP_MARKETS = {
    'nba': {'player_points': 'points', 'player_rebounds': 'rebounds', 'player_assists': 'assists'},
    'nfl': {'player_pass_yds': 'pass_yds', 'player_rush_yds': 'rush_yds',
            'player_reception_yds': 'rec_yds', 'player_receptions': 'receptions'},
}
MAX_AGE_SECONDS = 300
MAX_SKEW_SECONDS = 30


class InvalidHandoff(ValueError):
    """The internal evidence contract cannot safely support comparison."""


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise InvalidHandoff('invalid_timestamp')
    return parsed


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
        and all(character in '0123456789abcdef' for character in value))


def _name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidHandoff('invalid_identity')
    return ' '.join(value.casefold().split())


def _decimal(value, *, minimum=Decimal(0), maximum=None) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise InvalidHandoff('invalid_number') from exc
    if not result.is_finite() or result < minimum or (maximum is not None and result > maximum):
        raise InvalidHandoff('invalid_number')
    return result


def _unavailable(sport: str, now: datetime, reason: str) -> dict:
    return dict(schema_version=1, sport=sport, screened_at=now.isoformat(), status='unavailable',
        reason=reason, coverage={}, comparisons=[], execution_ready=False)


def _evidence(handoff: dict | None, sport: str, now: datetime) -> tuple[dict, datetime, int]:
    if not isinstance(handoff, dict):
        raise InvalidHandoff('missing_handoff')
    version=handoff.get('schema_version')
    if (type(version) is not int or version not in (1,2)
            or handoff.get('sport') != sport or handoff.get('status') != 'observed'
            or handoff.get('execution_ready') is not False):
        raise InvalidHandoff('handoff_not_observed')
    captured = _timestamp(handoff.get('captured_at'))
    age = (now-captured).total_seconds()
    if not -1 <= age <= MAX_AGE_SECONDS:
        raise InvalidHandoff('handoff_future_or_stale')
    evidence = handoff.get('evidence')
    if (not isinstance(evidence, dict) or handoff.get('evidence_sha256') != _digest(evidence)
            or evidence.get('partial_coverage') is not False):
        raise InvalidHandoff('handoff_incomplete_or_corrupt')
    coverage = evidence.get('coverage')
    counts = [coverage.get(key) for key in ('series_observed', 'series_expected',
        'player_resolved_quote_markets', 'structured_quote_markets')] if isinstance(coverage, dict) else []
    if (not isinstance(coverage, dict) or coverage.get('discovery_complete') is not True
            or any(type(value) is not int or value < 0 for value in counts)
            or coverage.get('series_expected', 0) < 1
            or coverage.get('series_observed') != coverage.get('series_expected')
            or coverage.get('player_resolved_quote_markets') != coverage.get('structured_quote_markets')):
        raise InvalidHandoff('handoff_incomplete_or_corrupt')
    if not isinstance(evidence.get('quotes'), list) or not isinstance(evidence.get('games'), list) \
            or not isinstance(evidence.get('player_targets'), dict):
        raise InvalidHandoff('handoff_incomplete_or_corrupt')
    if version==2:
        contexts=evidence.get('fee_contexts')
        fee_counts=[coverage.get(key) for key in ('fee_contexts_expected','fee_contexts_observed')]
        if (not isinstance(contexts,dict)
                or any(type(value) is not int or value<0 for value in fee_counts)
                or coverage['fee_contexts_observed']!=len(contexts)
                or coverage['fee_contexts_expected']<coverage['fee_contexts_observed']
                or any(not isinstance(event,str) or not event for event in contexts)):
            raise InvalidHandoff('handoff_incomplete_or_corrupt')
    return evidence, captured, version


def _game(event: dict, evidence: dict) -> dict | None:
    start = _timestamp(event.get('commence_time'))
    home, away = _name(event.get('home_team')), _name(event.get('away_team'))
    matches = []
    seen = set()
    for game in evidence['games']:
        try:
            milestone = game['milestone_id']
            if not isinstance(milestone, str) or not milestone or milestone in seen:
                raise InvalidHandoff('ambiguous_game_context')
            seen.add(milestone)
            if type(game['home_team_aliases']) is not list or type(game['away_team_aliases']) is not list:
                raise InvalidHandoff('invalid_game_context')
            aliases_home = {_name(value) for value in game['home_team_aliases']}
            aliases_away = {_name(value) for value in game['away_team_aliases']}
            if (not aliases_home or not aliases_away or game['home_team_id'] == game['away_team_id']
                    or not isinstance(game.get('main_game_event_ticker'), str)
                    or not game['main_game_event_ticker']
                    or _timestamp(game['scheduled_game_start_time']) != start):
                continue
            if home in aliases_home and away in aliases_away:
                matches.append(game)
        except (KeyError, TypeError):
            raise InvalidHandoff('invalid_game_context') from None
    if len(matches) > 1:
        raise InvalidHandoff('ambiguous_event_identity')
    return matches[0] if matches else None


def _ask(value) -> tuple[Decimal, Decimal] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidHandoff('invalid_quote')
    cost = _decimal(value.get('cost'), maximum=Decimal(1))
    size = _decimal(value.get('displayed_size'))
    if not 0 < cost < 1 or size <= 0:
        raise InvalidHandoff('invalid_quote')
    return cost, size


def _fee_scenario(evidence: dict, quote: dict, ask: tuple[Decimal, Decimal],
        sportsbook_cost: Decimal, observed_at: datetime) -> dict | None:
    """Price one hypothetical Kalshi taker contract from captured public fee terms."""
    if ask[1] < 1:
        return None
    event=quote.get('event_ticker');series=quote.get('series_ticker')
    context=evidence['fee_contexts'].get(event)
    if not isinstance(event,str) or not event or not isinstance(series,str) or not series \
            or not isinstance(context,dict):
        return None
    if (context.get('event_ticker')!=event or context.get('series',{}).get('ticker')!=series
            or not all(_sha256(context.get(key)) for key in (
                'series_sha256','series_changes_sha256','event_changes_sha256'))
            or _timestamp(context.get('received_at'))>observed_at):
        return None
    waiver=quote.get('fee_waiver_expiration_time')
    if waiver is not None and _timestamp(waiver)>observed_at:
        return None
    _,multiplier=fee_terms(context,event,observed_at)
    legs={label:taker_buy_cost(ask[0],Decimal(1),multiplier,precision)
        for label,precision in (('direct',Decimal('.0001')),('non_direct',Decimal('.01')))}
    return dict(kalshi_leg=legs,combined_cost={label:str(
        sportsbook_cost+Decimal(cost['total_cost'])) for label,cost in legs.items()},
        schedule_ref='https://kalshi.com/regulatory/fee-schedule',
        scope='One hypothetical Kalshi taker fill for one contract using captured fee terms. '
            'The sportsbook leg uses its quoted payout cost. Account limits, fills, funding, '
            'exceptional charges and settlement differences are excluded.')


def screen_sportsbooks(event: dict, sport: str, quotes: list[PlayerPropSnapshotCreate],
        now: datetime) -> dict:
    """Screen exact opposite props at distinct books using observed payout prices."""
    if sport not in PROP_MARKETS or now.utcoffset() is None:
        raise ValueError('Invalid screening request')
    try:
        start = _timestamp(event.get('commence_time'))
    except (InvalidHandoff, AttributeError, TypeError, ValueError):
        return _unavailable(sport, now, 'invalid_event')
    eligible=[];rejected=Counter()
    for quote in quotes:
        try:
            age=(now-quote.snapped_at).total_seconds()
        except (TypeError,AttributeError):
            rejected['sportsbook_timestamp'] += 1
            continue
        if (quote.sport != sport or quote.game_id != event.get('id')
                or quote.prop_type not in PROP_MARKETS[sport]):
            rejected['sportsbook_identity'] += 1
        elif (type(quote.price) is not int or abs(quote.price)<100
                or quote.implied_probability != american_to_raw_prob(quote.price)
                or quote.side not in ('Over','Under')):
            rejected['sportsbook_price'] += 1
        elif not -1 <= age <= MAX_AGE_SECONDS or quote.snapped_at >= start:
            rejected['sportsbook_future_or_stale'] += 1
        elif not isinstance(quote.line,Decimal) or not quote.line.is_finite() \
                or quote.line<0 or quote.line % 1 != Decimal('.5'):
            rejected['non_complementary_strike'] += 1
        else:
            eligible.append(quote)
    try:
        groups={(_name(quote.player_name),quote.prop_type,quote.line) for quote in eligible}
    except InvalidHandoff:
        return _unavailable(sport,now,'invalid_sportsbook_quote')
    comparisons=[];price_pairs=0
    for player,market,line in sorted(groups):
        matching=[quote for quote in eligible if (_name(quote.player_name),quote.prop_type,quote.line)==(
            player,market,line)]
        pairs=[(over,under) for over in matching if over.side=='Over' for under in matching
            if under.side=='Under' and over.sportsbook!=under.sportsbook
            and abs((over.snapped_at-under.snapped_at).total_seconds())<=MAX_SKEW_SECONDS]
        if not pairs:
            rejected['distinct_book_pair_or_skew'] += 1
            continue
        over,under=min(pairs,key=lambda pair:pair[0].implied_probability+pair[1].implied_probability)
        price_pairs += 1
        gross_cost=over.implied_probability+under.implied_probability
        if gross_cost >= 1:
            continue
        legs=[dict(venue='sportsbook',sportsbook=quote.sportsbook,side=quote.side,
            american_odds=quote.price,cost=str(quote.implied_probability),
            observed_at=quote.snapped_at.isoformat()) for quote in (over,under)]
        comparisons.append(dict(kind='sportsbook_sportsbook_prop',status='unverified',
            event_id=event['id'],player=over.player_name,prop_type=PROP_MARKETS[sport][market],line=str(line),
            legs=legs,gross_cost_to_one_dollar=str(gross_cost),gross_gap_to_one_dollar=str(1-gross_cost),
            settlement_equivalent=False,fee_adjusted_profit=None,realized_profit=None,execution_ready=False,
            reasons=['Sportsbook limits, DNP/void treatment, and stat rules are unreviewed.',
                'Observed prices can move and are not fills.']))
    return dict(schema_version=1,sport=sport,screened_at=now.isoformat(),status='observed',event_id=event['id'],
        coverage=dict(sportsbook_quotes=len(quotes),eligible_sportsbook_quotes=len(eligible),
            exact_markets=len(groups),price_pairs=price_pairs,positive_gross_gaps=len(comparisons),
            rejected=dict(rejected)),comparisons=comparisons,execution_ready=False)


def screen(event: dict, sport: str, sportsbook_quotes: list[PlayerPropSnapshotCreate],
        handoff: dict | None, now: datetime) -> dict:
    """Return positive gross price gaps only; no row is an executable arbitrage claim."""
    if sport not in PROP_MARKETS or now.utcoffset() is None:
        raise ValueError('Invalid screening request')
    try:
        evidence, captured, version = _evidence(handoff, sport, now)
        game = _game(event, evidence)
    except (InvalidHandoff, KeyError, TypeError, ValueError, AttributeError) as exc:
        reason = str(exc) if isinstance(exc, InvalidHandoff) else 'invalid_handoff'
        return _unavailable(sport, now, reason)
    if game is None:
        return _unavailable(sport, now, 'event_not_matched')

    start = _timestamp(event['commence_time'])
    team_ids = {game['home_team_id'], game['away_team_id']}
    targets = evidence['player_targets']
    names = Counter()
    for target in targets.values():
        try:
            if (not _sha256(target['target_sha256']) or not _sha256(target['target_page_sha256'])
                    or _timestamp(target['target_request_started_at']) > _timestamp(target['target_received_at'])
                    or _timestamp(target['target_received_at']) > captured):
                raise InvalidHandoff('invalid_player_targets')
            if target['team_target_id'] in team_ids:
                names[_name(target['player_name'])] += 1
        except (InvalidHandoff, KeyError, TypeError, ValueError, AttributeError):
            return _unavailable(sport, now, 'invalid_player_targets')

    books = []
    rejected = Counter()
    for quote in sportsbook_quotes:
        age = (now-quote.snapped_at).total_seconds()
        if quote.sport != sport or quote.game_id != event.get('id') or quote.prop_type not in PROP_MARKETS[sport]:
            rejected['sportsbook_identity'] += 1
        elif not -1 <= age <= MAX_AGE_SECONDS or quote.snapped_at >= start:
            rejected['sportsbook_future_or_stale'] += 1
        else:
            books.append(quote)

    comparisons = []
    exact_markets = price_pairs = 0
    try:
        for quote in evidence['quotes']:
            if quote.get('milestone_id') != game['milestone_id']:
                continue
            if (quote.get('scheduled_game_start_time') is None
                    or _timestamp(quote['scheduled_game_start_time']) != start
                    or quote.get('strike_type') != 'greater'
                    or not isinstance(quote.get('ticker'), str) or not quote['ticker']
                    or quote.get('prop_type') not in PROP_MARKETS[sport].values()
                    or not all(_sha256(quote.get(key)) for key in (
                        'market_sha256', 'source_page_sha256', 'rules_sha256'))
                    or quote.get('settlement_equivalent') is not False
                    or quote.get('execution_ready') is not False):
                raise InvalidHandoff('invalid_quote_identity')
            if version==2 and (not isinstance(quote.get('event_ticker'),str)
                    or not isinstance(quote.get('series_ticker'),str)):
                raise InvalidHandoff('invalid_quote_identity')
            target = targets.get(quote.get('player_target_id'))
            if (not isinstance(target, dict) or target.get('team_target_id') != quote.get('team_target_id')
                    or target.get('team_target_id') not in team_ids):
                raise InvalidHandoff('invalid_player_target')
            player = _name(target.get('player_name'))
            if names[player] != 1:
                rejected['ambiguous_player'] += 1
                continue
            line = _decimal(quote.get('line'))
            if line % 1 != Decimal('.5'):
                rejected['non_complementary_strike'] += 1
                continue
            received = _timestamp(quote.get('received_at'))
            requested = _timestamp(quote.get('request_started_at'))
            if requested > received or received >= start or not -1 <= (now-received).total_seconds() <= MAX_AGE_SECONDS:
                rejected['kalshi_future_or_stale'] += 1
                continue
            relevant = [book for book in books if (_name(book.player_name) == player
                and PROP_MARKETS[sport][book.prop_type] == quote.get('prop_type') and book.line == line)]
            if relevant:
                exact_markets += 1
            for kalshi_side, book_side in (('yes', 'Under'), ('no', 'Over')):
                ask = _ask(quote.get(kalshi_side+'_ask'))
                paired = [book for book in relevant if book.side == book_side
                    and abs((book.snapped_at-received).total_seconds()) <= MAX_SKEW_SECONDS]
                if not ask or not paired:
                    if relevant and ask:
                        rejected['observation_skew_or_missing_side'] += 1
                    continue
                book = min(paired, key=lambda item: item.implied_probability)
                price_pairs += 1
                gross_cost = ask[0] + book.implied_probability
                if gross_cost >= 1:
                    continue
                fee_scenario=None
                if version==2:
                    try:
                        fee_scenario=_fee_scenario(evidence,quote,ask,book.implied_probability,received)
                    except (InvalidHandoff,KeyError,TypeError,ValueError,ArithmeticError,AttributeError):
                        pass
                row=dict(kind='kalshi_sportsbook_prop', status='unverified',
                    event_id=event['id'], milestone_id=game['milestone_id'], player=target['player_name'],
                    prop_type=quote['prop_type'], line=str(line),
                    legs=[dict(venue='kalshi', ticker=quote['ticker'], side=kalshi_side,
                        cost=str(ask[0]), displayed_size=str(ask[1]), observed_at=received.isoformat()),
                        dict(venue='sportsbook', sportsbook=book.sportsbook, side=book_side,
                        american_odds=book.price, cost=str(book.implied_probability),
                        observed_at=book.snapped_at.isoformat())],
                    gross_cost_to_one_dollar=str(gross_cost), gross_gap_to_one_dollar=str(1-gross_cost),
                    evidence_sha256=handoff['evidence_sha256'], settlement_equivalent=False,
                    market_sha256=quote['market_sha256'], rules_sha256=quote['rules_sha256'],
                    source_page_sha256=quote['source_page_sha256'],
                    fee_adjusted_profit=None, realized_profit=None, execution_ready=False,
                    reasons=['Settlement rules, DNP/void treatment, and stat provider are unreviewed.',
                        ('Captured Kalshi fee terms model one hypothetical contract; sportsbook limits are not included.'
                            if fee_scenario else 'Kalshi fees and sportsbook limits are not included.'),
                        'One displayed Kalshi level is not a fill.'])
                if fee_scenario:
                    row['exchange_fee_scenarios']=fee_scenario
                comparisons.append(row)
    except (InvalidHandoff, KeyError, TypeError, ValueError, AttributeError):
        return _unavailable(sport, now, 'invalid_quote_evidence')

    return dict(schema_version=1, sport=sport, screened_at=now.isoformat(), status='observed',
        handoff_captured_at=captured.isoformat(), event_id=event['id'],
        coverage=dict(sportsbook_quotes=len(sportsbook_quotes), eligible_sportsbook_quotes=len(books),
            kalshi_quotes=sum(q.get('milestone_id') == game['milestone_id'] for q in evidence['quotes']),
            exact_markets=exact_markets, price_pairs=price_pairs,
            positive_gross_gaps=len(comparisons), rejected=dict(rejected)),
        comparisons=comparisons, execution_ready=False)
