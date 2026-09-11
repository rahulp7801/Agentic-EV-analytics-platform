import test from 'node:test';
import assert from 'node:assert/strict';
import {gameLog,overFrequency} from '../lib/gameLogMetrics.ts';

test('NFL fields and unknown venue survive game-log parsing without invented zeros',()=>{
  const log=gameLog({player:'Example',pass_yds:'210',pass_tds:0,rec_yds:null,rush_yds:'',is_home:null},'nfl','1');
  assert.equal(log.pass_yds,210);assert.equal(log.pass_tds,0);
  assert.equal(log.rec_yds,undefined);assert.equal(log.rush_yds,undefined);
  assert.equal(log.home_away,undefined);
});
test('over frequency excludes missing stats and ties, and accepts a zero threshold',()=>{
  const logs=[21,20,19,null].map((points,i)=>gameLog({points},'nba',String(i)));
  assert.deepEqual(overFrequency(logs,'points',20),{wins:1,losses:1,pushes:1,missing:1,decided:2,rate:.5});
  assert.equal(overFrequency(logs,'points',0).rate,1);
  assert.equal(overFrequency(logs,'rebounds',20).rate,null);
  assert.equal(overFrequency(logs,'points',NaN),null);
});
