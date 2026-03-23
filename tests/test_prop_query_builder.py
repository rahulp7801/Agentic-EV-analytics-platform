"""TDD tests for Phase 11 Plan 01: PropQueryBuilder — SQL gate and injection prevention.

Wave 0: Tests are written RED — PropQueryBuilder does not exist yet.
Wave 1 (Task 2): Implementation makes these tests GREEN.

Test inventory:
1. test_invalid_prop_type_rejected      — PropParams rejects prop_type="invalid"
2. test_parameterized_sql               — build() SQL has only $N placeholders, no user values
3. test_filter_allowlist_unknown_key_dropped — unknown filter key not in SQL string
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from sportsbet.graph.models import PropParams

try:
    from sportsbet.prop.query_builder import PropQueryBuilder
    _QB_IMPORTED = True
except ImportError:
    PropQueryBuilder = None  # type: ignore[assignment, misc]
    _QB_IMPORTED = False


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _valid_prop_params(**overrides: object) -> PropParams:
    """Return a minimal valid PropParams with optional field overrides."""
    base: dict[str, object] = {
        "game_id": "2023_01_KC_DET",
        "player_id": "00-0033873",
        "season": 2023,
        "sport": "nfl",
        "prop_type": "pass_yds",
        "line": Decimal("250"),
        "filters": {},
    }
    base.update(overrides)
    return PropParams(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit tests — Pydantic gate
# ---------------------------------------------------------------------------


def test_invalid_prop_type_rejected() -> None:
    """PropParams with prop_type='invalid' raises ValidationError before SQL is built."""
    with pytest.raises(ValidationError):
        PropParams(
            game_id="2023_01_KC_DET",
            player_id="00-0033873",
            season=2023,
            sport="nfl",
            prop_type="invalid",  # type: ignore[arg-type]
            line=Decimal("250"),
            filters={},
        )


def test_parameterized_sql() -> None:
    """PropQueryBuilder.build() SQL contains only $N placeholders — player_id and line not in string."""
    if not _QB_IMPORTED:
        pytest.fail("PropQueryBuilder not importable — implementation not yet provided (Wave 0 RED)")
    params = _valid_prop_params()
    sql, args = PropQueryBuilder.build(params)  # type: ignore[union-attr]
    assert isinstance(sql, str), "build() first element must be str"
    assert isinstance(args, tuple), "build() second element must be tuple"
    assert "$1" in sql, "SQL must use $1 positional placeholder"
    # player_id and line values must NOT appear in the SQL string (injection prevention)
    assert "00-0033873" not in sql, "player_id value must not appear in the SQL string"
    assert "250" not in sql, "line value must not appear in the SQL string"


def test_filter_allowlist_unknown_key_dropped() -> None:
    """Unknown filter keys are silently dropped — key and value absent from SQL/args."""
    if not _QB_IMPORTED:
        pytest.fail("PropQueryBuilder not importable — implementation not yet provided (Wave 0 RED)")
    params = _valid_prop_params(filters={"injected_col": "malicious_val", "week": 3})
    sql, args = PropQueryBuilder.build(params)  # type: ignore[union-attr]
    assert "injected_col" not in sql, "Unknown filter key must not appear in SQL"
    assert "malicious_val" not in str(args), "Unknown filter value must not appear in args"
    # "week" IS allowed — its value (3) must be in args
    assert 3 in args, "Allowed filter value must appear in args tuple"
