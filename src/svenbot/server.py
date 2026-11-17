"""Minimal localhost-only, non-streaming OpenAI-style chat completion shim.

Deliberately NO CORS, authentication, remote binding, tools, or streaming.
Do not expose this listener to a public network or put it behind a proxy.
"""
from __future__ import annotations

import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import Engine, Settings
from .providers import BackendError
from .store import Store

MAX_BODY = 262_144


def handler_factory(settings: Settings, db: str):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code, data):
            raw = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"status": "ok", "scope": "loopback"})
            elif self.path == "/v1/models":
                self._json(200, {"object": "list", "data": [{"id": "svenbot", "object": "model"}]})
            else:
                self._json(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self._json(404, {"error": "Unknown endpoint"})
                return
            try:
                n = int(self.headers.get("Content-Length", "-1"))
                if not 0 < n <= MAX_BODY:
                    raise ValueError("Invalid request size (max 256 KiB)")
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict) or data.get("stream", False):
                    raise ValueError("Only non-streaming JSON chat completions are supported")
                if data.get("model", "svenbot") != "svenbot":
                    raise ValueError("Requested model must be 'svenbot'")
                messages = data.get("messages")
                if not isinstance(messages, list) or not messages or len(messages) > 32:
                    raise ValueError("Expected 1–32 messages")
                if any(not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                       or not isinstance(m.get("content"), str) for m in messages):
                    raise ValueError("Only text user/assistant messages are supported")
                if messages[-1]["role"] != "user":
                    raise ValueError("Last message must be from the user")
                store = Store(db) if settings.workspace else None
                try:
                    # A new Engine per request avoids leaking state between callers.
                    per_request = Settings(**{**vars(settings), "session": None})
                    engine = Engine(per_request, store)
                    answer = engine.ask(messages[-1]["content"], prior=messages[:-1])
                finally:
                    if store:
                        store.close()
                self._json(200, {
                    "id": "chatcmpl-" + uuid.uuid4().hex,
                    "object": "chat.completion", "created": int(time.time()), "model": "svenbot",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": answer.text}}],
                })
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            except (BackendError, RuntimeError, OSError) as exc:
                self._json(503, {"error": str(exc)})

        def log_message(self, fmt, *args):
            # Do not log private prompts or request metadata.
            pass

    return Handler


def serve(settings: Settings, db: str, port: int = 8765):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be 1–65535")
    with ThreadingHTTPServer(("127.0.0.1", port), handler_factory(settings, db)) as server:
        print(f"Svenbot listening on http://127.0.0.1:{port} (localhost only; Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
