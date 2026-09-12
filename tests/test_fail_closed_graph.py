"""Unconfigured graph routes must never return fixture analysis."""
from datetime import datetime, timezone

import pytest

from sportsbet.graph.graph import create_graph


def state(request_type):
    return dict(session_id='fail-closed-test', request_type=request_type,
        created_at=datetime.now(timezone.utc), error=None, quant_result=None,
        ev_signal=None, pending_signals=[], cleared_signals=[])


@pytest.mark.parametrize(('request_type', 'code'), [
    ('quant_analysis', 'quant_agent_not_configured'),
    ('odds_check', 'arbitrage_agent_not_configured'),
    ('arbitrage_analysis', 'arbitrage_agent_not_configured'),
    ('context_update', 'context_agent_not_configured'),
    ('kinematic_analysis', 'kinematic_agent_not_configured'),
    ('prop_analysis', 'prop_quant_agent_not_configured'),
    ('nba_prop_analysis', 'nba_quant_agent_not_configured'),
    ('prop_arbitrage_analysis', 'prop_arbitrage_agent_not_configured'),
])
async def test_default_analysis_routes_fail_closed(request_type, code):
    result = await create_graph().ainvoke(state(request_type))
    assert result['error'] == code
    assert result.get('quant_result') is None
    assert result.get('ev_signal') is None
    assert result.get('pending_signals') == []
    assert result.get('cleared_signals') == []


async def test_unknown_route_returns_stable_error_without_echoing_input():
    unknown = 'private-route-canary'
    result = await create_graph().ainvoke(state(unknown))
    assert result['error'] == 'unknown_request_type'
    assert unknown not in repr(result)
