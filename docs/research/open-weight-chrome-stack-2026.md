# Svenbot × PM: Open-weight Chrome intelligence stack (research, 2026-11-17)

Status: **candidate components, not integrated or performance-validated.** This is a decision record based on project repositories, official model metadata and Chrome's platform documentation. Re-audit versions, licenses and dependency trees before distribution. The PM "Proceed Methodically" extension is a separate browser-UI dispatcher; it does **not** automatically coordinate results or run Svenbot workers.

## Product thesis

Combine an opt-in browser assistant with a local reasoning engine:

```
Chrome MV3 side panel (PM-style queue, page reader, approval UI)
  ├─ On-device WebGPU small model (optional, explicit model download)
  ├─ Content extraction on user-approved active tab only
  └─ Capability-gated native messaging host [proposed, not built]
       └─ Svenbot local daemon: model router, documents, evidence receipts
          ├─ Ollama/llama.cpp: small vision model or larger reasoning model
          ├─ Local embeddings + reranker + SQLite vectors
          └─ Mission scheduler: DAGs, leases, receipts, bounded workers
```

Never open a generic unauthenticated localhost endpoint to web pages using wildcard CORS. An extension/native host must verify the exact extension identity, validate each message, require explicit user-granted operations, and treat web content as untrusted. Native messaging is not a universal machine security boundary; local processes can invoke hosts independently. Keep no cloud fallback unless explicit.

## Recommended OSS components and decisions

| Layer | Candidate / upstream | Verified repo license | Why it matters | Decision |
| --- | --- | --- | --- | --- |
| Browser-only inference | [WebLLM](https://github.com/mlc-ai/web-llm), [MV3 service-worker example](https://github.com/mlc-ai/web-llm/tree/main/examples/chrome-extension-webgpu-service-worker) | Apache-2.0 | Real WebGPU inference in an extension; keep inference off the UI thread | Prototype against Transformers.js, do not assume MV3 service worker lives indefinitely |
| WebGPU embeddings + multimodal | [Transformers.js](https://github.com/huggingface/transformers.js) and [browser examples](https://github.com/huggingface/transformers.js-examples) | Apache-2.0 | On-device classification, embeddings, vision, short-form answers | **First browser PoC** |
| Real extension architecture | [Gemma 4 browser extension](https://github.com/nico-martin/gemma4-browser-extension) | MIT | Demonstrates Transformers.js, browser tab tools and semantic browsing | Study components and UX; audit runtime/permissions, not blindly fork |
| Local sidebar precedent | [Page Assist](https://github.com/n4ze3m/page-assist) | MIT | Browser UX talking to local models | Borrow UX, retain Svenbot's own privacy gates |
| Browser action abstraction | [Stagehand](https://github.com/browserbase/stagehand), [Playwright](https://github.com/microsoft/playwright) | MIT / Apache-2.0 | Structured observe/act/extract and reproducible browser tests | Adapter only; local support/version must be tested; no unconditional tool execution |
| Browser agent reference | [browser-use](https://github.com/browser-use/browser-use) | MIT | Python browser agent with Ollama option | Benchmark, not a required runtime dependency |
| Retrieval | [sqlite-vec](https://github.com/asg017/sqlite-vec) | Apache-2.0 | Add local vector retrieval alongside current FTS5 | **High priority**: hybrid lexical/vector ranking with deterministic citations |
| Documents | [Docling](https://github.com/docling-project/docling), [MarkItDown](https://github.com/microsoft/markitdown) | MIT / MIT | PDF tables, scanned document OCR and markdown conversion | Opt-in subprocess/format adapter; no arbitrary remote URL fetch, evaluate provenance |
| Tool interface | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT | Standard local tools when permissions exist | Only after deny-by-default capability authorization is implemented |
| Extension build | [WXT](https://github.com/wxt-dev/wxt) | MIT | MV3 side-panel build/test workflow | Evaluate against PM's existing extension source; no gratuitous migration |
| Regression / red team | [promptfoo](https://github.com/promptfoo/promptfoo) | MIT | Prompt injection, RAG and agent adversarial fixture testing | Add offline CI fixtures |

Licenses in this table are GitHub repository metadata as checked 2026-11-17; dependencies, model files, conversions and bundled assets have separate license obligations.

## Open-weight model candidates

All listed *upstream* model cards advertise Apache-2.0 at time checked. These are not automatically interchangeable with Chrome WebGPU, ONNX, GGUF, or Ollama formats; use compatible vetted conversions and verify weights/quantizations/model templates separately.

| Role | Model / card | Deployment hypothesis | Caveat |
| --- | --- | --- | --- |
| Browser-light LLM / page routing | [Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | Tiny first-pass prompt classifier via vetted WebGPU conversion | Must verify browser format and real accuracy; weak for complex actions |
| In-browser usable agent | [Gemma-4-E2B-it ONNX](https://huggingface.co/onnx-community/gemma-4-E2B-it-ONNX) | Transformers.js browser side-panel, concept validated by Gemma4 extension | GPU memory, latency and web permissions vary; explicit weight download |
| Local balanced multimodal | [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) or [9B](https://huggingface.co/Qwen/Qwen3.5-9B) | Ollama/llama.cpp server: page screenshot understanding, document tasks and structured generation | Real quantization + context memory measurement required |
| Local heavier reasoning | [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) | User-selected deeper task planning/review via supported inference server | ~16 GB model memory for suitable quantization, plus overhead; not a browser model |
| Semantic search | [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Local document and page vectors | Hardware and embedding throughput need measurement; never embed sensitive pages without permission |
| Cross-encoder reranking | [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Rerank FTS/vector candidates before citing | Added latency and CPU/GPU memory; measure quality difference |

Distinguish **open-source code** from **open weights**. Do not advertise model training data or complete training pipelines as open merely because weights and code are available. Avoid blanket "superintelligent" capability claims.

## Proposed release experiments

### A. Extension-scope proof of concept (first)

- Add a new optional MV3 companion extension with side panel; do not modify PM's ChatGPT-only dispatcher or claim compatibility without accessing its actual source.
- User clicks "Summarize this page" and grants `activeTab`; extract visible user-approved page text (no hidden login fields, passwords, form secrets or cross-origin frames).
- Infer on-device with a small model **or** explicitly paired Svenbot local host. Show selected model, privacy route, citations to the current page and failure reasons.
- Package JS + WebAssembly; **do not remotely load executable code**. Download model weights only after opt-in, and cache/clear predictably.
- Test MV3 worker restart, GPU unavailable/out-of-memory, model download cancellation, idle timeout, malicious DOM prompt injection, multiple tabs and no telemetry.
- Acceptance: 20 hand-labeled pages, 0 unapproved page transmissions, 0 unapproved browser mutations, browser session restart recovery. Measure median/p95 response latency and extension memory on named hardware. Do not claim product readiness from mocks alone.

### B. Capability-gated local bridge

- Prefer native messaging or an explicitly paired loopback token/channel to broad CORS. Decide via threat model; **no permissive wildcard origins**.
- Authentication is necessary but not sufficient: validate extension identity, enforce allowlisted `summarize`, `search`, `queue_plan` actions, cap bytes and job time, and require confirmation for `click`, `fill`, `submit`, `download` or filesystem mutations.
- Browser DOM is untrusted; model output is a proposal. Never grant shell, network or file access based on page text alone. Separate PM chat-dispatch feature from general browsing.
- Acceptance: hostile origin and prompt-injection suite, forged extension messages, token mismatch, cross-tab access, safe retry under ambiguous submission, no cross-workspace leakage.

### C. Mission Control + grounded retrieval

- Hybrid FTS5+sqlite-vec, citations checked against immutable snapshot, opt-in semantic embeddings and reranker.
- Bounded SQLite task DAG, checkpointing, no duplicate side effects on uncertain browser actions, deterministic artifact receipts, independent verification. Existing issue #14 is the owner for scheduler.
- Evaluate against single-model baseline, rule-only FTS, and semantic-only retrieval; report source precision, exact-quote rate, human-judged support, p50/p95 latency, cost, peak memory, and recovery rate.

## Chrome platform constraints

- MV3 service workers are not persistent background processes. Use official lifecycle guidance and offscreen documents where appropriate, validate restarts; persist only non-sensitive queue state.
- Request `activeTab` or optional per-site host permissions, not `<all_urls>` by default. No broad access to user's browsing history in initial release.
- Chrome Web Store policies restrict remotely hosted JS/Wasm/executable code; bundle runtime code and audit build outputs. Model weight download is not a license to run remote scripts.
- A Chrome native messaging host manifest can restrict allowed extension origins, but this does not protect against arbitrary same-user local programs by itself.
- Do not use brittle ChatGPT DOM automation as the foundation of Svenbot's own intelligence or attempt to bypass platform model limits.

Official references: [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), [MV3 lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle), [optional permissions](https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions), [MV3 remote hosted code policy](https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements/).

## Investment decision

First prove browser-local Gemma/Transformers.js plus a safe source extraction and visible model provenance; next deliver secure Svenbot pairing and hybrid retrieval; only then allow action-taking agents with approvals. Compare models before selecting a permanent default. PM should remain an explicit user-driven companion, not automatically granted all-tabs access.
