## New in Chrome Companion 0.1.4 — Page Atlas

**Long-form research and snapshot receipts.** On pages with more than 60 qualifying text blocks, the reader now samples through the entire inspected page, including late conclusions and distributed headings, instead of silently reading only the introduction. The capture status identifies sampled/clipped text. The snapshot receipt is a reproducible SHA-256 fingerprint of the **normalized text captured at that moment**, title and displayed origin/path; it is not a digital signature from the website and does not prove that an AI claim is supported. Use **Copy receipt** to retain it deliberately; nothing is stored or uploaded automatically. Page B gets a separate status fingerprint. The reader also filters nested ARIA-hidden/form/editable/CSS-invisible text and rejects source references that do not exactly match the current snapshots.

This remains a **bounded excerpt sampler**, not an exhaustive document reader; evidence can still be missed. Capturing visually readable text may expose confidential information, so review both previews before allowing optional model analysis. No extension permissions were added. A real Chromium **synthetic DOM** smoke test is available with `python extension/reader_dom_e2e.py` if Python Playwright and local Chromium are installed. It is not proof that the actual unpacked extension works on unmanaged Chrome. Native Gemini Nano and fully bundled open-weight WebGPU are separate architectures.

# Svenbot Companion — read-only Chrome side panel (alpha)

An experimental Manifest V3 side panel for Chrome/Chromium browsers. Click **Read selected tab**, review **all** captured excerpts, optionally pair with a local Svenbot model, and ask questions about the selected page. The extension never sends a page anywhere just because the panel opens. With no model, **Find exact passages · Offline** matches words against the captured excerpts right in the side panel, with no network activity or AI generation. It is a search, not an AI answer.

**There are now three separate modes.** (1) Lexical source lookup runs offline with no model, (2) **Chrome built-in Prompt API** can optionally run browser-managed Gemini Nano on eligible devices without a Python/Ollama server, and (3) a token-paired local bridge uses already-installed Ollama/llama.cpp-compatible models. Chrome's Gemini Nano is NOT open-weight and its download is managed by Chrome; first-party WebGPU open-weight inference remains unimplemented. The browser model has not been validated on real eligible hardware in this managed environment. There is no automatic weight download, arbitrary browser click, browser-history scraping, or ChatGPT/PM DOM automation. The WebGPU/browser-native open-weight model experiment remains in [issue #16](https://github.com/Svyable/svenbot/issues/16).

## Install (developer/alpha)

1. Install Svenbot from this checkout: `python -m pip install -e .` (or install the matching wheel). Install and start Ollama with a model that fits your machine, e.g. `ollama pull llama3.2`. No models are downloaded by the extension. You can use offline passage search and, if Chrome supports it, browser-managed AI without Ollama/Python.
2. Use `python extension/build.py` to create `dist/svenbot-companion-alpha.zip`, then unzip it. Alternatively, Chrome can load `extension/companion` directly.
3. In `chrome://extensions`, turn on **Developer mode** and **Load unpacked** from that extracted directory. Pin **Svenbot Companion**. Open it on an ordinary webpage by clicking the toolbar icon.
4. **Optional Chrome AI without a bridge:** On an eligible desktop Chrome version, press **Read selected tab**, then **Check Chrome AI availability** (read-only). If supported, press **Enable Chrome AI** to consent to any required Chrome-managed model download, with progress shown. Then **Analyze Page A in Chrome** or capture a second page and **Compare A + B in Chrome**. No page text is sent to the bridge in this mode. Chrome may download weights; do not click Enable if you do not want that. Gemini Nano is a proprietary-weight browser component, not an open-weight model.
5. **Optional paired Svenbot backend:** Expand **Pair with Svenbot** and copy its 32-letter extension ID (also visible in `chrome://extensions`). In a terminal, run:

   ```sh
   svenbot bridge --extension-id YOUR_32_LETTER_ID --backend ollama --model llama3.2
   ```

   The bridge binds to **127.0.0.1:8767**, denies remote endpoints, and prints a new high-entropy pairing token for that process. Copy/paste the token into the side panel and click **Connect**. Chrome then asks for optional access to localhost. Never share the token or use a remote browser for this pairing. Pairing is session-only; restarting the bridge requires a new token. The panel distinguishes **paired** from **model listed**, **endpoint reachable**, and **model server offline**. The status is only a read-only endpoint/inventory check, **not** a test response generated by the model. You can click **Disconnect & forget pairing** to clear the session token and request removal of optional localhost permission.
6. On the target webpage, click **Read selected tab**, review the source preview, choose a question, then **Analyze with local model**. The panel shows model output and the exact excerpts passed to it. Or enter search terms and click **Find exact passages · Offline** for a fast, entirely on-device source lookup with no model. **Citations are excerpts, not independent correctness checks.**

To try an OpenAI-compatible **local** server instead, use `--backend openai --model local --openai-url http://127.0.0.1:8080`. Neither mode exposes Svenbot's general web-chat endpoint to extension pages.


## Compare two selected webpages (v0.1.2)

1. On the first article, click the extension toolbar icon, open the side panel and choose **Read selected tab**. Review the first preview.
2. Navigate to or select the second ordinary webpage, click the extension toolbar icon **on that page** to grant fresh `activeTab` access, then choose **Read second selected tab**. Review the second preview. Each click reads only the currently active tab; no other tab is enumerated or crawled.
3. Choose **Crosscheck passages · Offline** to see shared-vocabulary pairs and verbatim snippets labelled **Page A** and **Page B**. This runs without Python, Ollama, WebGPU or network traffic. It does **not** establish that claims agree, contradict or are true. If no pairs appear, that also says nothing about semantic relatedness.
4. Optionally start your already-installed local Ollama/llama.cpp model and pair the bridge, then choose **Compare with local AI**. The extension sends both user-reviewed text captures and the optional question to a separate, authenticated loopback `/v1/extension/compare` endpoint; the URL/path, cookies and query parameters are *not* forwarded. Results show exact separately labelled source snippets but do not independently verify model claims.
5. **Clear captured pages + answer** discards both in-memory snapshots; closing the panel also discards them. There is no saved history or cross-tab monitoring. Changing Page A clears the previous Page B to prevent accidentally comparing different sessions.

The paired comparison endpoint limits requests to 128,000 bytes and independently enforces each captured page's text/structure bounds. Pages may still contain sensitive visible text; inspect both previews before submitting either to a local model. Local model servers may log requests independently.

Developer smoke: `python extension/mock_compare_e2e.py` tests browser controls using mocked extension APIs and a fake model reply. This is **not** a real unpacked extension or a real model benchmark.

## Privacy and capabilities

- **Only explicit active-tab reads:** `activeTab` + `scripting`, not `<all_urls>`, `tabs` history, clipboard read, downloads or cookie permissions. Chrome may refuse injection on internal/restricted pages; open an ordinary http(s) page. Click the extension's toolbar icon on the new tab to grant fresh access.
- **User review before transmission:** the DOM reader extracts only formatted visible text from headings, paragraphs, list items, blockquotes, code/preformatted blocks and cells; excludes form controls, hidden elements, editable fields, scripts, frames, nav and footer, up to 60 blocks / ~29K characters. The preview shows all blocks in a scrollable area. Untrusted page content can still contain secrets visibly rendered as ordinary text. Review before clicking Analyze.
- **Origin-only metadata:** the bridge receives a document title and selected text blocks; the URL is shown inside Chrome but not sent. The query string, URL fragment, cookie headers and browser storage are never extracted. Browsers may display sensitive data as ordinary text; this is not a formal DLP guarantee.
- **Pairing:** optional host permission is requested on Connect; the bridge requires a matching `chrome-extension://<ID>` Origin, exact loopback Host, constant-time session token comparison, strict JSON shape and bounded request. The token lives in `chrome.storage.session`, not the page. Chrome extensions have access to the token only within their extension context; the bridge is not a multi-user auth service. Any local process with access to the terminal/session can potentially read it.
- **No silent remote calls:** the bridge refuses `--allow-remote`, workspace DB or chat session; the model must be served at loopback. External Ollama/llama.cpp logging and model internals are outside the extension's control. The bridge creates fresh in-memory task context and writes no prompts, pages or answers to disk.
- **No browser mutation:** no click, form fill, submission, scraping across tabs, browser network tool, shell, filesystem or MCP capability is exposed. Page strings are untrusted reference data. Browser UI renders all returned text using `textContent`, never `innerHTML`.
- **Local inference readiness:** an authenticated, explicit Connect makes a *read-only* probe to the configured local runtime's model inventory. Ollama's `/api/tags` verifies a matching installed model name when possible; a compatible server's `/v1/models` verifies only endpoint reachability. Only actually running Analyze tests a real completion. Pairing never downloads models or runs prompts.
- **Session lifetime:** closing/restarting the browser or bridge requires re-pairing. The extension saves only the pairing token in Chrome *session* storage, not model answers, browsing history or page extracts.

## Developer checks

```sh
python -m unittest discover -s tests -v
node --check extension/companion/background.js
node --check extension/companion/reader.js
node --check extension/companion/page-tools.js
node --check extension/companion/browser-ai.js
node --check extension/companion/panel.js
node --test extension/companion/tests/*.cjs
python extension/build.py --output dist/svenbot-companion-alpha.zip
```

The browser-native adapter tests mock Chrome's `LanguageModel` API, and the UI tests simulate Chrome events; **they do not demonstrate real Gemini Nano inference**. The Python bridge tests use a real localhost HTTP server and mocked local-model replies; JavaScript tests exercise extraction contracts. These **do not prove** browser-extension end-to-end compatibility with all Chrome versions or live local-model quality. The sandbox Chromium in development did not expose a loaded extension service worker, so manual testing with an actual Chrome extension install is an outstanding release gate.


## Is it actually working? Real-Chrome acceptance test

**Verified by automated tests:** the Python 3.10/3.13 bridge and the unmocked Engine reach *protocol-compatible* Ollama/OpenAI fixture servers over real localhost HTTP, including authentication and source propagation; the JavaScript source matching/extraction tests and mock Chromium DOM flow pass. **Not yet verified:** a real installed Chrome extension invoking a live locally downloaded model. A managed browser on the development host enforces `ExtensionInstallBlocklist: ["*"]` and `URLBlocklist: ["*"]`, so it cannot serve as a real extension test machine; do not bypass that administrator policy.

To conduct a legitimate acceptance test on **your own, unmanaged Chrome/Edge installation**:

1. On an ordinary public article you control or trust, load the unpacked extension and use **Read selected tab**. Confirm the entire excerpt preview contains only information you intend to analyze; the URL query/fragment is omitted.
2. With Ollama/Python still stopped, type a distinctive term and click **Find exact passages · Offline**. Verify exact text is returned, an absent term returns *no matches*, and your browser makes no page-content request to a remote API.
3. Start an already-installed local model (`ollama list`, `ollama serve` if not running, and if needed `ollama pull llama3.2` **only with your consent**). Run `svenbot bridge --extension-id YOUR_ID --backend ollama --model llama3.2` in a separate terminal. Pair with the printed token. Verify the panel says **Paired · model listed**; if not, check the reported state.
4. Press **Analyze with local model**. A real-model test is successful only if a non-empty response appears, the backend is labelled, excerpts match your preview, and the local Ollama process logs a request (not merely a successful Connect).
5. Click **Disconnect & forget pairing**, verify the UI says disconnected and Analyze disables; then refresh Chrome/restart the bridge and verify the old pairing token no longer authorizes.
6. Record Chrome version, OS, extension ID prefix (not token), model and quantization, first-token/total response times, screenshots with private material removed, and failure states. Repeat on Chrome/Edge and macOS/Windows/Linux before recommending consumer release.

For an optional **mock UI-only** test (not an installed extension): `python extension/mock_ui_e2e.py` requires Python Playwright plus a local Chromium binary. It never requires an inference model and is not a substitute for step 4.

## Next experiments

1. Actual open-weight inference: first-party, bundled Transformers.js/WebLLM WebGPU runtime with explicit open-weight model download and memory budget. No remote executable JavaScript.
2. Compare browser-only small model with paired Qwen3.5 4B/9B or other approved local models on 20 independent pages, including long, contradictory and adversarial documents; judge source support separately from response plausibility.
3. Hybrid local document and page comparison, verified quotes, job receipts and Mission Control; no action-taking or wider permissions until explicit approval gates exist.

On eligible Chrome hardware, test the built-in AI mode separately: check availability without installing, explicitly enable and observe model download, capture a page, generate a non-empty answer, verify Page A/B excerpts, cancel mid-generation, restart Chrome, and confirm no localhost network request. Hardware needs vary; Chrome documents Windows/macOS/Linux desktop and free storage/GPU or RAM requirements at https://developer.chrome.com/docs/ai/prompt-api. This end-to-end hardware gate remains **unverified**.

This is an experimental developer extension. Do not publish a Chrome Web Store listing or claim production certification without real Chrome/Edge testing, security review, accessibility evaluation and Chrome Web Store policy review.
