"""Wave 0 TDD test stubs for PropParams situational filter fields (Phase 18 — SC-3).

These tests define the contract for PropParams optional situational fields:
    last_n_games, teammate_out, opponent_team, home_away

Tests are RED until Task 2 adds the fields to PropParams in models.py.
Tests use direct assertions — no pytest.importorskip — so failures are FAILED
(not ERROR) when fields are absent, serving as TDD RED indicators.
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sportsbet.graph.models import PropParams

# ---------------------------------------------------------------------------
# Base fixture — minimal valid PropParams kwargs shared across all tests.
# ---------------------------------------------------------------------------

_BASE = dict(
    game_id="g1",
    player_id="p1",
    season=2023,
    sport="nfl",
    prop_type="pass_yds",
    line=Decimal("250.5"),
    filters={},
)


# ---------------------------------------------------------------------------
# Situational field tests
# ---------------------------------------------------------------------------


def test_prop_params_accepts_none_situational_fields() -> None:
    """PropParams validates without situational fields; new fields default to None."""
    p = PropParams(**_BASE)
    assert p.last_n_games is None
    assert p.teammate_out is None
    assert p.opponent_team is None
    assert p.home_away is None


def test_prop_params_accepts_last_n_games() -> None:
    """last_n_games=10 is accepted; value is preserved."""
    p = PropParams(**_BASE, last_n_games=10)
    assert p.last_n_games == 10


def test_prop_params_accepts_opponent_team() -> None:
    """opponent_team='GSW' is accepted; value is preserved."""
    p = PropParams(**_BASE, opponent_team="GSW")
    assert p.opponent_team == "GSW"


def test_prop_params_accepts_home_away_home() -> None:
    """home_away='home' is accepted."""
    p = PropParams(**_BASE, home_away="home")
    assert p.home_away == "home"


def test_prop_params_accepts_home_away_away() -> None:
    """home_away='away' is accepted."""
    p = PropParams(**_BASE, home_away="away")
    assert p.home_away == "away"


def test_prop_params_rejects_bad_home_away() -> None:
    """home_away='center' raises ValidationError — only 'home'/'away' are valid."""
    with pytest.raises(ValidationError):
        PropParams(**_BASE, home_away="center")  # type: ignore[arg-type]


def test_prop_params_accepts_teammate_out() -> None:
    """teammate_out=['1628384'] is accepted; list is preserved."""
    p = PropParams(**_BASE, teammate_out=["1628384"])
    assert p.teammate_out == ["1628384"]
