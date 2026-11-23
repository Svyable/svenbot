# Svenbot Model Lab — measurable local reasoning for the Chrome harness

**Status:** v0.7.6 developer feature. Runs on *already installed*, explicitly selected local Ollama or OpenAI-compatible models. No weight download, browser access, tool execution, autonomous routing or remote inference. A score is a **synthetic task-contract proxy**, not general intelligence or validated human task success.

## Why

[Inkling 2 Mini](https://thinkingmachines.ai/news/inkling-2-mini/) is promising because its looped sparse architecture makes substantial computation possible without a conventional dense 26B activation cost. Yet its full checkpoint is around 20 GB and published highly compressed GGUFs are around 8–17 GB. The often-quoted ~90% figure for some Unsloth quantizations measures **top-token agreement against a reference**, not a 90% cut in the original weight file and not 90% accuracy on browser tasks. Runtime buffers and context add memory demands. A browser-native WebGPU backend for the looped MoE is **not** implemented in Svenbot.

We should compare a fast small model and a more capable local Inkling using the **same source-grounded task contract**, rather than route based on parameter count or marketing benchmarks.

## Run the offline audit (no model installed)

```sh
svenbot model-lab --dry-run
```

This validates the bundled, fixed 20-task JSONL fixture and prints its SHA-256 and category counts without a model call. A checkout copy also exists in `benchmarks/browser-harness-20.jsonl`; installed wheels include an identical copy in `svenbot/fixtures`.

## Run local model comparisons

Install and start Ollama separately and confirm models manually with `ollama list`. No `ollama pull` is executed by Svenbot. On a machine with enough RAM/VRAM, you may explicitly opt to install Inkling from Ollama's library; check the model tag printed by `ollama list` before benchmarking.

```sh
# Fast smoke: explicit already-installed models, only 4 bounded tasks.
svenbot model-lab \
  --backend ollama \
  --model qwen3.5:4b \
  --model inkling-2-mini \
  --limit 4 \
  --hardware 'Mac, Apple silicon, 32 GB unified memory' \
  --output ./model-lab-smoke.json

# Complete fixture, one request per task per model.
svenbot model-lab \
  --model qwen3.5:4b --model inkling-2-mini \
  --output ./model-lab-full.json
```

The example model names are illustrative; only request models you already have and whose runtime supports the format. `--runs 1..3` repeats cases, `--timeout 5..600` bounds each network request, and `--cases /path/to/your.jsonl` lets you supply a separately audited fixture (max 100 tasks). Up to four model names, never parallelized or automatically downloaded. The `--output` is **not** created in dry-run mode.

For a loopback llama.cpp server with an OpenAI-compatible route, use `--backend openai --openai-url http://127.0.0.1:8080 --model LOCAL_ALIAS`. Svenbot refuses remote hosts even when given an explicit URL; it does not have a `--allow-remote` flag in Model Lab.

**Workload warning:** 20 cases × 2 models × 1 run = **40 complete model requests**. Some local models will take considerable time. Start with `--limit 2` to verify format/tool contract compatibility. Full 8–20GB models may run out of memory or fail to load; that is a recorded error, not automatic evidence that quantization is useless.

## Fixture coverage and scoring

| Category | Cases | What is checked |
| --- | ---: | --- |
| Extract | 6 | Exact facts, numbers, dates, caveats, and late conclusions |
| Compare | 4 | Conflicting/agreeing facts and two-page citation presence |
| Read-only tool proposals | 4 | Structured `find_text`/`scroll_to`/`select_tab` suggestion or abstention; **never executed** |
| Code | 4 | Simple grounded code explanations and source citations |
| Adversarial | 2 | Simple injected page instructions, answer terms, and absence of forbidden text/actions |

The model receives a fresh two-message context for every case and must return JSON **exactly** `{ "answer": "...", "citations": [{"source": "A:1", "quote": "exact passage"}], "proposal": null }`. Proposal objects must match the read-only tool contract. No page tools are actually installed into a model session.

A sample passes only if the JSON schema is accepted, every quotation is a verbatim substring of its referenced fixture source, required source IDs are cited, narrowly authored expected terms are included/forbidden terms absent, and any read-only proposal matches the expected JSON. This is a useful **falsification test**, not an entailment or factual-correctness judge: models could game keyword matches or make unsupported additional claims. Cite validation proves only a quote occurs in a supplied fixture, not that an answer follows from it.

## Report schema and privacy

The JSON report contains a fixture SHA-256; local backend/model identifiers; user-entered hardware description; category-level proxy pass rates; end-to-end wall latency p50/p95; status/error types; and tentative measured per-category route candidates. It does **not** serialize full prompts, captured source passages, generated answers, or the pairing token. Files are atomically written and mode `0600` on POSIX. The local model server has its own storage and logging behavior, so test with synthetic fixtures and audit its settings.

A category candidate is shown only when at least **two distinct task IDs** from that category were evaluated and the proxy pass rate is ≥ 0.8. **No runtime automatically routes based on these recommendations**; a candidate is a development hint requiring a human quality and hardware audit. Model Lab does not capture process-external model RAM/VRAM, tokens per second, power, or first-token latency. Do not compare timings across dissimilar hardware as though they were equivalent.

## Next gates

1. Run real hardware-backed Inkling native/Q4/Q2/IQ1_M variants against the same 20 tasks and larger independently audited BrowserHarness-60 dataset, with named hardware, loaded-model memory and quantization.
2. Verify model-specific tool JSON compliance, quote quality and injection robustness with humans; add multi-turn and interrupted workflow tasks rather than assuming 20 simple cases measure agentic capability.
3. Only after replicated results, introduce optional explicit **category-level routing** into the Chrome bridge with opt-in preference, caps, uncertain-action recovery and review.
4. Separately develop bundled open-weight **browser WebGPU** inference (#18); Inkling's GGUF/Ollama checkpoint is not automatically compatible with Transformers.js/WebLLM or ordinary browser GPU memory.

Source links: [Thinking Machines Inkling 2 Mini](https://thinkingmachines.ai/news/inkling-2-mini/) · [Hugging Face official model](https://huggingface.co/thinkingmachines/Inkling-2-Mini) · [Unsloth quantized GGUFs](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF) · [Svenbot issue #28](https://github.com/Svyable/svenbot/issues/28).
