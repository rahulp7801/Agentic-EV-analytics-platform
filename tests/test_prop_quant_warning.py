"""Test that prop_quant_agent emits a WARNING when kinematic_result is None for a receiving prop.

TDD RED test — verifies that a structlog WARNING with event
'prop_quant_agent_kinematic_missing' is emitted when:
- kinematic_result is None
- prop_type is in RECEIVING_PROPS (rec_yds, rec_tds, receptions)

This test must FAIL (RED) before agents.py is patched, and PASS (GREEN)
after the log.warning call is added.

SC-4 success criterion: log.warning is called when kinematic_result is None
and prop_type is in RECEIVING_PROPS.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
import structlog.testing


def _make_prop_result_stub() -> Any:
    """Return a minimal PropResult with enough fields to pass the agent."""
    from sportsbet.graph.models import PropResult

    return PropResult(
        game_id="2025_01_KC_LAC",
        player_id="00-0012345",
        prop_type="rec_yds",
        line=Decimal("60.5"),
        true_probability=Decimal("0.55"),
        sample_size=35,
        data_source="postgresql",
    )


def test_kinematic_missing_warning() -> None:
    """prop_quant_agent must emit WARNING 'prop_quant_agent_kinematic_missing'
    when kinematic_result is None and prop_type is 'rec_yds' (in RECEIVING_PROPS).
    """
    from sportsbet.prop.agents import make_prop_quant_agent

    # MagicMock pool — follows Phase 4 locked decision (not AsyncMock)
    mock_pool = MagicMock()

    prop_result_stub = _make_prop_result_stub()

    # Minimal GraphState for a receiving-prop request
    state: dict[str, Any] = {
        "session_id": "test-session-warning-001",
        "receiver_gsis_id": "00-0012345",
        "season": 2025,
        "game_id": "2025_01_KC_LAC",
        "prop_type": "rec_yds",
        "prop_line": "60.5",
        "prop_filters": {},
        "situational_params": None,
        "kinematic_result": None,  # <-- key: kinematic is absent
    }

    # Capture structlog output
    with structlog.testing.capture_logs() as cap_logs:
        with patch(
            "sportsbet.prop.agents.run_prop_query",
            new=AsyncMock(return_value=prop_result_stub),
        ):
            agent_fn = make_prop_quant_agent(mock_pool)
            asyncio.run(agent_fn(state))

    # Assert that the warning was emitted
    warning_events = [
        entry
        for entry in cap_logs
        if entry.get("event") == "prop_quant_agent_kinematic_missing"
        and entry.get("log_level") == "warning"
    ]
    assert warning_events, (
        "Expected WARNING 'prop_quant_agent_kinematic_missing' to be emitted when "
        "kinematic_result=None and prop_type='rec_yds' (in RECEIVING_PROPS), but no "
        "such warning was found in captured logs.\n"
        f"Captured log events: {[e.get('event') for e in cap_logs]}"
    )
