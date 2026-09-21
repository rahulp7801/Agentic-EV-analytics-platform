from datetime import datetime, timedelta, timezone

from sportsbet.picks import build_pick_board


def row(identity: str, captured: datetime, start: datetime, *, probability=.7, outcome=None):
    return dict(prediction_id=identity*64,game_id='game',player='Player',player_id='00-1',sport='nfl',
        game_date=start.date().isoformat(),home_team='Home',away_team='Away',prop_type='pass_yds',
        direction='over',line=250.5,sportsbook='book',american_odds=-110,
        model_probability=probability,push_probability=0,model_sample_size=40,
        model_mean_stat=260.25,
        model_confidence_interval=[.55,.8],captured_at=captured.isoformat(),
        game_start_time=start.isoformat(),quote_time=captured.isoformat(),model_generated_at=captured.isoformat(),
        quote_source_provider='the_odds_api',quote_source_sha256='a'*64,
        quote_source_record_sha256='b'*64,accepted=True,gate_reason='accepted',stake_fraction=.01,
        model_version='empirical-jeffreys-v4',recommendation_policy_version='confidence-floor-v2',
        trade_plan=['one','two','three'],forecast_cutoff=start.date().isoformat(),
        outcome=outcome,outcome_source='observed_final_stats' if outcome is not None else None,
        outcome_ref='proof' if outcome is not None else None,outcome_observed_at=(start+timedelta(hours=4)).isoformat() if outcome is not None else None,
        actual_value=300 if outcome is not None else None,outcome_evidence={'proof':True} if outcome is not None else None)


def test_board_uses_latest_approved_capture_before_fixed_lock(monkeypatch):
    start=datetime(2026,9,20,20,tzinfo=timezone.utc)
    rows=[row('a',start-timedelta(hours=3),start,probability=.65),
          row('b',start-timedelta(minutes=70),start,probability=.7),
          row('c',start-timedelta(minutes=45),start,probability=.8)]
    monkeypatch.setattr('sportsbet.picks.quote_evidence_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.settlement_identity_valid',lambda value:True)
    board=build_pick_board(rows,'nfl',start-timedelta(minutes=30))
    assert len(board['current'])==1
    assert board['current'][0]['prediction_id']=='b'*64
    assert board['current'][0]['board_state']=='locked'
    assert board['current'][0]['lock_at']==(start-timedelta(minutes=60)).isoformat()
    assert board['current'][0]['mean_stat']==260.25
    assert board['selection_policy_version']=='pregame-t60-v1'


def test_board_rejects_invalid_retained_mean(monkeypatch):
    start=datetime(2026,9,20,20,tzinfo=timezone.utc)
    invalid=row('a',start-timedelta(hours=2),start)
    invalid['model_mean_stat']='NaN'
    monkeypatch.setattr('sportsbet.picks.quote_evidence_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.settlement_identity_valid',lambda value:True)
    assert build_pick_board([invalid],'nfl',start-timedelta(hours=1,minutes=30))['current']==[]


def test_board_never_grades_without_reproducible_settlement(monkeypatch):
    start=datetime(2026,9,20,20,tzinfo=timezone.utc)
    rows=[row('a',start-timedelta(minutes=70),start,outcome=True)]
    monkeypatch.setattr('sportsbet.picks.quote_evidence_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.settlement_identity_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.verified_settlement_evidence',lambda *args:False)
    board=build_pick_board(rows,'nfl',start+timedelta(hours=5))
    assert board['history'][0]['result']=='pending'
    assert board['history'][0]['actual_value'] is None
    assert board['summary']=={'current':0,'settled':0,'pending':1,'wins':0,'losses':0,'pushes':0,'verified_win_rate':None}


def test_board_rejects_conflicting_player_game_identity(monkeypatch):
    start=datetime(2026,9,20,20,tzinfo=timezone.utc)
    first=row('a',start-timedelta(hours=3),start)
    second=row('b',start-timedelta(hours=2),start+timedelta(minutes=30))
    monkeypatch.setattr('sportsbet.picks.quote_evidence_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.settlement_identity_valid',lambda value:True)
    board=build_pick_board([first,second],'nfl',start-timedelta(hours=1))
    assert board['current']==[]


def test_board_reports_only_verified_prospective_results(monkeypatch):
    start=datetime(2026,9,20,20,tzinfo=timezone.utc)
    rows=[row('a',start-timedelta(minutes=70),start,outcome=True)]
    monkeypatch.setattr('sportsbet.picks.quote_evidence_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.settlement_identity_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.verified_settlement_evidence',lambda *args:True)
    board=build_pick_board(rows,'nfl',start+timedelta(hours=5))
    assert board['history'][0]['result']=='win' and board['history'][0]['result_verified'] is True
    assert board['summary']['wins']==1 and board['summary']['verified_win_rate']==1


def test_board_totals_describe_only_bounded_public_records(monkeypatch):
    start=datetime(2026,9,20,20,tzinfo=timezone.utc)
    rows=[]
    for index in range(205):
        item=row(f'{index:064x}'[-1],start-timedelta(minutes=70),start,outcome=index % 2 == 0)
        item['prediction_id']=f'{index:064x}'
        item['game_id']=f'game-{index}'
        item['player']=f'Player {index}'
        rows.append(item)
    monkeypatch.setattr('sportsbet.picks.quote_evidence_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.settlement_identity_valid',lambda value:True)
    monkeypatch.setattr('sportsbet.picks.verified_settlement_evidence',lambda *args:True)
    board=build_pick_board(rows,'nfl',start+timedelta(hours=5))
    assert len(board['history'])==200
    assert board['summary']['settled']==200
    assert board['summary']['wins']+board['summary']['losses']==200
