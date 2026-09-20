from datetime import date

import pytest

from sportsbet.prop.injury_context import (_nba_split, _nfl_split, current_contexts,
    relevant_availability_reports)


def test_contexts_require_relevant_unit_and_exact_nfl_identity():
    context={'status':'observed','pfr_player_identities':{'1':'ReceDa00','2':'DefeDa00'},'teams':[
        {'abbreviation':'NE','roster_ids':{'1':'Receiver','9':'Target'},'reports':[
            {'player':'Receiver','position':'WR','status':'Out'},
            {'player':'Guard','position':'G','status':'Active'},
            {'player':'Corner teammate','position':'CB','status':'Out'}]},
        {'abbreviation':'NYJ','roster_ids':{'2':'Defender','3':'Other'},'reports':[
            {'player':'Defender','position':'CB','status':'Questionable'},
            {'player':'Other','position':'WR','status':'Out'}]}]}
    rows=current_contexts(context,'NE','Target','nfl')
    assert [(row['player'],row['relationship'],row['unit'],row['participant_id']) for row in rows]==[
        ('Receiver','teammate','offense','ReceDa00'),
        ('Defender','opponent','defense','DefeDa00')]


def test_relevant_reports_exclude_same_team_defense_and_opponent_offense_without_requiring_crosswalk():
    context={'status':'observed','teams':[
        {'abbreviation':'NE','reports':[
            {'player':'Receiver','position':'WR','status':'Out','reported_at':'2026-09-20T00:00:00Z'},
            {'player':'Corner teammate','position':'CB','status':'Out','reported_at':'2026-09-20T00:00:00Z'}]},
        {'abbreviation':'NYJ','reports':[
            {'player':'Defender','position':'CB','status':'Questionable','reported_at':'2026-09-20T00:00:00Z'},
            {'player':'Quarterback','position':'QB','status':'Out','reported_at':'2026-09-20T00:00:00Z'}]}]}
    rows=relevant_availability_reports(context,'NE','Target','nfl')
    assert [(row['player'],row['relationship'],row['unit']) for row in rows]==[
        ('Receiver','teammate','offense'),('Defender','opponent','defense')]


def test_nba_reports_treat_teammates_and_opponents_as_relevant_lineup_context():
    context={'status':'observed','teams':[
        {'abbreviation':'BOS','reports':[{'player':'Guard','position':'PG','status':'Out'}]},
        {'abbreviation':'NY','reports':[{'player':'Center','position':'C','status':'Questionable'}]}]}
    rows=relevant_availability_reports(context,'BOS','Target','nba')
    assert [(row['player'],row['relationship'],row['unit']) for row in rows]==[
        ('Guard','teammate','offense'),('Center','opponent','defense')]


@pytest.mark.asyncio
async def test_nfl_split_requires_tenure_source_coverage_and_strips_internal_id():
    class Connection:
        async def fetchrow(self,sql,*args):
            self.sql,self.args=sql,args
            return {'active_games':8,'active_mean':241.25,'active_hits':5,
                    'absent_games':2,'absent_mean':278,'absent_hits':2}
    conn=Connection()
    result=await _nfl_split(conn,'target',2024,date(2026,9,20),'pass_yds',225.5,'over',
        {'player':'Defender','status':'Out','position':'CB','team':'WSH','stat_team':'WAS',
         'relationship':'opponent','unit':'defense','participant_id':'DefeDa00'})
    assert 'MIN(season*100+week)' in conn.sql and 'CASE WHEN EXISTS' in conn.sql
    assert 'defense_snaps>0' in conn.sql and conn.args[-2:]==('WAS','DefeDa00')
    assert result['active']=={'games':8,'mean':241.25,'hit_rate':.625}
    assert result['absent']=={'games':2,'mean':278.0,'hit_rate':1.0}
    assert 'participant_id' not in result and result['team']=='WSH'


@pytest.mark.asyncio
async def test_nba_split_uses_canonical_team_and_integer_subject_identity():
    class Connection:
        async def fetch(self,sql,*args):
            assert args==('Injured Teammate','LAC')
            return [{'player_id':321}]
        async def fetchrow(self,sql,*args):
            self.sql,self.args=sql,args
            return {'active_games':10,'active_mean':25,'active_hits':7,
                    'absent_games':5,'absent_mean':29,'absent_hits':4}
    conn=Connection()
    result=await _nba_split(conn,'123',2024,date(2026,9,20),'points',22.5,'over',
        {'player':'Injured Teammate','status':'Out','position':'SG','team':'LA',
         'stat_team':'LAC','relationship':'teammate','unit':'offense'})
    assert conn.args[0] == 123 and conn.args[-2:] == ('LAC',321)
    assert result['absent']=={'games':5,'mean':29.0,'hit_rate':.8}
    assert 'stat_team' not in result
