"""TDD tests for PropParams and PropResult Pydantic models (Phase 10 Plan 01).

These tests are written RED — they import from sportsbet.graph.models which does
not yet export PropParams or PropResult. Tests will fail until Task 2 adds those
classes.

Tests verify:
- PropParams rejects invalid prop_type (not in Literal union)
- PropParams rejects season < 2000
- PropResult instantiates with all-None fields (stub node compatible)
"""
from __future__ import annotations

import pytest
import pydantic


def test_prop_params_invalid_prop_type() -> None:
    """PropParams rejects prop_type not in the Literal union with ValidationError."""
    from sportsbet.graph.models import PropParams
    from decimal import Decimal

    with pytest.raises(pydantic.ValidationError):
        PropParams(
            game_id="2024_01_KC_BUF",
            player_id="00-0033873",
            season=2024,
            sport="nfl",
            prop_type="invalid_type",
            line=Decimal("250.5"),
            filters={},
        )


def test_prop_params_invalid_season() -> None:
    """PropParams rejects season < 2000 (ge=2000 constraint) with ValidationError."""
    from sportsbet.graph.models import PropParams
    from decimal import Decimal

    with pytest.raises(pydantic.ValidationError):
        PropParams(
            game_id="2024_01_KC_BUF",
            player_id="00-0033873",
            season=1990,
            sport="nfl",
            prop_type="pass_yds",
            line=Decimal("250.5"),
            filters={},
        )


def test_prop_result_all_nullable() -> None:
    """PropResult() instantiates with all-None fields — no ValidationError raised.

    This verifies stub-node compatibility: Phase 11 stub nodes can return
    PropResult() without DB access during development.
    """
    from sportsbet.graph.models import PropResult

    result = PropResult()
    assert result.true_probability is None
    assert result.sample_size is None
    assert result.confidence_interval is None
    assert result.data_source is None
    assert result.mean_stat is None
