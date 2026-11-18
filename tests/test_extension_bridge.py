"""Fail-closed origin/auth/provenance tests for the browser-only local bridge."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from svenbot.cli import parser
from svenbot.engine import Answer, Settings
from svenbot.providers import BackendError
from svenbot.extension_bridge import (handler_factory, select_references,
                                      validate_settings)

EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"
TOKEN = "a" * 48


def payload(question="What do the experiments conclude?"):
    return {"question": question, "page": {"title": "A study", "blocks": [
        {"id": "B1", "text": "Researchers tested the new hypothesis in 2025."},
        {"id": "B2", "text": "The experiments concluded the results were inconclusive."},
        {"id": "B3", "text": "This paragraph has the references for other investigations."},
    ]}}


class ValidationTests(unittest.TestCase):
    def test_remote_endpoint_and_rules_refused(self):
        for settings in (
            Settings(backend="rules"),
            Settings(backend="ollama", allow_remote=True),
            Settings(backend="openai", openai_url="https://api.example.com"),
            Settings(backend="openai", session="private"),
            Settings(backend="ollama", workspace="/private"),
        ):
            with self.subTest(settings=settings):
                with self.assertRaises((ValueError, BackendError)):
                    validate_settings(settings, EXTENSION_ID)

    def test_extension_identity_strict(self):
        for bad in ("", "ABCDEF", "a" * 31, "a" * 33, "q" * 32, "../etc/passwd"):
            with self.assertRaises(ValueError, msg=bad):
                validate_settings(Settings(), bad)

    def test_source_selection_deterministic_and_verifiable(self):
        query, title, hits, refs = select_references(payload())
        self.assertEqual(query, "What do the experiments conclude?")
        self.assertEqual(title, "A study")
        self.assertEqual(len(hits), len(refs))
        self.assertEqual(hits[1].line, 2)
        self.assertEqual(refs[1]["text"], hits[1].excerpt)
        self.assertEqual(len(hits[1].chunk_id), 64)
        self.assertEqual(refs[1]["sha256"], hits[1].chunk_id)
        self.assertEqual([r["block_id"] for r in refs], ["B1", "B2", "B3"])

    def test_invalid_blocks_fail_closed(self):
        p = payload()
        bads = [
            {**p, "page": {"title": "Page", "blocks": []}},
            {**p, "page": {"title": "Page", "blocks": [{"id": "B1", "text": "x" * 900}]}},
            {**p, "page": {"title": "Page", "blocks": [{"id": "B1", "text": "a"}, {"id": "B1", "text": "b"}]}},
            {**p, "page": {"title": "Page", "blocks": [{"id": "B1", "text": "hidden\x00"}]}},
            {**p, "page": {"title": "Page", "blocks": [{"id": "A1", "text": "wrong"}]}},
            {**p, "page": {"title": "Page", "blocks": [{"id": "B1", "text": "hello", "href": "https://secret"}]}},
            {"question": "x" * 1001, "page": p["page"]},
            {"question": "x", "page": p["page"], "do": "write"},
        ]
        for bad in bads:
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaises(ValueError):
                    select_references(bad)

    def test_bridge_cli_has_no_remote_toggle(self):
        args = parser().parse_args(["bridge", "--extension-id", EXTENSION_ID,
                                    "--backend", "ollama", "--model", "llama3.2"])
        self.assertEqual(args.command, "bridge")
        self.assertEqual(args.model, "llama3.2")
        self.assertFalse(hasattr(args, "allow_remote"))


class HttpBridgeTests(unittest.TestCase):
    def setUp(self):
        class LocalServer(ThreadingHTTPServer):
            daemon_threads = True
        self.server = LocalServer(("127.0.0.1", 0), handler_factory(Settings(backend="ollama", model="fixture"),
                                                                   EXTENSION_ID, TOKEN))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"127.0.0.1:{self.server.server_port}"
        self.origin = f"chrome-extension://{EXTENSION_ID}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Host": self.host, "Origin": self.origin, **(headers or {})}
        body = json.dumps(data) if isinstance(data, dict) else data
        if body is not None and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        result = (response.status, dict(response.getheaders()), json.loads(raw) if raw else None)
        conn.close()
        return result

    def test_auth_and_exact_extension_origin(self):
        correct = {"X-Svenbot-Token": TOKEN}
        self.assertEqual(self.request("GET", "/v1/extension/status", headers=correct)[0], 200)
        for headers in (
            {}, {"X-Svenbot-Token": "wrong"},
            {**correct, "Origin": "https://evil.example"},
            {**correct, "Origin": "null"},
            {**correct, "Host": "evil.example"},
            {**correct, "Host": f"localhost:{self.server.server_port}"},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("GET", "/v1/extension/status", headers=headers)[0], 403)

    def test_preflight_is_origin_restricted(self):
        headers = {"Access-Control-Request-Method": "POST",
                   "Access-Control-Request-Headers": "content-type, x-svenbot-token"}
        status, response, _ = self.request("OPTIONS", "/v1/extension/analyze", headers=headers)
        self.assertEqual(status, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], self.origin)
        self.assertEqual(self.request("OPTIONS", "/v1/extension/analyze",
                                      headers={**headers, "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("OPTIONS", "/v1/extension/analyze",
                                      headers={**headers, "Access-Control-Request-Headers": "authorization, x-svenbot-token"})[0], 403)

    @patch("svenbot.extension_bridge.Engine.ask", return_value=Answer("Local answer [source 1]", "ollama"))
    def test_real_http_analyze_contract(self, mocked):
        status, headers, data = self.request("POST", "/v1/extension/analyze", payload(),
                                             {"X-Svenbot-Token": TOKEN})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], self.origin)
        self.assertEqual(data["answer"], "Local answer [source 1]")
        self.assertEqual(data["backend"], "ollama")
        self.assertEqual(len(data["references"]), 3)
        self.assertEqual(mocked.call_args.kwargs["prior"], [])
        self.assertTrue(all(hit.path == "selected-browser-page" for hit in
                            mocked.call_args.kwargs["source_override"]))
        self.assertNotIn("https", json.dumps(data))

    @patch("svenbot.extension_bridge.Engine.ask")
    def test_unsafe_and_malformed_requests_never_call_model(self, mocked):
        headers = {"X-Svenbot-Token": TOKEN}
        self.assertEqual(self.request("POST", "/v1/extension/analyze", payload(),
                                      {"X-Svenbot-Token": "wrong"})[0], 403)
        self.assertEqual(self.request("POST", "/v1/extension/analyze", payload(),
                                      {**headers, "Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/v1/extension/analyze", {"do": "click"},headers)[0], 400)
        self.assertEqual(self.request("POST", "/v1/extension/analyze", "x" * 65000,headers)[0], 400)
        self.assertEqual(self.request("POST", "/v1/extension/execute", payload(), headers)[0], 404)
        mocked.assert_not_called()

    @patch("svenbot.extension_bridge.Engine.ask", side_effect=RuntimeError("secret local model traceback"))
    def test_provider_error_does_not_leak_private_input(self, mocked):
        status, _, result = self.request("POST", "/v1/extension/analyze", payload(),
                                         {"X-Svenbot-Token": TOKEN})
        self.assertEqual(status, 503)
        self.assertNotIn("secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
