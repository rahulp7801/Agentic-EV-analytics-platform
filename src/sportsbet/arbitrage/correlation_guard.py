"""CorrelationGuard: hardcoded conflicting market exposure stops.

Enforces CLAUDE.md rule: "hardcoded validation to prevent conflicting
market exposures (e.g., advising an Over on passing yards while
simultaneously advising an Under on total team points)."

CONFLICT_PAIRS is a frozenset of frozenset[str] pairs. Each inner frozenset
contains exactly two market_type strings that must not both appear in the
same signal batch. This is a set-intersection check — O(n * |CONFLICT_PAIRS|).

Design: pure class, no LangGraph coupling. Accepts list[EVSignal], returns
list[EVSignal] with conflicting pairs removed. If any two signals in the
input have market_types that form a known conflict pair, BOTH are removed.
"""
from __future__ import annotations

from sportsbet.graph.models import EVSignal

CONFLICT_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"over_passing_yards", "under_total_points"}),
    frozenset({"over_rushing_yards", "over_total_points"}),
    frozenset({"over_passing_yards", "under_passing_yards"}),
    frozenset({"over_total_points", "under_total_points"}),
})


class CorrelationGuard:
    """Check a batch of EVSignals for conflicting market exposures.

    Stateless: a new instance per request is acceptable. All conflict
    detection is performed in check() using the module-level CONFLICT_PAIRS.
    """

    def check(self, signals: list[EVSignal]) -> list[EVSignal]:
        """Return signals with conflicting pairs removed.

        For each CONFLICT_PAIR, if both market_types appear in the batch,
        remove all signals with those market_types from the output.
        Non-conflicting signals pass through unchanged.
        """
        market_types_present = {s.market_type for s in signals}
        blocked: set[str] = set()
        for pair in CONFLICT_PAIRS:
            if pair.issubset(market_types_present):
                blocked.update(pair)
        return [s for s in signals if s.market_type not in blocked]
