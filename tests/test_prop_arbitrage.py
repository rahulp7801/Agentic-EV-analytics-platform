"""TDD test suite for PropArbitrageAgent (PROP-06) and CorrelationGuard extension (PROP-07).

Phase 13, Plan 01 — tests written RED first before implementation exists.

Tests:
  PROP-06: PropArbitrageAgent closure factory — EV computation, Kelly sizing, Trade Plan, guard returns.
  PROP-07: CorrelationGuard extended CONFLICT_PAIRS — prop-to-prop and prop-to-game-total pairs.

Phase 23, Plan 01 — adds snapshot match path tests (PROP-06 EV fix):
  TestProp06PlayerPropSnapshot: snapshot match uses prop implied_prob, prop_type normalization
  TestProp06NoSnapshotGuard: None/empty/no-match snapshot returns _NO_SIGNAL
  TestProp06CommensurableEV: EV computed against prop-market probability (not h2h moneyline)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsbet.graph.models import (
    AgentOddsSnapshot,
    ContextSignals,
    EVSignal,
    PropResult,
)

# Import guard: wrap make_prop_arbitrage_agent import so test file is importable
# even before Task 2 creates the implementation. Tests will fail with a clear error.
try:
    from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
    _IMPORT_OK = True
except ImportError:
    make_prop_arbitrage_agent = None  # type: ignore[assignment]
    _IMPORT_OK = False

try:
    from sportsbet.arbitrage.correlation_guard import CONFLICT_PAIRS
except ImportError:
    CONFLICT_PAIRS = frozenset()  # type: ignore[assignment]

# Phase 23 — PROP-06 snapshot match path: import PlayerPropSnapshotCreate for fixture use
try:
    from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
    _SNAPSHOT_IMPORT_OK = True
except ImportError:
    PlayerPropSnapshotCreate = None  # type: ignore[assignment, misc]
    _SNAPSHOT_IMPORT_OK = False


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_nfl_state(
    true_prob: Decimal = Decimal("0.62"),
    implied_prob: Decimal = Decimal("0.50"),
    market_type: str = "over_pass_yds",
    prop_result: PropResult | None = ...,  # type: ignore[assignment]
    player_prop_snapshots: list | None = ...,  # type: ignore[assignment]
) -> dict:
    """Return a minimal GraphState dict suitable for prop_arbitrage_agent unit tests.

    Phase 23 update: adds player_prop_snapshots keyword arg. Defaults to a list
    containing one PlayerPropSnapshotCreate for Patrick Mahomes passing yards,
    matching prop_type="player_pass_yards" (Odds API format) and line=250.5.
    Supply player_prop_snapshots=None or [] to test no-snapshot guard paths.
    """
    if prop_result is ...:  # type: ignore[comparison-overlap]
        prop_result = PropResult(
            true_probability=true_prob,
            sample_size=45,
            confidence_interval=(Decimal("0.54"), Decimal("0.70")),
            data_source="postgresql",
            mean_stat=Decimal("265.0"),
        )
    # Default player_prop_snapshots: one snap matching prop_type="pass_yds" alias and line=250.5
    if player_prop_snapshots is ...:  # type: ignore[comparison-overlap]
        if _SNAPSHOT_IMPORT_OK:
            player_prop_snapshots = [
                PlayerPropSnapshotCreate(
                    sport="nfl",
                    game_id="2024_01_KC_LV",
                    player_name="Patrick Mahomes",
                    sportsbook="draftkings",
                    prop_type="player_pass_yards",  # Odds API market key format
                    line=Decimal("250.5"),
                    price=-115,
                    implied_probability=implied_prob,
                )
            ]
        else:
            player_prop_snapshots = None
    return {
        "session_id": "test-session",
        "request_type": "prop_analysis",
        "prop_result": prop_result,
        "nba_prop_result": None,
        "context_signals": ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=AgentOddsSnapshot(
                game_id="2024_01_KC_LV",
                sportsbook="draftkings",
                market_type=market_type,
                implied_probability=implied_prob,
                snapped_at=datetime.now(timezone.utc),
            ),
            signals_captured_at=datetime.now(timezone.utc),
        ),
        "pending_signals": [],
        "cleared_signals": [],
        "prop_type": "pass_yds",
        "prop_line": "250.5",
        "player_prop_snapshots": player_prop_snapshots,
    }


def _make_nba_state(
    true_prob: Decimal = Decimal("0.62"),
    implied_prob: Decimal = Decimal("0.50"),
    player_prop_snapshots: list | None = ...,  # type: ignore[assignment]
) -> dict:
    """Return a minimal GraphState dict with nba_prop_result set (sport='nba' branch).

    Phase 23 update: adds player_prop_snapshots keyword arg. Defaults to a list
    containing one PlayerPropSnapshotCreate for LeBron James points,
    matching prop_type="player_points" (Odds API format) and line=22.5.
    """
    nba_prop_result = PropResult(
        true_probability=true_prob,
        sample_size=30,
        confidence_interval=(Decimal("0.54"), Decimal("0.70")),
        data_source="postgresql",
        mean_stat=Decimal("22.5"),
    )
    # Default player_prop_snapshots: one snap matching prop_type="points" alias and line=22.5
    if player_prop_snapshots is ...:  # type: ignore[comparison-overlap]
        if _SNAPSHOT_IMPORT_OK:
            player_prop_snapshots = [
                PlayerPropSnapshotCreate(
                    sport="nba",
                    game_id="2024_NBA_LAL_BOS",
                    player_name="LeBron James",
                    sportsbook="draftkings",
                    prop_type="player_points",  # Odds API market key format
                    line=Decimal("22.5"),
                    price=-115,
                    implied_probability=implied_prob,
                )
            ]
        else:
            player_prop_snapshots = None
    return {
        "session_id": "test-session-nba",
        "request_type": "prop_analysis",
        "prop_result": None,
        "nba_prop_result": nba_prop_result,
        "context_signals": ContextSignals(
            game_id="2024_NBA_LAL_BOS",
            injury_flags={},
            odds_snapshot=AgentOddsSnapshot(
                game_id="2024_NBA_LAL_BOS",
                sportsbook="draftkings",
                market_type="over_points",
                implied_probability=implied_prob,
                snapped_at=datetime.now(timezone.utc),
            ),
            signals_captured_at=datetime.now(timezone.utc),
        ),
        "pending_signals": [],
        "cleared_signals": [],
        "prop_type": "points",
        "prop_line": "22.5",
        "player_prop_snapshots": player_prop_snapshots,
    }


def _make_ev_signal(market_type: str, ev_pct: str = "0.05") -> EVSignal:
    """Helper: create a minimal EVSignal for CorrelationGuard tests."""
    return EVSignal(
        ev_percentage=Decimal(ev_pct),
        true_probability=Decimal("0.55"),
        implied_probability=Decimal("0.50"),
        kelly_fraction=Decimal("0.05"),
        trade_plan=["Bullet 1", "Bullet 2", "Bullet 3"],
        market_type=market_type,
    )


# ---------------------------------------------------------------------------
# PROP-06 tests — PropArbitrageAgent
# ---------------------------------------------------------------------------

class TestProp06EVSignalProduced:
    """PROP-06: +EV case returns EVSignal with ev_percentage > 0."""

    def test_prop06_ev_signal_produced(self) -> None:
        """Agent returns EVSignal with ev_percentage > 0 when true_prob > implied_prob."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(true_prob=Decimal("0.62"), implied_prob=Decimal("0.50"))
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, "Expected EVSignal for +EV prop, got None"
        assert ev_signal.ev_percentage > Decimal("0"), (
            f"ev_percentage should be > 0, got {ev_signal.ev_percentage}"
        )

    def test_prop06_kelly_fraction_non_flat(self) -> None:
        """kelly_fraction must be in (0, 0.25] — never flat, never zero."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(true_prob=Decimal("0.62"), implied_prob=Decimal("0.50"))
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, "Expected EVSignal for +EV prop"
        assert Decimal("0") < ev_signal.kelly_fraction <= Decimal("0.25"), (
            f"kelly_fraction {ev_signal.kelly_fraction} not in (0, 0.25]"
        )

    def test_prop06_no_ev_suppressed(self) -> None:
        """Negative EV (true_prob < implied_prob) returns ev_signal=None."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(true_prob=Decimal("0.45"), implied_prob=Decimal("0.50"))
        result = asyncio.run(agent(state))
        assert result.get("ev_signal") is None, (
            "Expected None ev_signal for -EV prop, got a signal"
        )

    def test_prop06_trade_plan_length(self) -> None:
        """EVSignal.trade_plan must contain exactly 3 non-empty bullet strings."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(true_prob=Decimal("0.62"), implied_prob=Decimal("0.50"))
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, "Expected EVSignal for +EV prop"
        assert len(ev_signal.trade_plan) == 3, (
            f"trade_plan must have 3 bullets, got {len(ev_signal.trade_plan)}"
        )
        for i, bullet in enumerate(ev_signal.trade_plan):
            assert isinstance(bullet, str) and bullet.strip(), (
                f"trade_plan[{i}] is empty or not a string: {bullet!r}"
            )

    def test_prop06_missing_prop_result(self) -> None:
        """State with prop_result=None returns ev_signal=None."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(prop_result=None)
        result = asyncio.run(agent(state))
        assert result.get("ev_signal") is None, (
            "Expected None ev_signal when prop_result is None"
        )


# ---------------------------------------------------------------------------
# PROP-07 tests — CorrelationGuard extension
# ---------------------------------------------------------------------------

class TestProp07CorrelationGuard:
    """PROP-07: CorrelationGuard CONFLICT_PAIRS covers prop-to-prop pairs."""

    def test_prop07_prop_conflict_blocked(self) -> None:
        """Batch with over_pass_yds + under_rec_yds — CorrelationGuard removes both."""
        from sportsbet.arbitrage.correlation_guard import CorrelationGuard
        guard = CorrelationGuard()
        signals = [
            _make_ev_signal("over_pass_yds"),
            _make_ev_signal("under_rec_yds"),
            _make_ev_signal("over_rush_yds"),  # this one should survive
        ]
        cleared = guard.check(signals)
        market_types = {s.market_type for s in cleared}
        assert "over_pass_yds" not in market_types, "over_pass_yds should be blocked"
        assert "under_rec_yds" not in market_types, "under_rec_yds should be blocked"
        assert "over_rush_yds" in market_types, "over_rush_yds should pass (no conflict)"

    def test_prop07_conflict_pairs_extended(self) -> None:
        """CONFLICT_PAIRS contains frozenset({'over_pass_yds', 'under_rec_yds'})."""
        expected_pair = frozenset({"over_pass_yds", "under_rec_yds"})
        assert expected_pair in CONFLICT_PAIRS, (
            f"Expected {expected_pair} in CONFLICT_PAIRS. "
            f"Current CONFLICT_PAIRS: {CONFLICT_PAIRS}"
        )

    def test_prop07_no_conflict_passes(self) -> None:
        """Single non-conflicting signal (over_pass_yds alone) passes guard unchanged."""
        from sportsbet.arbitrage.correlation_guard import CorrelationGuard
        guard = CorrelationGuard()
        signals = [_make_ev_signal("over_pass_yds")]
        cleared = guard.check(signals)
        assert len(cleared) == 1, (
            f"Single non-conflicting signal should pass, got {len(cleared)} signals"
        )
        assert cleared[0].market_type == "over_pass_yds"


# ---------------------------------------------------------------------------
# End-to-end pipeline tests
# ---------------------------------------------------------------------------

class TestE2EPropPipeline:
    """End-to-end integration tests calling make_prop_arbitrage_agent directly."""

    def test_e2e_nfl_prop_pipeline(self) -> None:
        """NFL prop pipeline: PropResult + ContextSignals -> non-None EVSignal."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(true_prob=Decimal("0.62"), implied_prob=Decimal("0.50"))
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, "E2E NFL: expected non-None EVSignal"
        assert isinstance(ev_signal.ev_percentage, Decimal)
        assert isinstance(ev_signal.kelly_fraction, Decimal)
        assert isinstance(ev_signal.trade_plan, list)
        pending = result.get("pending_signals", [])
        assert len(pending) == 1, f"Expected 1 pending signal, got {len(pending)}"
        assert pending[0] is ev_signal

    def test_e2e_nba_prop_pipeline(self) -> None:
        """NBA prop pipeline: reads nba_prop_result when sport='nba'."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nba")
        state = _make_nba_state(true_prob=Decimal("0.62"), implied_prob=Decimal("0.50"))
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, (
            "E2E NBA: expected non-None EVSignal from nba_prop_result"
        )
        assert isinstance(ev_signal.ev_percentage, Decimal)
        pending = result.get("pending_signals", [])
        assert len(pending) == 1


# ---------------------------------------------------------------------------
# Phase 23 — PROP-06 snapshot match path tests
# ---------------------------------------------------------------------------

class TestProp06PlayerPropSnapshot:
    """PROP-06 Phase 23: PropArbitrageAgent uses matched PlayerPropSnapshot implied_prob."""

    def test_snapshot_match_uses_prop_implied_prob(self) -> None:
        """When player_prop_snapshots is in state (no odds_snapshot), agent uses snapshot implied_prob.

        State has player_prop_snapshots=[snap(prop_type="player_pass_yards", line=250.5,
        implied_probability=0.50)] and context_signals.odds_snapshot=None.
        Asserts ev_signal is not None and ev_signal.implied_probability == Decimal("0.50").
        """
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        assert _SNAPSHOT_IMPORT_OK, "PlayerPropSnapshotCreate not importable"
        agent = make_prop_arbitrage_agent(sport="nfl")
        snap = PlayerPropSnapshotCreate(
            sport="nfl",
            game_id="2024_01_KC_LV",
            player_name="Patrick Mahomes",
            sportsbook="draftkings",
            prop_type="player_pass_yards",
            line=Decimal("250.5"),
            price=-115,
            implied_probability=Decimal("0.50"),
        )
        # Build state with prop snapshot but NO odds_snapshot (prop-specific path)
        state = _make_nfl_state(
            true_prob=Decimal("0.62"),
            implied_prob=Decimal("0.50"),
            player_prop_snapshots=[snap],
        )
        # Remove odds_snapshot from context_signals to force snapshot match path
        from sportsbet.graph.models import ContextSignals
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, (
            "Expected non-None EVSignal when player_prop_snapshots match exists"
        )
        assert ev_signal.implied_probability == Decimal("0.50"), (
            f"implied_probability should be Decimal('0.50') from snapshot, "
            f"got {ev_signal.implied_probability}"
        )

    def test_prop_type_normalization(self) -> None:
        """prop_type='pass_yds' (PropParams format) matches snapshot prop_type='player_pass_yards' (Odds API format).

        State has player_prop_snapshots with prop_type='player_pass_yards' and state
        prop_type='pass_yds'. Asserts match succeeds (ev_signal is not None).
        """
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        assert _SNAPSHOT_IMPORT_OK, "PlayerPropSnapshotCreate not importable"
        agent = make_prop_arbitrage_agent(sport="nfl")
        snap = PlayerPropSnapshotCreate(
            sport="nfl",
            game_id="2024_01_KC_LV",
            player_name="Patrick Mahomes",
            sportsbook="draftkings",
            prop_type="player_pass_yards",  # Odds API format
            line=Decimal("250.5"),
            price=-115,
            implied_probability=Decimal("0.50"),
        )
        state = _make_nfl_state(
            true_prob=Decimal("0.62"),
            implied_prob=Decimal("0.50"),
            player_prop_snapshots=[snap],
        )
        # prop_type="pass_yds" is already set in _make_nfl_state — must normalize to "player_pass_yards"
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, (
            "Expected non-None EVSignal: prop_type alias 'pass_yds'->'player_pass_yards' should match"
        )


class TestProp06NoSnapshotGuard:
    """PROP-06 Phase 23: no-snapshot fallback guard returns _NO_SIGNAL."""

    def test_none_snapshots_returns_no_signal(self) -> None:
        """player_prop_snapshots=None and odds_snapshot=None returns ev_signal=None."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(
            true_prob=Decimal("0.62"),
            implied_prob=Decimal("0.50"),
            player_prop_snapshots=None,
        )
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        assert result.get("ev_signal") is None, (
            "Expected None ev_signal when player_prop_snapshots=None and no odds_snapshot"
        )

    def test_empty_snapshots_returns_no_signal(self) -> None:
        """player_prop_snapshots=[] and odds_snapshot=None returns ev_signal=None."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        agent = make_prop_arbitrage_agent(sport="nfl")
        state = _make_nfl_state(
            true_prob=Decimal("0.62"),
            implied_prob=Decimal("0.50"),
            player_prop_snapshots=[],
        )
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        assert result.get("ev_signal") is None, (
            "Expected None ev_signal when player_prop_snapshots=[] and no odds_snapshot"
        )

    def test_no_type_match_returns_no_signal(self) -> None:
        """player_prop_snapshots has snap with wrong prop_type — no match, returns ev_signal=None."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        assert _SNAPSHOT_IMPORT_OK, "PlayerPropSnapshotCreate not importable"
        agent = make_prop_arbitrage_agent(sport="nfl")
        snap = PlayerPropSnapshotCreate(
            sport="nfl",
            game_id="2024_01_KC_LV",
            player_name="Derrick Henry",
            sportsbook="draftkings",
            prop_type="player_rush_yards",  # different prop_type, no match for "pass_yds"
            line=Decimal("80.5"),
            price=-115,
            implied_probability=Decimal("0.50"),
        )
        state = _make_nfl_state(
            true_prob=Decimal("0.62"),
            implied_prob=Decimal("0.50"),
            player_prop_snapshots=[snap],
        )
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        assert result.get("ev_signal") is None, (
            "Expected None ev_signal when no snapshot matches prop_type='pass_yds'"
        )


class TestProp06CommensurableEV:
    """PROP-06 Phase 23: EV computed against prop-market probability, not h2h moneyline."""

    def test_ev_uses_prop_implied_prob_not_h2h(self) -> None:
        """EV computed against prop snapshot implied_prob=0.50, not h2h moneyline.

        true_prob=0.55, matched snapshot implied_probability=0.50:
        asserts ev_signal.ev_percentage > 0 and ev_signal.implied_probability == 0.50.
        """
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        assert _SNAPSHOT_IMPORT_OK, "PlayerPropSnapshotCreate not importable"
        agent = make_prop_arbitrage_agent(sport="nfl")
        snap = PlayerPropSnapshotCreate(
            sport="nfl",
            game_id="2024_01_KC_LV",
            player_name="Patrick Mahomes",
            sportsbook="draftkings",
            prop_type="player_pass_yards",
            line=Decimal("250.5"),
            price=-115,
            implied_probability=Decimal("0.50"),
        )
        state = _make_nfl_state(
            true_prob=Decimal("0.55"),
            implied_prob=Decimal("0.55"),  # h2h moneyline would give 0 EV
            player_prop_snapshots=[snap],
        )
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, (
            "Expected non-None EVSignal: prop snapshot implied=0.50 vs true=0.55 is +EV"
        )
        assert ev_signal.ev_percentage > Decimal("0"), (
            f"ev_percentage should be > 0, got {ev_signal.ev_percentage}"
        )
        assert ev_signal.implied_probability == Decimal("0.50"), (
            f"implied_probability should come from prop snapshot (0.50), not h2h"
        )

    def test_kelly_sizing_nonzero_with_positive_ev(self) -> None:
        """Kelly fraction is in (0, 0.25] when EV > 0 from prop snapshot match."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        assert _SNAPSHOT_IMPORT_OK, "PlayerPropSnapshotCreate not importable"
        agent = make_prop_arbitrage_agent(sport="nfl")
        snap = PlayerPropSnapshotCreate(
            sport="nfl",
            game_id="2024_01_KC_LV",
            player_name="Patrick Mahomes",
            sportsbook="draftkings",
            prop_type="player_pass_yards",
            line=Decimal("250.5"),
            price=-115,
            implied_probability=Decimal("0.50"),
        )
        state = _make_nfl_state(
            true_prob=Decimal("0.55"),
            implied_prob=Decimal("0.55"),
            player_prop_snapshots=[snap],
        )
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        ev_signal = result.get("ev_signal")
        assert ev_signal is not None, "Expected non-None EVSignal for +EV prop snapshot"
        assert Decimal("0") < ev_signal.kelly_fraction <= Decimal("0.25"), (
            f"kelly_fraction {ev_signal.kelly_fraction} not in (0, 0.25]"
        )

    def test_ev_zero_when_true_prob_equals_implied(self) -> None:
        """No edge when true_prob == snapshot implied_probability — ev_signal is None."""
        assert _IMPORT_OK, "make_prop_arbitrage_agent not importable yet"
        assert _SNAPSHOT_IMPORT_OK, "PlayerPropSnapshotCreate not importable"
        agent = make_prop_arbitrage_agent(sport="nfl")
        snap = PlayerPropSnapshotCreate(
            sport="nfl",
            game_id="2024_01_KC_LV",
            player_name="Patrick Mahomes",
            sportsbook="draftkings",
            prop_type="player_pass_yards",
            line=Decimal("250.5"),
            price=-115,
            implied_probability=Decimal("0.50"),
        )
        state = _make_nfl_state(
            true_prob=Decimal("0.50"),  # true_prob == snapshot implied_prob -> zero EV
            implied_prob=Decimal("0.50"),
            player_prop_snapshots=[snap],
        )
        state["context_signals"] = ContextSignals(
            game_id="2024_01_KC_LV",
            injury_flags={},
            odds_snapshot=None,
            signals_captured_at=datetime.now(timezone.utc),
        )
        result = asyncio.run(agent(state))
        assert result.get("ev_signal") is None, (
            "Expected None ev_signal when true_prob == snapshot implied_probability (no edge)"
        )


# ---------------------------------------------------------------------------
# Quick Task 2 — PROP-06 alias key audit (TestPropAliasMapKeys)
# ---------------------------------------------------------------------------

class TestPropAliasMapKeys:
    """PROP-06 quick-2: Audit _PROP_TYPE_ALIAS_MAP NFL values against NFL_PROP_MARKETS keys.

    NFL_PROP_MARKETS contains:
      player_pass_yds, player_pass_tds, player_rush_yds, player_rush_tds,
      player_reception_yds, player_reception_tds, player_receptions

    Each NFL entry in _PROP_TYPE_ALIAS_MAP must map to a value present in that set.
    NBA keys (points, rebounds, assists, pra) are not in NFL_PROP_MARKETS and are skipped.
    """

    def test_rec_yds_maps_to_player_reception_yds(self) -> None:
        """rec_yds must map to 'player_reception_yds' (not 'player_receiving_yards')."""
        from sportsbet.prop.arbitrage import _PROP_TYPE_ALIAS_MAP
        assert _PROP_TYPE_ALIAS_MAP["rec_yds"] == "player_reception_yds", (
            f"rec_yds maps to {_PROP_TYPE_ALIAS_MAP['rec_yds']!r} — "
            f"expected 'player_reception_yds' (NFL_PROP_MARKETS key)"
        )

    def test_all_nfl_alias_values_in_nfl_prop_markets(self) -> None:
        """All NFL-related _PROP_TYPE_ALIAS_MAP values must be present in NFL_PROP_MARKETS."""
        from sportsbet.prop.arbitrage import _PROP_TYPE_ALIAS_MAP
        from sportsbet.ingestion.odds_poller import NFL_PROP_MARKETS

        # Parse NFL_PROP_MARKETS string into a set of keys
        nfl_markets_set = set(NFL_PROP_MARKETS.replace("\n", "").replace(" ", "").split(","))

        # NBA-only keys — not expected in NFL_PROP_MARKETS
        nba_only_keys = {"points", "rebounds", "assists", "pra"}

        mismatches: list[str] = []
        for prop_key, market_value in _PROP_TYPE_ALIAS_MAP.items():
            if prop_key in nba_only_keys:
                continue  # Skip NBA props
            if market_value not in nfl_markets_set:
                mismatches.append(
                    f"  {prop_key!r} -> {market_value!r} (not in NFL_PROP_MARKETS)"
                )

        assert not mismatches, (
            "NFL _PROP_TYPE_ALIAS_MAP values not found in NFL_PROP_MARKETS:\n"
            + "\n".join(mismatches)
        )

    def test_nba_keys_not_in_nfl_prop_markets(self) -> None:
        """NBA-only keys (points, rebounds, assists, pra) are not in NFL_PROP_MARKETS — verify skip is safe."""
        from sportsbet.prop.arbitrage import _PROP_TYPE_ALIAS_MAP
        from sportsbet.ingestion.odds_poller import NFL_PROP_MARKETS

        nfl_markets_set = set(NFL_PROP_MARKETS.replace("\n", "").replace(" ", "").split(","))
        nba_only_keys = {"points", "rebounds", "assists", "pra"}

        for prop_key in nba_only_keys:
            market_value = _PROP_TYPE_ALIAS_MAP.get(prop_key)
            if market_value is not None:
                # NBA value should NOT be in NFL markets
                assert market_value not in nfl_markets_set, (
                    f"NBA key {prop_key!r} maps to {market_value!r} which is unexpectedly in NFL_PROP_MARKETS"
                )
