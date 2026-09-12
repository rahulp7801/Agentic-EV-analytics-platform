"""Failure diagnostics must be safe and failed requests cannot reuse old estimates."""
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from sportsbet.graph.agents import make_kinematic_agent, make_quant_agent
from sportsbet.graph.graph import create_graph
from sportsbet.graph.models import PropResult
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.prop.agents import make_prop_quant_agent
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent

CANARY = 'private-diagnostic-canary-do-not-log'


class BrokenDatabase:
    """Exercise the actual query builders/executors without a provider or database."""
    calls = 0

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def fetchrow(self, *args):
        self.calls += 1
        raise RuntimeError(CANARY)


def request(sport='nfl'):
    prop = 'points' if sport == 'nba' else 'pass_yds'
    result = PropResult(true_probability=Decimal('.60'), sample_size=40,
        confidence_interval=(Decimal('.55'),Decimal('.70')), data_source='postgresql')
    return dict(session_id='failure-regression', request_type='nba_prop_analysis' if sport == 'nba' else 'prop_analysis',
        season=2025, week=1, game_id='fixture-game', home_team='KC', away_team='LV',
        receiver_gsis_id='1620001' if sport=='nba' else 'fixture-player', player_name='Fixture Player', sport=sport,
        prop_type=prop, prop_line=Decimal('20.5'), prop_side='over', last_n_games=40,
        prop_result=result if sport=='nfl' else None, nba_prop_result=result if sport=='nba' else None,
        player_prop_snapshots=[PlayerPropSnapshotCreate(sport=sport, player_name='Fixture Player',
            sportsbook='draftkings', prop_type='player_'+prop, side='Over', line=Decimal('20.5'),
            price=100, implied_probability=Decimal('.5'))])


@pytest.mark.parametrize('factory,result_key', [
    (make_prop_quant_agent, 'prop_result'), (make_nba_quant_agent, 'nba_prop_result'),
    (make_quant_agent, 'quant_result'), (make_kinematic_agent, 'kinematic_result')])
async def test_database_failure_cannot_escape_into_logs_or_returned_state(factory, result_key):
    pool = BrokenDatabase()
    state = request('nba' if result_key=='nba_prop_result' else 'nfl')
    with capture_logs() as logs:
        update = await factory(pool)(state)
    assert pool.calls == 1
    assert update['error'] and CANARY not in update['error']
    assert CANARY not in repr(logs)
    assert all(not row.get('exc_info') and 'exception' not in row for row in logs)
    assert update[result_key] is None or update[result_key].true_probability is None


@pytest.mark.parametrize('sport', ['nfl', 'nba'])
@pytest.mark.parametrize('bad_field,bad_value', [('season', CANARY), ('prop_line', CANARY)])
async def test_invalid_prop_request_clears_prior_model_before_signal_generation(sport, bad_field, bad_value):
    pool = BrokenDatabase()
    graph = create_graph(prop_quant_node=make_prop_quant_agent(pool),
        nba_quant_node=make_nba_quant_agent(pool), prop_arbitrage_node=make_prop_arbitrage_agent(sport=sport))
    state = request(sport)
    # Demonstrate that the old estimate and quote are otherwise capable of yielding a signal.
    prior = (await make_prop_arbitrage_agent(sport=sport)(state))['ev_signal']
    assert prior is not None
    state.update(ev_signal=prior, pending_signals=[prior], cleared_signals=[prior])
    state[bad_field] = bad_value
    with capture_logs() as logs:
        result = await graph.ainvoke(state)
    key = 'nba_prop_result' if sport=='nba' else 'prop_result'
    assert result[key] is None or result[key].true_probability is None
    assert result.get('ev_signal') is None and result.get('pending_signals') == []
    assert result.get('cleared_signals') == []
    assert result['error'] and CANARY not in result['error']
    assert CANARY not in repr(logs) and not any(row.get('exc_info') for row in logs)
    assert pool.calls == 0


async def test_router_does_not_log_old_error_or_return_old_signals():
    state = request()
    prior = (await make_prop_arbitrage_agent(sport='nfl')(state))['ev_signal']
    state.update(error=CANARY, ev_signal=prior, pending_signals=[prior], cleared_signals=[prior])
    with capture_logs() as logs:
        result = await create_graph().ainvoke(state)
    assert result['ev_signal'] is None and result['pending_signals'] == [] and result['cleared_signals'] == []
    assert CANARY not in repr(logs)
