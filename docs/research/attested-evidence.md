# Experiment 001 — Proof-carrying extractive evidence

**Status:** Implemented in Svenbot v0.3.0 as an opt-in experimental mode. **Scientific novelty has not been established.** This is an engineering hypothesis and executable trust boundary, not a claim to have solved hallucination or invented cryptographic provenance.

## Falsifiable hypothesis

For local document question-answering, a constrained selector + deterministic validator can guarantee that every *displayed quoted character* comes from an explicitly indexed snapshot, even when the selector model nominates an unsupported quote or source. The approach gives up free-form synthesis in the evidence lane. It does **not** establish the truth, relevance, completeness, logical entailment, or authenticity of the documents.

## Mechanism

1. A user explicitly indexes a workspace. Svenbot retrieves up to eight FTS5 chunks (max 1,400 characters each).
2. An offline lexical selector, or an optional **local** LLM, nominates up to three exact contiguous quotations. The LLM emits **selection data only**, not final assistant prose. A response must be a JSON object with an array of `{ "source": n, "quote": "..." }` items. Invalid or missing selections fail closed.
3. A deterministic validator checks the source number against the offered chunks, quote containment, output size, duplicate selection, character offsets, line spans, and SHA-256 digests. The receipt is built from Svenbot's indexed source text, never blindly from LLM fields.
4. A receipt containing excerpt text and chunk/quote digests may be saved explicitly. `svenbot verify` checks it against the current **indexed SQLite snapshot** for the same resolved workspace. It never silently consults live source files or an external server.

## Run the experiment

```sh
svenbot index docs --workspace .
svenbot evidence "How does the cooling design work?" --workspace . --output cooling.evidence.json
svenbot verify cooling.evidence.json --workspace .

# Optional local LLM selects exact quotes; unmatched or malformed selections are rejected.
svenbot evidence "How does the cooling design work?" --workspace . \
  --selector model --backend ollama --model llama3.2

# Falsification cases are self-contained and run fully offline.
svenbot evidence-eval --cases benchmarks/evidence-contract.jsonl
```

The `evidence` command **does not** produce a free-form answer. It returns attestable passages for human or downstream examination. Do not substitute it for a medical, legal, safety-critical, or independently verified factual conclusion.

## Security and limitations

- Hashes are integrity digests **not signatures**. Someone able to tamper with both receipt and SQLite content can forge a new self-consistent receipt. There is no third-party trust anchor or original file signature.
- Verification guarantees quote presence in the **current index**, not on-disk files. A changed source file remains undetected until the user reindexes; then outdated receipts fail verification.
- An exact quotation can itself be false, malicious, irrelevant, selective, or a prompt-injection instruction. The model receives source text as explicitly untrusted; without a fully isolated model, prompt injection may still influence *which* verbatim quote it nominates.
- Model selection can fail if the local model ignores JSON constraints; this is intentional fail-closed behavior. `--selector lexical` needs no weights or inference server.
- The source index and explicitly saved receipts contain plaintext excerpts. Keep receipts private, avoid committing them to public repos, and purge local workspace content if necessary. No background indexing or cloud judge runs.
- Existing v0.2 normal `ask`, `chat`, `bench`, and HTTP API modes remain unchanged; only the explicit `evidence` lane enforces extractive output.

## Evaluation plan and gates

| Gate | Test | Meaning |
|---|---|---|
| Quote integrity | exact quote + hash + offsets, tampered variants | Must reject any unsupported character or source reassignment |
| Staleness | mutate document, reindex, verify old receipt | Must reject old index revision |
| Workspace separation | verify against different path | Must fail |
| Prompt injection | fake model ignores contract / fabricates quote | Must reject unsupported selection; **not** all instruction-following failure |
| Offline | lexical selection with model adapters disabled | Must still work |
| Compatibility | full v0.2 suite | No regressions |

The included **11 synthetic contract cases** are acceptance tests, not a statistical estimate of hallucination probability. Next: publish real-world datasets, independent assessments of relevance and entailment, model compliance rate, end-to-end latency, and false-abstention tradeoffs against free-form RAG and extractive baselines. Log runs with hardware, quantization, model digest, dates and complete methods. A winning research claim requires externally reproducible improvements; none are asserted here.
