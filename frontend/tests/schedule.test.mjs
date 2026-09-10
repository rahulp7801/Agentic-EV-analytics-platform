import test from 'node:test';
import assert from 'node:assert/strict';
import { GET } from '../app/api/games/route.ts';

test('NFL schedule requests use football endpoint and numeric dates', async t => {
  const requested=[];
  t.mock.method(globalThis,'fetch',async url => {
    requested.push(url);
    return Response.json({events:[{date:'2026-09-10T20:00:00Z',competitions:[{competitors:[
      {homeAway:'home',team:{abbreviation:'H',displayName:'Home'}},
      {homeAway:'away',team:{abbreviation:'A',displayName:'Away'}}
    ]}]}]});
  });
  const response=await GET(new Request('http://localhost/api/games?sport=nfl'));
  assert.equal(response.status,200);
  assert.equal((await response.json()).games.length,3);
  assert.ok(requested.every(url => /football\/nfl\/scoreboard\?dates=\d{8}$/.test(url)));
});

test('upstream failures cannot masquerade as an empty valid schedule', async t => {
  t.mock.method(globalThis,'fetch',async () => new Response('',{status:503}));
  const response=await GET(new Request('http://localhost/api/games?sport=nfl'));
  assert.equal(response.status,503);
  assert.equal((await response.json()).partial,true);
  assert.equal((await GET(new Request('http://localhost/api/games?sport=bad'))).status,400);
});
