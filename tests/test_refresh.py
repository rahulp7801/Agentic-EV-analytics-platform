from datetime import date
from unittest.mock import MagicMock, patch

from sportsbet.refresh import refresh


def test_manual_refresh_publishes_failure_then_recovery_without_error_text(monkeypatch,capsys):
    import sys
    import pytest
    from sportsbet import refresh as module
    stored=[]
    monkeypatch.setattr(module,'publish_snapshot',lambda key,value:stored.append((key,value)))
    monkeypatch.setattr(sys,'argv',['refresh','--sport','both'])
    def provider(sport,day,backfill):
        if sport=='nfl': raise RuntimeError('private-provider-credential')
        return {'provider':'espn','rows':0}
    monkeypatch.setattr(module,'refresh',provider)
    with pytest.raises(SystemExit) as exc: module.main()
    assert exc.value.code==1
    assert [(key,value['status']) for key,value in stored]==[
        ('refresh:nfl','running'),('refresh:nfl','failed'),('refresh:nba','running'),('refresh:nba','complete')]
    assert 'private-provider-credential' not in capsys.readouterr().out
    assert stored[1][1]['error_type']=='RuntimeError'
    assert stored[-1][1]['coverage']=={'provider':'espn','rows':0}
    monkeypatch.setattr(module,'refresh',lambda *args:{'provider':'nflverse'})
    assert module.refresh_history('nfl',date(2026,9,11))['status']=='complete'


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
