const {test} = require('node:test');
const assert = require('node:assert/strict');
const {extractVisiblePage} = require('../reader.js');
function node(text, attrs = {}, parent = null) {
  return {tagName: attrs.tagName || 'P', innerText: text,
    parentElement: parent, isContentEditable: !!attrs.editable,
    getAttribute(k) {return attrs[k] || null;},
    hasAttribute(k) {return Object.prototype.hasOwnProperty.call(attrs,k);}};
}
function fakePage(items) {
  global.window = {getComputedStyle(el) {
    return {display: el.getAttribute('display') || 'block',
      visibility: el.getAttribute('visibility') || 'visible'};
  }};
  const parent = node('',{tagName:'DIV'});
  global.document = {
    title:'Example page', documentElement: node('',{tagName:'HTML'}),
    body:{querySelectorAll:()=>items.map(x=>x(parent))},
    querySelector:()=>null
  };
  global.location = {origin:'https://example.com',pathname:'/public',search:'?token=SHOULD_NOT_BE_SENT'};
}

test('captures real text but excludes form, hidden, input and editable content', () => {
  fakePage([
    p=>node('A sufficiently long public description of the experiment.',{},p),
    p=>node('Secret hidden API key: abcdefghij',{display:'none'},p),
    p=>node('Form message contains private account credentials.',{},node('',{tagName:'FORM'},p)),
    p=>node('Editable draft password should not be read.',{editable:true},p),
    p=>node('Hidden aria label with private bank information.',{'aria-hidden':'true'},p),
    p=>node('A second public report with multiple observations.',{},p),
  ]);
  const x=extractVisiblePage();
  assert.equal(x.blocks.length,2);
  assert.equal(x.blocks[0].id,'B1');
  assert.match(x.blocks[1].text,/second public/);
  assert.doesNotMatch(JSON.stringify(x),/abcdef|credentials|password|SHOULD_NOT_BE_SENT/);
  assert.equal(x.page_label,'https://example.com/public');
});

test('strict bounds and deduplication of repeated content', () => {
  fakePage(Array.from({length:300},(v,i)=>p=>node('Article text '.repeat(60)+ (i % 2),{},p)));
  const x=extractVisiblePage();
  assert.equal(x.blocks.length,2);
  assert.ok(x.blocks[0].text.length<=800);
  assert.ok(x.total_characters<=29000);
});
