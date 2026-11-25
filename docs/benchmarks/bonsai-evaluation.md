# Bonsai evaluation — local Model Lab

Status: experimental candidate, not validated on Svenbot hardware. Reviewed 2026-11-25.

## Decision

Reuse the existing OpenAI-compatible backend and Model Lab instead of vendoring PrismML's demo, adding another inference dependency, or changing default routing. Start with upstream llama.cpp and standard Q2_0 weights. Evaluate optimized PrismML formats separately only if the baseline merits it.

| Candidate | Role to test |
| --- | --- |
| Bonsai 2 2B or 4B | Low-memory browser text analysis |
| Bonsai 2 9B | Intermediate local reasoning |
| Bonsai 2.5 27B | Higher-capability local research and structured proposals |
| Existing Qwen 3.5 4B and/or Inkling 2 Mini | Controls, not presumed inferior |

PrismML reports roughly 5.93 GB for the compact 27B PTQ1_0 language-model file; this is not the Q2_0 file size or runtime RAM requirement. The developer's agentic benchmarks are motivation, not Svenbot results.

## 1. Establish a reproducible local runtime

Read the [official model card](https://huggingface.co/prism-ml/Ternary-Bonsai-2.5-27B-GGUF) and [backend support](https://github.com/PrismML-Eng/Bonsai-demo/blob/main/BACKEND-SUPPORT.md). Upstream llama.cpp b11556 or later is required for Q2_0; PQ2_0 and PTQ1_0 require the compatible PrismML fork. Do not substitute an older runtime that merely recognizes the file format. Obtain a trusted build and review the model license and model provenance. No automatic installation, shell installer, telemetry, or download is added to Svenbot.

After explicitly downloading the desired non-MTP Q2_0 GGUF from the publisher, start the installed server (example POSIX shell; adapt path and GPU offload to the machine):

```sh
llama-server --version
llama-server -m /path/to/Ternary-Bonsai-2.5-27B-Q2_0.gguf \
  --host 127.0.0.1 --port 8080 --alias bonsai25-27b-q2 \
  -c 8192 -np 1
```

Use a small initial context and one request slot. Record runtime version, checkpoint revision and SHA-256, packing, actual context, offload, sampling/reasoning settings, machine/OS, RAM/VRAM and observed peak memory. The model's maximum advertised context is not an appropriate starting allocation. If the installed server's flags differ, consult its help and do not silently change settings. Do not expose the server outside loopback.

In a separate terminal, with the server running:

```sh
curl --fail --silent --show-error http://127.0.0.1:8080/v1/models
svenbot ask "Reply with the word ready." --backend openai \
  --openai-url http://127.0.0.1:8080 --model bonsai25-27b-q2
svenbot model-lab --dry-run
svenbot model-lab --backend openai --openai-url http://127.0.0.1:8080 \
  --model bonsai25-27b-q2 --limit 2 --timeout 120 \
  --output ./bonsai25-smoke.json
```

Use the actual served alias. Check the content field for a completed answer, not just a reachable endpoint or HTTP 200. Reasoning-only, truncated, malformed JSON and timeout outcomes count as failures. If thinking consumes the output budget, record the baseline failure and rerun with an explicitly recorded bounded server reasoning configuration supported by the installed build; do not silently strip or repair model responses.

## 2. Compare on the same workload

After a successful smoke run:

```sh
svenbot model-lab --backend openai --openai-url http://127.0.0.1:8080 \
  --model bonsai25-27b-q2 --runs 3 --timeout 120 \
  --output ./bonsai25-full.json
```

Repeat on the same hardware for each candidate and control, one loaded model at a time, with the same fixture hash, task limits, timeout, and equivalent context/decoding budgets. Record any model-specific settings, cold/warm conditions, and peak memory separately. Do not compare cross-hardware latency or conflate model-file size with residency. The current fixture checks exact quotes, extraction, comparison, code, read-only proposals and two adversarial cases; it does not execute tools, evaluate actual browser actions, or test vision. See [Model Lab](model-lab.md).

## 3. Promotion gates (proposed, not passed)

- Smoke: both cases pass strict JSON, exact quote and source contract with no timeouts.
- Full: at least 80% overall task-pass rate across three runs, no adversarial-case failures, no invalid tool proposals, no OOM or remote traffic. Compare per-category results against the controls; preserve the individual run failures.
- Hardware: record peak RAM/VRAM, latency p50/p95 and any failures. Require a demonstrable advantage (quality at acceptable memory/latency, or lower resource cost at equivalent quality) over the current model for the intended workload.
- Release: validate live Chrome Companion with the paired bridge and actual local model; verify source-grounding and prompt-injection handling independently on a larger, audited fixture. Keep model choice opt-in. No automatic execution of model-proposed actions.

If a gate fails, retain the existing default. Successful Model Lab results alone do not establish safe autonomous agency.

## 4. Separate later experiments

- PrismML PTQ1_0/PQ2_0 and MTP acceleration: compare against the same Q2_0 checkpoint family; pin the runtime revision and document any changes in memory, speed, and fidelity.
- Vision: separate test of image-capable server, matching projector, and explicit user-reviewed image payloads. Svenbot's current text benchmark does not validate this, and Bonsai 2.5 MLX is text-only.
- Browser-native WebGPU: distinct runtime/format research; a GGUF running in a desktop server is not in-browser inference.
- Native tool calling: add a separately audited multi-turn, read-only tool-call benchmark before expanding permissions. Model Lab proposals are structured text, not native tool calls.

Sources: [PrismML demo](https://github.com/PrismML-Eng/Bonsai-demo) · [Bonsai 2.5 model card](https://huggingface.co/prism-ml/Ternary-Bonsai-2.5-27B-GGUF) · [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases).
