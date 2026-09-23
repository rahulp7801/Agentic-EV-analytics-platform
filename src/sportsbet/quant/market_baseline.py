"""Exact source-backed sportsbook no-vig baseline for future forecast audits."""
from __future__ import annotations

from decimal import Decimal
from math import isfinite

from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, prop_quote_evidence_valid
from sportsbet.model_contract import PROP_MARKETS
from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative


def paired_market_baseline(quote: PlayerPropSnapshotCreate,
                           quotes: list[PlayerPropSnapshotCreate]) -> dict:
    """Retain a source-backed no-vig price only for one exact opposite side."""
    if quote.side not in ('Over', 'Under') or not prop_quote_evidence_valid(quote):
        return {}
    opposite_side = 'Under' if quote.side == 'Over' else 'Over'
    opposites = [candidate for candidate in quotes if (
        candidate.sport == quote.sport
        and candidate.game_id == quote.game_id
        and candidate.player_name == quote.player_name
        and candidate.prop_type == quote.prop_type
        and candidate.line == quote.line
        and candidate.sportsbook == quote.sportsbook
        and candidate.snapped_at == quote.snapped_at
        and candidate.game_start_time == quote.game_start_time
        and candidate.source_provider == quote.source_provider
        and candidate.source_sha256 == quote.source_sha256
        and candidate.side == opposite_side
        and prop_quote_evidence_valid(candidate)
    )]
    if len(opposites) != 1:
        return {}
    other = opposites[0]
    try:
        fair = remove_vig_multiplicative([
            american_to_raw_prob(quote.price), american_to_raw_prob(other.price)])
    except (ArithmeticError, TypeError, ValueError):
        return {}
    return dict(market_no_vig_probability=float(fair[0]),
                market_opposite_american_odds=other.price,
                market_opposite_quote_source_record_sha256=other.source_record_sha256)


def verified_recorded_market_baseline(payload: dict) -> float | None:
    """Reproduce a retained opposite quote and no-vig probability from its hash."""
    try:
        stored = payload.get('market_no_vig_probability')
        odds = payload.get('market_opposite_american_odds')
        if (type(stored) not in (float, int) or not isfinite(stored)
                or type(odds) is not int or not 100 <= abs(odds) <= 32767):
            return None
        markets = PROP_MARKETS[payload['sport']]
        provider_market, = (key for key, value in markets.items()
                            if value == payload['prop_type'])
        main = american_to_raw_prob(payload['american_odds'])
        from sportsbet.ledger import utc_timestamp
        opposite = PlayerPropSnapshotCreate(
            sport=payload['sport'], game_id=payload['game_id'],
            player_name=payload['player'], sportsbook=payload['sportsbook'],
            prop_type=provider_market, line=Decimal(str(payload['line'])),
            price=odds, implied_probability=american_to_raw_prob(odds),
            game_start_time=utc_timestamp(payload['game_start_time']),
            source_provider=payload['quote_source_provider'],
            source_sha256=payload['quote_source_sha256'],
            source_record_sha256=payload['market_opposite_quote_source_record_sha256'],
            snapped_at=utc_timestamp(payload['quote_time']),
            side='Under' if payload['direction'] == 'over' else 'Over',
        )
        if not prop_quote_evidence_valid(opposite):
            return None
        fair = remove_vig_multiplicative([main, opposite.implied_probability])[0]
        if abs(float(fair)-stored) > 1e-10:
            return None
        return float(fair)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return None
