"""Terminal interface for local-first inference, diagnostics and retrieval."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .engine import Engine, Settings
from .providers import BackendError, probe
from .rules import _upstream_root
from .store import Store, default_db_path, workspace_key


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="svenbot", description="Local AI. Your machine, your models, your files.")
    p.add_argument("--version", action="version", version=f"svenbot {__version__}")
    subs = p.add_subparsers(dest="command")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--backend", choices=["auto", "ollama", "openai", "rules"],
                        default=os.getenv("SVENBOT_BACKEND", "auto"))
    common.add_argument("--model", default=os.getenv("SVENBOT_MODEL"))
    common.add_argument("--ollama-url", default=os.getenv("SVENBOT_OLLAMA_URL", "http://127.0.0.1:11434"))
    common.add_argument("--openai-url", default=os.getenv("SVENBOT_OPENAI_URL", "http://127.0.0.1:8080"))
    common.add_argument("--allow-remote", action="store_true", help="opt in to contacting non-loopback endpoints")
    common.add_argument("--session", metavar="NAME", help="opt in to persistent local conversation history")
    common.add_argument("--workspace", metavar="PATH", help="enable searching explicitly indexed local files")
    common.add_argument("--db", default=str(default_db_path()), help="local SQLite database path")
    common.add_argument("--verbose", action="store_true", help="show the backend used and cited files")
    ask = subs.add_parser("ask", parents=[common], help="single prompt")
    ask.add_argument("prompt", help="question to ask")
    ask.add_argument("--stream", action="store_true", help="print response tokens as they arrive")
    chat = subs.add_parser("chat", parents=[common], help="interactive streaming terminal chat")
    chat.add_argument("--no-stream", action="store_true", help="wait for the full response before printing")
    index = subs.add_parser("index", help="explicitly add text/code files to local FTS search")
    index.add_argument("path")
    index.add_argument("--workspace", default=".")
    index.add_argument("--db", default=str(default_db_path()))
    purge = subs.add_parser("purge", help="delete indexed files and saved chats for a workspace")
    purge.add_argument("--workspace", required=True)
    purge.add_argument("--db", default=str(default_db_path()))
    purge.add_argument("--yes", action="store_true", help="confirm irreversible workspace data removal")
    bench = subs.add_parser("bench", parents=[common], help="local latency benchmark; no prompt text in reports")
    bench.add_argument("--prompts", required=True, help="explicit JSONL fixture file")
    bench.add_argument("--runs", type=int, default=3, help="measured repetitions per prompt")
    bench.add_argument("--warmup", type=int, default=1, help="unmeasured warmup calls")
    bench.add_argument("--output", required=True, help="write JSON report to this path")
    evidence = subs.add_parser("evidence", parents=[common],
                               help="extract verifiable quotes from indexed sources; never synthesize claims")
    evidence.add_argument("question", help="question for evidence selection")
    evidence.add_argument("--selector", choices=["lexical", "model"], default="lexical",
                          help="offline deterministic selection, or local model nomination")
    evidence.add_argument("--output", metavar="JSON", help="optionally save a new, non-overwriting receipt")
    verify = subs.add_parser("verify", help="check a receipt against the current local indexed snapshot")
    verify.add_argument("receipt", help="path to an evidence JSON receipt")
    verify.add_argument("--workspace", required=True)
    verify.add_argument("--db", default=str(default_db_path()))
    evaluate = subs.add_parser("evidence-eval", help="offline falsification suite for the quote selection contract")
    evaluate.add_argument("--cases", required=True, help="JSONL adversarial test cases")
    search = subs.add_parser("search", help="search local indexed files")
    search.add_argument("query")
    search.add_argument("--workspace", default=".")
    search.add_argument("--db", default=str(default_db_path()))
    doctor = subs.add_parser("doctor", help="inspect available local backends")
    doctor.add_argument("--ollama-url", default=os.getenv("SVENBOT_OLLAMA_URL", "http://127.0.0.1:11434"))
    doctor.add_argument("--openai-url", default=os.getenv("SVENBOT_OPENAI_URL", "http://127.0.0.1:8080"))
    doctor.add_argument("--allow-remote", action="store_true")
    serve = subs.add_parser("serve", parents=[common], help="loopback web UI and chat-completion API")
    serve.add_argument("--port", type=int, default=8765)
    web = subs.add_parser("web", parents=[common], help="launch local web chat on http://127.0.0.1:8765")
    web.add_argument("--port", type=int, default=8765)
    return p


def make_engine(args) -> tuple[Engine, Store | None]:
    store = Store(args.db) if (args.session or args.workspace) else None
    settings = Settings(backend=args.backend, model=args.model, ollama_url=args.ollama_url,
                        openai_url=args.openai_url, allow_remote=args.allow_remote,
                        session=args.session, workspace=args.workspace)
    return Engine(settings, store), store


def emit(answer, verbose: bool):
    print(answer.text)
    if verbose:
        print(f"[backend: {answer.backend}]", file=sys.stderr)
        for attempt in answer.attempts:
            print(f"[route: {attempt.backend} {attempt.status} {attempt.elapsed_ms:.1f} ms]", file=sys.stderr)
        for i, h in enumerate(answer.sources, 1):
            print(f"[source {i}: {h.path}:{h.line}-{h.end_line or h.line}]", file=sys.stderr)


def emit_stream(engine: Engine, prompt: str, verbose: bool):
    """Keep the terminal responsive while preserving the no-partial-save rule."""
    import re
    backend = None
    printed = False
    try:
        for part in engine.stream(prompt):
            if part.done:
                if verbose:
                    print(f"[backend: {part.backend}]", file=sys.stderr)
                    for attempt in part.attempts:
                        print(f"[route: {attempt.backend} {attempt.status} {attempt.elapsed_ms:.1f} ms]",
                              file=sys.stderr)
                continue
            # Model output is untrusted terminal text; strip escape/control bytes.
            safe = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "�", part.text)
            print(safe, end="", flush=True)
            printed = True
    finally:
        if printed:
            print(flush=True)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in (None, "chat", "ask", "serve", "web"):
            # No args runs chat using parser defaults, but CLI options attach to subcommands.
            if args.command is None:
                args = parser().parse_args(["chat"])
            engine, store = make_engine(args)
            try:
                if args.command == "ask":
                    if args.stream:
                        emit_stream(engine, args.prompt, args.verbose)
                    else:
                        emit(engine.ask(args.prompt), args.verbose)
                elif args.command in ("serve", "web"):
                    from .server import serve
                    serve(engine.settings, args.db, args.port)
                else:
                    print("Svenbot — local-first AI. /reset clears this session, /exit quits.")
                    while True:
                        try:
                            prompt = input("you> ").strip()
                        except (EOFError, KeyboardInterrupt):
                            print()
                            break
                        if prompt.lower() in ("/exit", "/quit"):
                            break
                        if prompt.lower() == "/reset":
                            engine.reset()
                            print("Session cleared.")
                            continue
                        if not prompt:
                            continue
                        if args.no_stream:
                            emit(engine.ask(prompt), args.verbose)
                        else:
                            emit_stream(engine, prompt, args.verbose)
            finally:
                if store:
                    store.close()
        elif args.command == "index":
            store = Store(args.db)
            try:
                count, skipped = store.add_path(args.path, args.workspace)
                print(f"Indexed {count} files; skipped {skipped}. Workspace: {workspace_key(args.workspace)}")
            finally:
                store.close()
        elif args.command == "purge":
            if not args.yes:
                raise ValueError("Pass --yes to delete all indexed files and saved chats for this workspace")
            store = Store(args.db)
            try:
                count, messages = store.clear_workspace(args.workspace)
                print(f"Deleted {count} indexed files and {messages} messages for {workspace_key(args.workspace)}")
            finally:
                store.close()
        elif args.command == "bench":
            from .benchmark import load_prompts, run_benchmark, save_report
            if args.session:
                raise ValueError("Benchmarks cannot use --session")
            prompts = load_prompts(args.prompts)
            engine, store = make_engine(args)
            try:
                report = run_benchmark(engine, prompts, runs=args.runs, warmup=args.warmup)
            finally:
                if store:
                    store.close()
            save_report(report, args.output)
            print(f"Wrote {report['successful_samples']} timing samples, "
                  f"{report['failed_samples']} errors to {args.output}")
            if report["failed_samples"]:
                return 1
        elif args.command == "evidence":
            from .evidence import create_receipt, save_receipt
            if not args.workspace:
                raise ValueError("evidence requires --workspace with explicitly indexed files")
            if args.session:
                raise ValueError("evidence mode does not access or persist conversations; omit --session")
            store = Store(args.db)
            try:
                settings = Settings(backend=args.backend, model=args.model,
                                    ollama_url=args.ollama_url, openai_url=args.openai_url,
                                    allow_remote=args.allow_remote)
                receipt = create_receipt(store, args.workspace, args.question,
                                         selector=args.selector, settings=settings)
                if args.output:
                    save_receipt(receipt, args.output)
                for entry in receipt["evidence"]:
                    print(f"{entry['path']}:{entry['line_start']}-{entry['line_end']} "
                          f"[chunk {entry['chunk_id']}]\n{json.dumps(entry['quote'], ensure_ascii=False)}\n")
                if args.output:
                    print(f"Saved {len(receipt['evidence'])} verifiable quotes to {args.output}")
            finally:
                store.close()
        elif args.command == "verify":
            from .evidence import load_receipt, verify_receipt
            store = Store(args.db)
            try:
                count = verify_receipt(store, args.workspace, load_receipt(args.receipt))
                print(f"Verified {count} exact quotes against current indexed snapshot.")
            finally:
                store.close()
        elif args.command == "evidence-eval":
            from .evaluation import evaluate_contract
            report = evaluate_contract(args.cases)
            print(f"Evidence contract: {report['passed']}/{report['cases']} cases passed; "
                  f"false accepts={report['false_accepts']}, false rejects={report['false_rejects']}")
            if report["failed"]:
                return 1
        elif args.command == "search":
            store = Store(args.db)
            try:
                for hit in store.search(args.workspace, args.query):
                    print(f"{hit.path}:{hit.line}-{hit.end_line or hit.line} [chunk {hit.chunk_id}]\n{hit.excerpt}\n")
            finally:
                store.close()
        elif args.command == "doctor":
            root = _upstream_root()
            print(f"PyBot rules: {'available (' + str(root) + ')' if root else 'not installed (optional submodule)'}")
            for label, url, route in (("Ollama", args.ollama_url, "/api/tags"),
                                      ("OpenAI-compatible", args.openai_url, "/v1/models")):
                ok, info = probe(url, route, allow_remote=args.allow_remote)
                print(f"{label}: {'reachable' if ok else 'unavailable'} ({info})")
        return 0
    except (BackendError, ValueError, RuntimeError, OSError) as exc:
        print(f"svenbot: {exc}", file=sys.stderr)
        return 1
