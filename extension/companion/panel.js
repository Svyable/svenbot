'use strict';
// All runtime assets are packaged with the extension. No remote JS, analytics
// or browser actions beyond the single user-initiated activeTab read.
const HOST = 'http://127.0.0.1:8767';
let page = null;
let secondPage = null;
let sessionToken = '';
let paired = false;
let controller = null;

const byId = name => document.getElementById(name);
function status(text, id = 'analysis-status') { byId(id).textContent = text; }
function refresh() {
  byId('ask').disabled = !page || !paired || !!controller;
  byId('find').disabled = !page || !!controller;
  byId('capture-compare').disabled = !page || !!controller;
  byId('compare-offline').disabled = !page || !secondPage || !!controller;
  byId('compare-online').disabled = !page || !secondPage || !paired || !!controller;
}
function clearAnalysis() {
  byId('answer-card').hidden = true;
  byId('answer').textContent = '';
  byId('sources').hidden = true;
  byId('source-items').replaceChildren();
  status('');
}
function setPage(next) {
  page = next;
  setSecondPage(null);
  clearAnalysis();
  byId('page-preview').hidden = !next;
  if (next) {
    const lines = next.blocks.map(b => `${b.id} · ${b.text}`);
    byId('page-preview').textContent = `${next.page_label}\n${next.title}\n\n${lines.join('\n\n')}`;
    status(`${next.blocks.length} visible text blocks · ${next.total_characters} characters. Review the preview before sending.`, 'page-status');
  } else {
    byId('page-preview').textContent = '';
    status('No page selected.', 'page-status');
  }
  refresh();
}

function setSecondPage(next) {
  secondPage = next;
  clearAnalysis();
  byId('compare-preview').hidden = !next;
  if (next) {
    byId('compare-preview').textContent = `${next.page_label}\n${next.title}\n\n` +
      next.blocks.map(b => `${b.id} · ${b.text}`).join('\n\n');
    status(`Second page: ${next.blocks.length} visible text blocks. Review before sending.`, 'compare-status');
  } else {
    byId('compare-preview').textContent = '';
    status('No second page selected.', 'compare-status');
  }
  refresh();
}

async function readCurrentTab() {
  const active = await chrome.tabs.query({active: true, currentWindow: true});
  const tab = active[0];
  if (!tab?.id || !/^https?:\/\//i.test(tab.url || '')) {
    throw new Error('Select a normal http(s) page and click the Svenbot toolbar icon again.');
  }
  const result = await chrome.scripting.executeScript({
    target: {tabId: tab.id}, func: extractVisiblePage
  });
  const current = result?.[0]?.result;
  if (!current?.blocks?.length) throw new Error('No eligible visible text on this page. Protected pages and forms are not readable.');
  // A tab may have changed during the read; never silently use stale content.
  const latest = await chrome.tabs.get(tab.id);
  if (latest.url !== tab.url) throw new Error('Tab navigated during capture; click Read again.');
  return current;
}

async function connect() {
  const proposed = byId('token').value.trim();
  if (!proposed) { status('Paste the token printed by svenbot bridge.'); return; }
  // This permission is requested only from the user interaction.
  const allowed = await chrome.permissions.request({origins: ['http://127.0.0.1/*']});
  if (!allowed) throw new Error('Localhost access was not granted.');
  const response = await fetch(`${HOST}/v1/extension/status`, {
    headers: {'X-Svenbot-Token': proposed}, cache:'no-store', redirect:'error'
  });
  if (!response.ok) throw new Error('Bridge refused pairing. Check extension ID and current token.');
  const data = await response.json();
  if (data.connected !== true) throw new Error('Local bridge returned an unexpected response.');
  sessionToken = proposed;
  paired = true;
  await chrome.storage.session.set({pairingToken: proposed});
  byId('token').value = '';
  const inference = data.inference?.status || 'unverified';
  const readable = ({model_listed:'model listed', models_present_unverified:'models detected',
    model_not_listed:'model not listed', no_models:'no models',
    endpoint_reachable:'endpoint reachable', endpoint_unavailable:'model server offline'})[inference] || 'not checked';
  byId('pair-label').textContent = `Paired · ${readable}`;
  byId('pairing').open = false;
  status(`Paired with Svenbot. ${readable}. This is a read-only endpoint check, not proof of successful inference; no page text was sent.`);
  refresh();
}

function presentSources(refs) {
  const root = byId('source-items');
  root.replaceChildren();
  for (const source of refs) {
    const card = document.createElement('div'); card.className = 'source-item';
    const label = document.createElement('div'); label.className = 'source-label';
    label.textContent = `[source ${root.childElementCount + 1}] · ${source.page ? `Page ${source.page} · ` : ""}${source.block_id} · block ${source.page_block_number}`;
    const excerpt = document.createElement('p'); excerpt.textContent = source.text;
    card.append(label, excerpt); root.append(card);
  }
  byId('sources').hidden = refs.length === 0;
}

function findSourcesOffline() {
  if (!page || controller) return;
  const question = byId('question').value.trim();
  clearAnalysis();
  if (!question) { status('Enter search terms in the Question box first.'); return; }
  const hits = matchPageEvidence(page, question);
  byId('answer').textContent = hits.length
    ? `Found ${hits.length} matching captured passage(s). No AI or network was used. These are lexical matches, not verified answers.`
    : 'No matching captured passages. This is a text match, not a judgment that the page lacks an answer.';
  byId('backend').textContent = 'offline · exact text';
  byId('answer-card').hidden = false;
  presentSources(hits.map(h => ({block_id:h.id, text:h.text, page_block_number:h.position+1})));
  status('Offline source lookup complete. Page text has not left this extension.');
}

function compareSourcesOffline() {
  if (!page || !secondPage || controller) return;
  clearAnalysis();
  const pairs = comparePageEvidence(page, secondPage);
  const refs = [];
  for (const pair of pairs) {
    refs.push({page:'A', block_id:pair.left.id, text:pair.left.text,
      page_block_number:pair.left.position + 1});
    refs.push({page:'B', block_id:pair.right.id, text:pair.right.text,
      page_block_number:pair.right.position + 1});
  }
  byId('answer').textContent = pairs.length ?
    `Found ${pairs.length} pair(s) sharing vocabulary across two explicitly captured pages. ` +
    `Terms include: ${[...new Set(pairs.flatMap(p => p.common))].slice(0, 20).join(', ')}. ` +
    'These matches do not establish agreement, contradiction or truth. No AI or network used.' :
    'No substantial shared vocabulary found among the captured passages. This does not prove the pages are unrelated.';
  byId('backend').textContent = 'offline · lexical crosscheck';
  byId('answer-card').hidden = false;
  presentSources(refs);
  status('Offline crosscheck complete. Neither page was transmitted.');
}

async function disconnect() {
  if (controller) controller.abort();
  paired = false; sessionToken = '';
  await chrome.storage.session.remove('pairingToken');
  try { await chrome.permissions.remove({origins:['http://127.0.0.1/*']}); }
  catch (_) { /* Revocation may be unavailable; the session token is gone. */ }
  byId('token').value = '';
  byId('pair-label').textContent = 'Not connected';
  byId('pairing').open = true;
  clearAnalysis();
  status('Disconnected. Session pairing token forgotten; reconnect to use a local model.');
  refresh();
}

async function runModelRequest(route, payload) {
  if (!paired || controller) return;
  clearAnalysis();
  const current = new AbortController();
  controller = current;
  refresh();
  status(route === 'compare' ? 'Comparing two excerpts sets on your local model…' :
    'Analyzing selected excerpts on your local model…');
  const timeout = setTimeout(() => current.abort(), 180_000);
  try {
    const response = await fetch(`${HOST}/v1/extension/${route}`, {
      method:'POST', cache:'no-store', redirect:'error', signal:current.signal,
      headers:{'Content-Type':'application/json', 'X-Svenbot-Token':sessionToken},
      body:JSON.stringify(payload)
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `Local bridge returned HTTP ${response.status}`);
    }
    const data = await response.json();
    if (current.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
    byId('answer').textContent = data.answer || '(No response)';
    byId('backend').textContent = data.backend || 'local';
    byId('answer-card').hidden = false;
    presentSources(data.references || []);
    status('Complete · Source excerpts are exact captured text, not verification of model claims.');
  } catch (e) {
    status(e?.name === 'AbortError' ? 'Cancelled or timed out. No result saved.' :
      `Unable to analyze: ${e.message}`);
  } finally {
    clearTimeout(timeout);
    if (controller === current) controller = null;
    refresh();
  }
}

async function analyze(event) {
  event.preventDefault();
  const question = byId('question').value.trim();
  if (!page || !question || !paired || controller) return;
  return runModelRequest('analyze', {question, page:{title:page.title, blocks:page.blocks}});
}

async function compareWithModel() {
  if (!page || !secondPage || !paired || controller) return;
  const question = byId('question').value.trim() ||
    'Compare the supported findings, disagreements, and missing evidence.';
  return runModelRequest('compare', {question, pages:[
    {title:page.title,blocks:page.blocks},
    {title:secondPage.title,blocks:secondPage.blocks}
  ]});
}

async function bootstrap() {
  byId('extid').textContent = chrome.runtime.id;
  byId('capture').addEventListener('click', async () => {
    if (controller) controller.abort();
    status('Reading the selected page…', 'page-status');
    try { setPage(await readCurrentTab()); }
    catch (e) { setPage(null); status(e.message, 'page-status'); }
  });
  byId('connect').addEventListener('click', async () => {
    try { await connect(); } catch (e) { paired=false;sessionToken='';refresh();status(e.message); }
  });
  byId('find').addEventListener('click', findSourcesOffline);
  byId('capture-compare').addEventListener('click', async () => {
    if (!page || controller) return;
    status('Reading second selected page…', 'compare-status');
    try { setSecondPage(await readCurrentTab()); }
    catch(e) { setSecondPage(null); status(e.message, 'compare-status'); }
  });
  byId('compare-offline').addEventListener('click', compareSourcesOffline);
  byId('compare-online').addEventListener('click', compareWithModel);
  byId('disconnect').addEventListener('click', () => {
    disconnect().catch(e => status(`Could not complete disconnect: ${e.message}`));
  });
  byId('copy-id').addEventListener('click', () => navigator.clipboard.writeText(chrome.runtime.id));
  byId('copy-answer').addEventListener('click', () => navigator.clipboard.writeText(byId('answer').textContent));
  byId('ask-form').addEventListener('submit', analyze);
  byId('clear').addEventListener('click', () => {
    if (controller) controller.abort();
    setPage(null);byId('question').value='';
  });
  document.querySelectorAll('[data-question]').forEach(node => node.addEventListener('click', () => {
    byId('question').value = node.dataset.question;
    byId('question').focus();
  }));
  const previous = await chrome.storage.session.get('pairingToken');
  if (previous.pairingToken) {
    byId('token').value=previous.pairingToken;
    // No silent server call: user must explicitly reconnect.
    status('Previous session pairing is available. Click Connect to verify it.');
  }
  refresh();
}
bootstrap().catch(e => status(`Initialization failed: ${e.message}`));
