import assert from 'node:assert/strict';
import test from 'node:test';
import { gameLogRequest, publicGameLogs } from '../lib/publicGameLogs.ts';

test('public game logs retain real sport fields and strip unexpected view data',()=>{
  const nba=publicGameLogs([{date:'2026-04-12',player:'A.J. Lawson',team:'TOR',opponent:'BKN',
    is_home:true,points:10,minutes:10.6,pass_yds:999,source_sha256:'internal'}],'nba')[0];
  assert.deepEqual(nba,{date:'2026-04-12',player:'A.J. Lawson',team:'TOR',opponent:'BKN',
    is_home:true,points:10,minutes:10.6});
  const nfl=publicGameLogs([{date:'2026-09-10',player:'Runner',team:'LA',opponent:'SF',
    is_home:false,rush_yds:-1,receptions:0,points:99}],'nfl')[0];
  assert.equal(nfl.rush_yds,-1);assert.equal(nfl.receptions,0);assert.equal('points' in nfl,false);
  const cfb=publicGameLogs([{date:'2026-09-12',player:'Quarterback',team:'TEX',opponent:'OSU',
    is_home:true,pass_yds:281,pass_tds:4,points:99}],'cfb')[0];
  assert.equal(cfb.pass_yds,281);assert.equal('pass_tds' in cfb,false);assert.equal('points' in cfb,false);
});

test('public game logs reject malformed identity, dates, booleans, stats and oversized results',()=>{
  const valid={date:'2026-09-10',player:'Player',team:'LA',opponent:'SF',is_home:true,rush_yds:1};
  for(const changed of [{...valid,date:'yesterday'},{...valid,date:'2026-02-31'},{...valid,player:''},{...valid,is_home:'true'},
    {...valid,rush_yds:NaN},{...valid,receptions:-1},{...valid,rush_yds:10001}]) {
    assert.throws(()=>publicGameLogs([changed],'nfl'));
  }
  assert.throws(()=>publicGameLogs(Array(201).fill(valid),'nfl'));
});

test('college-football game-log requests retain exact player lookup',()=>{
  const request=gameLogRequest(new URLSearchParams({sport:'cfb',player:'A.J. Player',exact:'1',limit:'20'}));
  assert.deepEqual(request,{sport:'cfb',player:'A.J. Player',limit:20,exact:true,before:null});
});
