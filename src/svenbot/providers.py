"""Dependency-free adapters for *local* inference servers.

No remote host is contacted unless allow_remote is explicitly enabled. Upstream
model servers have their own security implications; Svenbot never starts one.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class BackendError(RuntimeError):
    """The requested inference backend is unavailable or malformed."""


def validate_base_url(base_url: str, allow_remote: bool = False) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BackendError("Backend URL must start with http:// or https:// and have a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BackendError("Backend URL cannot include credentials, queries, or fragments")
    if not allow_remote and parsed.hostname.lower() not in ("localhost", "127.0.0.1", "::1"):
        raise BackendError("Remote endpoints are blocked by default; use --allow-remote explicitly")
    return base_url.rstrip("/")


def request_json(base_url: str, route: str, payload: dict | None = None,
                 *, timeout: float = 12, allow_remote: bool = False) -> dict:
    root = validate_base_url(base_url, allow_remote)
    # The route is fixed code, never model-supplied.
    url = root + route
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="GET" if body is None else "POST",
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise BackendError("Backend attempted an HTTP redirect; refusing to follow it")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise BackendError(f"{url}: HTTP {response.status}")
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise BackendError("Backend response exceeded 4 MB")
            result = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise BackendError(f"Cannot use {url}: {exc}") from exc
    if not isinstance(result, dict):
        raise BackendError("Backend returned a non-object JSON response")
    return result


def chat_ollama(messages: list[dict], *, model: str, base_url: str,
                timeout: float = 120, allow_remote: bool = False) -> str:
    result = request_json(base_url, "/api/chat", {
        "model": model, "messages": messages, "stream": False,
    }, timeout=timeout, allow_remote=allow_remote)
    message = result.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise BackendError("Ollama returned no text (check the model and its output format)")
    return content.strip()


def chat_openai(messages: list[dict], *, model: str, base_url: str,
                timeout: float = 120, allow_remote: bool = False) -> str:
    result = request_json(base_url, "/v1/chat/completions", {
        "model": model, "messages": messages, "stream": False,
    }, timeout=timeout, allow_remote=allow_remote)
    try:
        content = result["choices"][0]["message"]["content"]
    except (IndexError, TypeError, KeyError) as exc:
        raise BackendError("OpenAI-compatible backend returned no message") from exc
    if not isinstance(content, str) or not content.strip():
        raise BackendError("OpenAI-compatible backend returned no text")
    return content.strip()


def probe(base_url: str, route: str, *, allow_remote: bool = False) -> tuple[bool, str]:
    try:
        request_json(base_url, route, timeout=1.5, allow_remote=allow_remote)
        return True, "reachable"
    except BackendError as exc:
        return False, str(exc)
