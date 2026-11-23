### Model Lab: compare your open-weight local brains (v0.7.6)

Model Lab provides a **reproducible, 20-case synthetic browser research task benchmark** to compare an already-installed smaller Ollama model with Inkling 2 Mini or any supported local OpenAI-compatible model. Scores cover source fidelity, strict JSON schema, read-only tool proposals, simple answer-term checks, and errors/latency. This is **not** a general-intelligence benchmark, real browser automation, or evidence that an 8 GB quantization matches the original on end tasks. The benchmark never downloads models, executes browser tools, persists page text or sends data to a remote host.

```sh
svenbot model-lab --dry-run
svenbot model-lab --model qwen3.5:4b --model inkling-2-mini \
  --limit 4 --output ./model-lab-smoke.json
```

Only include model tags returned by your local `ollama list`, and start with a small smoke run. See [the benchmark guide](docs/benchmarks/model-lab.md) for exact scoring, caveats and full instructions. **Chrome Companion remains v0.1.4**; the model-lab research path runs in the local Python CLI and does not change any browser permission.

### Chrome Companion 0.1.4: Page Atlas (Svenbot 0.7.5)

The optional Chrome side panel now distributes a bounded text capture over long webpages (including late caveats), reports sampling/truncation, fingerprints the normalized in-memory snapshot with SHA-256 and refuses to present mismatched source references as exact quotes. No new browser permissions, cloud requests, stored page text or automatic model downloads are introduced. **A fingerprint does not authenticate the website or prove the model's claims**; source previews still require user review. See [`extension/README.md`](extension/README.md) and [`extension/reader_dom_e2e.py`](extension/reader_dom_e2e.py) for QA. Real installed Chrome/model hardware validation and third-party readability bake-offs are still open.

# Svenbot

**Local AI should mean local.** Your inference, your documents, your hardware, and a clear answer about which engine answered.

Svenbot is an independent, local-first orchestration project inspired by [Hugging Face PyBot](https://github.com/huggingface/pybot). PyBot took a wonderfully strange approach: hundreds of thousands of lines of hand-written/generated Python rules instead of model weights. Svenbot keeps that experiment available as an **optional, pinned upstream submodule**, and adds actual on-device LLM inference, local retrieval, opt-in conversation persistence, and a small local HTTP interface.

It is an **experimental 0.7 beta, not a release-proven Chrome extension or the best local AI assistant**. We intend to earn that through reproducible benchmarks, latency and memory efficiency, extensibility, and safety—not marketing claims.

## Chrome Companion (experimental browser-native AI)

The Chrome side panel now has **three distinct execution paths**. First, *Find exact passages* and the two-page lexical crosscheck operate entirely inside Chrome without models or network. Second, **Chrome on-device AI** optionally uses Chrome's own built-in Prompt API (browser-managed **Gemini Nano, not open weights**) for generative analysis of one or two explicitly reviewed page captures. Third, an optional, token-paired `svenbot bridge` connects the same interface to independently installed open-weight Ollama/llama.cpp models on your computer.

Chrome AI is not automatically enabled: choose **Check Chrome AI availability**, and then **Enable Chrome AI** to explicitly allow Chrome to download its on-device model if needed. Hardware/storage/Chrome-version eligibility varies; if unsupported, offline source lookup and the bridge remain available. Prompt API source citations identify input excerpts, not fact checks, and page content may attempt prompt injection.

**Open-weight WebGPU inference using Transformers.js/WebLLM is still not implemented.** The Prompt API is a real browser-native option on supported Chrome versions, but it does not make Gemini Nano an open-weight model. Automated adapter tests and mocked Chromium interactions **do not establish live hardware model inference**; unmanaged Chrome device validation remains an open release gate.

## Chrome Companion (new alpha)

Svenbot includes an optional **read-only Chrome MV3 side panel**. Choose a tab, inspect extracted visible text, **find exact passages offline without a model**, and optionally analyze selected excerpts with a paired locally served model (Ollama or llama.cpp). Chrome asks for localhost access only when you choose to pair. The pairing view checks only local endpoint inventory and now distinguishes the bridge being paired from a model being listed/reachable. No all-sites permissions, automatic scans, hidden cloud fallbacks or browser actions.

**[Installation, pairing, security and limitations](extension/README.md).** This release does **not** yet run **open-weight** inference inside WebGPU; that is a separately tracked experiment. Chrome extension end-to-end testing on an actual user machine is still needed: the managed Chromium here disables all extensions, so a real unpacked installation cannot be certified from our passing protocol and mock UI tests.

```sh
python extension/build.py
# Load the extracted dist/svenbot-companion-alpha.zip using chrome://extensions
# Copy the displayed extension ID and start a local model bridge:
svenbot bridge --extension-id YOUR_32_LETTER_ID --backend ollama --model llama3.2
```

## Quick start

Python 3.10+; the base installation has no Python runtime dependencies. Text-based PDF parsing is optional.

```bash
git clone --recurse-submodules https://github.com/Svyable/svenbot.git
cd svenbot
python -m pip install -e .

# Ollama must be installed and running separately. Svenbot checks only local endpoints.
svenbot setup
# If no models are installed, explicitly choose and pull a suitable model with Ollama.
# Then Svenbot selects a small-footprint installed model when --model is omitted.
svenbot web --open-browser
# Or use the terminal:
svenbot chat
```

Ollama must be installed separately; it serves models on `127.0.0.1:11434` by default. Svenbot **never pulls models automatically**. If Ollama has locally installed models, v0.5's CLI checks `/api/tags` once at startup and tentatively chooses the smallest known *on-disk footprint* unless you explicitly provide `--model`. This is **not** a benchmark-based quality selection, a guaranteed chat-compatible model, or a RAM/VRAM fit test. You can always choose a specific model. See [read-only first-run diagnostics](#first-run-setup-and-model-discovery-new-in-v05).

With an OpenAI-compatible **local** server such as llama.cpp on port 8080:

```bash
svenbot ask "Explain this error" --backend openai --openai-url http://127.0.0.1:8080 --model local
```

Without any model, use PyBot's original rules engine (large startup import, zero model weights):

```bash
svenbot ask "What is a star?" --backend rules
# If the submodule was not cloned:
git submodule update --init --recursive
```

`--backend auto` (the default) tries Ollama, then the OpenAI-compatible server, then PyBot rules. It reports backend failures rather than making up a reply. `--verbose` prints the selected backend, individual attempted routes with local timings, and sources on stderr. Rule-engine memory lasts for the running process only; it is not recovered from SQLite across restarts.

## First-run setup and model discovery (new in v0.5)

The first-run assistant does not download weights, start daemons, change system settings or upload hardware information. It makes only bounded read-only requests to the inference endpoints you specify (loopback only by default). It reports observed RAM/cgroup limits and locally installed model names. Commands:

```bash
svenbot setup               # Human-readable readiness, model inventory and copyable launch command
svenbot setup --json        # Machine-readable diagnostic snapshot (local names/hardware metadata)
svenbot models              # List Ollama's already-installed models and their disk sizes
svenbot doctor              # Original lightweight reachability checks
svenbot web --open-browser  # Best-effort launch using a tentatively selected installed model
svenbot web --backend ollama --model YOUR_INSTALLED_MODEL
```

When both Ollama and a compatible local server are unavailable, `setup` explains what is missing; the browser shows a helpful local-only setup panel rather than pretending inference works. The app never downloads Ollama or starts its daemon. `--allow-remote` remains an explicit privacy-compromising exception for configured endpoints. Supported metadata originates from [Ollama's List Local Models API](https://docs.ollama.com/api/tags).

**Hardware caveat:** Physical RAM or cgroup limits are not free RAM, GPU VRAM, or an accurate model-serving budget. Ollama's model `size` describes its storage footprint—not exact runtime memory or chat capability. Selecting the smallest installed model is a *low-friction suggestion*, not a certification of fit or quality. Use `svenbot bench` on your actual hardware to compare candidates; choose with `--model` when quality matters.

## Talk to Svenbot in your browser (new in v0.4)

A real, single-command, dependency-free local chat interface is included in the Python package. **No npm, CDN, external fonts, analytics, account, or browser storage.**

```bash
# Start Ollama separately; install a model of your choosing if needed:
svenbot setup
svenbot web --open-browser
# Or pin a known model: svenbot web --backend ollama --model YOUR_MODEL
# Open http://127.0.0.1:8765 in a browser on this computer.
```

The chat streams words as they arrive, shows which backend answered, supports stop/reset/copy, and keeps temporary conversation context only in the open tab. Closing or reloading the page clears it. When running `--backend auto`, any fallback must happen before visible output begins. If a backend fails mid-answer, the partial reply is marked incomplete, no second backend is spliced into it, and that turn is not saved. Browser messages use text-only rendering, never executable model HTML.

For a responsive terminal instead:

```bash
svenbot chat --backend ollama --model llama3.2
svenbot ask "Explain locality" --backend ollama --stream
# Legacy full-response behavior remains available:
svenbot chat --backend ollama --no-stream
```

The existing non-streaming OpenAI-style API still works; callers may now send `"stream": true` to `/v1/chat/completions` for text-only SSE chunks ending with `data: [DONE]`. This is a subset of the API, not full feature parity. The web and API server are **127.0.0.1 only** and unauthenticated: do not port-forward them or put them behind a public proxy. Same-origin browser requests are allowed; cross-origin requests, unexpected Host headers, and non-JSON writes are rejected. Source retrieval requires explicitly indexed workspace files. The UI does not expose `evidence` receipts; use the CLI for verified quotations.

## Temporary browser document Q&A (new in v0.7)

**Attach a document, ask a question, then remove it.** In First Light, choose or drag one `.docx`, `.html`/`.htm`, `.csv`/`.tsv`, or text-based `.pdf` file into the toolbar immediately above the composer. No folder scan, extension or web account is needed.

```bash
# PDF support is optional; Word/HTML/CSV/TSV work without pypdf.
python -m pip install -e '.[documents]'
svenbot web --backend ollama --model YOUR_INSTALLED_MODEL --open-browser
# Attach a file in the browser, ask questions, and click Remove document.
```

This new browser lane is **temporary** and independent of the persistent Knowledge library. A file is deliberately selected in the browser; Svenbot extracts its text on the loopback server and holds it only in process memory. No originals, prompts, or responses are added to SQLite or browser storage by the document workflow. The server enforces **1 MB input**, **180,000 extracted characters**, **four active documents**, and **20-minute fixed expiration** per attachment. `Remove document` revokes its opaque handle and clears the displayed chat; the server also discards expired documents opportunistically. Closing a browser tab does **not** instantly revoke its handle; it expires or is removed explicitly, and Python memory removal is not forensic erasure. Previously sent text may still exist in the separate local model server's memory or logs.

**Grounding:** Each document question builds an isolated, temporary SQLite FTS5 index and chooses up to six relevant text excerpts. For broad questions without lexical matches, it uses initial excerpts instead. The model sees citations and is told to avoid claims unsupported by them; this does **not** prove that its answer is factually correct or logically entailed. The browser lists cited excerpt locations in extracted text, not guaranteed Word page layout. Use `svenbot evidence` and `verify` on an explicitly indexed document for independently validated **exact quotes**. Large documents may be incompletely represented by the selected context.

**Security:** If the Svenbot server is started with `--allow-remote`, browser document upload and document Q&A are **refused**, even for a loopback URL. Restart without that option. The feature never automatically sends files to a remote endpoint, saves them to the library, downloads a model or executes embedded content. Its random handle is a temporary bearer capability, not user authentication; the loopback server remains accessible to other processes on the computer. Do not expose the listener to the public Internet. PDF parsing is best effort and bounded by input/pages/text limits but **is not CPU-time sandboxed**; use trusted files and avoid hostile PDFs until process-level isolation is shipped. Image-only/scanned PDFs need separate OCR and currently fail with an explicit error.

**Compatibility:** v0.6 `ask-file` is still available for terminal-only one-shot private Q&A. v0.7's browser attachment does not yet offer a persistent **Save to library** control: persistent indexing remains an explicit `svenbot index` CLI action, and no attachment is silently saved.

## Work with real documents (new in v0.6)

Svenbot now extracts **Word `.docx`, HTML, CSV/TSV, and text-based PDF** files on your own machine. Word, HTML and CSV/TSV use only the Python standard library. PDFs use the optional local `pypdf` parser; Svenbot does not perform OCR, download parsing services, execute Word macros, evaluate CSV spreadsheet formulas, run embedded scripts, or fetch linked resources.

```bash
# One-time optional PDF parser; not required for Word, HTML, CSV or text.
python -m pip install -e '.[documents]'

# Index only the chosen file/folder, not your whole computer.
svenbot index ~/projects/notes/report.pdf --workspace ~/projects/notes
svenbot index ~/projects/notes/invoices --workspace ~/projects/notes
svenbot library --workspace ~/projects/notes
svenbot search "invoice 4873" --workspace ~/projects/notes

# Q&A about a single file, WITHOUT a persistent index or saved chat:
svenbot ask-file ~/projects/notes/report.docx "What did revenue do?" --backend ollama
# Restrict the source context supplied to the model if needed:
svenbot ask-file ~/projects/notes/report.csv "Which SKU is low?" --max-chunks 6

# Remove precisely one indexed copy, not the original document:
svenbot forget invoices/2026.csv --workspace ~/projects/notes --yes
svenbot library --workspace ~/projects/notes --json
```

**Ephemeral file Q&A:** `ask-file` builds its index in an in-memory SQLite database, selects at most 12 source excerpts, and asks a configured local language model. It does **not** persist the document or chat. A `--backend auto` request attempts Ollama and a local compatible server but deliberately **does not** fall back to PyBot's ungrounded rules. Remote endpoints remain blocked unless you explicitly pass `--allow-remote`. No source files are modified. The answer is still model-generated and may be wrong or hallucinate citations; use the `evidence` and `verify` commands for exact-quote integrity. Long files may exceed the selected excerpt budget.

**Persistent library:** `index` stores plaintext *extracted text* in SQLite and is explicit, workspace-bound, capped at 1,000 files per invocation and limited to 8 MB per document and 1.5 million extracted characters. PDF extraction caps at 100 pages; scanned/image-only or encrypted PDFs aren't supported. `library` lists the first 500 indexed file names, hashes and chunk counts without reading documents again; `forget ... --yes` removes one indexed copy, leaving the original file untouched. Directory re-indexing can add a forgotten file again. Prior indexed documents remain after deleting/moving originals until re-index or purge. **Cited line numbers refer to extracted text rather than original Word/PDF visual line numbers**; extracted PDFs include `[PDF page N]` markers. Review indexed folders for secrets and use disk encryption for sensitive data.

**Browser knowledge panel:** Start `svenbot web --workspace ~/projects/notes` and open **Knowledge**. It lists only previously indexed sources and searches FTS5 excerpts without invoking a model or indexing anything new. The `/v1/local/library` read-only and `/v1/local/search` JSON endpoints require that the server be explicitly launched with `--workspace`; they remain same-origin and localhost only. The Knowledge panel itself never uploads or indexes files; v0.7 adds a **separate temporary attachment** in the chat composer.

## Make your files searchable (explicitly)

No implicit filesystem crawl or background indexing. Choose which local text/code/document files to index:

```bash
svenbot index docs --workspace .
svenbot search "architecture" --workspace .
svenbot ask "Summarize our architecture" --backend ollama --workspace . --verbose
```

The search index lives in SQLite on your machine, under `~/.local/share/svenbot/svenbot.db` by default. Indexing stays within `--workspace`, doesn't follow symlinks, skips common secret filenames and dependency directories, and caps file size and index batch size. Review the chosen folder yourself: automatic filters cannot detect every secret. Retrieved excerpts are marked untrusted and shown to the model as context, never executed as commands. Results are **line-cited, bounded chunks** ranked by local lexical FTS5, **not yet semantic RAG**. Re-indexing a selected directory skips unchanged files and removes deleted files only within that directory; it is not a background watcher. Existing v0.1 SQLite indexes are migrated on first v0.2 use. Index batches are atomic; an over-limit batch rolls back instead of half-pruning. Hidden directories, sensitive filenames, and symlinks are skipped, but automatic filters cannot guarantee a secret-free index. `--workspace` enables retrieval of files you previously indexed with the same workspace and database.

The index contains plaintext copies of each chunk, not links to files on disk. Old text remains searchable until you re-index its directory or purge its workspace. If you need to remove the indexed content **and** persisted chats for a particular workspace:

```bash
svenbot purge --workspace . --yes
```

`purge` deletes SQLite entries for that resolved workspace; it does not erase your source files, independent backups, or guarantee forensic erasure of storage media. Be aware that any SQLite backup might still contain previous data.

Session history is **ephemeral by default**. To opt into SQLite persistence:

```bash
svenbot chat --backend ollama --session my-project --workspace .
```

`/reset` clears the current named session and in-process rules memory. The database is stored locally as plaintext (file mode 0600 on POSIX). Do not store regulated or sensitive material without your own disk encryption and access controls. A `--session` is scoped to the resolved workspace path.

## Reproducible local latency lab (new in v0.2)

```bash
# Only the selected local model is used. No remote judge or download.
svenbot bench --backend ollama --model llama3.2 \
  --prompts benchmarks/smoke.jsonl --runs 5 --warmup 2 \
  --output results/local-llama3.2.json
```

JSONL fixtures contain one object per line: `{"id":"reasoning-01", "category":"reasoning", "prompt":"..."}`. IDs must be unique; prompts are capped at 32,000 characters and 1,000 examples per file. Results record per-prompt **IDs and response latency**, requested route/model, selected backend, error type, sample counts, p50 and p95 wall time, and machine/Python basics. **They intentionally never store raw prompts or model replies.** The report is created mode 0600 on POSIX. Opting into a remote endpoint still requires the explicit `--allow-remote` flag.

This is a *performance harness*, not a scored model-quality evaluation. Latency includes Python routing and HTTP transport, while reported peak RSS covers the Svenbot Python process, **not Ollama or a separate model server**. Report hardware, quantization, concurrency, cold/warm state, and independent accuracy evaluation before claiming a model win. The included smoke dataset tests only that the harness runs; it cannot establish model superiority.

## Proof-carrying extractive evidence (experimental in v0.3)

Normal `ask` and chat remain generative. The new **opt-in** `evidence` lane is different:
its output is only exact quotations from the local indexed snapshot. You can run it entirely
**offline**, or ask a local model to nominate relevant verbatim passages while a deterministic
validator checks all quoted text, source IDs, character offsets, chunk hashes, and line spans.

```bash
svenbot index docs --workspace .
svenbot evidence "How does the cooling system work?" --workspace . \
  --output cooling.evidence.json
svenbot verify cooling.evidence.json --workspace .

# Local model selection is optional and still cannot write an unsupported quote.
svenbot evidence "How does the cooling system work?" --workspace . \
  --selector model --backend ollama --model llama3.2

# Reproducible synthetic adversarial contract checks (no model/network)
svenbot evidence-eval --cases benchmarks/evidence-contract.jsonl
```

This is **provenance verification, not truth verification or natural-language entailment**.
The receipts check against the **current indexed SQLite snapshot**, not live disk contents,
and SHA-256 hashes are **not signatures**. Reindex before checking for stale source files.
An exact source quote may be false or misleading. The optional model can still choose an
irrelevant or malicious quote, but it cannot introduce new words as if they were quoted from a
source in this explicit lane. Receipts contain plaintext source text and should not be
published or committed indiscriminately. Save is opt-in and refuses to overwrite an existing file.
See [the research hypothesis, prior art, threat model, and falsification plan](docs/research/attested-evidence.md). The field already includes established citation and proof-carrying answer research; no claim of scientific priority is made.

## Chrome Companion two-page crosscheck (v0.7.3)

The optional, separately installed Chrome MV3 companion now supports **two user-selected pages** in its side panel. It requires a deliberate `activeTab` capture for each page; `Crosscheck passages · Offline` returns exact pairwise snippets sharing vocabulary with **no model or network traffic**. `Compare with local AI` is optional and uses the existing token-paired, loopback-only `svenbot bridge` through a distinct `/v1/extension/compare` endpoint. Source receipts keep Page A and Page B separate. This is not semantic contradiction detection, fact checking or autonomous browsing; there is no all-sites permission, data persistence or implicit upload. See [`extension/README.md`](extension/README.md) for exact steps, constraints, and real Chrome acceptance tests.

## Local API

```bash
svenbot serve --backend ollama --model llama3.2 --port 8765
curl -s http://127.0.0.1:8765/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"svenbot","messages":[{"role":"user","content":"Hello"}]}'
```

The text-only `/v1/chat/completions` endpoint supports non-streaming responses and bounded SSE streaming; it follows a small subset of the OpenAI schema, plus `GET /health`, `GET /v1/models`, read-only `GET /v1/local/status`, explicitly workspace-scoped knowledge listing/search endpoints, and the opt-in temporary-document endpoints. Models and machine metadata never leave the local status endpoint unless you explicitly reconfigure the server for remote access. API calls are isolated; request histories supplied as user/assistant messages are not persisted. Tools, images, arbitrary system messages, and multi-user authentication **are not implemented**. The listener binds to `127.0.0.1` only, requires JSON requests, accepts only same-origin browser requests and rejects unrecognized `Host` values to reduce DNS rebinding/CSRF exposure, adds no permissive CORS header, and must **not** be publicly exposed or reverse-proxied as an open service. Any local process can still call it; it is not an authenticated multi-user service.

## Design principles

- **No hidden cloud fallback:** only loopback inference endpoints are allowed by default; `--allow-remote` is an explicit, potentially privacy-compromising exception. No built-in telemetry or API keys.
- **Rules, not replacement:** original Hugging Face PyBot stays pinned under `upstream/pybot`, preserving the source and Apache 2.0 attribution. Rules are opt-in or last-resort fallback, not silently confused with LLM-generated answers.
- **Trust boundaries:** no shell execution, no plugin execution, no autonomous tool calls, no implicit file access. Retrieved documents are untrusted input. Models can still be wrong or susceptible to prompt injection.
- **Small core, measurable results:** stdlib-only orchestration, a non-leaking local benchmark runner, and deterministic regression fixtures. Faster or better is a benchmark question, not a slogan.

## Architecture

```text
CLI / localhost API
       |
  Session + Retrieval (opt-in SQLite; workspace-scoped)
       |
  Backend Router  ---> Ollama (local model)
       |            ---> llama.cpp / OpenAI-compatible local server
       +------------> PyBot (pinned rules-only upstream, optional)
```

This repo does not bundle weights, start a server, train a model, or replicate PyBot's ~640k lines as native Svenbot files.

## Roadmap to earn the crown

1. **Performance lab:** a local wall-time JSONL benchmark harness is shipped. Next: publish real CPU, Apple Silicon, and GPU results including throughput, full model-server memory, first token timing, and separately judged answer quality.
2. **Real retrieval:** document extraction for Word/HTML/CSV and optional PDF, chunked ingestion, incremental updates, file inventory/removal and line references are shipped. Proof-carrying extractive receipts and offline contract falsification now ship; next: optional local embeddings, independent entailment evaluation, and relevance benchmarks.
3. **Adaptive routing:** an auditable per-task model choice with explicit cost/quality budgets, deterministic heuristics, and real benchmark datasets.
4. **Trustworthy agents:** sandboxed capabilities, allowlisted tool permissions, confirmations for mutations, security audits and red-team suites.
5. **First-class experience:** terminal + web streaming chat, installed-model discovery and a read-only knowledge browser now ship. Next: cross-platform installers, accessibility review, desktop wrappers, observability, and actual VRAM-fit verification.

Contributions should include tests and before/after measurements. Claims about local privacy must document every network boundary.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Licensing and origin

Svenbot's original code is Apache-2.0. The optional PyBot submodule is the unmodified upstream project at the pinned Git commit and is also Apache-2.0; its own license and attribution are retained there. See [NOTICE.md](NOTICE.md). **Svenbot is an independent project, not an official Hugging Face product or a claim of endorsement.**
