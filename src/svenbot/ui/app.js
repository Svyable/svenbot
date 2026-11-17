'use strict';
// This UI deliberately has no analytics, remote assets or browser storage.
const $ = id => document.getElementById(id);
const form = $('prompt-form'), input = $('prompt'), sendButton = $('send');
const stopButton = $('stop'), log = $('messages'), welcome = $('welcome');
const scroller = $('scroll-region'), runtime = $('runtime-label');
let history = [], busy = false, aborter = null;
let documentId = null, documentName = null, documentBusy = false;

function adjustHeight() {
  input.style.height = '0px';
  input.style.height = Math.min(input.scrollHeight, 200) + 'px';
}
function setBusy(active) {
  busy = active;
  sendButton.disabled = active || documentBusy;
  $('document-input').disabled = active || documentBusy;
  $('document-clear').disabled = active || documentBusy;
  stopButton.classList.toggle('hidden', !active);
  $('composer-hint').textContent = active ? 'Generating locally…' : '↵ Send · Shift + ↵ New line';
}
function nearBottom() {
  return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 240;
}
function scrollBottom() { scroller.scrollTop = scroller.scrollHeight; }
function addMessage(role, text = '') {
  const row = document.createElement('article');
  row.className = 'message ' + (role === 'user' ? 'user' : 'assistant');
  const header = document.createElement('div');
  header.className = 'message-header';
  header.textContent = role === 'user' ? 'You' : 'Svenbot';
  const content = document.createElement('div');
  content.className = 'message-content';
  content.textContent = text; // never render model HTML
  const meta = document.createElement('div');
  meta.className = 'message-meta';
  row.append(header, content, meta);
  if (role === 'assistant') row.classList.add('pending');
  log.append(row);
  scrollBottom();
  return {row, content, meta};
}
function completeMessage(node, text, backend) {
  node.row.classList.remove('pending');
  if (backend) node.meta.textContent = '↳ ' + backend + ' · local engine';
  const action = document.createElement('div');
  action.className = 'message-actions';
  const copy = document.createElement('button');
  copy.className = 'copy'; copy.type = 'button'; copy.textContent = 'Copy response';
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(text); copy.textContent = 'Copied'; }
    catch { copy.textContent = 'Copy unavailable'; }
  });
  action.append(copy); node.row.append(action);
}
function parseFrame(frame) {
  const lines = frame.split('\n');
  const event = lines.find(line => line.startsWith('event:'));
  const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
  return {kind: event ? event.slice(6).trim() : 'message', data};
}
async function consumeStream(response, onData) {
  if (!response.body) throw Error('Streaming response body unavailable');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', finished = false;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true}).replace(/\r\n/g, '\n');
      if (buffer.length > 5_000_000) throw Error('Stream exceeded the safety limit');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const {kind, data} = parseFrame(frame);
        if (kind === 'error') throw Error('The local model stopped before completing. Partial answer not saved.');
        if (data === '[DONE]') { finished = true; break; }
        if (data) onData(JSON.parse(data));
      }
      if (finished) break;
    }
    if (!finished) throw Error('Local model connection closed before completion.');
  } finally { reader.releaseLock(); }
}
// Browser file bytes go only to Svenbot's own loopback endpoint. No browser
// persistence, FormData boundary parsing, CDN, or background directory crawl.
function encodeDocument(bytes) {
  const parts = [];
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    parts.push(String.fromCharCode(...bytes.subarray(offset, offset + 8192)));
  }
  return btoa(parts.join(''));
}
function documentStatus(text) { $('document-status').textContent = text; }
async function forgetTemporaryDocument(token) {
  try {
    await fetch('/v1/local/document/clear', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      credentials: 'omit', body: JSON.stringify({document_id: token})
    });
  } catch { /* The server's bounded TTL also expires abandoned handles. */ }
}
async function detachDocument() {
  if (documentBusy) return;
  const token = documentId;
  documentId = null; documentName = null;
  history = []; log.replaceChildren();
  $('document-clear').classList.add('hidden');
  documentStatus('No document attached · max 1 MB · memory only');
  if (token) await forgetTemporaryDocument(token);
}
async function attachDocument(file) {
  if (!file || busy || documentBusy) return;
  const supported = /\.(pdf|docx|html?|csv|tsv)$/i;
  if (!supported.test(file.name) || file.size < 1 || file.size > 1_000_000) {
    documentStatus('Select a supported document between 1 byte and 1 MB.');
    return;
  }
  documentBusy = true; setBusy(busy);
  documentStatus('Reading document locally…');
  try {
    const raw = new Uint8Array(await file.arrayBuffer());
    const response = await fetch('/v1/local/document', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      credentials: 'omit',
      body: JSON.stringify({filename: file.name, content_base64: encodeDocument(raw)})
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Document could not be attached.');
    const previous = documentId;
    documentId = result.document_id; documentName = result.name;
    history = []; log.replaceChildren(); welcome.classList.remove('hidden');
    $('document-clear').classList.remove('hidden');
    documentStatus(`${result.name} · ${result.characters.toLocaleString()} text characters · expires in 20 min`);
    if (previous) await forgetTemporaryDocument(previous);
  } catch (error) {
    documentStatus(error.message || 'Document could not be attached.');
  } finally {
    documentBusy = false; $('document-input').value = ''; setBusy(busy);
  }
}
$('document-input').addEventListener('change', event => attachDocument(event.target.files?.[0]));
$('document-clear').addEventListener('click', () => detachDocument());
const dropzone = $('document-dropzone');
dropzone.addEventListener('dragover', event => {
  if (event.dataTransfer?.types?.includes('Files')) {
    event.preventDefault(); dropzone.classList.add('dragover');
  }
});
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', event => {
  event.preventDefault(); dropzone.classList.remove('dragover');
  attachDocument(event.dataTransfer?.files?.[0]);
});
const knowledgePanel = $('knowledge-panel');
function showKnowledge(visible) {
  knowledgePanel.classList.toggle('hidden', !visible);
  log.classList.toggle('hidden', visible);
  welcome.classList.toggle('hidden', visible || log.childElementCount > 0);
  $('knowledge-nav').classList.toggle('selected', visible);
  $('chat-nav').classList.toggle('selected', !visible);
  $('knowledge-nav').setAttribute('aria-expanded', String(visible));
  $('knowledge-top').setAttribute('aria-expanded', String(visible));
  $('chat-nav').setAttribute('aria-current', visible ? 'false' : 'page');
  if (visible) { loadKnowledge(); $('knowledge-query').focus(); }
  else input.focus();
}
async function loadKnowledge() {
  const status = $('knowledge-status');
  status.textContent = 'Loading indexed files…';
  $('knowledge-files').replaceChildren();
  try {
    const response = await fetch('/v1/local/library', {credentials: 'omit'});
    if (!response.ok) throw Error(response.status === 409 ?
      'Enable --workspace when starting svenbot web to use the knowledge library.' : 'Unable to load the local index.');
    const result = await response.json();
    const files = result.files || [];
    status.textContent = `${files.length} indexed file(s) available, up to 500 listed.`;
    for (const file of files) {
      const li = document.createElement('li');
      li.textContent = file.path;
      const meta = document.createElement('small');
      meta.textContent = `${file.chunks} excerpts`;
      li.append(meta); $('knowledge-files').append(li);
    }
  } catch (error) { status.textContent = error.message; }
}
$('knowledge-nav').addEventListener('click', () => showKnowledge(true));
$('chat-nav').addEventListener('click', () => showKnowledge(false));
$('knowledge-top').addEventListener('click', () => showKnowledge(knowledgePanel.classList.contains('hidden')));
$('knowledge-form').addEventListener('submit', async event => {
  event.preventDefault();
  const query = $('knowledge-query').value.trim();
  if (!query) return;
  const status = $('knowledge-status'), results = $('knowledge-results');
  status.textContent = 'Searching local knowledge…'; results.replaceChildren();
  try {
    const response = await fetch('/v1/local/search', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'omit',
      body: JSON.stringify({query})
    });
    if (!response.ok) throw Error('Local search was unavailable (' + response.status + ').');
    const data = await response.json();
    status.textContent = data.results.length ? `${data.results.length} matched excerpt(s).` : 'No matching excerpts.';
    for (const item of data.results) {
      const article = document.createElement('article'); article.className = 'knowledge-hit';
      const title = document.createElement('strong');
      title.textContent = `${item.path}:${item.line}-${item.end_line || item.line}`;
      const body = document.createElement('pre'); body.textContent = item.excerpt;
      article.append(title, body); results.append(article);
    }
  } catch (error) { status.textContent = error.message; }
});
async function submit(prompt) {
  if (busy || documentBusy || !prompt.trim()) return;
  if (!knowledgePanel.classList.contains('hidden')) showKnowledge(false);
  const text = prompt.trim();
  input.value = ''; adjustHeight();
  welcome.classList.add('hidden');
  addMessage('user', text);
  const output = addMessage('assistant');
  let responseText = '', backend = '', finished = false, citations = []; 
  aborter = new AbortController(); setBusy(true);
  try {
    const conversation = [...history.slice(-30), {role: 'user', content: text}];
    const response = await fetch('/v1/chat/completions', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      credentials: 'omit', signal: aborter.signal,
      body: JSON.stringify({model: 'svenbot', stream: true, messages: conversation,
                            ...(documentId ? {document_id: documentId} : {})})
    });
    if (!response.ok) {
      if (response.status === 404 && documentId) {
        documentId = null; documentName = null;
        $('document-clear').classList.add('hidden');
        documentStatus('Document expired or cleared. Attach it again to ask questions.');
      }
      throw Error(response.status === 503 ? 'No local inference engine is ready. Check svenbot doctor.' : 'Request rejected (' + response.status + ').');
    }
    await consumeStream(response, packet => {
      backend = packet.svenbot_backend || backend;
      if (Array.isArray(packet.svenbot_sources)) citations = packet.svenbot_sources;
      const delta = packet.choices?.[0]?.delta?.content;
      if (typeof delta === 'string') {
        const follow = nearBottom();
        responseText += delta;
        output.content.textContent = responseText;
        if (follow) scrollBottom();
      }
      if (packet.choices?.[0]?.finish_reason === 'stop') finished = true;
    });
    if (!finished) throw Error('Stream ended without completion confirmation.');
    history.push({role: 'user', content: text}, {role: 'assistant', content: responseText});
    history = history.slice(-30);
    completeMessage(output, responseText, backend);
    if (documentId && citations.length) {
      const sources = document.createElement('div');
      sources.className = 'message-sources';
      const label = document.createElement('strong');
      label.textContent = 'Retrieved source excerpts · not independently verified claims';
      sources.append(label);
      for (const [i, item] of citations.entries()) {
        const line = document.createElement('span');
        line.textContent = `[source ${i + 1}] ${item.path}:${item.line}-${item.end_line}`;
        sources.append(line);
      }
      output.row.append(sources);
    }
  } catch (error) {
    output.row.classList.remove('pending'); output.row.classList.add('error');
    const message = error.name === 'AbortError' ? 'Stopped. Partial answer was not saved.' :
      (error instanceof SyntaxError ? 'Malformed response from local engine.' : error.message);
    output.meta.textContent = message;
    if (!responseText) output.content.textContent = 'Unable to finish this response.';
  } finally {
    aborter = null; setBusy(false); input.focus(); scrollBottom();
  }
}
form.addEventListener('submit', event => {event.preventDefault(); submit(input.value);});
input.addEventListener('input', adjustHeight);
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); submit(input.value);
  }
});
stopButton.addEventListener('click', () => aborter?.abort());
$('reset').addEventListener('click', () => {
  aborter?.abort(); history = []; log.replaceChildren(); showKnowledge(false); welcome.classList.remove('hidden');
  detachDocument();
  input.value = ''; adjustHeight(); input.focus();
});
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => submit(button.dataset.prompt)));
fetch('/health', {credentials: 'omit'})
  .then(response => response.ok ? response.json() : Promise.reject())
  .then(info => { runtime.textContent = `${info.backend === 'auto' ? 'Auto route' : info.backend}${info.model ? ' · ' + info.model : ''}`; })
  .catch(() => {runtime.textContent = 'Engine unavailable';});
// Read-only diagnostics; no downloads, background polling, or persistent settings.
fetch('/v1/local/status', {credentials: 'omit'})
  .then(response => response.ok ? response.json() : Promise.reject())
  .then(info => {
    const ready = info.backends?.ollama === 'ready' ||
                  info.backends?.openai === 'ready' || info.pybot_available;
    const setup = $('setup-panel');
    if (!ready) {
      $('setup-title').textContent = 'Your private workspace is ready. Add a local model.';
      $('setup-description').textContent = 'No usable local engine detected yet. Run this read-only check in your terminal to see what is missing. Svenbot never downloads models by itself.';
      $('setup-command').textContent = 'svenbot setup';
      setup.classList.remove('hidden');
    } else if (info.configured_model && info.backends?.ollama === 'ready') {
      // Keep configured model visible, not the advisory alternative.
      runtime.title = 'Configured model: ' + info.configured_model;
    }
  })
  .catch(() => { /* Health/error text already reports connectivity. */ });
input.focus(); adjustHeight();
