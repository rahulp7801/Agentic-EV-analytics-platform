"""Execute date-filtered SQL against small historical fixtures (no external DB).

SQLite supports these aggregates/placeholders; only PostgreSQL casts and ILIKE
are normalized here. This verifies selected rows, not PostgreSQL connectivity.
"""
import sqlite3
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sportsbet.graph.models import PropParams, PropResult
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.prop.nba_executor import run_nba_prop_query
from sportsbet.prop.nba_query_builder import NBAQueryBuilder


def params(**overrides):
    return PropParams(**(dict(game_id="target", player_id="1", season=2025, sport="nba",
        prop_type="points", line=Decimal("20.5"), filters={}, as_of_date=date(2026, 1, 10)) | overrides))


def query_fixture(p):
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE nba_player_gamelogs (player_id INT, season INT, game_id TEXT, game_date TEXT, "
                   "points INT, rebounds INT, assists INT, steals INT, blocks INT, threes_made INT, "
                   "opponent_team TEXT, is_home INT, player_name TEXT)")
        db.executemany("INSERT INTO nba_player_gamelogs VALUES (1,2025,?,?,?,10,5,0,0,2,'BOS',1,'Player')",
                       [("old", "2026-01-01", 30), ("recent", "2026-01-09", 10),
                        ("target", "2026-01-10", 90), ("future", "2026-01-15", 100)])
        sql, args = NBAQueryBuilder.build(p)
        bound = {str(i): value.isoformat() if isinstance(value, date) else value
                 for i, value in enumerate(args, 1)}
        return dict(db.execute(sql.replace("::float", "").replace("ILIKE", "LIKE"), bound).fetchone())


def test_target_and_future_games_do_not_change_probability_sample():
    result = query_fixture(params(home_away="home"))
    assert result["total"] == 2
    assert result["successes"] == 1
    assert result["mean_val"] == 20


def test_recent_window_applies_cutoff_before_limit():
    result = query_fixture(params(last_n_games=1))
    assert result["total"] == 1
    assert result["successes"] == 0
    assert result["mean_val"] == 10


def test_dated_unconditional_and_double_double_use_actual_history():
    assert query_fixture(params())["total"] == 2
    result = query_fixture(params(prop_type="double_double", line=Decimal("0")))
    assert result["total"] == 2
    assert result["successes"] == 2


def test_empty_pre_game_history_stays_empty():
    assert query_fixture(params(as_of_date=date(2025, 12, 31)))["total"] == 0


async def test_empty_matchup_falls_back_to_pre_game_logs_not_season_totals():
    conn = AsyncMock()
    conn.fetchrow.side_effect = [{"total": 0, "successes": 0, "mean_val": None},
                                {"total": 2, "successes": 1, "mean_val": 20}]
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    result = await run_nba_prop_query(pool, params(opponent_team="LAL"))
    assert result.true_probability == Decimal("0.5")
    assert result.data_source == "pregame_fallback"
    for call in conn.fetchrow.call_args_list:
        assert "nba_player_gamelogs" in call.args[0]
        assert date(2026, 1, 10) in call.args
    assert "opponent_team =" not in conn.fetchrow.call_args_list[-1].args[0]


async def test_underpowered_matchup_falls_back_to_same_rolling_window():
    conn = AsyncMock()
    conn.fetchrow.side_effect = [
        {"total": 5, "successes": 3, "pushes": 0, "mean_val": 22},
        {"total": 40, "successes": 22, "pushes": 1, "mean_val": 21},
    ]
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    result = await run_nba_prop_query(
        pool,
        params(opponent_team="LAL", home_away="home", last_n_games=40),
    )

    assert result.sample_size == 40
    assert result.data_source == "pregame_fallback"
    fallback_sql, *fallback_args = conn.fetchrow.call_args_list[-1].args
    assert "opponent_team =" not in fallback_sql
    assert "is_home =" not in fallback_sql
    assert "LIMIT" in fallback_sql
    assert 40 in fallback_args
    assert date(2026, 1, 10) in fallback_args


async def test_agent_forwards_prediction_date():
    run = AsyncMock(return_value=PropResult(data_source="insufficient_sample", sample_size=0))
    with patch("sportsbet.prop.nba_agents.run_nba_prop_query", run):
        await make_nba_quant_agent(MagicMock())({"receiver_gsis_id": "1", "season": 2025,
            "game_id": "target", "prop_type": "points", "prop_line": "20.5",
            "as_of_date": date(2026, 1, 10)})
    assert run.call_args.args[1].as_of_date == date(2026, 1, 10)


async def test_factory_date_and_context_date_agree():
    from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer

    cutoff = date(2026, 1, 10)
    run = AsyncMock(return_value=PropResult(data_source="insufficient_sample", sample_size=0))
    state = {"receiver_gsis_id": "1", "season": 2025, "game_id": "target",
             "prop_type": "points", "prop_line": "20.5"}
    with patch("sportsbet.prop.nba_agents.run_nba_prop_query", run):
        await make_nba_quant_agent(MagicMock(), target_date=cutoff)(state)
    assert run.call_args.args[1].as_of_date == cutoff
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    override = date(2026, 1, 5)
    await make_nba_context_signals_producer(pool, target_date=cutoff)(state | {"as_of_date": override})
    assert conn.fetchrow.call_args.args[-1] == override
