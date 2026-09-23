import test from 'node:test';
import assert from 'node:assert/strict';
import {researchPlayerPreview} from '../lib/bestPicks.ts';
test('player previews retain the displayed watchlist side instead of the last opposite line',()=>{
 const best={id:'best',sport:'nfl',player:'Austin Hooper',direction:'over',line:0.5};
 const opposite={...best,id:'opposite',direction:'under'};
 const other={...best,id:'other',player:'Christian Watson'};
 const input=[best,opposite,other];
 assert.deepEqual(researchPlayerPreview(input),[best,other]);
 assert.deepEqual(input,[best,opposite,other]);
 assert.deepEqual(researchPlayerPreview(input,1),[best]);
 assert.deepEqual(researchPlayerPreview([]),[]);
});
