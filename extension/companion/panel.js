'use strict';
// All runtime assets are packaged with the extension. No remote JS, analytics
// or browser actions beyond the single user-initiated activeTab read.
const HOST = 'http://127.0.0.1:8767';
let page = null;
let sessionToken = '';
let paired = false;
let controller = null;

const byId = name => document.getElementById(name);
function status(text, id = 'analysis-status') { byId(id).textContent = text; }
function refresh() { byId('ask').disabled = !page || !paired || !!controller; }
function clearAnalysis() {
  byId('answer-card').hidden = true;
  byId('answer').textContent = '';
  byId('sources').hidden = true;
  byId('source-items').replaceChildren();
  status('');
}
function setPage(next) {
  page = next;
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
  byId('pair-label').textContent = `Connected · ${data.backend}`;
  byId('pairing').open = false;
  status('Paired with local Svenbot. No data has been transmitted yet.');
  refresh();
}

async function analyze(event) {
  event.preventDefault();
  const question = byId('question').value.trim();
  if (!page || !paired || !question || controller) return;
  clearAnalysis();
  controller = new AbortController();
  refresh();
  status('Analyzing selected excerpts on your local model…');
  const timeout = setTimeout(() => controller?.abort(), 180_000);
  try {
    const response = await fetch(`${HOST}/v1/extension/analyze`, {
      method:'POST', cache:'no-store', redirect:'error', signal:controller.signal,
      headers:{'Content-Type':'application/json', 'X-Svenbot-Token':sessionToken},
      body:JSON.stringify({question, page:{title:page.title, blocks:page.blocks}})
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `Local bridge returned HTTP ${response.status}`);
    }
    const data = await response.json();
    byId('answer').textContent = data.answer || '(No response)';
    byId('backend').textContent = data.backend || 'local';
    byId('answer-card').hidden = false;
    const root = byId('source-items');
    root.replaceChildren();
    for (const source of (data.references || [])) {
      const card = document.createElement('div');card.className='source-item';
      const label = document.createElement('div');label.className='source-label';
      label.textContent = `[source ${root.childElementCount + 1}] · ${source.block_id} · page block ${source.page_block_number}`;
      const excerpt = document.createElement('p'); excerpt.textContent = source.text;
      card.append(label,excerpt);root.append(card);
    }
    byId('sources').hidden = !data.references?.length;
    status('Complete · Excerpts are exact captured text, not verification of model claims.');
  } catch (e) {
    status(e?.name === 'AbortError' ? 'Cancelled or timed out. No result saved.' :
      `Unable to analyze: ${e.message}`);
  } finally {
    clearTimeout(timeout); controller = null; refresh();
  }
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
