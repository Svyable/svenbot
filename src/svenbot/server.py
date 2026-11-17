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
from .document_sessions import DocumentVault, MAX_UPLOAD_BYTES, DOCUMENT_TTL_SECONDS
from .documents import DocumentError
from .providers import BackendError
from .store import Store

MAX_BODY = 262_144
MAX_UPLOAD_BODY = 1_450_000  # Base64 of at most 1 MB of explicitly chosen input.
UI_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def handler_factory(settings: Settings, db: str):
    vault = DocumentVault()  # server-lifetime only; never persists file contents

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
                                 "backend": settings.backend,
                                 "model": settings.model or settings.ollama_suggested_model})
            elif self.path == "/v1/local/status":
                # Read-only, same-origin/loopback protected diagnostic snapshot.
                from .discovery import survey
                from .rules import _upstream_root
                report = survey(settings.ollama_url, settings.openai_url,
                                allow_remote=settings.allow_remote)
                report["pybot_available"] = _upstream_root() is not None
                report["configured_backend"] = settings.backend
                report["configured_model"] = settings.model or settings.ollama_suggested_model
                self._json(200, report)
            elif self.path == "/v1/local/library":
                if not settings.workspace:
                    self._json(409, {"error": "Start Svenbot with --workspace to use the knowledge library"})
                    return
                store = Store(db)
                try:
                    files = store.list_files(settings.workspace)
                finally:
                    store.close()
                self._json(200, {"files": files, "max_files": 500})
            elif self.path == "/v1/models":
                self._json(200, {"object": "list", "data": [{"id": "svenbot", "object": "model"}]})
            else:
                self._json(404, {"error": "Unknown endpoint"})

        def _sse(self, engine: Engine, messages: list[dict], sources=None):
            iterator = engine.stream(messages[-1]["content"], prior=messages[:-1],
                                     source_override=sources)
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
                for index, part in enumerate(chain((first,), iterator)):
                    packet = {"id": completion_id, "object": "chat.completion.chunk",
                               "created": created, "model": "svenbot",
                               "svenbot_backend": part.backend,
                               "choices": [{"index": 0,
                                            "delta": {} if part.done else {"content": part.text},
                                            "finish_reason": "stop" if part.done else None}]}
                    if sources is not None and index == 0:
                        packet["svenbot_sources"] = self._source_meta(sources)
                    send_data(packet)
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

        @staticmethod
        def _source_meta(hits):
            return [{"path": h.path, "line": h.line, "end_line": h.end_line,
                     "chunk_id": h.chunk_id} for h in hits]

        def _parse_json(self, maximum: int):
            headers = self.headers.get_all("Content-Length", [])
            if len(headers) != 1 or self.headers.get("Transfer-Encoding") is not None:
                raise ValueError("Exactly one Content-Length header is required; chunked requests are unsupported")
            try:
                size = int(headers[0])
            except ValueError as exc:
                raise ValueError("Invalid request size") from exc
            if not 0 < size <= maximum:
                raise ValueError(f"Request exceeds its {maximum} byte limit")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data

        def _temporary_sources(self, slot, query):
            # An isolated SQLite FTS index, created and disposed of for this
            # question. The uploaded original never touches the filesystem.
            temp = Store(":memory:")
            try:
                scope = "/__svenbot_temporary_document__"
                with temp.conn:
                    temp._store_content(scope, slot.name, slot.content)
                hits = temp.search(scope, query, limit=6)
                return hits or temp.file_chunks(scope, slot.name, limit=6)
            finally:
                temp.close()

        def do_POST(self):
            if not self._trusted_request():
                return
            if self.path not in ("/v1/chat/completions", "/v1/local/search",
                                 "/v1/local/document", "/v1/local/document/clear"):
                self._json(404, {"error": "Unknown endpoint"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._json(415, {"error": "Content-Type must be application/json"})
                return
            if self.path == "/v1/local/document":
                if settings.allow_remote:
                    self._json(403, {"error": "Temporary documents require a server without --allow-remote"})
                    return
                try:
                    data = self._parse_json(MAX_UPLOAD_BODY)
                    token, slot = vault.upload(data.get("filename"), data.get("content_base64"))
                except (ValueError, DocumentError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(201, {"document_id": token, "name": slot.name,
                                 "characters": len(slot.content),
                                 "expires_in_seconds": DOCUMENT_TTL_SECONDS,
                                 "stored": "server_memory_only"})
                return
            if self.path == "/v1/local/document/clear":
                try:
                    data = self._parse_json(256)
                    token = data.get("document_id")
                    if not isinstance(token, str) or len(token) > 128:
                        raise ValueError("Invalid temporary document handle")
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, {"cleared": vault.clear(token)})
                return
            if self.path == "/v1/local/search":
                if not settings.workspace:
                    self._json(409, {"error": "Start Svenbot with --workspace to search the knowledge library"})
                    return
                try:
                    data = self._parse_json(4096)
                    if not isinstance(data.get("query"), str):
                        raise ValueError("Expected a JSON object with a text query")
                    question = data["query"].strip()
                    if not 1 <= len(question) <= 256:
                        raise ValueError("Search query must be 1–256 characters")
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                store = Store(db)
                try:
                    hits = store.search(settings.workspace, question, limit=6)
                finally:
                    store.close()
                self._json(200, {"results": [
                    {"path": hit.path, "line": hit.line, "end_line": hit.end_line,
                     "chunk_id": hit.chunk_id, "excerpt": hit.excerpt}
                    for hit in hits]})
                return
            try:
                data = self._parse_json(MAX_BODY)
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

            has_document = "document_id" in data
            document_id = data.get("document_id")
            sources = None
            if has_document:
                if settings.allow_remote:
                    self._json(403, {"error": "Temporary document Q&A refuses --allow-remote"})
                    return
                slot = vault.get(document_id)
                if slot is None:
                    self._json(404, {"error": "Temporary document expired, cleared, or unknown; attach again"})
                    return
                if settings.backend == "rules":
                    self._json(503, {"error": "Document Q&A requires a local LLM, not rules-only mode"})
                    return
                sources = self._temporary_sources(slot, messages[-1]["content"])
            store = None
            try:
                store = Store(db) if settings.workspace and not has_document else None
                # Fresh engine every request. Temporary document mode never
                # reads the persistent library or permits rules-only fallback.
                per_request = Settings(**{**vars(settings), "session": None,
                                          "workspace": None if has_document else settings.workspace,
                                          "rules_fallback": False if has_document else settings.rules_fallback})
                engine = Engine(per_request, store)
                if streaming:
                    self._sse(engine, messages, sources=sources)
                else:
                    answer = engine.ask(messages[-1]["content"], prior=messages[:-1],
                                        source_override=sources)
                    packet = {
                        "id": "chatcmpl-" + uuid.uuid4().hex,
                        "object": "chat.completion", "created": int(time.time()),
                        "model": "svenbot", "svenbot_backend": answer.backend,
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": answer.text}}],
                    }
                    if sources is not None:
                        packet["svenbot_sources"] = self._source_meta(sources)
                    self._json(200, packet)
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


def serve(settings: Settings, db: str, port: int = 8765, *, open_browser: bool = False):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be 1–65535")

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = True

    with LocalServer(("127.0.0.1", port), handler_factory(settings, db)) as server:
        url = f"http://127.0.0.1:{port}"
        print(f"Svenbot web chat: {url} (localhost only; Ctrl+C to stop)")
        if open_browser:
            import webbrowser
            try:
                webbrowser.open(url)
            except Exception:
                print("Could not open the browser automatically; copy the localhost URL above.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
