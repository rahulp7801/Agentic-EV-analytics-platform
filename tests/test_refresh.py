from datetime import date
from unittest.mock import MagicMock, patch

from sportsbet.refresh import refresh


def test_opening_season_backfill_and_daily_refresh():
    engine = MagicMock()
    with patch('sportsbet.refresh.get_sync_engine', return_value=engine), \
         patch('sportsbet.refresh.ingest_games_seasons') as games, \
         patch('sportsbet.refresh.ingest_player_stats_seasons') as nfl, \
         patch('sportsbet.refresh.ingest_nba_gamelogs_season') as nba:
        refresh('nfl', date(2026,9,10), backfill=True)
        games.assert_called_once_with([2024,2025,2026], engine)
        nfl.assert_called_once_with([2024,2025,2026], engine)
        refresh('nba', date(2026,10,20), backfill=True)
        assert [call.args[0] for call in nba.call_args_list] == [2025,2026]
        nba.reset_mock()
        refresh('nba', date(2027,1,10))
        nba.assert_called_once_with(2026,engine)
        assert engine.dispose.call_count == 3
