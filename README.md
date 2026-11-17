# Svenbot

**Local AI should mean local.** Your inference, your documents, your hardware, and a clear answer about which engine answered.

Svenbot is an independent, local-first orchestration project inspired by [Hugging Face PyBot](https://github.com/huggingface/pybot). PyBot took a wonderfully strange approach: hundreds of thousands of lines of hand-written/generated Python rules instead of model weights. Svenbot keeps that experiment available as an **optional, pinned upstream submodule**, and adds actual on-device LLM inference, local retrieval, opt-in conversation persistence, and a small local HTTP interface.

It is a **working 0.1 foundation, not yet the best local AI assistant**. We intend to earn that through reproducible benchmarks, latency and memory efficiency, extensibility, and safety—not marketing claims.

## Quick start

Python 3.10+; no Python runtime dependencies.

```bash
git clone --recurse-submodules https://github.com/Svyable/svenbot.git
cd svenbot
python -m pip install -e .

# In a separate terminal: install Ollama and start its service.
ollama pull llama3.2
svenbot doctor
svenbot ask "What does local-first AI mean?" --backend ollama --model llama3.2
svenbot chat --backend ollama --model llama3.2
```

Ollama needs to be installed separately; it serves models on `127.0.0.1:11434` by default. Existing compatible models may be selected with `--model`. Installation and model availability depend on your hardware.

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

`--backend auto` (the default) tries Ollama, then the OpenAI-compatible server, then PyBot rules. It reports backend failures rather than making up a reply. `--verbose` prints the selected backend on stderr. Rule-engine memory lasts for the running process only; it is not recovered from SQLite across restarts.

## Make your files searchable (explicitly)

No implicit filesystem crawl or background indexing. Choose which local text/code files to index:

```bash
svenbot index docs --workspace .
svenbot search "architecture" --workspace .
svenbot ask "Summarize our architecture" --backend ollama --workspace . --verbose
```

The search index lives in SQLite on your machine, under `~/.local/share/svenbot/svenbot.db` by default. Indexing stays within `--workspace`, doesn't follow symlinks, skips common secret filenames and dependency directories, and caps file size and index batch size. Review the chosen folder yourself: automatic filters cannot detect every secret. Retrieved excerpts are marked untrusted and shown to the model as context, never executed as commands. Results are best-effort lexical FTS5, **not yet semantic RAG**. `--workspace` enables retrieval of files you previously indexed with the same workspace and database.

Session history is **ephemeral by default**. To opt into SQLite persistence:

```bash
svenbot chat --backend ollama --session my-project --workspace .
```

`/reset` clears the current named session and in-process rules memory. The database is stored locally as plaintext (file mode 0600 on POSIX). Do not store regulated or sensitive material without your own disk encryption and access controls. A `--session` is scoped to the resolved workspace path.

## Local API

```bash
svenbot serve --backend ollama --model llama3.2 --port 8765
curl -s http://127.0.0.1:8765/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"svenbot","messages":[{"role":"user","content":"Hello"}]}'
```

The non-streaming text-only `/v1/chat/completions` response follows a small subset of the OpenAI schema, plus `GET /health` and `GET /v1/models`. API calls are isolated; request histories supplied as user/assistant messages are not persisted. Tools, images, streaming, arbitrary system messages, and multi-user authentication **are not implemented**. The listener binds to `127.0.0.1` only, adds no permissive CORS header, and must **not** be publicly exposed or reverse-proxied as an open service.

## Design principles

- **No hidden cloud fallback:** only loopback inference endpoints are allowed by default; `--allow-remote` is an explicit, potentially privacy-compromising exception. No built-in telemetry or API keys.
- **Rules, not replacement:** original Hugging Face PyBot stays pinned under `upstream/pybot`, preserving the source and Apache 2.0 attribution. Rules are opt-in or last-resort fallback, not silently confused with LLM-generated answers.
- **Trust boundaries:** no shell execution, no plugin execution, no autonomous tool calls, no implicit file access. Retrieved documents are untrusted input. Models can still be wrong or susceptible to prompt injection.
- **Small core, measurable results:** stdlib-only orchestration and deterministic test fixtures. Faster or better is a benchmark question, not a slogan.

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

1. **Performance lab:** publish fully reproducible throughput/latency/RAM tests on CPU, Apple Silicon, and GPU; compare local models and PyBot without conflating quality with speed.
2. **Real retrieval:** chunked ingestion, incremental updates, citations with verified offsets, optional local embedding models, and retrieval evaluation.
3. **Adaptive routing:** an auditable per-task model choice with explicit cost/quality budgets, deterministic heuristics, and real benchmark datasets.
4. **Trustworthy agents:** sandboxed capabilities, allowlisted tool permissions, confirmations for mutations, security audits and red-team suites.
5. **First-class experience:** streaming, model discovery, cross-platform packaging, web/desktop UI, observability, hardware-aware model recommendations.

Contributions should include tests and before/after measurements. Claims about local privacy must document every network boundary.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Licensing and origin

Svenbot's original code is Apache-2.0. The optional PyBot submodule is the unmodified upstream project at the pinned Git commit and is also Apache-2.0; its own license and attribution are retained there. See [NOTICE.md](NOTICE.md). **Svenbot is an independent project, not an official Hugging Face product or a claim of endorsement.**
