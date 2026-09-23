import test from 'node:test';
import assert from 'node:assert/strict';
import {pickCardPresentation,pickDisplayState,shortlistPresentation} from '../lib/pickPresentation.ts';

test('only an unretained signal is presented as an actionable live price',()=>{
  assert.equal(pickDisplayState({}),'live');
  assert.deepEqual(pickCardPresentation({},1),{
    state:'live',actionable:true,rankLabel:'Top suggested pick',status:'Live price',
    priceLabel:'Current price',returnLabel:'Model-estimated net per $100',
  });
  assert.equal(pickCardPresentation({},2).rankLabel,'Suggested pick #2');
});

test('recorded and locked picks never expose the actionable presentation',()=>{
  const recorded=pickCardPresentation({board_state:'recorded'},1);
  assert.equal(recorded.actionable,false);assert.equal(recorded.status,'Price expired');
  assert.equal(recorded.priceLabel,'Recorded price');assert.equal(recorded.returnLabel,'At recorded price');
  const locked=pickCardPresentation({board_state:'locked'},2);
  assert.equal(locked.actionable,false);assert.equal(locked.status,'Locked T−60');
  assert.equal(locked.priceLabel,'Locked price');assert.equal(locked.rankLabel,'Locked pick #2');
});

test('shortlist copy states exactly whether prices are live or historical',()=>{
  assert.deepEqual(shortlistPresentation(3,0),{
    state:'live',eyebrow:'Suggested picks',title:'Suggested picks you can check now',
    description:'Player-history estimates screened against the captured price, roster, injury reports and risk limits. One line per player.',count:'3 live',
  });
  assert.deepEqual(shortlistPresentation(0,2),{
    state:'recorded',eyebrow:'Recorded board',title:'Last approved picks',
    description:'These exact captures passed every gate earlier. Prices shown are historical.',
    count:'0 live · 2 to reprice',
  });
  assert.equal(shortlistPresentation(0,0).title,'No current suggested pick available');
});
