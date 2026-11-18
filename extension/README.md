# Svenbot Companion — read-only Chrome side panel (alpha)

A working, optional Manifest V3 side panel for Chrome/Chromium browsers. Click **Read selected tab**, review **all** captured excerpts, optionally pair with a local Svenbot model, and ask questions about the selected page. The extension never sends a page anywhere just because the panel opens.

**This is a local-hosted-model extension, not yet model inference inside WebGPU.** The source-reading interface works with no model. AI answers require a locally running Ollama/llama.cpp-compatible model and the narrow bridge service below. There is no automatic weight download, arbitrary browser click, browser-history scraping, or ChatGPT/PM DOM automation. The WebGPU/browser-native open-weight model experiment remains in [issue #16](https://github.com/Svyable/svenbot/issues/16).

## Install (developer/alpha)

1. Install Svenbot from this checkout: `python -m pip install -e .` (or install the matching wheel). Install and start Ollama with a model that fits your machine, e.g. `ollama pull llama3.2`. No models are downloaded by the extension.
2. Use `python extension/build.py` to create `dist/svenbot-companion-alpha.zip`, then unzip it. Alternatively, Chrome can load `extension/companion` directly.
3. In `chrome://extensions`, turn on **Developer mode** and **Load unpacked** from that extracted directory. Pin **Svenbot Companion**. Open it on an ordinary webpage by clicking the toolbar icon.
4. Expand **Pair with Svenbot** and copy its 32-letter extension ID (also visible in `chrome://extensions`). In a terminal, run:

   ```sh
   svenbot bridge --extension-id YOUR_32_LETTER_ID --backend ollama --model llama3.2
   ```

   The bridge binds to **127.0.0.1:8767**, denies remote endpoints, and prints a new high-entropy pairing token for that process. Copy/paste the token into the side panel and click **Connect**. Chrome then asks for optional access to localhost. Never share the token or use a remote browser for this pairing. Pairing is session-only; restarting the bridge requires a new token.
5. On the target webpage, click **Read selected tab**, review the source preview, choose a question, then **Analyze with local model**. The panel shows model output and the exact excerpts passed to it. **Citations are excerpts, not independent correctness checks.**

To try an OpenAI-compatible **local** server instead, use `--backend openai --model local --openai-url http://127.0.0.1:8080`. Neither mode exposes Svenbot's general web-chat endpoint to extension pages.

## Privacy and capabilities

- **Only explicit active-tab reads:** `activeTab` + `scripting`, not `<all_urls>`, `tabs` history, clipboard read, downloads or cookie permissions. Chrome may refuse injection on internal/restricted pages; open an ordinary http(s) page. Click the extension's toolbar icon on the new tab to grant fresh access.
- **User review before transmission:** the DOM reader extracts only formatted visible text from headings, paragraphs, list items, blockquotes, code/preformatted blocks and cells; excludes form controls, hidden elements, editable fields, scripts, frames, nav and footer, up to 60 blocks / ~29K characters. The preview shows all blocks in a scrollable area. Untrusted page content can still contain secrets visibly rendered as ordinary text. Review before clicking Analyze.
- **Origin-only metadata:** the bridge receives a document title and selected text blocks; the URL is shown inside Chrome but not sent. The query string, URL fragment, cookie headers and browser storage are never extracted. Browsers may display sensitive data as ordinary text; this is not a formal DLP guarantee.
- **Pairing:** optional host permission is requested on Connect; the bridge requires a matching `chrome-extension://<ID>` Origin, exact loopback Host, constant-time session token comparison, strict JSON shape and bounded request. The token lives in `chrome.storage.session`, not the page. Chrome extensions have access to the token only within their extension context; the bridge is not a multi-user auth service. Any local process with access to the terminal/session can potentially read it.
- **No silent remote calls:** the bridge refuses `--allow-remote`, workspace DB or chat session; the model must be served at loopback. External Ollama/llama.cpp logging and model internals are outside the extension's control. The bridge creates fresh in-memory task context and writes no prompts, pages or answers to disk.
- **No browser mutation:** no click, form fill, submission, scraping across tabs, browser network tool, shell, filesystem or MCP capability is exposed. Page strings are untrusted reference data. Browser UI renders all returned text using `textContent`, never `innerHTML`.
- **Session lifetime:** closing/restarting the browser or bridge requires re-pairing. The extension saves only the pairing token in Chrome *session* storage, not model answers, browsing history or page extracts.

## Developer checks

```sh
python -m unittest discover -s tests -v
node --check extension/companion/background.js
node --check extension/companion/reader.js
node --check extension/companion/panel.js
node --test extension/companion/tests/*.cjs
python extension/build.py --output dist/svenbot-companion-alpha.zip
```

The Python bridge tests use a real localhost HTTP server and mocked local-model replies; JavaScript tests exercise extraction contracts. These **do not prove** browser-extension end-to-end compatibility with all Chrome versions or live local-model quality. The sandbox Chromium in development did not expose a loaded extension service worker, so manual testing with an actual Chrome extension install is an outstanding release gate.

## Next experiments

1. First-party, bundled Transformers.js/WebLLM WebGPU runtime with explicit open-weight model download and memory budget. No remote executable JavaScript.
2. Compare browser-only small model with paired Qwen3.5 4B/9B or other approved local models on 20 independent pages, including long, contradictory and adversarial documents; judge source support separately from response plausibility.
3. Hybrid local document and page comparison, verified quotes, job receipts and Mission Control; no action-taking or wider permissions until explicit approval gates exist.

This is an experimental developer extension. Do not publish a Chrome Web Store listing or claim production certification without real Chrome/Edge testing, security review, accessibility evaluation and Chrome Web Store policy review.
