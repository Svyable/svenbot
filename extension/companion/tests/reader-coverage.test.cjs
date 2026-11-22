'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {extractVisiblePage} = require('../reader.js');
const {fingerprintPage, filterCaptureReferences} = require('../page-tools.js');

function node(text, attrs={}, parent=null) {
  return {tagName:attrs.tagName || 'P', innerText:text, parentElement:parent,
    isContentEditable:!!attrs.editable,
    getAttribute(k) {return attrs[k] ?? null;},
    hasAttribute(k) {return Object.prototype.hasOwnProperty.call(attrs,k);}};
}
function page(items) {
  delete global.document;
  delete global.NodeFilter;
  global.window={getComputedStyle(el) {return {display:el.getAttribute('display')||'block',
    visibility:el.getAttribute('visibility')||'visible',
    contentVisibility:el.getAttribute('contentVisibility')||'visible'};}};
  const parent=node('',{tagName:'DIV'});
  global.document={title:'Local report',documentElement:node('',{tagName:'HTML'}),
    querySelector:()=>null,body:{querySelectorAll:()=>items.map(x=>x(parent))}};
  global.location={origin:'https://example.test',pathname:'/private/report',search:'?token=must-not-leak'};
}

test('samples late conclusions from long page instead of dropping the tail',()=>{
  page(Array.from({length:250},(_,i)=>p=>node(
    i === 249 ? 'Final independent conclusion: the downstream trial was inconclusive and requires replication.' :
      `Paragraph ${i} explains methodology and evaluation with distinct study number ${i}.`,
    i % 17 === 0 ? {tagName:'H2'} : {},p)));
  const capture=extractVisiblePage();
  assert.equal(capture.blocks.length,60);
  assert.equal(capture.capture.eligible,250);
  assert.equal(capture.capture.sampled,true);
  assert.ok(capture.blocks.some(b=>b.text.includes('downstream trial was inconclusive')));
  assert.ok(capture.blocks.some(b=>b.text.includes('Paragraph 0')));
  assert.ok(capture.blocks.some(b=>/Paragraph (9[0-9]|10[0-9])\b/.test(b.text))); 
  assert.ok(capture.total_characters<=29000);
  assert.equal(capture.blocks[0].id,'B1');
  assert.equal(capture.blocks.at(-1).id,'B60');
  assert.doesNotMatch(JSON.stringify(capture),/must-not-leak/);
});

test('fair character allocation preserves a conclusion when many blocks are long',()=>{
  page(Array.from({length:90},(_,i)=>p=>node(
    `Observation ${i} `+'measurement '.repeat(75)+(i===89?'closing caveat about confidence':'control'),{},p)));
  const capture=extractVisiblePage();
  assert.equal(capture.blocks.length,60);
  assert.ok(capture.capture.clipped>0);
  assert.ok(capture.total_characters<=29000);
  assert.ok(capture.blocks.at(-1).text.startsWith('Observation 89'));
  assert.ok(capture.blocks.every(x=>x.text.length<=800));
});

test('closed disclosures, inert regions, CSS hidden elements and short headings are handled',()=>{
  page([
    p=>node('Methodology',{tagName:'H2'},p),
    p=>node('This article compares evidence from many independent sources.',{},p),
    p=>node('Sensitive hidden information should never appear.',{},node('',{tagName:'DETAILS'},p)),
    p=>node('Security token that cannot be inspected.',{contentVisibility:'hidden'},p),
    p=>node('An inert dashboard should not expose its private values.',{},node('',{inert:''},p)),
    p=>node('The final analysis explicitly describes study limitations.',{},p)
  ]);
  const capture=extractVisiblePage();
  assert.equal(capture.blocks.length,3);
  assert.equal(capture.blocks[0].text,'Methodology');
  assert.doesNotMatch(JSON.stringify(capture),/Security token|Sensitive hidden|inert dashboard/);
});

test('real DOM-style text walker excludes aria-hidden and nested form text',()=>{
  const parent=node('',{tagName:'MAIN'});
  const visible=node('This visible text supports a limited public conclusion.',{},parent);
  const hidden=node('',{'aria-hidden':'true',tagName:'SPAN'},visible);
  const editable=node('',{editable:true,tagName:'SPAN'},visible);
  const form=node('',{tagName:'FORM'},visible);
  page([()=>visible]);
  global.NodeFilter={SHOW_TEXT:4};
  global.document.createTreeWalker=()=>{
    const parts=[
      {nodeValue:'This visible text supports a limited public conclusion.',parentElement:visible},
      {nodeValue:' HIDDEN ACCESS KEY abcdefghijkl',parentElement:hidden},
      {nodeValue:' SECRET DRAFT',parentElement:editable},
      {nodeValue:' PASSWORD FORM VALUE',parentElement:form}
    ]; let i=0;
    return {nextNode:()=>parts[i++]||null};
  };
  const capture=extractVisiblePage();
  assert.equal(capture.blocks.length,1);
  assert.equal(capture.blocks[0].text,'This visible text supports a limited public conclusion.');
  assert.doesNotMatch(JSON.stringify(capture),/ACCESS KEY|SECRET DRAFT|PASSWORD/);
});

test('capture fingerprint is reproducible and detects any changed excerpt or page identity',async()=>{
  page([p=>node('A public observation with enough context to be meaningful.',{},p)]);
  const capture=extractVisiblePage();
  const first=await fingerprintPage(capture);
  assert.match(first,/^[a-f0-9]{64}$/);
  assert.equal(first,await fingerprintPage(structuredClone(capture)));
  const edited=structuredClone(capture);
  edited.blocks[0].text+=' Not in original.';
  assert.notEqual(first,await fingerprintPage(edited));
  edited.blocks[0].text=capture.blocks[0].text;
  edited.page_label='https://example.test/another';
  assert.notEqual(first,await fingerprintPage(edited));
});

test('citations are shown as exact captures only; altered quote, position, or page rejected',()=>{
  const first={blocks:[{id:'B1',text:'The first page has verifiable text.'}]};
  const second={blocks:[{id:'B1',text:'The second page is distinctly different.'}]};
  const goodA={page:'A',block_id:'B1',page_block_number:1,text:first.blocks[0].text};
  const goodB={page:'B',block_id:'B1',page_block_number:1,text:second.blocks[0].text};
  const altered={...goodA,text:'A fabricated exact quote.'};
  const wrongPage={...goodB,page:'A'};
  const badPosition={...goodA,page_block_number:2};
  const r=filterCaptureReferences([goodA,goodB,altered,wrongPage,badPosition],first,second);
  assert.deepEqual(r.valid,[goodA,goodB]);
  assert.equal(r.rejected.length,3);
  assert.equal(filterCaptureReferences([goodB],first).valid.length,0);
});
