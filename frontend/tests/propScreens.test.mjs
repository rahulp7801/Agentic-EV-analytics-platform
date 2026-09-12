import test from 'node:test';
import assert from 'node:assert/strict';
import { publicPropScreen } from '../lib/propScreens.ts';

function snapshot() {
  return {schema_version:1,scan_id:'internal',sport:'nfl',generated_at:'2026-09-11T12:00:00Z',
    status:'observed',coverage:{events:1,observed_events:1,unavailable_events:0,positive_gross_gaps:1,
      sportsbook_gaps:0,kalshi_sportsbook_gaps:1},
    comparisons:[{kind:'kalshi_sportsbook_prop',status:'unverified',event_id:'game',milestone_id:'internal',
      player:'Player',prop_type:'pass_yds',line:'249.5',gross_cost_to_one_dollar:'0.85',
      gross_gap_to_one_dollar:'0.15',evidence_sha256:'internal',market_sha256:'internal',
      legs:[{venue:'kalshi',ticker:'KX-PROP',side:'yes',cost:'0.45',displayed_size:'12',
        observed_at:'2026-09-11T12:00:00Z'},{venue:'sportsbook',sportsbook:'book',side:'Under',
        american_odds:150,cost:'0.4',observed_at:'2026-09-11T12:00:00Z'}],
      reasons:['Rules are unreviewed.'],settlement_equivalent:false,fee_adjusted_profit:null,
      realized_profit:null,execution_ready:false}],execution_ready:false};
}

test('public prop screen omits internal evidence and retains all non-executable labels', () => {
  const result=publicPropScreen(snapshot(),Date.parse('2026-09-11T12:01:00Z'));
  assert.equal(result.comparisons[0].gross_gap_to_one_dollar,'0.15');
  assert.equal(result.comparisons[0].execution_ready,false);
  assert.equal(result.execution_ready,false);
  assert.equal('scan_id' in result,false);
  assert.equal('milestone_id' in result.comparisons[0],false);
  assert.equal('evidence_sha256' in result.comparisons[0],false);
});

test('public prop screen accepts distinct-book complements without adding profit fields', () => {
  const changed=snapshot(), row=changed.comparisons[0];
  row.kind='sportsbook_sportsbook_prop';delete row.milestone_id;
  row.legs=[{venue:'sportsbook',sportsbook:'over-book',side:'Over',american_odds:150,cost:'0.4',
    observed_at:'2026-09-11T12:00:00Z'},{venue:'sportsbook',sportsbook:'under-book',side:'Under',
    american_odds:122,cost:'0.45045045045045046',observed_at:'2026-09-11T12:00:00Z'}];
  row.gross_cost_to_one_dollar='0.8504504504504505';row.gross_gap_to_one_dollar='0.1495495495495495';
  changed.coverage.sportsbook_gaps=1;changed.coverage.kalshi_sportsbook_gaps=0;
  const result=publicPropScreen(changed,Date.parse('2026-09-11T12:01:00Z'));
  assert.equal(result.comparisons[0].kind,'sportsbook_sportsbook_prop');
  assert.equal(result.comparisons[0].execution_ready,false);
});

test('public prop screen rejects profit, settlement, and execution claims', () => {
  for (const [key,value] of [['execution_ready',true],['settlement_equivalent',true],
      ['fee_adjusted_profit','0.1'],['realized_profit','0.1']]) {
    const changed=snapshot(); changed.comparisons[0][key]=value;
    assert.throws(() => publicPropScreen(changed,Date.parse('2026-09-11T12:01:00Z')));
  }
  const changed=snapshot();changed.comparisons[0].legs[1].cost='0.41';
  changed.comparisons[0].gross_cost_to_one_dollar='0.86';
  changed.comparisons[0].gross_gap_to_one_dollar='0.14';
  assert.throws(() => publicPropScreen(changed,Date.parse('2026-09-11T12:01:00Z')));
});

test('stale public screens retain audit counts but expose no candidate', () => {
  const result=publicPropScreen(snapshot(),Date.parse('2026-09-11T12:06:00Z'));
  assert.equal(result.status,'stale');
  assert.equal(result.coverage.captured_positive_gross_gaps,1);
  assert.equal(result.coverage.captured_kalshi_sportsbook_gaps,1);
  assert.equal(result.coverage.positive_gross_gaps,0);
  assert.equal(result.coverage.kalshi_sportsbook_gaps,0);
  assert.deepEqual(result.comparisons,[]);
});
