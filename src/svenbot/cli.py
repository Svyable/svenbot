"""Terminal interface for local-first inference, diagnostics and retrieval."""
from __future__ import annotations

import argparse
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
    subs.add_parser("chat", parents=[common], help="interactive terminal chat")
    index = subs.add_parser("index", help="explicitly add text/code files to local FTS search")
    index.add_argument("path")
    index.add_argument("--workspace", default=".")
    index.add_argument("--db", default=str(default_db_path()))
    search = subs.add_parser("search", help="search local indexed files")
    search.add_argument("query")
    search.add_argument("--workspace", default=".")
    search.add_argument("--db", default=str(default_db_path()))
    doctor = subs.add_parser("doctor", help="inspect available local backends")
    doctor.add_argument("--ollama-url", default=os.getenv("SVENBOT_OLLAMA_URL", "http://127.0.0.1:11434"))
    doctor.add_argument("--openai-url", default=os.getenv("SVENBOT_OPENAI_URL", "http://127.0.0.1:8080"))
    doctor.add_argument("--allow-remote", action="store_true")
    serve = subs.add_parser("serve", parents=[common], help="loopback-only, non-streaming chat completion API")
    serve.add_argument("--port", type=int, default=8765)
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
        for i, h in enumerate(answer.sources, 1):
            print(f"[source {i}: {h.path}:{h.line}]", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in (None, "chat", "ask", "serve"):
            # No args runs chat using parser defaults, but CLI options attach to subcommands.
            if args.command is None:
                args = parser().parse_args(["chat"])
            engine, store = make_engine(args)
            try:
                if args.command == "ask":
                    emit(engine.ask(args.prompt), args.verbose)
                elif args.command == "serve":
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
                        emit(engine.ask(prompt), args.verbose)
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
        elif args.command == "search":
            store = Store(args.db)
            try:
                for hit in store.search(args.workspace, args.query):
                    print(f"{hit.path}:{hit.line}\n{hit.excerpt}\n")
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
