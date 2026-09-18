import test from 'node:test';
import assert from 'node:assert/strict';
import {pickTerms,latestRecordedQuote} from '../lib/pickTerms.ts';
import {base,now} from './fixtures/qualifiedSignal.mjs';
test('displayed bet returns equal an independent win/loss/refund payout calculation',()=>{
  let checked=0;
  for(const odds of [-200,-150,-110,100,120,200]) for(const push of [0,.1]) for(const direction of ['over','under']) {
    const win=.65*(1-push),net=odds<0 ? 100/Math.abs(odds) : odds/100;
    const quote={...base,american_odds:odds,push_probability:push,true_prob:win,direction,confidence_interval:[win-.025,win+.025]};
    const terms=pickTerms(quote,now);
    const breakEven=(1-push)/(1+net),expected=win*(net*100)+(1-win-push)*(-100)+push*0;
    const shouldQualify=win-breakEven<=.15+1e-12 && win-.025>breakEven;
    assert.equal(Boolean(terms),shouldQualify);
    if(!terms) continue;
    checked++;assert.ok(Math.abs(terms.expectedPer100-expected)<1e-9);
    assert.ok(Math.abs(terms.signal.implied_prob-breakEven)<1e-12);
    assert.ok(Math.abs(terms.lowerBoundPer100-((win-.025)*net*100+(1-(win-.025)-push)*-100))<1e-9);
    assert.ok(terms.lowerBoundPer100>0);assert.equal(terms.pick,`${direction==='over' ? 'Over' : 'Under'} 249.5 passing yards`);
    assert.equal(terms.price,odds>0 ? '+'+odds : String(odds));
  }
  assert.ok(checked>=8);
});
test('missing approval, stale prices, contradictory uncertainty and invalid cutoffs cannot display bet terms',()=>{
  for(const patch of [{gated:undefined},{gated:null},{gated:0},{gated:'false'},{forecast_cutoff:undefined},
    {forecast_cutoff:'2026-09-09'},{forecast_cutoff:'2026-09-11'},
    {confidence_interval:null},{confidence_interval:[.7,.8]},{confidence_interval:[.49,.8]},
    {american_odds:NaN},{true_prob:.95},{sportsbook:'prizepicks'},
    {availability:undefined},{kelly_fraction:0}]) assert.equal(pickTerms({...base,...patch},now),null,JSON.stringify(patch));
  assert.ok(pickTerms(base,now));assert.equal(pickTerms(base,now+300001),null);
  assert.equal(pickTerms({...base,game_start_time:new Date(now).toISOString()},now),null);
});
test('cutoffs use the event Eastern calendar day, including a game after midnight UTC',()=>{
  const quote={...base,game_start_time:'2026-09-11T02:00:00Z'};
  assert.ok(pickTerms(quote,now));assert.equal(pickTerms({...quote,forecast_cutoff:'2026-09-11'},now),null);
});

test('NBA terms use the same payout calculation and reject football props in basketball',()=>{
  const nba={...base,sport:'nba',prop_type:'points',line:24.5,mean_stat:26,
    home_team:'Los Angeles Lakers',away_team:'Boston Celtics',market_type:'player_points',
    availability:{...base.availability,team:'LAL',
      source_url:'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries',
      roster_source_url:'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/13/roster'}};
  const terms=pickTerms(nba,now);
  assert.equal(terms.pick,'Over 24.5 points');assert.ok(Math.abs(terms.expectedPer100-30)<1e-9);
  assert.equal(pickTerms({...nba,prop_type:'pass_yds'},now),null);
  assert.equal(pickTerms({...base,prop_type:'points'},now),null);
  assert.ok(pickTerms({...nba,game_start_time:'2026-09-11T02:00:00Z'},now));
});

test('empty-shortlist context describes only real validated loaded quote timestamps',()=>{
  assert.equal(latestRecordedQuote([],now),null);
  assert.equal(latestRecordedQuote([{player:'Invented',snapped_at:new Date(now).toISOString()}],now),null);
  assert.deepEqual(latestRecordedQuote([base],now),{observed_at:base.snapped_at,expired:false});
  assert.equal(latestRecordedQuote([base],now+300001).expired,true);
  assert.equal(latestRecordedQuote([{...base,snapped_at:new Date(now+60001).toISOString()}],now),null);
  const older={...base,snapped_at:new Date(now-3600000).toISOString()};
  assert.equal(latestRecordedQuote([older,base],now).observed_at,base.snapped_at);
});
