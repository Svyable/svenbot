# Changelog

## 0.7.2 — Trust-but-verify Chrome alpha

- Added **Find exact passages · Offline** inside the Chrome companion. It searches only user-captured page excerpts without invoking a model, using the network, or pretending lexical matches are AI answers. Added explicit **Disconnect & forget pairing** to clear the session token and request localhost-permission removal.
- Fixed a misleading readiness state: the bridge now performs a bounded, read-only **local model inventory/endpoint check** when an authenticated extension explicitly connects. It distinguishes a paired bridge from a listed model, an unverified model server, a missing model, or an offline endpoint; **none** implies proven model inference or quality.
- Added real HTTP integration tests through the *unmocked Svenbot engine* to protocol-compatible loopback Ollama/OpenAI fixture servers, plus independent invalid-origin/token checks. No live weights or consumer hardware are implied.
- Added deterministic offline-match JavaScript tests and an optional, honestly labeled mocked Chromium UI smoke script. Reproduced real Chrome validation blocker: the development environment enforces managed Chromium `ExtensionInstallBlocklist: ["*"]` and `URLBlocklist: ["*"]`. No attempt was made to bypass device policy; manual unpacked-extension QA remains open.
- Packaging, Python/Node CI and v0.7.2 wheel/extension version updated.

## 0.7.1 — Chrome Companion alpha

- Added an optional Chrome MV3 side panel that reads only the explicitly selected active webpage and previews source text before user-triggered model analysis.
- Added an isolated `svenbot bridge` command: loopback-only, token-paired with one extension ID, no database, remote inference or browser actions. Its sole AI operation selects bounded page excerpts and asks a configured already-installed local LLM.
- Added browser extension tests, deterministic extension ZIP packaging and CI checks. Browser model inference via WebGPU, real-device extension QA and agent actions remain unimplemented.

## 0.7.0 — Private document drop (First Light)

- Added an explicit, opt-in single-document attachment in the local browser chat: `.docx`, `.html`/`.htm`, `.csv`/`.tsv`, and optional text-based `.pdf` via `svenbot[documents]`. Users can choose or drop a document, ask follow-up questions, see source excerpt line labels, replace the attachment, and remove it; the conversation resets when a document changes.
- Added temporary `POST /v1/local/document` and `/v1/local/document/clear` endpoints. Originals are never written to disk. The server keeps only extracted text in an opaque capability-token slot, capped at 1 MB input/180,000 extracted characters, four concurrent slots and a 20-minute lifetime. No browser storage, persistent index or implicit library save.
- Document questions reuse `/v1/chat/completions` with `document_id`. Each question gets an isolated in-memory FTS5 index and a bounded excerpt selection. Workspace-indexed data is *excluded* from these requests; auto routing excludes PyBot rules. Streams include source metadata; these are retrieval pointers, not guarantees of citation correctness.
- Document uploads and Q&A refuse server-wide `--allow-remote` mode regardless of explicit model choice. Same-origin, DNS-rebinding and strict JSON controls stay in effect. Local inference servers may separately log prompts; restart without `--allow-remote` to use the browser document lane.
- Extended cross-source isolation, token expiry/revocation, malformed input, size, HTTP and SSE tests; reviewed static layout in Chromium at 390/768/1440 widths. The sandbox blocks Chromium's actual loopback navigation, so real browser-to-server interaction QA is still outstanding.
- Explicit persistence to the indexed library, actual scanned-PDF OCR, model-grounded citation entailment, CPU-time isolation for untrusted PDF parsing, multi-user auth, and cross-platform product QA remain future work.

## 0.6.0 — Knowledge Desk: work with real documents

- Added local, bounded extraction for Word `.docx`, HTML, CSV/TSV using the Python standard library; optional `pypdf` enables text-based PDF ingestion with per-page markers. No OCR, macros, formula evaluation, external network, or implicit file crawling.
- Added `svenbot ask-file PATH QUESTION` for one-off document Q&A using an **in-memory SQLite index** that is discarded after the request; no persistent session or database. Model-based only, with no ungrounded PyBot fallback.
- Added `svenbot library` for workspace-scoped inventory and `svenbot forget PATH --yes` to remove one indexed text copy while preserving its original file. Existing retrieval schema is unchanged.
- Added a responsive local **Knowledge** browser panel for previously indexed sources and read-only source excerpts, backed by same-origin `/v1/local/library` and POST `/v1/local/search`. No file upload, local filesystem scan, analytics, or browser storage.
- Defensive size and parser limits, explicit optional parser failures, source escaping and regression cases covering forged Host/Origin, malformed input, document extraction, and ephemeral persistence.
- Existing `ask`, `chat`, evidence receipts, local model discovery, and API compatibility stay in place. PDF OCR, real-device validation and professional security review remain open.

## 0.5.0 — Local Launch: read-only discovery and first-run guidance

- Added `svenbot setup` (human/JSON output) and `svenbot models`: bounded read-only installed model inventory and best-effort physical/cgroup RAM observations; no automatic model pulls, remote telemetry or shell execution.
- User-facing `ask`, `chat` and `web` choose a small-footprint **already-installed** Ollama model if no `--model` is supplied, while preserving explicit model selection. Disk size is not a runtime-memory, capability or quality guarantee.
- Added same-origin `/v1/local/status` endpoint and browser first-run guidance when no inference engine is detected; no automatic browser polling, external assets or stored settings.
- Added opt-in `svenbot web --open-browser` to open only the bound loopback URL.
- Added 15 discovery/inventory regression tests including malicious metadata, zero-download protocol fixtures, local host/origin protections, explicit-model bypass and constrained-memory advisory.
- Existing provider routing, streaming, evidence integrity, local-only defaults and persistence behavior remain unchanged. Hardware smoke tests and real browser visual QA are still release gates.

## 0.4.0 — First Light: streaming local web chat

- New standalone, dependency-free local web chat at `svenbot web`, with intentional privacy defaults, accessible controls, mobile layout, stop/reset/copy and text-only rendering (no third-party assets, analytics, accounts or browser storage).
- End-to-end text streaming for Ollama NDJSON and OpenAI-compatible SSE; `svenbot chat` streams by default, `svenbot ask --stream` is opt-in, and existing non-streaming clients continue to work.
- `/v1/chat/completions` supports `stream: true` SSE chunks and `[DONE]`, with a clear error event if streaming fails after output begins; browser UI never treats an interrupted stream as a completed reply.
- Stream routing is fail-closed: fallback is permitted only before any visible content; partial outputs are not persisted or combined with a different backend's answer.
- Strict local URL policy remains unchanged; upstream streaming ignores HTTP proxy environment settings and refuses redirects. Stream lines, aggregate bytes and output length are bounded.
- Hardened localhost Host, Origin and `Sec-Fetch-Site` validation for the same-origin browser UI. CSP forbids inline scripts and external assets; no permissive CORS.
- Added HTTP streaming fixture integration tests and security/interrupt regressions; tested Python wheel assets. No model-quality or performance superiority claims.

## 0.3.0 — Proof-carrying extractive evidence

- New opt-in `svenbot evidence` and `svenbot verify` commands: deterministic offline selection or local-model nomination of exact quoted text with path, line span, character offsets, and source/quote digests.
- New `svenbot evidence-eval` offline adversarial JSONL contract harness, pinned synthetic fixtures, and research protocol.
- No changes to generative `ask`/`chat`/HTTP API. No claim of semantic truth, cryptographic authentication, or scientific originality.
- Backward-compatible indexed SQLite data; existing chunk IDs and migration retained.

## 0.2.0 — local performance lab and retrieval integrity

- Added an explicit JSONL local benchmark command with warmups, measured repetitions, per-backend latency summaries, sanitized errors and a machine-readable report. Benchmark outputs never contain prompt or completion text. It does not measure answer quality or external model-server memory.
- Added line-bounded FTS5 chunks with stable content-derived identifiers, preserving source spans. Improved ingestion with content hashing, atomic updates, unchanged-file skipping, bounded batches, and scoped pruning of deleted files.
- Migrates prior v0.1 full-document SQLite indexes on first open rather than dropping local knowledge.
- Added opt-in workspace purge to remove indexed text and persisted chat records. Backups and physical disk remnants are not affected.
- Added route-attempt status and local timing in verbose CLI output.
- Hardened the loopback API against browser Origin requests, unexpected Host headers, and non-JSON POST bodies; disabled environment-driven HTTP proxies on inference requests.
- Added regression tests for data isolation, migration, source spans, benchmark privacy, and HTTP request boundaries.

The v0.1 backend ordering remains unchanged; the router is deterministic, not yet adaptive. No new model weights or external services are bundled.
