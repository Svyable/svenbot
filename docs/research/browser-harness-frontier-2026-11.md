# Chrome as a local, permissioned AI harness: frontier scan

**Research date:** 2026-11-21. **Status:** verified upstream/documentation scan and proposed experiments, **not implemented functionality**. Previous design record: [open-weight-chrome-stack-2026.md](./open-weight-chrome-stack-2026.md). Existing Svenbot: Chrome Companion v0.1.3 / Svenbot v0.7.4 (offline exact passages, Chrome built-in non-open-weight Prompt API where available, and paired local inference). The latest built-in AI is not a replacement for an open-weight WebGPU implementation.

## Decision

Build a **tiered browser capability harness**, not an autonomous all-tabs scraper or a permanently privileged extension.

1. **User intent + scoped tab/session permission** — every browser capture starts with an explicit gesture. Keep existing activeTab permissions.
2. **WebMCP when a cooperating site exposes real tools** — a discovery/preview/propose channel before actions. Experimental / feature-detected; never assume it is available or that a Chrome extension automatically gets tool-consumer access.
3. **Deterministic accessibility/DOM observations when no tool exists** — compact role/name/ref snapshots, fresh refs after DOM change, locator visibility checks, and no screenshots if semantic controls suffice.
4. **Vision-based grounding only for inaccessible interfaces** — user-approved screenshot capture, local vision models, grounding confidence, and human confirmation for all mutations.
5. **Separately authorized execution transport** — native messaging or an explicit local DevTools/CDP session, subject to a capabilities policy. The read-only Chrome Companion should not silently gain chrome.debugger or broad host permissions.
6. **Local model cascade** — heuristic/offline retrieval, small open-weight model in WebGPU (not yet shipped), more capable local Ollama/llama.cpp backend, optional Chrome built-in model. Never invisible cloud failover.
7. **Durable recovery and evidence** — integrate existing Svenbot Link durable task ledger and future Mission Control; produce observations, proposed action, approval, attempted commit and verified postcondition as distinct records.

This ordering is an engineering **hypothesis**: benchmark each stage versus single-agent, screenshot-only and existing Svenbot baselines before declaring superiority.

## Most valuable new upstream discoveries

| Candidate | Source / license | What to borrow | Integration decision |
| --- | --- | --- | --- |
| Chrome WebMCP | [Official guide](https://developer.chrome.com/docs/modern-web-guidance/guides/webmcp/webmcp), [Imperative API](https://developer.chrome.com/docs/ai/webmcp/imperative-api), [Declarative API](https://developer.chrome.com/docs/ai/webmcp/declarative-api) | Site-defined semantic tools, JSON input schemas, actionable form annotations; tools are part of the current page, not a remote MCP server | **Experimental adapter** for participating sites only, feature detect, require browser opt-in and human approval for state-changing tools |
| Chrome DevTools MCP | [Google project](https://github.com/ChromeDevTools/chrome-devtools-mcp), [configuration](https://developer.chrome.com/docs/devtools/agents/get-started/configuration/) — Apache-2.0 | Connect a **separate agent process** to an existing Chrome session, accessibility inspection, network/performance debugging, and debugging WebMCP tools | Use for real QA and an optional advanced connection, not default extension permissions |
| agent-browser | [Vercel Labs](https://github.com/vercel-labs/agent-browser) — Apache-2.0 | Compact accessibility snapshots and element refs; verify after every action; refs expire with DOM changes | Compare as a native-host executor and import observation design, do not put Rust/CDP in the side panel |
| Nanobrowser 0.3 | [Project](https://github.com/nanobrowser/nanobrowser), [Oct 2026 release](https://github.com/nanobrowser/nanobrowser/releases) — Apache-2.0 | Its **new** architecture is a single agent plus chrome.debugger/CDP, element IDs, per-site allow/ask/block, explicit confirmation for side effects. Old planner+navigator details are superseded | Study approval UX and action results; no automatic merger or elevated permission grant |
| Defuddle / Mozilla Readability | [Defuddle](https://github.com/kepano/defuddle) MIT, [Readability](https://github.com/mozilla/readability) Apache-2.0 | Better article extraction, metadata, headings, footnotes, code and clean Markdown | **First low-risk integration experiment**: compare source recall/fidelity against current 60-block heuristic, never fetch undisclosed URLs |
| Midscene | [Midscene.js](https://github.com/web-infra-dev/midscene) MIT | Visual grounding from screenshots in unfamiliar or canvas-heavy UIs | Evaluator/fallback behind explicit screenshot consent; prefer deterministic locators |
| Stagehand / browser-use | [Stagehand](https://github.com/browserbase/stagehand) MIT, [browser-use](https://github.com/browser-use/browser-use) MIT | Competing browser action/agent loops, structured extraction and tool use | Benchmark components, not required dependencies |
| BrowserGym / AgentLab | [BrowserGym](https://github.com/ServiceNow/BrowserGym) Apache-2.0 (upstream LICENSE), [AgentLab](https://github.com/ServiceNow/AgentLab) | Benchmarks across WebArena/VisualWebArena/WorkArena etc., reproducible resets and tasks | Build Svenbot's own auditable local-task fixture suite; later reproduce public benchmark slices |
| DoomArena / OWASP AISVS | [DoomArena](https://servicenow.github.io/DoomArena/), [OWASP agent guidance](https://github.com/OWASP/AISVS) | Adversarial page content can trick agents even without an explicit hostile user command | Test all action-capable releases for injections, misleading tool definitions, approval spoofing and exfil attempts |
| BrowserOS | [BrowserOS](https://github.com/browseros-ai/BrowserOS) AGPL-3.0 | Full agentic-browser UX and memory as comparative product reference | **Do not fold its code into our extension** without AGPL compliance review and explicit product decision |

Repository license statements are sourced from upstream LICENSE/repository metadata as checked on the research date; transitive dependencies and model conversions need separate audits.

## WebMCP: important 2026 details

- Chrome now documents **document.modelContext.registerTool()**; older references to navigator.modelContext should not be copied. Declarative forms use toolname / tooldescription attributes. The guide was updated 2026-11-20.
- This is **Early Preview**, origin trial / flag-dependent, not broadly deployable as the only action strategy. The browser's consumer mechanism is distinct from tools registered in a page: a content script does not automatically inherit native consumer APIs. First prove discovery+execution in a controlled local test app or Chrome's DevTools MCP experimental WebMCP category before promising direct extension calls.
- Tool registrations must be treated as **untrusted page data** even if the browser surfaces typed inputs. A malicious site can describe harmful behavior as an apparently harmless tool. UI approval must show the exact origin, tool name, arguments, expected side effect and capability being granted. Never auto-execute because annotations claim read-only.
- Respect WebMCP abort registration, secure origin, form visibility and permission policy. A cancellation received after a tool commits is **uncertain**, not automatic rollback/retry.
- Chrome's official docs explicitly warn that WebMCP only exposes tools, **not** the Resources/Prompts used by backend MCP; do not conflate the protocols.

## Three high-leverage engineering optimizations

**1. Adaptive observation compression (cheap and testable).** Measure current extraction versus Defuddle/Readability on 60 page fixtures: articles, docs, ecommerce listings, SPA tables, long comments, embedded widgets and deliberately malicious markup. Preserve a provenance map to exact captured text. Strip forms/secrets by policy regardless of extractor output. Add a concise accessibility tree with role/name/stable-in-snapshot refs for actionable controls. Measure relevant information recall, token/character count, accidental sensitive captures, p95 extraction time and DOM-change recovery. Keep current extraction as fallback.

**2. Task-aware model cascade, not a giant model at every step.** Label page question as extract, compare, classify, form preparation or action. Prefer deterministic extraction for exact facts, a small local open-weight browser model for intent/candidates (Transformers.js/WebLLM if compatible), and larger user-selected local host inference for hard reasoning. Permit independent verifier for important claims. Track decision route and fallback; never imply that lightweight classification alone is deep reasoning. Chrome's built-in Prompt API remains a separate browser-managed **non-open-weight** option with explicit setup. Test format and signed model files; downloadable weights are not remote executable code.

**3. Observe → propose → approve → execute once → verify.** Use stable step IDs and immutable input/snapshot hashes. For a page mutation, display a diff/preview, check user-authorization scope, execute only through an allowlisted adapter, then re-observe actual result before declaring success. If execution acknowledgment is lost or a process dies after the action begins, write **uncertain** to the ledger and require reconciliation, not blind retries. This is at-most-once attempted execution, not a claim of exactly-once externally observable effects.

## Chrome DevTools MCP privacy threat model

Chrome DevTools MCP is excellent for QA, but connecting to a signed-in browser can expose session state. Official configuration says:
- Existing Chrome session auto-connect uses Chrome 144+ with remote debugging enabled and an **Allow** dialog; manual CDP debugging needs a separate, carefully scoped profile/port.
- Usage statistics are **enabled by default**, and performance CrUX requests can transmit URLs by default. For confidential local tests, explicitly disable both, do not copy sensitive traces/screenshots to external services, and audit flags before first use.
- JavaScript evaluation is **enabled by default**; disable it for read-only audits, but recognize that page-origin scripts and interactions still run. Restrict filesystem roots, allowed URL patterns and tool categories when possible.
- Never expose Chrome's remote debugging port on public interfaces or reuse a private primary browser profile for hostile-site research.

For a shipping Chrome extension, keep activeTab and user-selected capture as default. A later chrome.debugger-based executor must be separately installed/activated with prominent scope/permission disclosure; do not hide a high-privilege background pathway behind the existing "read" UI.

## Open-weight WebGPU notes

Continue #18; do not call Chrome's built-in Gemini Nano open-weight. Use audited, pinned, bundled runtime code and explicit one-time model weight opt-in. Candidate ecosystems: [Transformers.js](https://github.com/huggingface/transformers.js) (Apache-2.0), [WebLLM](https://github.com/mlc-ai/web-llm) (Apache-2.0), and experiments such as [transformers.js-chrome](https://github.com/tantara/transformers.js-chrome) (Apache-2.0). A newer [BrowserAI SDK](https://github.com/MissionSquad/BrowserAI) supports WebLLM + ONNX + small multimodal/voice models, but is a very small ecosystem and its documented defaults include CDN-bundled Kokoro components/proxy options; **do not integrate without checking all extension JS/Wasm complies with MV3 remote-code rules**.

Use a dedicated browser-visible inference context; MV3 service workers are suspendable and offscreen-document APIs have lifecycle/reason constraints. Require measurable GPU/VRAM and storage fit, progress/cancel, cache-delete and no silent network calls. The user should be able to use *offline exact source lookup* even when every model fails.

## Evaluation strategy and acceptance gates

Maintain a committed, reproducible **BrowserHarness-60** benchmark: 20 read/extract, 20 multi-step local mock-app tasks, 10 compare/provenance, 10 adversarial or interruption tasks; record exact expected state transitions and screenshots/DOM snapshots only where necessary. Reuse BrowserGym/AgentLab methodology, not ungrounded model-only score claims.

Run each version against at least three baselines: existing Svenbot v0.7.4 read-only behavior, pure accessibility/DOM policy, and model-first browser agent. Evaluate three hardware tiers with named browser/OS/model quantization:
- Verified task completion (%), independent of model self-report.
- Human-checked passage/claim support and cross-page provenance.
- P50/p95 latency, first-token time, tokens/characters processed, peak RAM/VRAM and number of browser calls.
- Sensitive-content leaks (target zero), unauthorized actions (target zero), duplicate side effects (target zero), cancelled/uncertain action resolution.
- MV3 worker restarts, tab navigation, DOM changes, GPU loss, model download interruption, offline mode and process crash.

**Proposed P0 patch — no extra Chrome permission:** introduce a pluggable on-device document extractor (current heuristic, Defuddle, Readability) plus fixture corpus, exact-span provenance, extraction-quality telemetry **kept local**, and tests. Acceptance: no regression on current visible-text secrecy filters, improved relevant passage recall on hand-audited pages, deterministic bounded output, no remote requests.

**P1 patch:** a WebMCP fixture website with read-only and write-mock tools, feature-detected in Chrome 149+/enabled preview; validate tool registry, schema, origins, approval, cancellations, actual form state and nonparticipating-site fallback. Do **not** put an unverified WebMCP consumer in production.

**P2 patch:** separate native/DevTools advanced-executor prototype with explicit opt-in, content-scoped permissions, approval UI, uncertain-event ledger and low-risk mock-site actions; compare agent-browser/Midscene/Stagehand before choosing engine.

**P3 patch:** genuine open-weight WebGPU model, bundled runtime and verified browser memory/latency; local model scheduler/reader with fallback to current paired backend.

## Immediate decision

Lead with **better, privacy-preserving page observation** (Defuddle vs Readability vs existing) because it can improve every existing inference route and yields reliable testable data without high-risk permissions. Develop WebMCP on a parallel experimental lane, and only then introduce the separate approved browser executor. Ship the full harness only after genuine real-Chrome acceptance tests; mocked extension UIs and protocol fixtures remain necessary but insufficient.

## Primary source index

- Chrome WebMCP introduction / origin-trial and flag: https://developer.chrome.com/docs/modern-web-guidance/guides/webmcp/webmcp
- Chrome WebMCP imperative and latest semantics: https://developer.chrome.com/docs/ai/webmcp/imperative-api
- Chrome WebMCP agentic tools, consumer/producer and deprecations: https://developer.chrome.com/docs/modern-web-guidance/guides/webmcp/agentic-javascript-tools
- Chrome WebMCP best practices / commit points: https://developer.chrome.com/docs/ai/webmcp/best-practices
- Chrome DevTools MCP configuration and privacy defaults: https://developer.chrome.com/docs/devtools/agents/get-started/configuration/
- Chrome offscreen document and service-worker lifecycles: https://developer.chrome.com/docs/extensions/reference/api/offscreen ; https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
- Chrome DevTools MCP code: https://github.com/ChromeDevTools/chrome-devtools-mcp
- Agent browser snapshot refs: https://github.com/vercel-labs/agent-browser
- Nanobrowser 0.3 actual change log: https://github.com/nanobrowser/nanobrowser/releases
- Defuddle reader: https://github.com/kepano/defuddle
- BrowserGym: https://github.com/ServiceNow/BrowserGym
- DoomArena: https://servicenow.github.io/DoomArena/
- LangChain browser tool optimization report (Nov 3, 2026): https://www.langchain.com/blog/how-we-optimized-browser-use-for-deep-agents
