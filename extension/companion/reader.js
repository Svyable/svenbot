/* Injected only after a user gesture through chrome.scripting.executeScript.
   This function is self-contained because Chrome serializes its source. */
function extractVisiblePage() {
  'use strict';
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'FORM', 'INPUT',
    'TEXTAREA', 'SELECT', 'OPTION', 'BUTTON', 'IFRAME', 'OBJECT', 'EMBED',
    'SVG', 'CANVAS', 'NAV', 'FOOTER', 'HEADER', 'TEMPLATE']);
  const MAX_INSPECT = 4000, MAX_BLOCKS = 60, MAX_TOTAL = 29000, MAX_BLOCK = 800;
  const root = document.querySelector('article, main, [role="main"]') || document.body;
  const elements = root.querySelectorAll('h1,h2,h3,h4,p,li,blockquote,pre,td,th');
  const visibility = new WeakMap();

  // Check every ancestor: a visible paragraph can contain hidden/aria-hidden
  // child spans that innerText would otherwise include. Never read form values.
  function suppressed(el) {
    if (!el || el === document.documentElement) return false;
    if (visibility.has(el)) return visibility.get(el);
    const hidden = SKIP.has(el.tagName) || el.getAttribute('aria-hidden') === 'true' ||
      el.hasAttribute('hidden') || el.hasAttribute('inert') || el.isContentEditable ||
      el.getAttribute('contenteditable') === 'true' ||
      el.getAttribute('type') === 'password' ||
      (el.tagName === 'DETAILS' && !el.hasAttribute('open'));
    let result = hidden;
    if (!result) {
      const style = window.getComputedStyle(el);
      result = style.display === 'none' || style.visibility === 'hidden' ||
        style.visibility === 'collapse' || style.contentVisibility === 'hidden';
    }
    if (!result) result = suppressed(el.parentElement);
    visibility.set(el, result);
    return result;
  }

  function safeText(el) {
    // Real browsers: walk only visible text nodes, excluding nested aria-hidden
    // spans (which CSS innerText alone does not hide). The Node mock uses
    // innerText as a compatibility fallback; this fallback is never used in
    // Chrome, where createTreeWalker and NodeFilter always exist.
    if (typeof document.createTreeWalker !== 'function' ||
        typeof NodeFilter === 'undefined') return el.innerText || '';
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const parts = [];
    let node, inspected = 0, total = 0;
    while ((node = walker.nextNode()) && inspected++ < 1200 && total < 1600) {
      if (suppressed(node.parentElement)) continue;
      const value = node.nodeValue || '';
      parts.push(value);
      total += value.length;
    }
    return parts.join(' ');
  }

  const inspected = Math.min(elements.length, MAX_INSPECT);
  const candidates = [];
  const seen = new Set();
  for (let i = 0; i < inspected; ++i) {
    // Spread the inspection window across very long documents instead of
    // restricting it to the first four thousand elements.
    const index = inspected === elements.length ? i :
      Math.round(i * (elements.length - 1) / Math.max(inspected - 1, 1));
    const el = elements[index];
    if (suppressed(el)) continue;
    const heading = /^H[1-4]$/.test(el.tagName);
    const text = safeText(el).replace(/\s+/g, ' ').trim().slice(0, MAX_BLOCK);
    if (text.length < (heading ? 4 : 25) || seen.has(text)) continue;
    seen.add(text);
    candidates.push({text, heading});
  }

  const n = candidates.length, selected = new Set();
  function add(index) {
    if (index >= 0 && index < n && selected.size < MAX_BLOCKS) selected.add(index);
  }
  if (n <= MAX_BLOCKS) {
    for (let i = 0; i < n; i++) add(i);
  } else {
    for (let i = 0; i < 5; i++) { add(i); add(n - 1 - i); }
    const headings = candidates.map((c, i) => c.heading ? i : -1).filter(i => i >= 0);
    // Reserve a modest portion of the excerpt budget for page structure.
    for (let k = 0; k < Math.min(headings.length, 12); k++) {
      const pos = Math.round(k * (headings.length - 1) /
        Math.max(Math.min(headings.length, 12) - 1, 1));
      add(headings[pos]);
    }
    // Repeatedly bisect the widest unrepresented interval. Filling slots
    // from left to right would bias every capture toward the introduction.
    while (selected.size < MAX_BLOCKS) {
      const sorted = [...selected].sort((a, b) => a - b);
      let largest = 1, gapStart = -1, gapEnd = -1;
      for (let k = 1; k < sorted.length; k++) {
        const gap = sorted[k] - sorted[k - 1];
        if (gap > largest) {largest = gap; gapStart = sorted[k - 1]; gapEnd = sorted[k];}
      }
      if (gapStart < 0) break;
      add(Math.floor((gapStart + gapEnd) / 2));
    }
  }

  const chosen = [...selected].sort((a, b) => a - b).map(i => candidates[i]);
  // Water-fill the bounded char budget fairly across all selected passages.
  // Avoid old behavior that silently dropped the tail after reaching 29K.
  let lo = 0, hi = MAX_BLOCK;
  while (lo < hi) {
    const mid = Math.floor((lo + hi + 1) / 2);
    const chars = chosen.reduce((sum, c) => sum + Math.min(c.text.length, mid), 0);
    if (chars <= MAX_TOTAL) lo = mid;
    else hi = mid - 1;
  }
  let total = 0, clipped = 0;
  const blocks = chosen.map((c, i) => {
    const text = c.text.slice(0, lo);
    if (text.length < c.text.length) clipped++;
    total += text.length;
    return {id: `B${i + 1}`, text};
  });

  return {
    title: (document.title || '').replace(/[\x00-\x1f]/g, ' ').slice(0, 200),
    blocks, total_characters: total,
    // Local only: never included in bridge or inference payloads.
    capture: {elements: elements.length, inspected, eligible: n,
      sampled: n > blocks.length || elements.length > inspected, clipped},
    // Locally displayed; never sent to the model or local bridge.
    page_label: location.origin + location.pathname
  };
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {extractVisiblePage};
}
