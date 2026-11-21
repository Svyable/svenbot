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
if (typeof module !== 'undefined' && module.exports) module.exports = {matchPageEvidence, comparePageEvidence};
