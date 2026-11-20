'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {matchPageEvidence} = require('../page-tools.js');
const page = {blocks:[
  {id:'B1',text:'The results of the experiment were inconclusive.'},
  {id:'B2',text:'Privacy controls should protect personal data.'},
  {id:'B3',text:'Experiment results were not independently verified.'},
  {id:'B4',text:'This experiment was run on five devices.'}
]};
test('offline evidence selects matching exact page text deterministically',()=>{
  const hits = matchPageEvidence(page,'experiment results');
  assert.deepEqual(hits.map(h=>h.id),['B1','B3','B4']);
  assert.equal(hits[0].text,page.blocks[0].text);
  assert.equal(hits[0].position,0);
});
test('unsupported queries have no invented evidence or generic fallback',()=>{
  assert.deepEqual(matchPageEvidence(page,'nebula zebras'),[]);
  assert.deepEqual(matchPageEvidence(page,'what about the'),[]);
  assert.deepEqual(matchPageEvidence(page,'experiment',0),[]);
});
test('bad and malformed blocks are skipped without execution',()=>{
  assert.deepEqual(matchPageEvidence({blocks:[null, {id:'B1', text:'privacy policy data'}]},'privacy').map(h=>h.id),['B1']);
});
