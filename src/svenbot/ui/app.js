'use strict';
// This UI deliberately has no analytics, remote assets or browser storage.
const $ = id => document.getElementById(id);
const form = $('prompt-form'), input = $('prompt'), sendButton = $('send');
const stopButton = $('stop'), log = $('messages'), welcome = $('welcome');
const scroller = $('scroll-region'), runtime = $('runtime-label');
let history = [], busy = false, aborter = null;

function adjustHeight() {
  input.style.height = '0px';
  input.style.height = Math.min(input.scrollHeight, 200) + 'px';
}
function setBusy(active) {
  busy = active;
  sendButton.disabled = active;
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
  if (busy || !prompt.trim()) return;
  if (!knowledgePanel.classList.contains('hidden')) showKnowledge(false);
  const text = prompt.trim();
  input.value = ''; adjustHeight();
  welcome.classList.add('hidden');
  addMessage('user', text);
  const output = addMessage('assistant');
  let responseText = '', backend = '', finished = false;
  aborter = new AbortController(); setBusy(true);
  try {
    const conversation = [...history.slice(-30), {role: 'user', content: text}];
    const response = await fetch('/v1/chat/completions', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      credentials: 'omit', signal: aborter.signal,
      body: JSON.stringify({model: 'svenbot', stream: true, messages: conversation})
    });
    if (!response.ok) throw Error(response.status === 503 ? 'No local inference engine is ready. Check svenbot doctor.' : 'Request rejected (' + response.status + ').');
    await consumeStream(response, packet => {
      backend = packet.svenbot_backend || backend;
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
