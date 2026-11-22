/* Tiny, deterministic source lookup. No model, network, browser permissions,
   or page mutation. User-reviewed capture is provided by panel.js. */
'use strict';
const SVENBOT_STOPWORDS = new Set(['the', 'and', 'for', 'with', 'that', 'this', 'from', 'what',
  'which', 'where', 'when', 'were', 'have', 'does', 'into', 'about', 'their', 'there',
  'your', 'you', 'are', 'how', 'why', 'can', 'will', 'would', 'could', 'should']);
function matchPageEvidence(page, query, limit = 5) {
  if (!page || !Array.isArray(page.blocks) || typeof query !== 'string' ||
      !Number.isInteger(limit) || limit < 1 || limit > 10) return [];
  const terms = [...new Set((query.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || [])
    .filter(term => !SVENBOT_STOPWORDS.has(term)))].slice(0, 40);
  if (!terms.length) return [];
  const scores = [];
  page.blocks.slice(0, 60).forEach((b, position) => {
    if (typeof b?.id !== 'string' || typeof b?.text !== 'string') return;
    const words = new Set(b.text.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || []);
    const score = terms.filter(t => words.has(t)).length;
    if (score > 0) scores.push({position, score, id:b.id, text:b.text});
  });
  scores.sort((a,b) => b.score-a.score || a.position-b.position);
  return scores.slice(0, limit);
}
// Read-only lexical *comparison*, not semantic entailment or contradiction
// detection. Never fabricates quotations or silently reads additional tabs.
function comparePageEvidence(first, second, limit = 4) {
  if (!first || !second || !Array.isArray(first.blocks) ||
      !Array.isArray(second.blocks) || !Number.isInteger(limit) ||
      limit < 1 || limit > 10) return [];
  const words = s => new Set((s.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || [])
    .filter(t => !SVENBOT_STOPWORDS.has(t)).slice(0, 130));
  const normalize = p => p.blocks.slice(0, 60).map((block, index) => {
    if (typeof block?.id !== 'string' || typeof block?.text !== 'string' ||
        block.text.length > 800 || block.text.length === 0) return null;
    return {id:block.id, text:block.text, position:index, terms:words(block.text)};
  }).filter(Boolean);
  const left = normalize(first), right = normalize(second);
  const candidates = [];
  for (const a of left) for (const b of right) {
    const common = [...a.terms].filter(word => b.terms.has(word));
    if (common.length < 2) continue;
    const union = a.terms.size + b.terms.size - common.length;
    const similarity = common.length / Math.max(union, 1);
    candidates.push({a, b, common, similarity});
  }
  candidates.sort((x, y) => y.similarity - x.similarity ||
    y.common.length - x.common.length || x.a.position - y.a.position ||
    x.b.position - y.b.position);
  const results = [], usedA = new Set(), usedB = new Set();
  for (const pair of candidates) {
    if (usedA.has(pair.a.position) || usedB.has(pair.b.position)) continue;
    usedA.add(pair.a.position); usedB.add(pair.b.position);
    results.push({left:{id:pair.a.id, text:pair.a.text, position:pair.a.position},
      right:{id:pair.b.id, text:pair.b.text, position:pair.b.position},
      common:pair.common.slice(0, 12), similarity:pair.similarity});
    if (results.length === limit) break;
  }
  return results;
}
// The receipt attests to this in-memory normalized capture, not to the
// website or its authorship. It never leaves the extension automatically.
async function fingerprintPage(page) {
  if (!page || typeof page.title !== 'string' || typeof page.page_label !== 'string' ||
      !Array.isArray(page.blocks) || page.blocks.length > 60 ||
      page.blocks.some(b => typeof b?.id !== 'string' || typeof b?.text !== 'string'))
    throw Error('Cannot fingerprint an invalid capture.');
  if (!globalThis.crypto?.subtle) throw Error('SHA-256 is unavailable.');
  const canonical = JSON.stringify({schema:1, title:page.title,
    page_label:page.page_label, blocks:page.blocks.map(b=>[b.id,b.text])});
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return [...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('');
}

// Provenance guard: the bridge and model output may not claim that an unknown
// source label or altered excerpt is an exact quote of the active snapshot.
// Exact match is NOT semantic support, website authenticity or truth.
function filterCaptureReferences(refs, first, second = null) {
  const valid = [], rejected = [];
  if (!Array.isArray(refs)) return {valid, rejected:[{reason:'Invalid source list'}]};
  for (const ref of refs.slice(0, 20)) {
    const target = ref?.page === 'B' ? second :
      (ref?.page === undefined || ref?.page === 'A' ? first : null);
    const position = target?.blocks?.findIndex(block => block.id === ref?.block_id);
    if (position === undefined || position < 0 ||
        !Number.isInteger(ref?.page_block_number) || ref.page_block_number !== position + 1 ||
        target.blocks[position].text !== ref.text) {
      rejected.push({block_id:ref?.block_id || '(unknown)', reason:'Not an exact current capture match'});
    } else valid.push(ref);
  }
  if (refs.length > 20) rejected.push({reason:'Source list exceeds limit'});
  return {valid, rejected};
}
if (typeof module !== 'undefined' && module.exports) module.exports = {
  matchPageEvidence, comparePageEvidence, fingerprintPage, filterCaptureReferences
};
