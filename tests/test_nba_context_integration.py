"""End-to-end integration test for the NBA context signals pipeline.

Purpose: Satisfies ROADMAP Phase 20 Success Criterion 5:
    "An integration test with a realistic game scenario confirms pace/rest/def_rating
    adjustments produce a different probability than the unadjusted baseline."

Design:
    - Both tests are fully offline — no live DB or real asyncpg pool.
    - The producer (make_nba_context_signals_producer) uses the MagicMock pool
      pattern from Phase 4 with two sequential fetchrow returns.
    - The quant agent (make_nba_quant_agent) uses a patched run_nba_prop_query
      returning a deterministic base PropResult — isolates signal path verification
      from the NormalDist query engine.
    - asyncio_mode = "auto" is already configured in pyproject.toml — bare async def,
      no @pytest.mark.asyncio decorator.

Two tests:
    test_context_signals_adjust_probability  — ROADMAP SC 5 assertion
    test_none_signals_returns_baseline        — regression guard for None path
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.graph.models import NBAContextSignals, PropResult
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer
from sportsbet.prop.nba_executor import LEAGUE_AVG_DEF_RATING, LEAGUE_AVG_PACE


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_producer_pool(fetchrow_returns: list):
    """Build a MagicMock asyncpg pool with sequential fetchrow side_effect.

    The producer calls fetchrow twice within a single pool.acquire() context:
      1. Last gamelog row (team_abbreviation + game_date)
      2. Opponent scoring proxy row (avg_pts_per_game)
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow_returns)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


def _base_state(nba_context_signals=None):
    """Return a minimal GraphState-compatible dict for NBA prop analysis."""
    return {
        "receiver_gsis_id": "2345678",
        "season": 2024,
        "game_id": "0022400001",
        "prop_type": "points",
        "prop_line": "22.5",
        "home_team": "LAL",
        "away_team": "GSW",
        "prop_filters": {},
        "situational_params": None,
        "nba_context_signals": nba_context_signals,
        "session_id": "test-integration",
    }


# ---------------------------------------------------------------------------
# Test 1: context-adjusted probability differs from None-baseline
# ---------------------------------------------------------------------------


async def test_context_signals_adjust_probability():
    """Full pipeline: producer emits NBAContextSignals -> agent applies adjustments.

    Scenario:
    - Player on LAL (home team): is_home = True -> HOME_BOOST applied
    - Last game was yesterday (rest_days=0, B2B): REST_PENALTY applied
    - Opponent GSW has above-average scoring (avg_pts=12.0 > LEAGUE_AVG=8.0):
      high opponent_def_rating -> weaker defense -> def_ratio < 1.0

    Expected: adjusted probability != Decimal("0.55") baseline (ROADMAP SC 5).
    """
    # --- Producer phase ---
    # Row 1 (gamelog): team=LAL, last game was yesterday relative to target_date
    gamelog_row = {"team_abbreviation": "LAL", "game_date": date(2024, 11, 19)}
    # Row 2 (opponent scoring): above league average -> high def_rating
    opp_row = {"avg_pts_per_game": 12.0}

    producer_pool = _make_producer_pool([gamelog_row, opp_row])
    producer = make_nba_context_signals_producer(
        producer_pool, target_date=date(2024, 11, 20)
    )
    producer_state = _base_state()
    producer_result = await producer(producer_state)

    signals = producer_result["nba_context_signals"]

    # Verify producer emitted valid NBAContextSignals
    assert signals is not None
    assert isinstance(signals, NBAContextSignals)
    # NBA B2B semantics: date(2024,11,20) - date(2024,11,19) = 1 day -> rest_days = max(0, 1-1) = 0
    assert signals.rest_days == 0
    # team_abbr="LAL" == home_team="LAL"
    assert signals.is_home is True

    # --- Agent phase (run_nba_prop_query patched to return deterministic base) ---
    BASE_PROB = Decimal("0.55")
    base_result = PropResult(
        true_probability=BASE_PROB,
        data_source="postgresql",
        sample_size=60,
        confidence_interval=None,
    )
    agent_pool = MagicMock()  # agent's pool not called — run_nba_prop_query is patched
    agent = make_nba_quant_agent(agent_pool)

    with patch(
        "sportsbet.prop.nba_agents.run_nba_prop_query",
        new=AsyncMock(return_value=base_result),
    ):
        agent_state = _base_state(nba_context_signals=signals)
        result_dict = await agent(agent_state)

    adjusted_result = result_dict["nba_prop_result"]
    assert adjusted_result.true_probability is not None
    assert adjusted_result.true_probability != BASE_PROB  # adjustments fired
    assert adjusted_result.data_source == "postgresql+nba_context"

    # --- None-baseline comparison (ROADMAP Success Criterion 5) ---
    with patch(
        "sportsbet.prop.nba_agents.run_nba_prop_query",
        new=AsyncMock(return_value=base_result),
    ):
        baseline_state = _base_state(nba_context_signals=None)
        baseline_dict = await agent(baseline_state)

    baseline_result = baseline_dict["nba_prop_result"]
    assert baseline_result.true_probability == BASE_PROB  # no adjustments when None
    assert adjusted_result.true_probability != baseline_result.true_probability  # SC 5


# ---------------------------------------------------------------------------
# Test 2: None signals returns baseline unchanged (regression guard)
# ---------------------------------------------------------------------------


async def test_none_signals_returns_baseline():
    """None-signals path is stable: base probability returned unchanged.

    Verifies that when nba_context_signals=None, the four-stage adjustment
    pipeline is not entered and the exact base probability is preserved.
    """
    BASE_PROB = Decimal("0.42")
    base_result = PropResult(
        true_probability=BASE_PROB,
        data_source="postgresql",
        sample_size=45,
        confidence_interval=None,
    )
    agent_pool = MagicMock()
    agent = make_nba_quant_agent(agent_pool)

    with patch(
        "sportsbet.prop.nba_agents.run_nba_prop_query",
        new=AsyncMock(return_value=base_result),
    ):
        state = _base_state(nba_context_signals=None)
        result_dict = await agent(state)

    result = result_dict["nba_prop_result"]
    assert result.true_probability == Decimal("0.42")
    assert result.data_source == "postgresql"
