import test from 'node:test';
import assert from 'node:assert/strict';
import {bestPickGroups,bestPickOptions,bestPicks,compareQuality,groupAlternateLines,recentCandidateGroups} from '../lib/bestPicks.ts';
import {base,now} from './fixtures/qualifiedSignal.mjs';

test('lower raw edge can outrank a less supported high point estimate',()=>{
  const stronger={...base,id:'B',player:'B',true_prob:.6,confidence_interval:[.56,.64]};
  assert.deepEqual(bestPicks([base,stronger],now).map(p=>p.id),['B','A']);
});
test('the shortlist cannot manufacture picks from stale, uncertain, injured or blocked evidence',()=>{
  for(const patch of [{confidence_interval:null},{confidence_interval:[.49,.8]},
    {confidence_interval:[.7,.8]},{push_probability:.1,confidence_interval:[.52,.95]},{gated:true},
    {true_prob:.8},{snapped_at:new Date(now-300001).toISOString()},{sample_size:19},
    {availability:{...base.availability,teammates:[{player:'T',status:'Out',position:'WR',reported_at:new Date(now).toISOString()}]}}]) {
    assert.deepEqual(bestPicks([{...base,...patch}],now),[]);
  }
  assert.deepEqual(bestPicks([],now),[]);
});
test('a large exact-line disagreement remains eligible when its confidence floor clears the price',()=>{
  const supported={...base,true_prob:.8,confidence_interval:[.65,.9]};
  assert.deepEqual(bestPicks([supported],now).map(pick=>pick.id),[base.id]);
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
test('groups alternate thresholds beneath the strongest supported line',()=>{
  const best={...base,id:'best',line:235.5,confidence_interval:[.58,.7]};
  const alternate={...base,id:'alt',line:225.5,confidence_interval:[.54,.68]};
  const otherMarket={...base,id:'td',prop_type:'pass_tds',line:1.5,confidence_interval:[.53,.68]};
  const groups=bestPickGroups([alternate,otherMarket,best],now);
  assert.equal(groups.length,1);
  assert.equal(groups[0].pick.id,'best');
  assert.deepEqual(groups[0].alternatives.map(value=>value.id),['alt']);
  assert.deepEqual(bestPickOptions([alternate,best],now).map(value=>value.id),['best','alt']);
});
test('research grouping preserves its supplied ranking and removes duplicate offers',()=>{
  const duplicate={...base,id:'duplicate'};
  const alternate={...base,id:'alternate',line:230.5};
  const groups=groupAlternateLines([base,duplicate,alternate]);
  assert.equal(groups.length,1);
  assert.equal(groups[0].pick.id,base.id);
  assert.deepEqual(groups[0].alternatives.map(value=>value.id),['alternate']);
  const crowded=groupAlternateLines(Array.from({length:15},(_,index)=>({...base,id:`line-${index}`,line:200+index})));
  assert.equal(crowded[0].alternatives.length,10);
});
test('empty-board fallback keeps only bounded upcoming source-backed leans',()=>{
  const stale=new Date(now-300001).toISOString();
  const candidate={...base,snapped_at:stale};
  const groups=recentCandidateGroups([
    candidate,
    {...candidate,id:'alt',line:240.5},
    {...candidate,id:'second',player:'Second player'},
    {...candidate,id:'negative',player:'Negative',true_prob:.4},
    {...candidate,id:'extreme',player:'Extreme',true_prob:.8},
    {...candidate,id:'started',player:'Started',game_start_time:new Date(now-1).toISOString()},
    {...candidate,id:'unknown',player:'Unknown',availability:undefined},
  ],now);
  assert.deepEqual(groups.map(group=>group.pick.id),[base.id,'second']);
  assert.deepEqual(groups[0].alternatives.map(signal=>signal.id),['alt']);
  assert.ok(groups.every(group=>group.pick.gated));
});
