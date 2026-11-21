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

const {comparePageEvidence} = require('../page-tools.js');
test('offline comparison links exact distinct passages with shared lexical terms',()=>{
  const a={blocks:[
    {id:'B1',text:'The experiment showed significantly improved performance over baseline.'},
    {id:'B2',text:'The weather was clear during the summer.'}]};
  const b={blocks:[
    {id:'B1',text:'Experiment results did not show improved performance in trials.'},
    {id:'B2',text:'A famous artist painted a coastal landscape.'}]};
  const pairs=comparePageEvidence(a,b);
  assert.equal(pairs.length,1);
  assert.equal(pairs[0].left.text,a.blocks[0].text);
  assert.equal(pairs[0].right.text,b.blocks[0].text);
  assert.equal(pairs[0].left.id,'B1');
  assert.equal(pairs[0].right.id,'B1');
  assert.ok(pairs[0].common.includes('experiment'));
  assert.ok(pairs[0].similarity>0);
});

test('no invented comparison or generic overlap for unrelated excerpts',()=>{
  const a={blocks:[{id:'B1',text:'Winter rainfall measured in northern forests.'}]};
  const b={blocks:[{id:'B1',text:'Satellite images captured tropical shorelines.'}]};
  assert.deepEqual(comparePageEvidence(a,b),[]);
  assert.deepEqual(comparePageEvidence(a,{blocks:[]}),[]);
  assert.deepEqual(comparePageEvidence(a,b,0),[]);
  assert.deepEqual(comparePageEvidence(a,b,100),[]);
  assert.deepEqual(comparePageEvidence({blocks:[null,{id:'B1',text:'a'}]},b),[]);
});

test('compare respects bounds, never interprets text as markup or instructions',()=>{
  const a={blocks:[{id:'B1',text:'Comparison token should not execute <script>alert(1)</script>.'}]};
  const b={blocks:[{id:'B3',text:'Comparison token remains untrusted quoted HTML only.'}]};
  const results=comparePageEvidence(a,b);
  assert.equal(results.length,1);
  assert.equal(results[0].left.text,a.blocks[0].text);
  assert.equal(results[0].right.text,b.blocks[0].text);
  assert.equal(results[0].common.includes('comparison'),true);
});
