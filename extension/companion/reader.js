/* Injected only on explicit user request through chrome.scripting.executeScript.
   This function is intentionally self-contained because Chrome serializes it. */
function extractVisiblePage() {
  'use strict';
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'FORM', 'INPUT',
    'TEXTAREA', 'SELECT', 'OPTION', 'BUTTON', 'IFRAME', 'OBJECT', 'EMBED',
    'SVG', 'CANVAS', 'NAV', 'FOOTER', 'HEADER']);
  const selectors = 'h1,h2,h3,h4,p,li,blockquote,pre,td,th';
  const root = document.querySelector('article, main, [role="main"]') || document.body;
  const elements = root.querySelectorAll(selectors);
  const blocks = [];
  const seen = new Set();
  let total = 0;
  let checked = 0;
  for (const el of elements) {
    if (++checked > 4000 || blocks.length >= 60 || total >= 27000) break;
    let excluded = false;
    for (let p = el; p && p !== document.documentElement; p = p.parentElement) {
      if (SKIP.has(p.tagName) || p.getAttribute('aria-hidden') === 'true' ||
          p.hasAttribute('hidden') || p.hasAttribute('inert') ||
          p.isContentEditable || p.getAttribute('contenteditable') === 'true' ||
          p.getAttribute('type') === 'password') {
        excluded = true;
        break;
      }
      const style = window.getComputedStyle(p);
      if (style.display === 'none' || style.visibility === 'hidden' ||
          style.visibility === 'collapse') {
        excluded = true;
        break;
      }
    }
    if (excluded) continue;
    // innerText respects CSS text visibility. Do not read input values,
    // attributes, links, hidden tags, scripts or frame contents.
    const raw = typeof el.innerText === 'string' ? el.innerText : '';
    const text = raw.replace(/\s+/g, ' ').trim().slice(0, 800);
    if (text.length < 25 || seen.has(text)) continue;
    seen.add(text);
    if (total + text.length > 29000) break;
    blocks.push({id: `B${blocks.length + 1}`, text});
    total += text.length;
  }
  return {
    title: (document.title || '').replace(/[\x00-\x1f]/g, ' ').slice(0, 200),
    blocks,
    total_characters: total,
    // This is shown locally but never transmitted to the bridge.
    page_label: location.origin + location.pathname
  };
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {extractVisiblePage};
}
