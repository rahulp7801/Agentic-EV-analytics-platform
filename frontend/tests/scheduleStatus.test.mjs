import test from 'node:test';
import assert from 'node:assert/strict';
import {scheduleSnapshot} from '../lib/scheduleStatus.ts';

test('hosted schedules require recent evidence for the current Eastern date',()=>{
  const now=Date.parse('2026-09-11T18:00:00Z');
  const data={sport:'nfl',status:'complete',partial:false,captured_at:'2026-09-11T17:59:00Z',
    as_of_date:'2026-09-11',games:[]};
  assert.equal(scheduleSnapshot(data,'nfl',now).status,200);
  assert.equal(scheduleSnapshot({...data,status:'partial',partial:true},'nfl',now).body.partial,true);
  for (const value of [null,{...data,sport:'nba'},{...data,status:'unavailable'},{...data,as_of_date:'2026-09-10'},
    {...data,captured_at:'2026-09-11T15:00:00Z'},{...data,captured_at:'2026-09-11T19:00:00Z'}]) {
    assert.equal(scheduleSnapshot(value,'nfl',now).status,503);
  }
});

test('hosted schedules validate real games and expose only display fields',()=>{
  const now=Date.parse('2026-09-11T18:00:00Z');
  const game={provider_event_id:'401',home_abbr:'CIN',away_abbr:'TB',home_name:'Cincinnati Bengals',
    away_name:'Tampa Bay Buccaneers',date:'20260911',label:'Today',game_time:'2026-09-11T17:00:00Z',
    completed:false,source_url:'internal'};
  const data={sport:'nfl',status:'complete',partial:false,captured_at:'2026-09-11T17:59:00Z',
    as_of_date:'2026-09-11',games:[game],failures:[],sources:['internal']};
  const result=scheduleSnapshot(data,'nfl',now);
  assert.equal(result.status,200);
  assert.deepEqual(result.body.games,[{home_abbr:'CIN',away_abbr:'TB',home_name:'Cincinnati Bengals',
    away_name:'Tampa Bay Buccaneers',date:'20260911',label:'Today',game_time:'2026-09-11T17:00:00Z'}]);
  for(const changed of [{...game,date:'20260231'},{...game,date:'20260912'},
    {...game,label:'Tomorrow'},{...game,game_time:'2026-09-12T17:00:00Z'},{...game,completed:'false'}]) {
    assert.equal(scheduleSnapshot({...data,games:[changed]},'nfl',now).status,503);
  }
  assert.equal(scheduleSnapshot({...data,games:[game,{...game}]},'nfl',now).status,503);
});
