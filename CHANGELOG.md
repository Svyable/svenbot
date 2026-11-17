# Changelog

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
