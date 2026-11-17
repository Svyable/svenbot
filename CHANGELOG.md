# Changelog

## 0.2.0 — local performance lab and retrieval integrity

- Added an explicit JSONL local benchmark command with warmups, measured repetitions, per-backend latency summaries, sanitized errors and a machine-readable report. Benchmark outputs never contain prompt or completion text. It does not measure answer quality or external model-server memory.
- Added line-bounded FTS5 chunks with stable content-derived identifiers, preserving source spans. Improved ingestion with content hashing, atomic updates, unchanged-file skipping, bounded batches, and scoped pruning of deleted files.
- Migrates prior v0.1 full-document SQLite indexes on first open rather than dropping local knowledge.
- Added opt-in workspace purge to remove indexed text and persisted chat records. Backups and physical disk remnants are not affected.
- Added route-attempt status and local timing in verbose CLI output.
- Hardened the loopback API against browser Origin requests, unexpected Host headers, and non-JSON POST bodies; disabled environment-driven HTTP proxies on inference requests.
- Added regression tests for data isolation, migration, source spans, benchmark privacy, and HTTP request boundaries.

The v0.1 backend ordering remains unchanged; the router is deterministic, not yet adaptive. No new model weights or external services are bundled.
