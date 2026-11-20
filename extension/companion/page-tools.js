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
if (typeof module !== 'undefined' && module.exports) module.exports = {matchPageEvidence};
