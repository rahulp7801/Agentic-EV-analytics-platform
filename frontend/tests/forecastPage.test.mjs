import test from 'node:test';
import assert from 'node:assert/strict';
import {forecastRequest,forecastPage} from '../lib/forecastPage.ts';
import {fetchForecasts} from '../lib/fetchForecasts.ts';
const now=Date.now(),stamp=new Date(now).toISOString();
const base={id:'A',player:'A',team:'KC',opponent:'BUF',sport:'nfl',home_team:'Kansas City Chiefs',away_team:'Washington Commanders',game_id:'game',
  prop_type:'pass_yds',line:249.5,direction:'over',true_prob:.6,american_odds:100,push_probability:0,
  sportsbook:'draftkings',model_version:'empirical-jeffreys-v4',sample_size:40,mean_stat:260,
  confidence_interval:[.55,.65],kelly_fraction:.01,gated:false,forecast_cutoff:new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now+3600000),trade_plan:[],injury_flags:{},market_type:'player_pass_yds',
  snapped_at:stamp,game_start_time:new Date(now+3600000).toISOString(),
  availability:{status:'observed',roster_confirmed:true,subject_status:'Not listed on injury report',probability_adjusted:false,
    captured_at:stamp,team:'KC',teammates:[],
    source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',source_sha256:'a'.repeat(64),
    roster_source_url:'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/12/roster',roster_source_sha256:'b'.repeat(64)}};
const metadata={generated_at:stamp,signals:[],games:[]};
const request=()=>forecastRequest(new URL('https://example.test/api/signals?sport=nfl'));
function input(values,total=values.length) {
  return {rows:values.map(signal=>({payload:{generated_at:stamp,games:[],signals:[signal]}})),
    profiles:{},total_count:total,revision:'a'.repeat(64),metadata,invalid_envelopes:0,window_complete:true};
}
test('forecast requests reject unbounded offsets, limits and unsupported views',()=>{
  for(const query of ['sport=mlb','offset=-1','offset=1000','offset=50001','offset=01','limit=101','limit=0',
    'view=other','revision=bad','view=qualified&offset=1','view=qualified&revision='+ 'a'.repeat(64)]) {
    assert.throws(()=>forecastRequest(new URL('https://example.test/api/signals?'+query)));
  }
});

test('forecast requests accept the bounded CFB research library',()=>{
  assert.deepEqual(forecastRequest(new URL('https://example.test/api/signals?sport=cfb&view=library&offset=0&limit=36')),
    {sport:'cfb',view:'library',offset:0,limit:36,revision:null});
});
test('an accumulated archive exceeding 5,000 records still yields a bounded usable page',()=>{
  const result=forecastPage(input(Array(100).fill(base),6000),request(),now);
  assert.equal(result.signals.length,100);assert.equal(result.pagination.next_offset,100);
  assert.equal(result.pagination.complete,false);assert.equal(result.total_count,6000);
});
test('byte bounds include actual multibyte teammate evidence without erasing it',()=>{
  const teammate={player:'🏈'.repeat(50),status:'Active',position:'WR',reported_at:stamp};
  const larger={...base,availability:{...base.availability,teammates:Array(64).fill(teammate)}};
  const result=forecastPage(input(Array(100).fill(larger)),request(),now);
  assert.ok(result.signals.length<100);assert.ok(result.signals.length>0);
  assert.equal(result.signals[0].availability.teammates.length,64);
  assert.ok(Buffer.byteLength(JSON.stringify(result))<1.2*1024*1024);
  assert.equal(result.pagination.next_offset,result.signals.length);
});
test('independent qualified inspection can find the best candidate beyond the archive page',()=>{
  const weak={...base,true_prob:.61,confidence_interval:[.52,.7]};
  const stronger={...base,id:'BEST',player:'BEST',confidence_interval:[.58,.65]};
  const options=forecastRequest(new URL('https://example.test/api/signals?sport=nfl&view=qualified'));
  const result=forecastPage(input([...Array(100).fill(weak),stronger]),options,now);
  assert.equal(result.signals[0].id,'BEST');assert.equal(result.pagination.complete,true);
  const incomplete=forecastPage(input([base],5002),options,now);
  assert.deepEqual(incomplete.signals,[]);assert.equal(incomplete.pagination.complete,false);
  const incompleteWindow=forecastPage({...input([base]),window_complete:false},options,now);
  assert.deepEqual(incompleteWindow.signals,[]);assert.equal(incompleteWindow.pagination.complete,false);
  assert.throws(()=>forecastPage({...input([base]),revision:'b'.repeat(64)},
    {...request(),revision:'a'.repeat(64)},now));
});
test('client collects pages without truncation and detects moving snapshot revisions',async()=>{
  const values=Array.from({length:240},(_,i)=>({...base,id:String(i)}));
  let calls=0;
  const fetchImpl=async(url)=>{
    const options=forecastRequest(new URL(url,'https://example.test'));
    calls++;return {ok:true,json:async()=>forecastPage(input(values.slice(options.offset,options.offset+options.limit),values.length),options,now)};
  };
  const result=await fetchForecasts('nfl',undefined,'library',fetchImpl);
  assert.equal(calls,3);assert.equal(result.signals.length,240);assert.equal(result.complete,true);
  let page=0;
  await assert.rejects(fetchForecasts('nfl',undefined,'library',async(url)=>{
    const options=forecastRequest(new URL(url,'https://example.test'));
    const body=forecastPage(input(values.slice(options.offset,options.offset+options.limit),values.length),options,now);
    if(page++>0) body.pagination.revision='b'.repeat(64);
    return {ok:true,json:async()=>body};
  }),/coverage/);
});
test('client cannot confuse a bounded research window with a complete archive',async()=>{
  const result=await fetchForecasts('nfl',undefined,'library',async(url)=>{
    const options=forecastRequest(new URL(url,'https://example.test'));
    return {ok:true,json:async()=>forecastPage(input(Array(options.limit).fill(base),6000),options,now)};
  });
  assert.equal(result.signals.length,1000);assert.equal(result.total_count,6000);assert.equal(result.complete,false);
});
test('missing evidence stays absent and invalid rows advance the cursor safely',()=>{
  const result=forecastPage(input([{...base,player:undefined},base],200),request(),now);
  assert.equal(result.signals.length,1);assert.equal(result.invalid_signals,1);
  assert.equal(result.pagination.next_offset,2);
  const empty=forecastPage({...input([]),metadata:null},request(),now);
  assert.equal(empty.generated_at,null);assert.equal(empty.pagination.complete,true);
});

test('verified research survives a later timeout or temporary failure without claiming completeness',async()=>{
  for(const failure of [409,429,503,'timeout']) {
    let calls=0;
    const result=await fetchForecasts('nfl',undefined,'library',async(url)=>{
      if(calls++>0) {
        if(failure==='timeout') throw new DOMException('Timed out','TimeoutError');
        return {ok:false,status:failure};
      }
      const options=forecastRequest(new URL(url,'https://example.test'));
      return {ok:true,json:async()=>forecastPage(input(Array(100).fill(base),240),options,now)};
    });
    assert.equal(result.signals.length,100);assert.equal(result.total_count,240);
    assert.equal(result.complete,false);assert.equal(calls,2);
  }
});

test('explicit continuation loads the remaining verified revision without repeating the first page',async()=>{
  const values=Array.from({length:240},(_,i)=>({...base,id:String(i)})),offsets=[];
  const fetchImpl=async(url)=>{
    const options=forecastRequest(new URL(url,'https://example.test'));offsets.push(options.offset);
    return {ok:true,json:async()=>forecastPage(input(values.slice(options.offset,options.offset+options.limit),240),options,now)};
  };
  const first=await fetchForecasts('nfl',undefined,'library',fetchImpl,100);
  assert.equal(first.signals.length,100);assert.equal(first.cursor.offset,100);assert.equal(first.complete,false);
  const remaining=await fetchForecasts('nfl',undefined,'library',fetchImpl,1000,first.cursor);
  assert.equal(remaining.signals.length,140);assert.equal(remaining.cursor,null);assert.equal(remaining.complete,true);
  assert.equal(new Set([...first.signals,...remaining.signals].map(s=>s.id)).size,240);
  assert.deepEqual(offsets,[0,100,200]);
  await assert.rejects(fetchForecasts('nfl',undefined,'library',async()=>({ok:false,status:409}),1000,first.cursor),/unavailable/);
  await assert.rejects(fetchForecasts('nfl',undefined,'library',async()=>({ok:true,json:async()=>({...metadata,signals:[base]})}),1000,first.cursor),/coverage/);
  for(const cursor of [{...first.cursor,offset:0},{...first.cursor,offset:1000},
    {...first.cursor,revision:'invalid'},{...first.cursor,total_count:99}]) {
    await assert.rejects(fetchForecasts('nfl',undefined,'library',fetchImpl,1000,cursor),/cursor/);
  }
  await assert.rejects(fetchForecasts('nfl',undefined,'qualified',fetchImpl,1000,first.cursor),/cursor/);
});

test('initial failures, cancellation and inconsistent coverage cannot become a usable partial response',async()=>{
  await assert.rejects(fetchForecasts('nfl',undefined,'library',async()=>({ok:false,status:503})),/unavailable/);
  let calls=0;
  await assert.rejects(fetchForecasts('nfl',undefined,'library',async(url)=>{
    if(calls++>0) throw new DOMException('Cancelled','AbortError');
    const options=forecastRequest(new URL(url,'https://example.test'));
    return {ok:true,json:async()=>forecastPage(input(Array(100).fill(base),240),options,now)};
  }),{name:'AbortError'});
  for(const failure of ['total','cursor']) {
    calls=0;
    await assert.rejects(fetchForecasts('nfl',undefined,'library',async(url)=>{
      const options=forecastRequest(new URL(url,'https://example.test'));
      const body=forecastPage(input(Array(100).fill(base),240),options,now);
      if(calls++>0) {if(failure==='total') body.total_count=241;else body.pagination.next_offset=0;}
      return {ok:true,json:async()=>body};
    }),/coverage|cursor/);
  }
  const options=forecastRequest(new URL('https://example.test/api/signals?sport=nfl&view=qualified'));
  const result=await fetchForecasts('nfl',undefined,'qualified',async()=>({ok:true,json:async()=>forecastPage(input([base],5002),options,now)}));
  assert.deepEqual(result.signals,[]);assert.equal(result.complete,false);
});
