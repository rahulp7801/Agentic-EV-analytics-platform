import assert from 'node:assert/strict';
import test from 'node:test';
import { publicMarkets } from '../lib/publicMarkets.ts';

function snapshot(){const coverage={discovered_games:1,attempted_games:1,observed_games:1,quoted_games:1,
  failed_games:0,event_failed_games:0,market_failed_games:0,sample_complete_games:1,omitted_markets:0,
  discovery_complete:true};return {schema_version:2,sport:'nfl',captured_at:'2026-09-12T12:00:00Z',
  evidence_sha256:'internal',execution_ready:false,realized_profit:null,sources:{kalshi:{status:'observed',count:1,
  partial_coverage:false,coverage},sportsbook:{status:'not_requested',count:0,partial_coverage:true},
  prizepicks:{status:'unavailable',reason:'access_denied',count:0,partial_coverage:true}},comparisons:[{
  kind:'kalshi_pair',identity:'ticker',title:'A wins?',status:'unverified',execution_ready:false,
  fee_adjusted_profit:null,realized_profit:null,gross_cost:'0.9',gross_gap_to_one_dollar:'0.1',
  reasons:['Fees unverified.'],legs:[{book:'kalshi',team:'YES',cost:'0.4',observed_at:'2026-09-12T12:00:00Z',displayed_size:'10'},
  {book:'kalshi',team:'NO',cost:'0.5',observed_at:'2026-09-12T12:00:00Z',displayed_size:'20'}],
  exchange_fee_scenarios:{combined_cost:{direct:'0.93',non_direct:'0.95'},schedule_effective_date:'2026-07-07',scope:'internal',legs:{internal:true}},
  depth_fee_scenarios:{scope:'internal',cases:[{contracts_per_kalshi_leg:1,combined_cost:{direct:'0.93',non_direct:'0.95'},legs:{internal:true}}]}}]};}

test('public markets strips evidence, profit and fee calculation internals',()=>{const result=publicMarkets(snapshot(),'nfl');
  assert.equal('evidence_sha256' in result,false);assert.equal('realized_profit' in result,false);
  assert.equal('displayed_size' in result.comparisons[0].legs[0],false);
  assert.equal('legs' in result.comparisons[0].exchange_fee_scenarios,false);
  assert.equal('legs' in result.comparisons[0].depth_fee_scenarios.cases[0],false);
  assert.match(result.scope,/not verified arbitrage/);});

test('public markets rejects identity, accounting, status and coverage corruption',()=>{for(const mutate of [
  value=>{value.sport='nba';},value=>{value.execution_ready=true;},value=>{value.comparisons[0].gross_cost='0.8';},
  value=>{value.sources.kalshi.coverage.event_failed_games=1;},value=>{value.sources.prizepicks.reason='private URL';},
  value=>{value.comparisons[0].exchange_fee_scenarios.schedule_effective_date='unknown';}]){
  const value=snapshot();mutate(value);assert.throws(()=>publicMarkets(value,'nfl'));}});
