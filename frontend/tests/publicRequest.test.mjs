import test from 'node:test';
import assert from 'node:assert/strict';
import {publicRequest} from '../lib/publicRequest.ts';
const request=(path,method='GET',headers={})=>({url:'https://example.test'+path,method,headers:new Headers(headers)});
test('API boundary rejects mutation, ambiguous query values, excess input and foreign browser reads',()=>{
  for(const method of ['POST','PUT','PATCH','DELETE','TRACE','OPTIONS']) assert.equal(publicRequest(request('/api/signals',method)),405);
  assert.equal(publicRequest(request('/api/scan','POST')),403);
  for(const path of ['/api/signals?sport=nfl&sport=nba','/api/signals?cachebuster=1','/api/scans?x=1','/api/gamelogs?player='+ 'a'.repeat(129),'/api/gamelogs?player=a%00b']) assert.equal(publicRequest(request(path)),400);
  assert.equal(publicRequest(request('/api/gamelogs?player='+ 'a'.repeat(2100))),414);
  for(const site of ['cross-site','same-site','invalid']) {
    assert.equal(publicRequest(request('/api/signals','GET',{'sec-fetch-site':site})),403);
  }
  assert.equal(publicRequest(request('/api/signals','GET',{origin:'https://attacker.example'})),403);
  assert.equal(publicRequest(request('/api/signals','GET',{origin:'invalid'})),403);
  assert.equal(publicRequest(request('/api/unknown')),404);
});
test('ordinary API queries and a forged prefetch header still use the same boundary',()=>{
  for(const path of ['/api/signals?sport=nfl&view=qualified','/api/gamelogs?sport=nfl&player=Player&exact=1&before=2026-09-10&limit=40','/api/metrics?cohort=all&sport=nfl','/api/slate?sport=nba','/api/scan']) assert.equal(publicRequest(request(path)),null);
  assert.equal(publicRequest(request('/api/signals?x=1','GET',{'next-router-prefetch':'1'})),400);
  assert.equal(publicRequest(request('/api/scans','GET',{'sec-fetch-site':'same-origin',origin:'https://example.test'})),null);
  assert.equal(publicRequest(request('/terminal?readiness=1')),null);
});
