import test from 'node:test';
import assert from 'node:assert/strict';
import {forecastHistory} from '../lib/forecastHistory.ts';
import {gameLogRequest} from '../lib/publicGameLogs.ts';

const signal={player:'Player',sport:'nfl',forecast_cutoff:'2026-09-17',prop_type:'receptions',line:4,direction:'under'};
const row=(date,receptions,player='Player')=>({date,player,team:'BUF',opponent:'DET',receptions});
test('history excludes target/future games and similar names, and keeps ties/missing out of rates',()=>{
  const result=forecastHistory([row('2026-09-18',9),row('2026-09-17',9),row('2026-09-16',8,'Player Junior'),
    row('2026-09-15',0),row('2026-09-14',6),row('2026-09-13',4),row('2026-09-12',undefined)],signal);
  assert.equal(result.rows.length,4);assert.equal(result.wins,1);assert.equal(result.losses,1);
  assert.equal(result.ties,1);assert.equal(result.missing,1);assert.equal(result.rate,.5);
  assert.equal(result.mean,10/3);assert.equal(result.rows[0].stat,0);
  assert.equal(forecastHistory([row('2026-09-15',4)],signal).rate,null);
  assert.equal(forecastHistory([row('2026-09-15',undefined)],signal).mean,null);
});
test('history windows sort before limiting, PRA requires all components, duplicate games fail closed',()=>{
  const result=forecastHistory([row('2026-09-13',3),row('2026-09-15',6)],signal,1);
  assert.equal(result.rows[0].date,'2026-09-15');assert.equal(result.rate,0);
  const nba={...signal,sport:'nba',prop_type:'pra',direction:'over',line:10};
  const base={date:'2026-09-15',player:'Player',team:'BOS',opponent:'NY'};
  assert.equal(forecastHistory([{...base,points:6,rebounds:4,assists:1}],nba).rows[0].stat,11);
  assert.equal(forecastHistory([{...base,points:6,rebounds:4}],nba).rows[0].stat,null);
  assert.throws(()=>forecastHistory([row('2026-09-15',3),row('2026-09-15',3)],signal));
  assert.throws(()=>forecastHistory([],{...signal,forecast_cutoff:'2026-02-31'}));
});
test('historical API query bounds exact names, limits and strict calendar cutoffs',()=>{
  const parse=value=>gameLogRequest(new URLSearchParams(value));
  assert.deepEqual(parse('sport=nfl&player=Player&exact=1&before=2026-09-17&limit=20'),
    {sport:'nfl',player:'Player',exact:true,before:'2026-09-17',limit:20});
  assert.equal(parse('limit=999999').limit,200);assert.equal(parse('').before,null);
  for(const value of ['before=2026-02-31','before=2026-09-17T00:00Z','before=','exact=1','exact=2','limit=Infinity','limit=0','sport=mlb','player=A%00B']) assert.throws(()=>parse(value));
});
