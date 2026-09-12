from datetime import date, datetime, timedelta, timezone
import json

import pytest

from sportsbet.ledger import Ledger
from sportsbet.ingestion.provenance import stat_row_sha256
from sportsbet.settlement import pending_schedule_offsets, settle_final_props


def prediction(ledger, *, direction='over', line=20.5, sport='nba', prop_type='points', player_id='7'):
    now=datetime.now(timezone.utc)
    payload=dict(game_id='odds-event',player='Player',player_id=player_id,sport=sport,
        game_date=(now-timedelta(days=1)).date().isoformat(),home_team='Home',away_team='Away',
        prop_type=prop_type,direction=direction,line=line,sportsbook='book',american_odds=100,
        model_probability=.6,captured_at=(now-timedelta(days=1,hours=3)).isoformat(),
        game_start_time=(now-timedelta(days=1,hours=2)).isoformat())
    return ledger.record('scan',payload),payload


def schedule(payload, *, completed=True, home='Home', home_abbr='HOM', away_abbr='AWY'):
    return dict(status='complete',captured_at=datetime.now(timezone.utc).isoformat(),
        games=[dict(provider_event_id='espn-event',date=payload['game_date'],
        home_name=home,away_name='Away',home_abbr=home_abbr,away_abbr=away_abbr,completed=completed,
        game_time=payload['game_start_time'])])


def create_nba_stats(db):
    db.execute('''CREATE TABLE nba_player_gamelogs (player_id INTEGER, game_id TEXT,
        game_date TEXT, team_abbreviation TEXT, points INTEGER, rebounds INTEGER,
        assists INTEGER, source_provider TEXT, source_sha256 TEXT,
        source_record_sha256 TEXT, source_observed_at TEXT)''')


def add_nba_stat(db,payload,points,*,game_id='stat-game',team='HOM',provider='nba',record_hash=None,observed_at=None):
    row=dict(player_id=int(payload['player_id']),game_id=game_id,game_date=payload['game_date'],
        team_abbreviation=team,points=points,rebounds=5,assists=4)
    digest=record_hash if record_hash is not None else stat_row_sha256('nba',row)
    db.execute('INSERT INTO nba_player_gamelogs VALUES (?,?,?,?,?,?,?,?,?,?,?)',(
        *row.values(),provider,'a'*64,digest,observed_at or datetime.now(timezone.utc).isoformat()))


@pytest.mark.parametrize(('direction','line','actual','expected'),[
    ('over',20.5,21,True),('over',20.5,20,False),('over',20,20,'push'),
    ('under',20.5,20,True),('under',20.5,21,False),('under',20,20,'push'),
])
def test_settlement_uses_final_exact_game_and_observed_stat(tmp_path,direction,line,actual,expected):
    ledger=Ledger(tmp_path/'audit.sqlite')
    key,payload=prediction(ledger,direction=direction,line=line)
    with ledger.connect() as db:
        create_nba_stats(db);add_nba_stat(db,payload,actual)
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['settled']==1 and report['pending']==0
    row=next(row for row in ledger.predictions() if row['prediction_id']==key)
    assert row['outcome']==expected and row['actual_value']==actual
    assert row['outcome_source']=='observed_final_stats'
    assert row['outcome_ref'].startswith('espn_schedule+nba:espn-event:sha256:')
    assert datetime.fromisoformat(row['outcome_observed_at']).utcoffset() is not None
    assert row['outcome_evidence']['actual_value']==str(actual)
    assert row['outcome_evidence']['schedule_identity_version']==2
    assert (row['outcome_evidence']['home_abbr'],row['outcome_evidence']['away_abbr'])==('HOM','AWY')
    metrics=ledger.report()
    assert metrics['settled_count']==1 and metrics['unverified_settlements']==0


def test_metrics_reject_tampered_retained_settlement_evidence(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');key,payload=prediction(ledger)
    with ledger.connect() as db:
        create_nba_stats(db);add_nba_stat(db,payload,21)
    assert settle_final_props(ledger,'nba',schedule(payload))['settled']==1
    with ledger.connect() as db:
        proof=json.loads(db.execute('SELECT outcome_evidence FROM predictions WHERE id=?',(key,)).fetchone()[0])
        proof['actual_value']='99'
        db.execute('UPDATE predictions SET outcome_evidence=? WHERE id=?',
            (json.dumps(proof,sort_keys=True,separators=(',',':')),key))
    metrics=ledger.report()
    assert metrics['settled_count']==0 and metrics['pending_count']==1
    assert metrics['unverified_settlements']==1 and metrics['roi'] is None
    with ledger.connect() as db:
        db.execute('UPDATE predictions SET outcome_evidence=? WHERE id=?',('invalid-json',key))
    assert ledger.predictions()[0]['outcome_evidence'] is None
    assert ledger.report()['unverified_settlements']==1


@pytest.mark.parametrize(('schedule_change','stats','reason'),[
    ({'completed':False},[(21,)],'final_game_not_matched'),
    ({'home':'Different'},[(21,)],'final_game_not_matched'),
    ({},[],'stat_not_found_or_ambiguous'),
    ({},[(21,),(22,)],'stat_not_found_or_ambiguous'),
])
def test_settlement_never_guesses_game_dnp_or_ambiguous_stat(tmp_path,schedule_change,stats,reason):
    ledger=Ledger(tmp_path/'audit.sqlite');key,payload=prediction(ledger)
    with ledger.connect() as db:
        create_nba_stats(db)
        for index,(value,) in enumerate(stats):
            add_nba_stat(db,payload,value,game_id=f'stat-game-{index}')
    report=settle_final_props(ledger,'nba',schedule(payload,**schedule_change))
    assert report['settled']==0 and report['pending']==1 and report['reasons']=={reason:1}
    assert next(row for row in ledger.predictions() if row['prediction_id']==key)['outcome'] is None


def test_settlement_does_not_rewrite_existing_outcome(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');key,payload=prediction(ledger)
    ledger.settle({key:False})
    with ledger.connect() as db:
        create_nba_stats(db);add_nba_stat(db,payload,99)
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['candidates']==0 and report['settled']==0
    assert next(row for row in ledger.predictions() if row['prediction_id']==key)['outcome'] is False


def test_automatic_correction_only_rechecks_dates_in_supplied_evidence(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');key,payload=prediction(ledger)
    with ledger.connect() as db:
        create_nba_stats(db);add_nba_stat(db,payload,21)
    assert settle_final_props(ledger,'nba',schedule(payload))['settled']==1
    ledger.settle({key:True},source='espn_final_stats',source_ref='legacy')
    with ledger.connect() as db:
        corrected=dict(player_id=7,game_id='stat-game',game_date=payload['game_date'],
            team_abbreviation='HOM',points=20,rebounds=5,assists=4)
        db.execute('UPDATE nba_player_gamelogs SET points=20,source_record_sha256=? WHERE player_id=7',
            (stat_row_sha256('nba',corrected),))
    outside={**schedule(payload),'games':[]}
    assert settle_final_props(ledger,'nba',outside)['candidates']==0
    assert next(row for row in ledger.predictions() if row['prediction_id']==key)['outcome'] is True
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['candidates']==1 and report['settled']==1
    assert next(row for row in ledger.predictions() if row['prediction_id']==key)['outcome'] is False


def test_settlement_only_counts_dates_present_in_supplied_schedule(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');_,payload=prediction(ledger)
    outside=payload | {'game_id':'older-odds-event',
        'game_date':(date.fromisoformat(payload['game_date'])-timedelta(days=1)).isoformat()}
    ledger.record('older-scan',outside)
    with ledger.connect() as db:
        create_nba_stats(db)
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['candidates']==1 and report['pending']==1
    assert report['reasons']=={'stat_not_found_or_ambiguous':1}
    assert all(row['outcome'] is None for row in ledger.predictions())


def test_settlement_cannot_use_player_stat_from_another_same_day_game(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');_,payload=prediction(ledger)
    with ledger.connect() as db:
        create_nba_stats(db);add_nba_stat(db,payload,99,team='OTH')
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['settled']==0 and report['pending']==1
    assert report['reasons']=={'stat_not_found_or_ambiguous':1}


def test_nfl_settlement_joins_exact_player_week_team_and_game_date(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite')
    key,payload=prediction(ledger,line=250.5,sport='nfl',prop_type='pass_yds',player_id='gsis-7')
    with ledger.connect() as db:
        db.execute('''CREATE TABLE player_stats (player_id TEXT, season INTEGER, week INTEGER,
            team TEXT, passing_yards INTEGER, rushing_yards INTEGER, receiving_yards INTEGER, receptions INTEGER,
            source_provider TEXT, source_sha256 TEXT, source_record_sha256 TEXT,
            source_observed_at TEXT)''')
        db.execute('CREATE TABLE games (season INTEGER, week INTEGER, home_team TEXT, away_team TEXT, game_date TEXT)')
        row=dict(player_id='gsis-7',season=2026,week=1,team='LA',passing_yards=251,
            rushing_yards=0,receiving_yards=0,receptions=0)
        db.execute('INSERT INTO player_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
            *row.values(),'nflverse','b'*64,stat_row_sha256('nfl',row,legacy_nfl=True),
            datetime.now(timezone.utc).isoformat()))
        db.execute("INSERT INTO games VALUES (2026,1,'LA','SEA',?)",(payload['game_date'],))
    report=settle_final_props(ledger,'nfl',schedule(payload,home_abbr='LAR',away_abbr='SEA'))
    row=next(item for item in ledger.predictions() if item['prediction_id']==key)
    assert report['settled']==1 and row['outcome'] is True and row['actual_value']==251
    assert ledger.report()['unverified_settlements']==0


def test_nfl_settlement_preserves_negative_rushing_yards(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite')
    key,payload=prediction(ledger,direction='under',line=.5,sport='nfl',
        prop_type='rush_yds',player_id='gsis-7')
    with ledger.connect() as db:
        db.execute('''CREATE TABLE player_stats (player_id TEXT, season INTEGER, week INTEGER,
            team TEXT, passing_yards INTEGER, rushing_yards INTEGER, receiving_yards INTEGER, receptions INTEGER,
            source_provider TEXT, source_sha256 TEXT, source_record_sha256 TEXT,
            source_observed_at TEXT)''')
        db.execute('CREATE TABLE games (season INTEGER, week INTEGER, home_team TEXT, away_team TEXT, game_date TEXT)')
        row=dict(player_id='gsis-7',season=2026,week=1,team='HOM',passing_yards=0,
            rushing_yards=-2,receiving_yards=0,receptions=0)
        db.execute('INSERT INTO player_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
            *row.values(),'nflverse','b'*64,stat_row_sha256('nfl',row),datetime.now(timezone.utc).isoformat()))
        db.execute("INSERT INTO games VALUES (2026,1,'HOM','AWY',?)",(payload['game_date'],))
    report=settle_final_props(ledger,'nfl',schedule(payload))
    settled=next(item for item in ledger.predictions() if item['prediction_id']==key)
    assert report['settled']==1 and settled['outcome'] is True and settled['actual_value']==-2


@pytest.mark.parametrize(('legacy','expected'),[(False,1),(True,0)])
def test_nfl_reception_settlement_requires_reception_committed_provenance(tmp_path,legacy,expected):
    ledger=Ledger(tmp_path/f'audit-{legacy}.sqlite')
    key,payload=prediction(ledger,line=4.5,sport='nfl',prop_type='receptions',player_id='gsis-7')
    with ledger.connect() as db:
        db.execute('''CREATE TABLE player_stats (player_id TEXT, season INTEGER, week INTEGER,
            team TEXT, passing_yards INTEGER, rushing_yards INTEGER, receiving_yards INTEGER, receptions INTEGER,
            source_provider TEXT, source_sha256 TEXT, source_record_sha256 TEXT,
            source_observed_at TEXT)''')
        db.execute('CREATE TABLE games (season INTEGER, week INTEGER, home_team TEXT, away_team TEXT, game_date TEXT)')
        row=dict(player_id='gsis-7',season=2026,week=1,team='HOM',passing_yards=0,
            rushing_yards=0,receiving_yards=62,receptions=5)
        digest=stat_row_sha256('nfl',row,legacy_nfl=legacy)
        db.execute('INSERT INTO player_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
            *row.values(),'nflverse','b'*64,digest,datetime.now(timezone.utc).isoformat()))
        db.execute("INSERT INTO games VALUES (2026,1,'HOM','AWY',?)",(payload['game_date'],))
    report=settle_final_props(ledger,'nfl',schedule(payload))
    settled=next(item for item in ledger.predictions() if item['prediction_id']==key)
    assert report['settled']==expected
    assert settled['outcome'] is (True if expected else None)
    assert report['reasons']==({} if expected else {'stat_provenance_invalid':1})
    if expected:
        metrics=ledger.report()
        assert metrics['settled_count']==1 and metrics['unverified_settlements']==0


@pytest.mark.parametrize(('provider','record_hash','reason'),[
    ('unknown',None,'stat_provenance_invalid'),('nba','bad','stat_provenance_invalid')])
def test_settlement_rejects_missing_or_tampered_stat_provenance(tmp_path,provider,record_hash,reason):
    ledger=Ledger(tmp_path/'audit.sqlite');_,payload=prediction(ledger)
    with ledger.connect() as db:
        create_nba_stats(db);add_nba_stat(db,payload,21,provider=provider,record_hash=record_hash)
        if record_hash=='bad':
            db.execute("UPDATE nba_player_gamelogs SET source_record_sha256=?",('c'*64,))
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['settled']==0 and report['pending']==1 and report['reasons']=={reason:1}


def test_settlement_rejects_stat_observation_before_game_or_in_future(tmp_path):
    for observed in (datetime.now(timezone.utc)-timedelta(days=2),datetime.now(timezone.utc)+timedelta(days=1)):
        ledger=Ledger(tmp_path/(observed.date().isoformat()+'.sqlite'));_,payload=prediction(ledger)
        with ledger.connect() as db:
            create_nba_stats(db);add_nba_stat(db,payload,21,observed_at=observed.isoformat())
        report=settle_final_props(ledger,'nba',schedule(payload))
        assert report['settled']==0 and report['reasons']=={'stat_provenance_invalid':1}


def test_pending_schedule_catchup_is_bounded_oldest_first(monkeypatch):
    now=datetime(2026,9,30,16,tzinfo=timezone.utc)
    rows=[dict(sport='nba',prop_type='points',game_date=f'2026-09-{day:02}',outcome=None)
        for day in range(1,23)]
    status_rows=[
        dict(sport='nba',prop_type='points',game_date='2026-09-10',outcome=True,
            outcome_source='espn_final_stats'),
        dict(sport='nba',prop_type='points',game_date='2026-09-11',outcome=True,
            outcome_source='observed_final_stats'),
        dict(sport='nba',prop_type='points',game_date='2026-09-12',outcome=True,
            outcome_source='manual'),
        dict(sport='nfl',prop_type='pass_yds',game_date='2026-09-01',outcome=None),
    ]
    monkeypatch.setattr('sportsbet.settlement.verified_settlement_evidence',
        lambda *args:args[0].get('game_date')=='2026-09-11')
    class Audit:
        def predictions(self): return rows
    assert pending_schedule_offsets(Audit(),'nba',now)==tuple(range(-29,-22))
    class StatusAudit:
        def predictions(self): return status_rows
    assert pending_schedule_offsets(StatusAudit(),'nba',now)==(-20,)
    with pytest.raises(ValueError,match='scope'):
        pending_schedule_offsets(Audit(),'nba',datetime(2026,9,30))
