"""Loopback-only web chat and a subset of the OpenAI chat completions API.

No remote binding, implicit logging, permissive CORS, tool execution or multiuser
access. This is intentionally *not* a network-facing public server.
"""
from __future__ import annotations

import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from itertools import chain

from .engine import Engine, Settings
from .providers import BackendError
from .store import Store

MAX_BODY = 262_144
UI_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def handler_factory(settings: Settings, db: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _trusted_request(self) -> bool:
            """Reject browser cross-site requests and DNS-rebinding hostnames."""
            hosts = self.headers.get_all("Host", [])
            allowed = {f"127.0.0.1:{self.server.server_port}",
                       f"localhost:{self.server.server_port}"}
            host = hosts[0].lower() if len(hosts) == 1 else ""
            origins = self.headers.get_all("Origin", [])
            same_origin = len(origins) == 0 or (len(origins) == 1 and
                                                  origins[0].lower() == f"http://{host}")
            fetch_site = self.headers.get("Sec-Fetch-Site", "").lower()
            if host not in allowed or not same_origin or fetch_site not in ("", "same-origin", "none"):
                self._json(403, {"error": "Untrusted Host, Origin or request site"})
                return False
            return True

        def _base_headers(self, code: int, mime: str, content_length: int | None = None):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            if content_length is not None:
                self.send_header("Content-Length", str(content_length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                             "style-src 'self'; connect-src 'self'; base-uri 'none'; "
                             "frame-ancestors 'none'; form-action 'none'")

        def _json(self, code, data):
            raw = json.dumps(data).encode("utf-8")
            self._base_headers(code, "application/json; charset=utf-8", len(raw))
            if code >= 400:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(raw)

        def _static(self, path):
            filename, mime = UI_ASSETS[path]
            raw = resources.files("svenbot").joinpath("ui", filename).read_bytes()
            self._base_headers(200, mime, len(raw))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self._trusted_request():
                return
            if self.path in UI_ASSETS:
                self._static(self.path)
            elif self.path == "/health":
                self._json(200, {"status": "ok", "scope": "loopback",
                                 "backend": settings.backend, "model": settings.model})
            elif self.path == "/v1/models":
                self._json(200, {"object": "list", "data": [{"id": "svenbot", "object": "model"}]})
            else:
                self._json(404, {"error": "Unknown endpoint"})

        def _sse(self, engine: Engine, messages: list[dict]):
            iterator = engine.stream(messages[-1]["content"], prior=messages[:-1])
            try:
                # Resolve backend failures before committing the HTTP 200 headers.
                first = next(iterator)
            except (BackendError, RuntimeError, ValueError) as exc:
                iterator.close()
                self._json(503, {"error": "No streaming backend available", "kind": type(exc).__name__})
                return
            except StopIteration:
                iterator.close()
                self._json(503, {"error": "Streaming backend returned no response"})
                return

            completion_id = "chatcmpl-" + uuid.uuid4().hex
            created = int(time.time())
            self._base_headers(200, "text/event-stream; charset=utf-8")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            def send_data(data):
                raw = ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")
                self.wfile.write(raw)
                self.wfile.flush()

            try:
                for part in chain((first,), iterator):
                    send_data({"id": completion_id, "object": "chat.completion.chunk",
                               "created": created, "model": "svenbot",
                               "svenbot_backend": part.backend,
                               "choices": [{"index": 0,
                                            "delta": {} if part.done else {"content": part.text},
                                            "finish_reason": "stop" if part.done else None}]})
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # The client cancelled; do not persist an incomplete chat turn.
                pass
            except (BackendError, RuntimeError, OSError):
                # No prompt text or upstream exception string is returned to the browser.
                try:
                    self.wfile.write(b'event: error\ndata: {"error":"Stream interrupted; answer not saved"}\n\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            finally:
                iterator.close()

        def do_POST(self):
            if not self._trusted_request():
                return
            if self.path != "/v1/chat/completions":
                self._json(404, {"error": "Unknown endpoint"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._json(415, {"error": "Content-Type must be application/json"})
                return
            try:
                n = int(self.headers.get("Content-Length", "-1"))
                if not 0 < n <= MAX_BODY:
                    raise ValueError("Invalid request size (max 256 KiB)")
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                streaming = data.get("stream", False)
                if not isinstance(streaming, bool):
                    raise ValueError("stream must be a boolean")
                if data.get("model", "svenbot") != "svenbot":
                    raise ValueError("Requested model must be 'svenbot'")
                messages = data.get("messages")
                if not isinstance(messages, list) or not messages or len(messages) > 32:
                    raise ValueError("Expected 1–32 messages")
                if any(not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                       or not isinstance(m.get("content"), str) or len(m["content"]) > 32_000
                       for m in messages):
                    raise ValueError("Expected text user/assistant messages <= 32,000 characters")
                if messages[-1]["role"] != "user":
                    raise ValueError("Last message must be from the user")
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
                return

            store = None
            try:
                store = Store(db) if settings.workspace else None
                # Fresh engine every request. Browser sends previous turns explicitly;
                # no server-side sessions or accidental cross-user shared state.
                per_request = Settings(**{**vars(settings), "session": None})
                engine = Engine(per_request, store)
                if streaming:
                    self._sse(engine, messages)
                else:
                    answer = engine.ask(messages[-1]["content"], prior=messages[:-1])
                    self._json(200, {
                        "id": "chatcmpl-" + uuid.uuid4().hex,
                        "object": "chat.completion", "created": int(time.time()),
                        "model": "svenbot", "svenbot_backend": answer.backend,
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": answer.text}}],
                    })
            except (BackendError, RuntimeError, OSError) as exc:
                # _sse handles failures after headers have been sent.
                if not streaming:
                    self._json(503, {"error": str(exc)})
            finally:
                if store:
                    store.close()

        def log_message(self, fmt, *args):
            # Do not log prompts, URLs, or client addresses.
            pass

    return Handler


def serve(settings: Settings, db: str, port: int = 8765):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be 1–65535")

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = True

    with LocalServer(("127.0.0.1", port), handler_factory(settings, db)) as server:
        print(f"Svenbot web chat: http://127.0.0.1:{port} (localhost only; Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
