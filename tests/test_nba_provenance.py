from datetime import datetime, timedelta, timezone
import json

import pytest
import sqlalchemy as sa

from sportsbet.db.models import NBAPlayerGameLog
from sportsbet.ingestion.nba_provenance import (
    apply_plan, official_rows, recovery_plan, recover_response, value_digest)
from sportsbet.ingestion.provenance import stat_row_sha256

OBSERVED=datetime(2026,9,23,tzinfo=timezone.utc)
TABLE=NBAPlayerGameLog.__table__


def response():
    return dict(parameters=dict(SeasonYear='2025-26',SeasonType='Regular Season',
        MeasureType='Base',PerMode='Totals',LeagueID='00'),resultSets=[dict(name='PlayerGameLogs',
        headers=['PLAYER_ID','PLAYER_NAME','GAME_ID','GAME_DATE','TEAM_ABBREVIATION','MATCHUP',
            'MIN','PTS','REB','AST','FG3M','STL','BLK'],rowSet=[
            [101,'Player Jr.','0022500001','2026-01-01T00:00:00','LAL','LAL vs. BOS',20.15,21,0,3,1,0,0],
            [102,'Other','0022500001','2026-01-01T00:00:00','BOS','BOS @ LAL',32,30,4,7,3,2,1]])])


@pytest.fixture
def engine(tmp_path):
    engine=sa.create_engine('sqlite:///'+str(tmp_path/'nba.sqlite'))
    TABLE.create(engine)
    source=official_rows(json.dumps(response()),2025,OBSERVED)
    with engine.begin() as conn:
        conn.execute(TABLE.insert(),[dict(row,id=i+1,source_provider='nba',
            **({'player_name':'Player'} if i==0 else {})) for i,row in enumerate(source)])
    yield engine
    engine.dispose()


def retained(engine):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(sa.select(TABLE).order_by(TABLE.c.player_id)).mappings()]


def test_audit_writes_nothing_then_recovery_preserves_values_and_is_idempotent(engine,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    text=json.dumps(response());before=retained(engine)
    report=recover_response(engine,text,2025,OBSERVED)
    assert report['counts']=={'recoverable':2,'name_updates':1}
    assert report['updated_rows']==0 and not report['applied']
    assert retained(engine)==before and not list(tmp_path.rglob('*.json'))
    applied=recover_response(engine,text,2025,OBSERVED,apply=True)
    after=retained(engine)
    assert applied['updated_rows']==2 and applied['applied']
    assert value_digest(before)==value_digest(after)==report['values_sha256']
    assert after[0]['player_name']=='Player Jr.' and after[0]['minutes']==official_rows(text,2025,OBSERVED)[0]['minutes']
    for row in after:
        assert row['source_record_sha256']==stat_row_sha256('nba',row)
        assert row['source_observed_at'].replace(tzinfo=timezone.utc)==OBSERVED
    repeat=recover_response(engine,text,2025,OBSERVED,apply=True)
    assert repeat['updated_rows']==0 and repeat['counts']=={'existing_provenance':2}
    assert retained(engine)==after


@pytest.mark.parametrize('field,value',[('points',99),('minutes',24),('game_date',None),
    ('team_abbreviation','NYK'),('is_home',False),('opponent_team','NYK')])
def test_changed_model_values_are_excluded(engine,field,value,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    with engine.begin() as conn:
        conn.execute(TABLE.update().where(TABLE.c.player_id==101).values({field:value}))
    report=recover_response(engine,json.dumps(response()),2025,OBSERVED,apply=True)
    assert report['updated_rows']==1 and report['counts']['value_mismatch']==1
    assert report['mismatch_fields']=={field:1}
    assert retained(engine)[0]['source_record_sha256'] is None


@pytest.mark.parametrize('changes',[{'source_provider':'espn'},{'source_sha256':'a'*64},
    {'source_record_sha256':'b'*64}])
def test_existing_or_partial_provenance_is_never_replaced(engine,changes,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    with engine.begin() as conn:
        conn.execute(TABLE.update().where(TABLE.c.player_id==101).values(changes))
    previous=retained(engine)[0]
    assert recover_response(engine,json.dumps(response()),2025,OBSERVED,apply=True)['updated_rows']==1
    assert retained(engine)[0]==previous


@pytest.mark.parametrize('field,value',[('points',31),('source_record_sha256','c'*64),
    ('source_observed_at',OBSERVED+timedelta(seconds=1))])
def test_a_concurrent_change_rolls_back_all_earlier_updates(engine,field,value):
    source=official_rows(json.dumps(response()),2025,OBSERVED)
    updates,_=recovery_plan(retained(engine),source,2025,OBSERVED)
    with engine.begin() as conn:
        conn.execute(TABLE.update().where(TABLE.c.player_id==102).values({field:value}))
    with pytest.raises(ValueError,match='changed during recovery'):
        with engine.begin() as conn:
            apply_plan(conn,updates)
    rows=retained(engine)
    assert rows[0]['source_record_sha256'] is None and rows[0]['player_name']=='Player'
    actual=rows[1][field]
    if isinstance(actual,datetime):actual=actual.replace(tzinfo=timezone.utc)
    assert actual==value


@pytest.mark.parametrize('defect',['wrong_season','playoffs','pergame','duplicate_table','duplicate_header',
    'missing_stat','duplicate_row','wrong_game','wrong_matchup','future_game','bad_minutes',
    'fractional_stat','negative_stat','bool_stat','missing_player','oversized_name'])
def test_malformed_official_responses_are_rejected(defect):
    body=response();table=body['resultSets'][0];row=table['rowSet'][0]
    if defect=='wrong_season':body['parameters']['SeasonYear']='2024-25'
    elif defect=='playoffs':body['parameters']['SeasonType']='Playoffs'
    elif defect=='pergame':body['parameters']['PerMode']='PerGame'
    elif defect=='duplicate_table':body['resultSets'].append(table)
    elif defect=='duplicate_header':table['headers'][0]='PLAYER_NAME'
    elif defect=='missing_stat':table['headers'][-1]='UNKNOWN'
    elif defect=='duplicate_row':table['rowSet'].append(row)
    elif defect=='wrong_game':row[2]='0042500001'
    elif defect=='wrong_matchup':row[5]='NYK vs. BOS'
    elif defect=='future_game':row[3]='2027-01-01'
    elif defect=='bad_minutes':row[6]='NaN'
    elif defect=='fractional_stat':row[7]=20.5
    elif defect=='negative_stat':row[7]=-1
    elif defect=='bool_stat':row[7]=True
    elif defect=='missing_player':row[0]=None
    elif defect=='oversized_name':row[1]='x'*101
    with pytest.raises(ValueError):official_rows(json.dumps(body),2025,OBSERVED)



def test_a_timestamp_without_hashes_is_recovered_with_fresh_observation(engine,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    previous=OBSERVED-timedelta(days=12)
    with engine.begin() as conn:
        conn.execute(TABLE.update().values(source_observed_at=previous))
    report=recover_response(engine,json.dumps(response()),2025,OBSERVED,apply=True)
    assert report['updated_rows']==report['counts']['timestamp_only_recovered']==2
    for row in retained(engine):
        assert row['source_record_sha256']==stat_row_sha256('nba',row)
        assert row['source_observed_at'].replace(tzinfo=timezone.utc)==OBSERVED


def test_a_later_observation_is_not_replaced_by_an_older_response(engine,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    with engine.begin() as conn:
        conn.execute(TABLE.update().values(source_observed_at=OBSERVED+timedelta(days=1)))
    report=recover_response(engine,json.dumps(response()),2025,OBSERVED,apply=True)
    assert report['updated_rows']==0 and report['counts']['observation_after_source']==2
    assert all(row['source_record_sha256'] is None for row in retained(engine))
