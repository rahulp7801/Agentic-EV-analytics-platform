import test from 'node:test';
import assert from 'node:assert/strict';
import {bestPicks,compareQuality} from '../lib/bestPicks.ts';
const now=Date.parse('2026-09-10T12:00:00Z');
const base={id:'A',player:'A',team:'',opponent:'',sport:'nfl',home_team:'Home',away_team:'Away',game_id:'game',
  prop_type:'pass_yds',line:249.5,direction:'over',true_prob:.65,american_odds:100,push_probability:0,
  sportsbook:'draftkings',model_version:'empirical-jeffreys-v4',sample_size:40,mean_stat:260,
  confidence_interval:[.52,.78],kelly_fraction:.01,gated:false,trade_plan:[],injury_flags:{},market_type:'player_pass_yds',
  snapped_at:new Date(now).toISOString(),game_start_time:new Date(now+3600000).toISOString(),
  availability:{status:'observed',roster_confirmed:true,subject_status:'Not listed on injury report',probability_adjusted:false,
    captured_at:new Date(now).toISOString(),team:'KC',teammates:[],
    source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',source_sha256:'a'.repeat(64),
    roster_source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/12/roster',roster_source_sha256:'b'.repeat(64)}};
test('lower raw edge can outrank a less supported high point estimate',()=>{
  const stronger={...base,id:'B',player:'B',true_prob:.6,confidence_interval:[.56,.64]};
  assert.deepEqual(bestPicks([base,stronger],now).map(p=>p.id),['B','A']);
});
test('the shortlist cannot manufacture picks from stale, uncertain, injured, capped or blocked evidence',()=>{
  for(const patch of [{confidence_interval:null},{confidence_interval:[.49,.8]},{gated:true},
    {true_prob:.8},{true_prob:.650000001},{snapped_at:new Date(now-300001).toISOString()},{sample_size:19},
    {availability:{...base.availability,teammates:[{player:'T',status:'Out',position:'WR',reported_at:new Date(now).toISOString()}]}}]) {
    assert.deepEqual(bestPicks([{...base,...patch}],now),[]);
  }
  assert.deepEqual(bestPicks([],now),[]);
});
test('deduplicates player/game exposure, caps three and does not pad smaller supported sets',()=>{
  const candidates=Array.from({length:8},(_,i)=>({...base,id:String(i),player:'Player '+i}));
  assert.equal(bestPicks(candidates,now).length,3);
  assert.equal(bestPicks([base,{...base,id:'duplicate',sportsbook:'fanduel'}],now).length,1);
  assert.equal(bestPicks([base],now).length,1);
});
test('push-adjusted price and uncertainty drive ranking with stable missing-interval sorting',()=>{
  const pushed={...base,push_probability:.1,true_prob:.6,confidence_interval:[.5,.7]};
  assert.equal(bestPicks([pushed],now).length,1);
  assert.equal(compareQuality({...base,implied_prob:.5,confidence_interval:null},{...base,implied_prob:.5,confidence_interval:null}),0);
});
