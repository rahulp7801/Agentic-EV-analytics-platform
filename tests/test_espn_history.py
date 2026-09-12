"""Small explicit fixtures verify extraction, not model performance."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from sportsbet.ingestion.espn_history import parse_boxscore


def summary():
    return dict(header=dict(id='event', competitions=[dict(date='2026-01-29T00:00Z',
        status=dict(type=dict(completed=True)), competitors=[
            dict(id='1', team=dict(abbreviation='LAL')), dict(id='2', team=dict(abbreviation='CLE'))])]),
        boxscore=dict(players=[dict(team=dict(id='1'), statistics=[dict(
            keys=['points','rebounds','assists'], athletes=[
                dict(athlete=dict(id='player',displayName='Fixture'), stats=['0','3','--'], didNotPlay=False),
                dict(athlete=dict(id='dnp',displayName='Absent'), stats=[], didNotPlay=True)])])]))


def test_final_stats_preserve_zero_skip_missing_and_dnp():
    data = summary()
    rows = parse_boxscore(data, 'nba')
    assert [(r['prop_type'],r['actual_value']) for r in rows] == [('points',0),('rebounds',3)]
    assert all(r['game_date'] == '2026-01-28' for r in rows)
    assert all('price' not in r and 'line' not in r for r in rows)
    data['header']['competitions'][0]['status']['type']['completed'] = False
    assert parse_boxscore(data, 'nba') == []


def test_conflicting_stats_fail_instead_of_choosing_a_value():
    data = summary()
    duplicate = deepcopy(data['boxscore']['players'][0])
    duplicate['statistics'][0]['athletes'][0]['stats'][0] = '99'
    data['boxscore']['players'].append(duplicate)
    with pytest.raises(ValueError, match='Conflicting'):
        parse_boxscore(data, 'nba')


def test_nfl_boxscore_exports_receptions_for_unpriced_walkforward_data():
    data=summary()
    group=data['boxscore']['players'][0]['statistics'][0]
    group['keys']=['passingYards','rushingYards','receivingYards','receptions']
    group['athletes'][0]['stats']=['0','0','31','3']
    rows=parse_boxscore(data,'nfl')
    assert {(row['prop_type'],row['actual_value']) for row in rows}=={
        ('pass_yds',0),('rush_yds',0),('rec_yds',31),('receptions',3)}


async def test_walkforward_uses_exclusive_date_and_no_fabricated_quotes(monkeypatch):
    from sportsbet.quant import walkforward
    from sportsbet.graph.models import PropResult
    conn = AsyncMock()
    conn.fetch.return_value = [{'player_id':123}]
    class Pool:
        def acquire(self):
            context = AsyncMock()
            context.__aenter__.return_value = conn
            return context
        close = AsyncMock()
    pool = Pool()
    graph = AsyncMock()
    graph.ainvoke.return_value = dict(nba_prop_result=PropResult(
        true_probability=Decimal('0.4'), sample_size=40, push_probability=Decimal('0')))
    monkeypatch.setattr(walkforward, 'create_async_pool', AsyncMock(return_value=pool))
    monkeypatch.setattr(walkforward, 'create_graph', lambda **kwargs: graph)
    dataset = dict(kind='final_player_stats', sport='nba', records=parse_boxscore(summary(),'nba'))
    result = await walkforward.evaluate(dataset, 'points', Decimal('20.5'))
    state = graph.ainvoke.call_args.args[0]
    assert state['as_of_date'] == date(2026,1,28)
    assert state['last_n_games'] == 40 and state['player_prop_snapshots'] == []
    assert result['brier_score'] == pytest.approx(0.16)
    assert result['roi'] is None and result['clv'] is None
    pool.close.assert_awaited_once()
