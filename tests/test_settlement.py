from datetime import datetime, timedelta, timezone

import pytest

from sportsbet.ledger import Ledger
from sportsbet.settlement import settle_final_props


def prediction(ledger, *, direction='over', line=20.5):
    now=datetime.now(timezone.utc)
    payload=dict(game_id='odds-event',player='Player',player_id='7',sport='nba',
        game_date=(now-timedelta(days=1)).date().isoformat(),home_team='Home',away_team='Away',
        prop_type='points',direction=direction,line=line,sportsbook='book',american_odds=100,
        model_probability=.6,captured_at=(now-timedelta(days=1,hours=3)).isoformat(),
        game_start_time=(now-timedelta(days=1,hours=2)).isoformat())
    return ledger.record('scan',payload),payload


def schedule(payload, *, completed=True, home='Home'):
    return dict(status='complete',captured_at=datetime.now(timezone.utc).isoformat(),
        games=[dict(provider_event_id='espn-event',date=payload['game_date'],
        home_name=home,away_name='Away',completed=completed,
        game_time=payload['game_start_time'])])


@pytest.mark.parametrize(('direction','line','actual','expected'),[
    ('over',20.5,21,True),('over',20.5,20,False),('over',20,20,'push'),
    ('under',20.5,20,True),('under',20.5,21,False),('under',20,20,'push'),
])
def test_settlement_uses_final_exact_game_and_observed_stat(tmp_path,direction,line,actual,expected):
    ledger=Ledger(tmp_path/'audit.sqlite')
    key,payload=prediction(ledger,direction=direction,line=line)
    with ledger.connect() as db:
        db.execute('CREATE TABLE nba_player_gamelogs (player_id INTEGER, game_date TEXT, points INTEGER, rebounds INTEGER, assists INTEGER)')
        db.execute('INSERT INTO nba_player_gamelogs(player_id,game_date,points) VALUES (?,?,?)',(7,payload['game_date'],actual))
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['settled']==1 and report['pending']==0
    row=next(row for row in ledger.predictions() if row['prediction_id']==key)
    assert row['outcome']==expected and row['actual_value']==actual
    assert row['outcome_source']=='espn_final_stats' and row['outcome_ref']=='espn:espn-event:7:points'
    assert datetime.fromisoformat(row['outcome_observed_at']).utcoffset() is not None


@pytest.mark.parametrize(('schedule_change','stats','reason'),[
    ({'completed':False},[(21,)],'final_game_not_matched'),
    ({'home':'Different'},[(21,)],'final_game_not_matched'),
    ({},[],'stat_not_found_or_ambiguous'),
    ({},[(21,),(22,)],'stat_not_found_or_ambiguous'),
])
def test_settlement_never_guesses_game_dnp_or_ambiguous_stat(tmp_path,schedule_change,stats,reason):
    ledger=Ledger(tmp_path/'audit.sqlite');key,payload=prediction(ledger)
    with ledger.connect() as db:
        db.execute('CREATE TABLE nba_player_gamelogs (player_id INTEGER, game_date TEXT, points INTEGER, rebounds INTEGER, assists INTEGER)')
        for (value,) in stats:
            db.execute('INSERT INTO nba_player_gamelogs(player_id,game_date,points) VALUES (?,?,?)',(7,payload['game_date'],value))
    report=settle_final_props(ledger,'nba',schedule(payload,**schedule_change))
    assert report['settled']==0 and report['pending']==1 and report['reasons']=={reason:1}
    assert next(row for row in ledger.predictions() if row['prediction_id']==key)['outcome'] is None


def test_settlement_does_not_rewrite_existing_outcome(tmp_path):
    ledger=Ledger(tmp_path/'audit.sqlite');key,payload=prediction(ledger)
    ledger.settle({key:False})
    with ledger.connect() as db:
        db.execute('CREATE TABLE nba_player_gamelogs (player_id INTEGER, game_date TEXT, points INTEGER, rebounds INTEGER, assists INTEGER)')
        db.execute('INSERT INTO nba_player_gamelogs(player_id,game_date,points) VALUES (?,?,?)',(7,payload['game_date'],99))
    report=settle_final_props(ledger,'nba',schedule(payload))
    assert report['candidates']==0 and report['settled']==0
    assert next(row for row in ledger.predictions() if row['prediction_id']==key)['outcome'] is False
