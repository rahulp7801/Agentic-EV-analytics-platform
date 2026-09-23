import test from 'node:test';
import assert from 'node:assert/strict';
import {pickContext} from '../lib/pickContext.ts';
import {base} from './fixtures/qualifiedSignal.mjs';

test('a qualified suggestion shows verified roster and report context without a probability boost',()=>{
  const context=pickContext(base);
  assert.match(context.player,/roster confirmed/);
  assert.match(context.reports,/No relevant teammate or opposing defender report/);
  assert.match(context.detail,/do not add a probability boost/);
});

test('reported absences and available historical comparisons are descriptive',()=>{
  const signal={...base,availability:{...base.availability,teammates:[
    {player:'Receiver',status:'Out',position:'WR',reported_at:base.snapped_at},
    {player:'Defender',status:'Questionable',position:'CB',reported_at:base.snapped_at},
  ],context_splits:[{player:'Receiver'}]},next_gen_stats:{sample_weeks:3}};
  const context=pickContext(signal);
  assert.match(context.reports,/Receiver \(Out\), Defender \(Questionable\)/);
  assert.match(context.detail,/1 historical on\/off comparison/);
  assert.match(context.detail,/3 prior tracking weeks/);
});

test('missing availability is not presented as a cleared context check',()=>{
  assert.match(pickContext({...base,availability:undefined}).player,/unavailable/);
});
