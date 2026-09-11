"""Exercise real conditional builders instead of obsolete expected-failure stubs."""
from datetime import date
from decimal import Decimal

import pytest

from sportsbet.graph.models import PropParams
from sportsbet.prop.query_builder import PropQueryBuilder
from sportsbet.prop.nba_query_builder import NBAQueryBuilder


@pytest.mark.parametrize('sport,builder', [('nfl',PropQueryBuilder),('nba',NBAQueryBuilder)])
def test_conditional_filters_keep_untrusted_values_in_parameters(sport,builder):
    teammate = "Player'); DROP TABLE player_stats; --"
    opponent = "BOS' OR '1'='1"
    params = PropParams(game_id='target',player_id='123',season=2024,sport=sport,
        prop_type='pass_yds' if sport=='nfl' else 'points',line=Decimal('20.5'),
        as_of_date=date(2025,1,15),last_n_games=20,opponent_team=opponent,
        teammate_out=[teammate],filters={})
    sql,args=builder.build(params)
    for value in (opponent,teammate):
        assert value not in sql
        assert value in args
        assert f'${args.index(value)+1}' in sql
    assert date(2025,1,15) in args
    assert f'< ${args.index(date(2025,1,15))+1}' in sql
    assert 'LIMIT' in sql and 20 in args
    if sport=='nfl':
        assert 'INTERVAL' in sql and 'injury_reports' in sql
    else:
        assert 'NOT EXISTS' in sql and 'nba_player_gamelogs' in sql
