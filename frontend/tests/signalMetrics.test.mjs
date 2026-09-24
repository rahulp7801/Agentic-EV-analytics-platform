import test from 'node:test';
import assert from 'node:assert/strict';
import {signalMetrics,publicSignals,publicSignalSnapshots,parlayScenario,forecastWindow,latestForecastWindow,publicPlayerProfile} from '../lib/signalMetrics.ts';
const now = Date.parse('2026-09-10T12:00:00Z');
const quote = {gated:false,forecast_cutoff:'2026-09-10',confidence_interval:[.55,.7],true_prob: .6, american_odds: -110, push_probability: 0,
  direction: 'under', sportsbook: 'draftkings', model_version: 'empirical-jeffreys-v4',
  sample_size: 30, kelly_fraction: .04, snapped_at: new Date(now).toISOString(),
  game_start_time: new Date(now + 3600000).toISOString(),availability:{status:'observed',
    roster_confirmed:true,subject_status:'Not listed on injury report',probability_adjusted:false,
    captured_at:new Date(now).toISOString(),team:'KC',teammates:[],
    source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',source_sha256:'a'.repeat(64),
    roster_source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/12/roster',roster_source_sha256:'b'.repeat(64)}};
const publicQuote={...quote,id:'prediction',player:'Player',team:'',opponent:'',
  home_team:'Home',away_team:'Away',game_id:'game',sport:'nfl',prop_type:'pass_yds',line:249.5,
  mean_stat:260,confidence_interval:[.55,.7],trade_plan:[],injury_flags:{},
  market_type:'player_pass_yds',strength:'unrated'};
test('Next Gen Stats context is source-bound, pregame-only, and never changes probability',()=>{
  const evidence={status:'observed',stat_type:'passing',sample_weeks:8,cutoff_season:2026,
    cutoff_week:3,cutoff_exclusive:true,metrics:{avg_time_to_throw:2.71,aggressiveness:13.4},
    source_provider:'nflverse_ngs',
    source_url:'https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_passing.parquet',
    source_sha256:'c'.repeat(64),source_observed_at:new Date(now).toISOString(),probability_adjusted:false};
  const result=publicSignals([{...publicQuote,next_gen_stats:{...evidence,private:'secret'}}],now).signals[0];
  assert.equal(result.next_gen_stats.sample_weeks,8);assert.equal(result.true_prob,publicQuote.true_prob);
  assert.equal(result.next_gen_stats.private,undefined);assert.equal(result.next_gen_stats.probability_adjusted,false);
  for(const patch of [{source_url:'https://evil.example/ngs'},{probability_adjusted:true},
    {cutoff_exclusive:false},{sample_weeks:9},{metrics:{unknown:1}},{stat_type:'rushing'}]) {
    const projected=publicSignals([{...publicQuote,next_gen_stats:{...evidence,...patch}}],now).signals[0];
    assert.equal(projected.next_gen_stats,undefined);
    assert.equal(projected.true_prob,publicQuote.true_prob);
  }
});
test('full legitimate NFL/NBA/CFB team names survive both public forecast boundaries',()=>{
  for(const [sport,home,away] of [['nfl','Washington Commanders','Tampa Bay Buccaneers'],
    ['cfb','Ohio State Buckeyes','Texas Longhorns'],
    ['nba','Minnesota Timberwolves','Oklahoma City Thunder'],['nba','Golden State Warriors','Portland Trail Blazers']]) {
    const forecast={...publicQuote,sport,prop_type:sport==='nba' ? 'points' : 'pass_yds',
      market_type:sport==='nba' ? 'player_points' : 'player_pass_yds',home_team:home,away_team:away};
    const game={sport,game_id:'game',home_team:home,away_team:away,date:'20260910'};
    const result=publicSignalSnapshots([{generated_at:new Date(now).toISOString(),signals:[forecast],games:[game]}],now,sport);
    assert.equal(result.signals.length,1);assert.equal(result.invalid_signals,0);
    assert.equal(result.games[0].home_team,home);
    assert.equal(publicSignals([{...forecast,home_team:'x'.repeat(101)}],now).signals.length,0);
    assert.throws(()=>publicSignalSnapshots([{generated_at:new Date(now).toISOString(),signals:[],games:[{...game,away_team:'bad\nname'}]}],now));
  }
});
test('CFB availability keeps exact college sources and rejects unsupported context splits',()=>{
  const availability={...quote.availability,
    source_url:'https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries',
    roster_source_url:'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/194/roster',
    player_id:'4429000',player_image_url:'https://a.espncdn.com/i/headshots/college-football/players/full/4429000.png'};
  const signal={...publicQuote,sport:'cfb',availability};
  const projected=publicSignals([signal],now).signals[0];
  assert.equal(projected.sport,'cfb');
  assert.equal(projected.availability.player_id,'4429000');
  const withSplit={...availability,context_splits:[{player:'Defender'}]};
  const rejected=publicSignals([{...signal,availability:withSplit}],now).signals[0];
  assert.equal(rejected.availability,undefined);assert.equal(rejected.gated,true);
  assert.deepEqual(publicSignals([{...signal,prop_type:'points'}],now),{signals:[],invalid_signals:1});
});
test('latest available view retains archived forecasts without loosening eligibility',()=>{
  assert.equal(latestForecastWindow([publicQuote],now),'upcoming');
  const later=now+7200000;
  assert.equal(latestForecastWindow([publicQuote],later),'archive');
  const result=publicSignals([publicQuote],later).signals[0];
  assert.equal(result.gated,true);
  assert.equal(result.kelly_fraction,0);
  assert.equal(result.true_prob,publicQuote.true_prob);
});
test('current player presentation requires source and ID commitments and cannot override historical risk',()=>{
  const profile={player:'Player',name:'Player',team:'KC',player_id:'123',jersey:'0',position:'QB',
    image_url:'https://a.espncdn.com/i/headshots/nfl/players/full/123.png',captured_at:new Date(now).toISOString(),
    source_url:quote.availability.roster_source_url,source_sha256:'c'.repeat(64),private:'secret',gated:false};
  assert.equal(publicPlayerProfile(profile,'nfl','Player',now).jersey,'0');
  for(const patch of [{player:'Other'},{name:'Alias'},{source_url:profile.source_url+'?secret=x'},
    {image_url:profile.image_url.replace('123.png','456.png')},{captured_at:new Date(now+120000).toISOString()},
    {captured_at:new Date(now-15*86400000).toISOString()}]) assert.equal(publicPlayerProfile({...profile,...patch},'nfl','Player',now),undefined);
  const signal=publicSignals([{...publicQuote,player_profile:profile,gated:true,gate_reason:'risk_gate'}],now).signals[0];
  assert.equal(signal.gated,true);assert.equal(signal.kelly_fraction,0);
  assert.equal(signal.player_profile.private,undefined);assert.equal(signal.player_profile.gated,undefined);
  assert.equal(signal.true_prob,publicQuote.true_prob);
  assert.equal(signal.availability.captured_at,publicQuote.availability.captured_at);
  assert.equal(publicPlayerProfile({...profile,jersey:'<1>',position:'<script>'},'nfl','Player',now).jersey,undefined);
});
test('portraits require an exact ESPN URL tied to the roster athlete and league',()=>{
  const a={...quote.availability,player_id:'123',player_image_url:'https://a.espncdn.com/i/headshots/nfl/players/full/123.png'};
  const project=availability=>publicSignals([{...publicQuote,availability}],now).signals[0];
  assert.equal(project(a).availability.player_image_url,a.player_image_url);
  for(const player_image_url of ['https://evil.example/123.png',a.player_image_url+'?redirect=1',a.player_image_url.replace('/nfl/','/nba/'),a.player_image_url.replace('123.png','456.png')]) {
    const result=project({...a,player_image_url});
    assert.equal(result.availability.player_image_url,undefined);
    assert.equal(result.true_prob,.6);
  }
});
test('uses payout for expected return, separates edge and preserves Under', () => {
  const s = signalMetrics(quote, now);
  assert.equal(s.direction, 'under'); assert.equal(s.gated, false);
  assert.ok(Math.abs(s.expected_return - .145454545) < 1e-8);
  assert.ok(Math.abs(s.ev_pct - .076190476) < 1e-8);
  assert.deepEqual(s.confidence_interval,[.55,.7]); assert.equal(s.strength, 'unrated');
});
test('push refunds count toward expected return', () => {
  assert.ok(Math.abs(signalMetrics({...quote, true_prob:.5, push_probability:.1},now).expected_return - .0545454545) < 1e-8);
});
test('legacy, stale, synthetic, malformed and gated estimates cannot recommend stakes', () => {
  for (const patch of [{model_version: undefined}, {model_version:'empirical-jeffreys-v3'}, {snapped_at:'2020-01-01'},
    {sportsbook:'prizepicks'}, {sample_size:NaN}, {game_start_time:undefined},
    {gated:true}, {true_prob:null}, {kelly_fraction:NaN}, {direction:undefined}]) {
    const s=signalMetrics({...quote,...patch},now);
    assert.equal(s.gated,true,JSON.stringify(patch)); assert.equal(s.kelly_fraction,0);
  }
});
test('kickoff permanently overrides quote freshness',()=>{
  const started=signalMetrics({...quote,snapped_at:new Date(now-3600000).toISOString(),game_start_time:new Date(now).toISOString()},now);
  assert.equal(started.gated,true);assert.equal(started.gate_reason,'game_started');assert.equal(started.kelly_fraction,0);
});
test('uncertainty must come from a valid reported interval', () => {
  assert.equal(signalMetrics({...quote, confidence_interval:[.9,.2]},now).confidence_interval,null);
  assert.deepEqual(signalMetrics({...quote, confidence_interval:[.4,.8]},now).confidence_interval,[.4,.8]);
});

test('availability screens recommendations without changing model probabilities',()=>{
  for(const availability of [undefined,{...quote.availability,status:'unavailable'},
    {...quote.availability,subject_status:'Out'},
    {...quote.availability,captured_at:new Date(now-3600001).toISOString()},
    {...quote.availability,teammates:[{player:'Teammate',status:'Out',position:'WR',reported_at:new Date(now).toISOString()}]}]) {
    const result=publicSignals([{...publicQuote,availability}],now).signals[0];
    assert.equal(result.gated,true);assert.equal(result.kelly_fraction,0);assert.equal(result.true_prob,.6);
  }
  const result=publicSignals([{...publicQuote,availability:{...quote.availability,source_url:'https://evil.example',private:'secret'}}],now).signals[0];
  assert.equal(result.availability,undefined);assert.equal(result.gated,true);
  const projected=publicSignals([{...publicQuote,availability:{...quote.availability,private:'internal'}}],now).signals[0];
  assert.equal('private' in projected.availability,false);assert.equal(projected.gated,false);
  for(const context of [
    {player:'Teammate',status:'Questionable',position:'WR',reported_at:new Date(now).toISOString()},
    {player:'Teammate',status:'Injured Reserve',position:'WR',reported_at:new Date(now).toISOString()},
    {player:'Defender',status:'Out',position:'CB',reported_at:new Date(now).toISOString(),
      relationship:'opponent',team:'LV',unit:'defense',source_url:quote.availability.source_url,source_sha256:'a'.repeat(64)},
  ]) {
    const reviewed=publicSignals([{...publicQuote,availability:{...quote.availability,teammates:[context]}}],now).signals[0];
    assert.equal(reviewed.gated,false);assert.equal(reviewed.availability.teammates[0].status,context.status);
  }
  for(const patch of [{probability_adjusted:true},{roster_source_url:'https://evil.example/roster'},
    {roster_source_url:'https://site.api.espn.com.evil.example/apis/site/v2/sports/football/nfl/teams/12/roster'},
    {roster_source_url:'https://user:password@site.api.espn.com/apis/site/v2/sports/football/nfl/teams/12/roster'},
    {roster_source_url:quote.availability.roster_source_url+'?redirect=evil'},
    {source_url:'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries'}]) {
    const rejected=publicSignals([{...publicQuote,availability:{...quote.availability,...patch}}],now).signals[0];
    assert.equal(rejected.availability,undefined);assert.equal(rejected.gated,true);
  }
});

test('recorded injury context retains explicit participation cohorts and strips internal identities',()=>{
  const split={player:'Defender',status:'Out',position:'CB',team:'LV',relationship:'opponent',unit:'defense',
    source:'nflverse_snap_counts',participation:'recorded unit snaps',evidence_version:'recorded-participation-v2',unknown_games:2,participant_id:'private-pfr-id',
    active:{games:8,mean:241.25,hit_rate:.625},absent:{games:0,mean:null,hit_rate:null}};
  const result=publicSignals([{...publicQuote,availability:{...quote.availability,context_splits:[split]}}],now).signals[0];
  assert.deepEqual(result.availability.context_splits,[{player:'Defender',status:'Out',position:'CB',team:'LV',
    relationship:'opponent',unit:'defense',source:'nflverse_snap_counts',participation:'recorded unit snaps',evidence_version:'recorded-participation-v2',unknown_games:2,
    active:split.active,absent:split.absent}]);
  assert.equal(result.true_prob,.6);assert.equal(result.availability.probability_adjusted,false);
  const legacy={...split};delete legacy.evidence_version;
  const retained=publicSignals([{...publicQuote,availability:{...quote.availability,context_splits:[legacy]}}],now).signals[0];
  assert.equal(retained.availability.context_splits,undefined);
  assert.equal(retained.availability.roster_confirmed,true);assert.equal(retained.true_prob,.6);
  assert.deepEqual(retained.availability.teammates,quote.availability.teammates);
  const unknown={...split,active:{games:0,mean:null,hit_rate:null},unknown_games:8};
  const partial=publicSignals([{...publicQuote,availability:{...quote.availability,context_splits:[unknown]}}],now).signals[0];
  assert.equal(partial.availability.context_splits[0].unknown_games,8);
  for(const broken of [{...split,source:'private_feed'},{...split,active:{games:41,mean:1,hit_rate:.5}},
    {...split,absent:{games:0,mean:0,hit_rate:null}},
    {...split,active:{games:8,mean:null,hit_rate:.5}},
    {...split,active:{games:8,mean:1,hit_rate:null}},
    {...split,unknown_games:-1},{...split,unknown_games:33},{...split,unknown_games:1.5},
    {...split,evidence_version:'future-unsupported'},
    {...split,absent:{games:1,mean:2,hit_rate:1}}]) {
    const projected=publicSignals([{...publicQuote,availability:{...quote.availability,context_splits:[broken]}}],now).signals[0];
    assert.equal(projected.availability,undefined);assert.equal(projected.gated,true);
  }
});

test('relevant current reports retain team relationship and unit context',()=>{
  const report={player:'Defender',status:'Questionable',position:'CB',reported_at:new Date(now).toISOString(),
    team:'LV',relationship:'opponent',unit:'defense',source_url:quote.availability.source_url,source_sha256:'a'.repeat(64)};
  const result=publicSignals([{...publicQuote,availability:{...quote.availability,teammates:[report]}}],now).signals[0];
  assert.deepEqual(result.availability.teammates,[report]);
  assert.equal(result.gated,false);
  for(const broken of [{...report,relationship:'spectator'},{...report,team:'TOO-LONG'}]) {
    const projected=publicSignals([{...publicQuote,availability:{...quote.availability,teammates:[broken]}}],now).signals[0];
    assert.equal(projected.availability,undefined);assert.equal(projected.gated,true);
  }
});

test('forecast windows change at kickoff',()=>{
  assert.equal(forecastWindow(quote,now),'upcoming');
  assert.equal(forecastWindow(quote,now+3600000),'archive');
  assert.equal(forecastWindow({},now),'archive');
});

test('roster identity explanations require the NFL crosswalk commitment and strip internals',()=>{
  const availability={...quote.availability,roster_player_name:'Player III',
    identity_source_url:'https://github.com/nflverse/nflverse-data/releases/download/players/players.csv',
    identity_source_sha256:'c'.repeat(64),player_identities:{private:'internal'}};
  const project=a=>publicSignals([{...publicQuote,availability:a}],now).signals[0];
  const result=project(availability);
  assert.equal(result.availability.roster_player_name,'Player III');
  assert.equal(result.availability.identity_source_url,availability.identity_source_url);
  assert.equal('player_identities' in result.availability,false);
  assert.equal(result.true_prob,.6);
  for(const patch of [{identity_source_url:'https://evil.example/players.csv'},
    {identity_source_url:availability.identity_source_url+'?secret=1'},
    {identity_source_sha256:undefined},{roster_player_name:undefined},
    {identity_source_sha256:'bad'}]) {
    const rejected=project({...availability,...patch});
    assert.equal(rejected.availability,undefined);assert.equal(rejected.gated,true);
  }
});

test('roster injury sources require the exact committed roster URL and hash',()=>{
  const availability={...quote.availability, source_url:quote.availability.roster_source_url,
    source_sha256:quote.availability.roster_source_sha256,
    teammates:[{player:'Teammate',status:'Questionable',position:'RB',reported_at:new Date(now).toISOString()}]};
  const project=a=>publicSignals([{...publicQuote,availability:a}],now).signals[0];
  const result=project(availability);
  assert.equal(result.availability.source_url,availability.roster_source_url);
  assert.equal(result.gated,false);
  assert.equal(result.true_prob,.6);assert.equal(result.kelly_fraction,.04);
  for(const patch of [{source_sha256:'c'.repeat(64)},
    {source_url:availability.source_url.replace('/12/','/13/')},
    {source_url:availability.source_url+'?redirect=evil'},
    {source_url:availability.source_url.replace('/football/nfl/','/basketball/nba/')}]) {
    const rejected=project({...availability,...patch});
    assert.equal(rejected.availability,undefined);assert.equal(rejected.gated,true);
  }
});
test('public signals require real identity and price fields and omit internal data', () => {
  const value={...publicQuote,internal_evidence:'private implementation detail'};
  const result=publicSignals([value,{...value,sportsbook:undefined},{...value,american_odds:-105.5},
    {...value,sportsbook:'PrizePicks'}],now);
  assert.equal(result.invalid_signals,3);
  assert.equal(result.signals.length,1);
  assert.equal(result.signals[0].sportsbook,'draftkings');
  assert.equal(result.signals[0].american_odds,-110);
  assert.equal(result.signals[0].sport,'nfl');
  assert.equal(result.signals[0].prop_type,'pass_yds');
  assert.equal('internal_evidence' in result.signals[0],false);
});
test('public signals never fill missing fields with plausible market data', () => {
  for (const field of ['sport','prop_type','direction','line','true_prob','sportsbook','american_odds']) {
    const changed={...publicQuote};delete changed[field];
    assert.deepEqual(publicSignals([changed],now),{signals:[],invalid_signals:1},field);
  }
  for (const changed of [{...publicQuote,true_prob:1.1},{...publicQuote,push_probability:-.1},
    {...publicQuote,true_prob:.9,push_probability:.2}]) {
    assert.deepEqual(publicSignals([changed],now),{signals:[],invalid_signals:1});
  }
});
test('public signal snapshots project bounded metadata and strip stored internals',()=>{
  const snapshot={generated_at:new Date(now).toISOString(),signals:[publicQuote],coverage:{internal:true},
    games:[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260910',sport:'nfl',secret:'hidden'}]};
  const result=publicSignalSnapshots([snapshot],now);
  assert.equal(result.generated_at,snapshot.generated_at);assert.equal(result.signals.length,1);
  assert.deepEqual(result.games,[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260910',sport:'nfl'}]);
  assert.equal('coverage' in result,false);assert.equal('secret' in result.games[0],false);
});
test('public signal snapshots enforce the requested league boundary',()=>{
  const nbaQuote={...publicQuote,id:'nba-prediction',sport:'nba',prop_type:'points',
    home_team:'Celtics',away_team:'Knicks'};
  const snapshot={generated_at:new Date(now).toISOString(),signals:[publicQuote,nbaQuote],games:[
    {game_id:'game',home_team:'Home',away_team:'Away',date:'20260910',sport:'nfl'},
    {game_id:'nba-game',home_team:'Celtics',away_team:'Knicks',date:'20260910',sport:'nba'},
  ]};
  const result=publicSignalSnapshots([snapshot],now,'nba');
  assert.deepEqual(result.signals.map(signal=>signal.sport),['nba']);
  assert.deepEqual(result.games.map(game=>game.sport),['nba']);
  assert.equal(result.invalid_signals,0);
});
test('public signal snapshots reject malformed envelopes and bound attacker-controlled text',()=>{
  const snapshot={generated_at:new Date(now).toISOString(),signals:[publicQuote],games:[]};
  for(const changed of [{...snapshot,generated_at:'today'},
    {...snapshot,games:[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260231',sport:'nfl'}]},
    {...snapshot,games:[{game_id:'game',home_team:'Home',away_team:'Away',date:'20260910',sport:'mlb'}]}]) {
    assert.throws(()=>publicSignalSnapshots([changed],now));
  }
  assert.deepEqual(publicSignals([{...publicQuote,player:'x'.repeat(101)}],now),
    {signals:[],invalid_signals:1});
  assert.throws(()=>publicSignals(Array(5001).fill(publicQuote),now));
});
test('parlay scenario reports dependence bounds, not an optimized joint forecast', () => {
  const s=parlayScenario([.6,.6],3);
  assert.ok(Math.abs(s.lower-.2)<1e-8); assert.equal(s.upper,.6);
  assert.equal(s.independent,.36); assert.ok(Math.abs(s.expectedReturn-.08)<1e-8);
  assert.equal(parlayScenario([.6],3),null); assert.equal(parlayScenario([.6,NaN],3),null);
});


test('NBA explicit zero minutes and unknown participation remain separate',()=>{
  const split={player:'Guard',status:'Out',position:'SG',team:'KC',relationship:'teammate',unit:'offense',
    source:'nba_final_box_scores',participation:'recorded minutes',evidence_version:'recorded-participation-v2',
    unknown_games:3,active:{games:10,mean:25,hit_rate:.7},absent:{games:5,mean:29,hit_rate:.8}};
  const availability={...quote.availability,context_splits:[split],
    source_url:'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries',
    roster_source_url:'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/12/roster'};
  const result=publicSignals([{...publicQuote,sport:'nba',prop_type:'points',availability}],now).signals[0];
  assert.deepEqual(result.availability.context_splits,[split]);
  assert.equal(result.true_prob,.6);
});
