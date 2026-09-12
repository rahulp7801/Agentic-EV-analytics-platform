"""Fallback must preserve identities and missingness, not manufacture fresh history."""
import copy
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import ReadTimeout

from sportsbet.ingestion.nba_espn import index_rows, official_names, parse_game, refresh_recent
from sportsbet.ingestion.provenance import stat_row_sha256
from sportsbet.refresh import refresh


def example():
    game=dict(espn_game_id='123',nba_game_id='0022500001',game_date='2026-01-28',
        home_espn_team_id='1',away_espn_team_id='2',nba_home_team_id='101',nba_away_team_id='102')
    teams={str(i):dict(nba_team_id=str(100+i),nba_team_abbreviation=name) for i,name in ((1,'LAL'),(2,'BOS'))}
    players={str(i):dict(nba_player_id=str(1000+i),nba_player_name=f'Player {i}') for i in range(10)}
    keys=['minutes','points','rebounds','assists','steals','blocks','threePointFieldGoalsMade-threePointFieldGoalsAttempted']
    box=[]
    for team in (1,2):
        athletes=[dict(athlete={'id':str(i),'displayName':f'Player {i}'},didNotPlay=False,
            stats=['28:30','0','6','3','0','0','0-1']) for i in range((team-1)*5,team*5)]
        # DNP is explicit. It must neither require a mapping nor add fabricated zeros.
        athletes.append(dict(athlete={'id':'unmapped'},didNotPlay=True,stats=[]))
        box.append(dict(team={'id':str(team)},statistics=[dict(keys=keys.copy(),athletes=athletes)]))
    data=dict(header=dict(id='123',season={'year':2026,'type':2},competitions=[dict(
        date='2026-01-29T00:00Z',status={'type':{'completed':True}},
        competitors=[{'id':'1','homeAway':'home'},{'id':'2','homeAway':'away'}])]),boxscore={'players':box})
    return data,game,players,teams


def parse(data,game,players,teams,names=None):
    return parse_game(data,2025,game,players,teams,'a'*64,datetime(2026,1,30,tzinfo=timezone.utc),names)


def test_final_box_score_zero_dnp_and_exact_official_name_fallback():
    data,game,players,teams=example()
    del players['0']
    data['boxscore']['players'][0]['statistics'][0]['athletes'][0]['athlete']['displayName']='Nikola Vucevic'
    names=official_names([(1000,'Nikola Vučević')])
    rows=parse(data,game,players,teams,names)
    assert len(rows)==10
    assert rows[0]['points']==0 and rows[0]['minutes']==28.5
    assert rows[0]['player_id']==1000 and rows[0]['player_name']=='Nikola Vučević'
    assert rows[0]['game_id']=='0022500001' and rows[0]['game_date']==date(2026,1,28)
    assert rows[0]['is_home'] and rows[0]['opponent_team']=='BOS'
    assert rows[0]['source_provider']=='espn' and rows[0]['source_sha256']=='a'*64
    assert rows[0]['source_record_sha256']==stat_row_sha256('nba',rows[0])
    # Accent folding cannot choose between two official people with the same name.
    names=official_names([(1000,'Nikola Vučević'),(999,'Nikola Vucevic')])
    with pytest.raises(ValueError,match='verified NBA identity'): parse(data,game,players,teams,names)


@pytest.mark.parametrize('failure',['missing_stat','unknown_player','duplicate_player','wrong_date','wrong_team',
    'not_final','playoffs','invalid_minutes','invalid_threes','duplicate_team','duplicate_stat'])
def test_unusable_box_scores_fail_before_storage(failure):
    data,game,players,teams=example()
    group=data['boxscore']['players'][0]['statistics'][0]
    if failure=='missing_stat': group['athletes'][0]['stats'][1]='--'
    if failure=='unknown_player': del players['0']
    if failure=='duplicate_player': players['0']['nba_player_id']=players['1']['nba_player_id']
    if failure=='wrong_date': game['game_date']='2026-01-29'
    if failure=='wrong_team': game['nba_home_team_id']='999'
    if failure=='not_final': data['header']['competitions'][0]['status']['type']['completed']=False
    if failure=='playoffs': data['header']['season']['type']=3
    if failure=='invalid_minutes': group['athletes'][0]['stats'][0]='28:90'
    if failure=='invalid_threes': group['athletes'][0]['stats'][-1]='3-2'
    if failure=='duplicate_team': data['boxscore']['players'].append(copy.deepcopy(data['boxscore']['players'][0]))
    if failure=='duplicate_stat': group['keys'][1]='minutes'
    with pytest.raises(ValueError): parse(data,game,players,teams)


def test_crosswalk_rejects_fuzzy_empty_wrong_season_and_ambiguous_identity():
    row=dict(season='2026',source='one',target='100',match_confidence='1',match_method='exact_name')
    def check(rows): return index_rows(rows,'source',('target',),'exact_name',2026)
    assert check([row])['one']['target']=='100'
    for rows in ([],[row|{'match_confidence':'0.9'}],[row|{'season':'2027'}],
                 [row,row|{'target':'101'}],[row,row|{'source':'two'}]):
        with pytest.raises(ValueError): check(rows)


def test_only_provider_network_failure_uses_bounded_fallback():
    engine=MagicMock()
    with patch('sportsbet.refresh.get_sync_engine',return_value=engine), \
         patch('sportsbet.refresh.ingest_nba_gamelogs_season',side_effect=ReadTimeout) as primary, \
         patch('sportsbet.ingestion.nba_espn.refresh_recent',return_value={'provider':'espn'}) as fallback:
        assert refresh('nba',date(2026,9,11))=={'provider':'espn'}
        fallback.assert_called_once_with(2025,date(2026,9,11),engine)
        with pytest.raises(ReadTimeout): refresh('nba',date(2026,9,11),backfill=True)
        primary.side_effect=RuntimeError('Database failure')
        with pytest.raises(RuntimeError): refresh('nba',date(2026,9,11))
        assert fallback.call_count==1 and engine.dispose.call_count==3


def test_old_history_gap_cannot_be_reported_as_success(tmp_path,monkeypatch):
    import httpx
    import sportsbet.ingestion.nba_espn as module
    schedule='season,espn_game_id,nba_game_id,game_date,home_espn_team_id,away_espn_team_id,nba_home_team_id,nba_away_team_id,match_method,match_confidence\n2026,123,0022500001,2026-01-28,1,2,101,102,both,1\n'
    player='season,espn_athlete_id,nba_player_id,nba_player_name,match_method,match_confidence\n2026,1,1000,Fixture,exact_name,1\n'
    team='season,espn_team_id,nba_team_id,nba_team_abbreviation,match_method,match_confidence\n2026,1,101,LAL,exact_name,1\n'
    sources={'schedule':schedule,'player':player,'team':team}
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,text=next(v for k,v in sources.items() if f'nba_{k}_' in str(request.url)))
    client=httpx.Client(transport=httpx.MockTransport(handler))
    engine=MagicMock();engine.connect.return_value.__enter__.return_value.execute.return_value.scalars.return_value=[]
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:client)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError,match='backfill required'): refresh_recent(2025,date(2026,9,11),engine)
    assert len(calls)==3 and not list(tmp_path.rglob('*.json'))
    engine.begin.assert_not_called()


@pytest.mark.parametrize('today,known,success',[(date(2026,9,11),['0022500001'],True),(date(2026,1,30),[],False)])
def test_empty_scoreboards_require_existing_schedule_coverage(tmp_path,monkeypatch,today,known,success):
    import httpx
    import sportsbet.ingestion.nba_espn as module
    sources={
        'schedule':'season,espn_game_id,nba_game_id,game_date,home_espn_team_id,away_espn_team_id,nba_home_team_id,nba_away_team_id,match_method,match_confidence\n2026,123,0022500001,2026-01-28,1,2,101,102,both,1\n',
        'player':'season,espn_athlete_id,nba_player_id,nba_player_name,match_method,match_confidence\n2026,1,1000,Fixture,exact_name,1\n',
        'team':'season,espn_team_id,nba_team_id,nba_team_abbreviation,match_method,match_confidence\n2026,1,101,LAL,exact_name,1\n'}
    def handler(request):
        if '/scoreboard' in str(request.url): return httpx.Response(200,json={'events':[]})
        return httpx.Response(200,text=next(v for k,v in sources.items() if f'nba_{k}_' in str(request.url)))
    client=httpx.Client(transport=httpx.MockTransport(handler))
    engine=MagicMock();conn=engine.connect.return_value.__enter__.return_value
    existing=MagicMock();existing.scalars.return_value=known
    identity=MagicMock();identity.all.return_value=[(1000,'Fixture')]
    conn.execute.side_effect=[existing,identity]
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:client)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    monkeypatch.chdir(tmp_path)
    if success:
        report=refresh_recent(2025,today,engine)
        assert report['games']==report['rows']==0 and report['prior_game_count']==1
        assert report['checked_through']=='2026-09-11'
        import json
        from pathlib import Path
        archive=json.loads(Path(report['archive']).read_text())
        assert len(archive['sources'])==10 and archive['official_player_identities']==[[1000,'Fixture']]
        assert all(len(s['sha256'])==64 for s in archive['sources'])
    else:
        with pytest.raises(ValueError,match='Recent scheduled games'): refresh_recent(2025,today,engine)
    engine.begin.assert_not_called()
