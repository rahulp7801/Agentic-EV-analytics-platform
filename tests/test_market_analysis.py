"""Synthetic payoff fixtures test the real graph, not investment performance."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sportsbet.arbitrage.portfolio import MarketAnalysisRequest, PayoffCandidate, analyze_candidate
from sportsbet.graph.graph import create_graph

NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)


def candidate(venue='sportsbook', **updates):
    legs = [dict(leg_id=f'leg{i}', venue=venue, account=f'book{i}', quote_id=f'quote{i}',
        source_sha256='a'*64, rules_ref='fixture-rules', observed_at=NOW, available_at=NOW,
        event_start=NOW+timedelta(hours=1), unit_cost='0.45', fee_per_unit_bound='0',
        max_units='10', unit_step='1', payouts={'win': str(1-i), 'lose': str(i)}) for i in range(2)]
    return dict(candidate_id=venue, event_scope='fixture-event', coverage_review_ref='fixture-review',
                states=['win', 'lose'], legs=legs) | updates


def evaluate(data, **request_updates):
    request = MarketAnalysisRequest.model_validate(dict(as_of=NOW, budget='100', candidates=[data]) | request_updates)
    return analyze_candidate(request.candidates[0], request)


@pytest.mark.asyncio
async def test_actual_graph_routes_all_specialists_and_keeps_reports_separate():
    request = dict(as_of=NOW, budget='100', candidates=[candidate(venue)
                   for venue in ['sportsbook', 'kalshi', 'prizepicks']])
    output = await create_graph().ainvoke(dict(session_id='test', request_type='market_analysis', market_request=request))
    report = output['market_report']
    assert {r['specialist'] for r in report['results']} == {'sportsbook', 'kalshi', 'prizepicks'}
    for result in report['results']:
        assert result['status'] == 'scenario_edge'
        assert Decimal(result['worst_profit']) == 1
        assert Decimal(result['cost']) == 9
        assert result['units'] == {'leg0': '10', 'leg1': '10'}
        assert result['execution_ready'] is False
    assert report['execution_ready'] is False
    assert len(report['input_sha256']) == 64
    assert 'total_profit' not in report  # These portfolios may share liquidity.


def test_fees_exceptional_settlement_and_whole_units_can_remove_apparent_edge():
    data = candidate('kalshi')
    for leg in data['legs']:
        leg['fee_per_unit_bound'] = '.06'
    assert evaluate(data)['status'] == 'no_edge'
    data = candidate('kalshi', states=['win', 'lose', 'cancelled'])
    # In this fixture the Kalshi leg can settle at zero while the book refunds.
    data['legs'][0]['payouts']['cancelled'] = '0'
    data['legs'][1]['payouts']['cancelled'] = '.45'
    assert evaluate(data)['status'] == 'no_edge'
    assert evaluate(candidate(), budget='.89')['status'] == 'no_edge'
    result = evaluate(candidate(), budget='1')
    assert result['units'] == {'leg0': '1', 'leg1': '1'}
    assert Decimal(result['cost']) <= 1


@pytest.mark.parametrize(('field', 'value', 'reason'), [
    ('max_units', None, 'unknown_capacity'),
    ('fee_per_unit_bound', None, 'unknown_fees'),
    ('observed_at', NOW-timedelta(seconds=6), 'stale_quote'),
    ('available_at', NOW+timedelta(seconds=1), 'future_information'),
    ('event_start', NOW, 'event_started'),
    ('observed_at', NOW-timedelta(seconds=3), 'quote_time_skew'),
])
def test_missing_or_untimely_evidence_blocks(field, value, reason):
    data = candidate()
    data['legs'][0][field] = value
    result = evaluate(data)
    assert result['status'] == 'blocked'
    assert reason in result['reasons']
    assert result['worst_profit'] is None


def test_contract_schema_rejects_incomplete_states_and_duplicate_liquidity():
    assert evaluate(candidate(coverage_review_ref=None))['reasons'] == ['unreviewed_settlement_coverage']
    data = candidate()
    del data['legs'][0]['payouts']['lose']
    with pytest.raises(ValidationError):
        PayoffCandidate.model_validate(data)
    data = candidate()
    data['legs'][1]['account'] = 'book0'
    data['legs'][1]['quote_id'] = 'quote0'
    with pytest.raises(ValidationError, match='capacity'):
        PayoffCandidate.model_validate(data)
    data = candidate()
    data['legs'][0]['fee_per_unit_bound'] = 'NaN'
    with pytest.raises(ValidationError):
        PayoffCandidate.model_validate(data)


@pytest.mark.asyncio
async def test_replay_uses_same_graph_and_requires_explicit_settlement():
    from sportsbet.market_analysis import analyze
    request = MarketAnalysisRequest.model_validate(dict(as_of=NOW, budget='1', candidates=[candidate()]))
    result = await analyze(request, {})
    assert result['results'][0]['simulated_profit_bound'] is None
    result = await analyze(request, {'sportsbook': dict(state='lose', source_ref='fixture-result',
        resolved_at=(NOW+timedelta(hours=2)).isoformat())})
    assert Decimal(result['results'][0]['simulated_profit_bound']) == Decimal('.10')
    assert result['realized_roi'] is None
    with pytest.raises(ValueError, match='Unknown settlement'):
        await analyze(request, {'unknown': {}})
