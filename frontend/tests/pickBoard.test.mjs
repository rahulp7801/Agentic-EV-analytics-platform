import assert from 'node:assert/strict';
import test from 'node:test';
import {publicPickBoard} from '../lib/pickBoard.ts';

const now=Date.parse('2026-09-20T12:00:00Z');
const start=new Date(now+4*3600000).toISOString();
const captured=new Date(now-60000).toISOString();
const lock=new Date(Date.parse(start)-3600000).toISOString();
const signal={id:'a'.repeat(64),prediction_id:'a'.repeat(64),player:'Player',player_id:'00-1',sport:'nfl',
  game_id:'game',game_date:'2026-09-20',home_team:'Home',away_team:'Away',team:'',opponent:'',
  prop_type:'pass_yds',direction:'under',line:250.5,sportsbook:'fanduel',american_odds:-110,
  true_prob:.7,implied_prob:.523809,ev_pct:.176191,expected_return:.336364,push_probability:0,
  confidence_interval:[.55,.8],sample_size:40,mean_stat:null,model_version:'empirical-jeffreys-v4',
  kelly_fraction:.04,gated:false,gate_reason:'accepted',snapped_at:captured,captured_at:captured,
  game_start_time:start,lock_at:lock,board_state:'recorded',selection_policy_version:'pregame-t60-v1',
  strength:'unrated',trade_plan:[],injury_flags:{},market_type:'pass_yds',forecast_cutoff:'2026-09-20',
  availability:{status:'observed',roster_confirmed:true,subject_status:'Not listed on injury report',
    probability_adjusted:false,captured_at:captured,team:'KC',teammates:[],
    source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',
    source_sha256:'c'.repeat(64),
    roster_source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/12/roster',
    roster_source_sha256:'d'.repeat(64)}};

const summary=(patch={})=>({current:1,settled:0,pending:0,wins:0,losses:0,pushes:0,
  verified_win_rate:null,private_internal_count:999,...patch});
const board=(current=[signal],history=[],totals=summary())=>({schema_version:1,sport:'nfl',
  generated_at:new Date(now).toISOString(),lock_minutes:60,selection_policy_version:'pregame-t60-v1',
  current,history,summary:totals});

test('projects a source-bound recommendation and a verified final result',()=>{
  const projected=publicPickBoard(board(),null,'nfl',now);
  assert.equal(projected.current[0].prediction_id,signal.id);
  assert.equal('private_internal_count' in projected.summary,false);
  const final={...signal,board_state:'final',result:'win',result_verified:true,actual_value:220,
    settled_at:new Date(Date.parse(start)+4*3600000).toISOString()};
  const result=publicPickBoard(board([],[final],summary({current:0,settled:1,wins:1,
    verified_win_rate:1})),null,'nfl',Date.parse(start)+5*3600000);
  assert.equal(result.history[0].result,'win');
  assert.equal(result.summary.verified_win_rate,1);
});

test('rejects tampered identity, lock, totals and result evidence',()=>{
  const invalidRecords=[
    {...signal,prediction_id:'b'.repeat(64)},
    {...signal,lock_at:new Date(Date.parse(lock)+60000).toISOString()},
  ];
  for(const changed of invalidRecords) assert.throws(()=>publicPickBoard(board([changed]),null,'nfl',now));
  assert.throws(()=>publicPickBoard(board([signal],[],summary({current:2})),null,'nfl',now));
  assert.throws(()=>publicPickBoard(board([signal,{...signal,id:'b'.repeat(64),prediction_id:'b'.repeat(64)}],[],
    summary({current:2})),null,'nfl',now));
  const final={...signal,board_state:'final',result:'win',result_verified:false,actual_value:null,settled_at:null};
  assert.throws(()=>publicPickBoard(board([],[final],summary({current:0,pending:1})),null,'nfl',Date.parse(start)+5*3600000));
  const pending={...signal,board_state:'final',result:'pending',result_verified:false,actual_value:220,settled_at:null};
  assert.throws(()=>publicPickBoard(board([],[pending],summary({current:0,pending:1})),null,'nfl',Date.parse(start)+5*3600000));
  const wrongGrade={...signal,board_state:'final',result:'loss',result_verified:true,actual_value:220,
    settled_at:new Date(Date.parse(start)+4*3600000).toISOString()};
  assert.throws(()=>publicPickBoard(board([],[wrongGrade],summary({current:0,settled:1,losses:1,
    verified_win_rate:0})),null,'nfl',Date.parse(start)+5*3600000));
});
