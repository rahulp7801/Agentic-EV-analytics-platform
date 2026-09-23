"""Exact source-backed sportsbook no-vig baseline for future forecast audits."""
from __future__ import annotations

from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, prop_quote_evidence_valid
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


