import test from 'node:test';
import assert from 'node:assert/strict';
import { GET } from '../app/api/games/route.ts';

test('NFL schedule requests use football endpoint and numeric dates', async t => {
  const requested=[];
  t.mock.method(globalThis,'fetch',async url => {
    requested.push(url);
    const date=new URL(url).searchParams.get('dates');
    const day=`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}`;
    return Response.json({events:[{id:date,date:day+'T20:00:00Z',competitions:[{status:{type:{completed:false}},competitors:[
      {homeAway:'home',team:{abbreviation:'H',displayName:'Home'}},
      {homeAway:'away',team:{abbreviation:'A',displayName:'Away'}}
    ]}]}]});
  });
  const response=await GET(new Request('http://localhost/api/games?sport=nfl'));
  assert.equal(response.status,200);
  assert.equal((await response.json()).games.length,3);
  assert.ok(requested.every(url => /cdn\.espn\.com\/core\/nfl\/scoreboard\?xhr=1&limit=100&dates=\d{8}$/.test(url)));
});

test('CDN scoreboard envelopes are validated before fixtures are exposed', async t => {
  t.mock.method(globalThis,'fetch',async ()=>Response.json({content:{sbData:{events:[]}}}));
  const response=await GET(new Request('http://localhost/api/games?sport=nfl'));
  assert.equal(response.status,200);
  assert.deepEqual((await response.json()).games,[]);
});

test('hosted snapshot lookup failures recover from validated public scoreboard responses',async t=>{
  const previous=process.env.VERCEL;process.env.VERCEL='1';
  t.after(()=>{if(previous===undefined)delete process.env.VERCEL;else process.env.VERCEL=previous;});
  t.mock.method(globalThis,'fetch',async ()=>Response.json({events:[]}));
  const response=await GET(new Request('http://localhost/api/games?sport=nfl'));
  assert.equal(response.status,200);
  assert.equal((await response.json()).partial,false);
});

test('one unavailable date remains partial and all requested dates are needed for complete coverage',async t=>{
  let calls=0;
  t.mock.method(globalThis,'fetch',async ()=>++calls===1 ? new Response('',{status:503}) : Response.json({events:[]}));
  const response=await GET(new Request('http://localhost/api/games?sport=nfl'));
  assert.equal(response.status,200);
  assert.equal((await response.json()).partial,true);
  assert.equal(calls,3);
});

test('malformed, redirected, or oversized provider data cannot become healthy coverage',async t=>{
  for(const response of [Response.json({events:[{}]}),Response.json({events:'missing'}),new Response('',{status:302}),
    new Response('{"events":[]}',{headers:{'content-length':String(3*1024*1024)}})]) {
    t.mock.method(globalThis,'fetch',async ()=>response.clone());
    assert.equal((await GET(new Request('http://localhost/api/games?sport=nfl'))).status,503);
    t.mock.restoreAll();
  }
});

test('upstream failures cannot masquerade as an empty valid schedule', async t => {
  t.mock.method(globalThis,'fetch',async () => new Response('',{status:503}));
  const response=await GET(new Request('http://localhost/api/games?sport=nfl'));
  assert.equal(response.status,503);
  assert.equal((await response.json()).partial,true);
  assert.equal((await GET(new Request('http://localhost/api/games?sport=bad'))).status,400);
});
