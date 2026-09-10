"""Quote replay contract: preserve missing data and selection-specific outcomes."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from sportsbet.quant.backtest_replay import build_signals, load_snapshots
from sportsbet.quant.backtest import BacktestEngine

START = datetime(2024,1,14,18,tzinfo=timezone.utc)
ROW = dict(id=1,game_id='game',sportsbook='book',market_type='h2h',outcome_name='KC',line=None,
           price=-110, snapped_at=START-timedelta(hours=2),game_start_time=START)

def test_clv_only_mode():
    signals = build_signals([ROW, ROW | dict(id=2,price=-120,snapped_at=START-timedelta(minutes=1))])
    report = BacktestEngine().run(signals)
    assert signals[0].actual_outcome is None
    assert report.roi is None and report.hit_rate is None and report.brier_score is None
    assert report.clv_mean > 0

def test_outcomes_are_keyed_by_selection_entry_id():
    signals = build_signals([ROW, ROW | dict(id=3,outcome_name='DET')], {'1':True,'3':False})
    assert [s.actual_outcome for s in signals] == [True, False]

def test_missing_outcomes_and_rows():
    assert build_signals([]) == []
    assert build_signals([ROW | dict(game_start_time=None)]) == []
    assert build_signals([ROW], {'game':True})[0].actual_outcome is None

async def test_loader_does_not_guess_start_time():
    conn = AsyncMock()
    conn.fetch.return_value = []
    await load_snapshots(conn, 'game', 'h2h')
    sql, *args = conn.fetch.call_args.args
    assert '18 hours' not in sql and 'snapped_at < game_start_time' in sql
    assert args == ['game','h2h']

def test_model_replay_preserves_push_and_rejects_lookahead():
    row = ROW | dict(model_probability='0.4', push_probability='0.2',
        model_version='test-fixture', model_generated_at=ROW['snapped_at'])
    report = BacktestEngine().run(build_signals([row], {'1': True}))
    assert report.brier_score == pytest.approx(0.25)
    for invalid in (dict(model_generated_at=START), dict(model_version=None)):
        with pytest.raises(ValueError):
            build_signals([row | invalid])

def test_ambiguous_identity_does_not_produce_performance():
    with pytest.raises(ValueError, match='unique ID'):
        build_signals([ROW, ROW | dict(outcome_name='DET')])
    assert build_signals([ROW | dict(market_type='player_points', outcome_name='Over', line=20.5)]) == []

def test_cli_empty_dataset_fails_without_inventing_results(tmp_path, monkeypatch, capsys):
    import json
    from sportsbet.quant.backtest_replay import main
    path = tmp_path / 'quotes.json'
    path.write_text('[]')
    monkeypatch.setattr('sys.argv', ['backtest', '--snapshots-file', str(path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'no_usable_quotes'
    assert report['roi'] is None and report['sample_size'] == 0
    assert len(report['snapshots_sha256']) == 64
