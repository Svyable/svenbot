"""Real HTTP integration, not a mocked Engine: browser bridge -> local Ollama/OpenAI transport.

Simulates locally installed model *protocol*, not an actual model or installed Chrome.
No network access beyond loopback, no prompt logging outside in-memory fixture.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from svenbot.engine import Settings
from svenbot.extension_bridge import handler_factory

EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"
TOKEN = "live-fixture-not-a-user-secret-" + "x" * 40


class LocalModelFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/tags":
            result = {"models": [{"name": "test-fixture:latest"}]}
        elif self.path == "/v1/models":
            result = {"data": [{"id": "test-fixture"}]}
        else:
            self.send_error(404)
            return
        raw = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path not in ("/api/chat", "/v1/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 100_000:
            self.send_error(413)
            return
        data = json.loads(self.rfile.read(length))
        self.server.requests.append((self.path, data))
        if self.path == "/api/chat":
            result = {"message": {"role": "assistant", "content": "Fixture cites [source 1]."}}
        else:
            result = {"choices": [{"message": {"role": "assistant", "content": "Compatible fixture cites [source 1]."}}]}
        raw = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class LiveProtocolTests(unittest.TestCase):
    def setUp(self):
        self.model = ThreadingHTTPServer(("127.0.0.1", 0), LocalModelFixture)
        self.model.requests = []
        self.model_thread = threading.Thread(target=self.model.serve_forever, daemon=True)
        self.model_thread.start()
        self.bridge_servers = []

    def tearDown(self):
        for server, thread in self.bridge_servers:
            server.shutdown(); server.server_close(); thread.join(timeout=3)
        self.model.shutdown(); self.model.server_close(); self.model_thread.join(timeout=3)

    def bridge(self, backend="ollama"):
        url = f"http://127.0.0.1:{self.model.server_port}"
        settings = Settings(backend=backend, model="test-fixture", ollama_url=url,
                            openai_url=url, rules_fallback=False)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(settings, EXTENSION_ID, TOKEN))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.bridge_servers.append((server, thread))
        return server.server_port

    def request(self, port, method, path, body=None, *, token=TOKEN, origin=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        origin = origin if origin is not None else f"chrome-extension://{EXTENSION_ID}"
        headers = {"Host": f"127.0.0.1:{port}", "Origin": origin,
                   "X-Svenbot-Token": token}
        if body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(body).encode("utf-8")
        c.request(method, path, body=body, headers=headers)
        response = c.getresponse()
        payload = response.read()
        code = response.status
        cors = response.getheader("Access-Control-Allow-Origin")
        c.close()
        return code, json.loads(payload) if payload else None, cors

    @staticmethod
    def page():
        return {"question": "What did the study find?", "page": {"title": "Local test study", "blocks": [
            {"id": "B1", "text": "This study found several reproducible effects."},
            {"id": "B2", "text": "The authors note important uncertainty remains."},
        ]}}

    def test_real_ollama_http_round_trip_and_exact_source(self):
        port = self.bridge()
        code, status, _ = self.request(port, "GET", "/v1/extension/status")
        self.assertEqual(code, 200)
        self.assertEqual(status["inference"], {"status": "model_listed", "backend": "ollama"})
        self.assertEqual(self.model.requests, [])  # No inference during pairing
        code, data, cors = self.request(port, "POST", "/v1/extension/analyze", self.page())
        self.assertEqual(code, 200)
        self.assertEqual(cors, f"chrome-extension://{EXTENSION_ID}")
        self.assertEqual(data["answer"], "Fixture cites [source 1].")
        self.assertEqual(data["backend"], "ollama")
        self.assertEqual(data["references"][0]["sha256"], hashlib.sha256(
            data["references"][0]["text"].encode("utf-8")).hexdigest())
        self.assertEqual(len(self.model.requests), 1)
        route, body = self.model.requests[0]
        self.assertEqual(route, "/api/chat")
        self.assertEqual(body["model"], "test-fixture")
        self.assertEqual(body["stream"], False)
        self.assertIn("UNTRUSTED REFERENCE EXCERPTS", body["messages"][0]["content"])
        self.assertIn("[source 1]", body["messages"][0]["content"])
        self.assertEqual(body["messages"][-1]["content"], self.page()["question"])
        self.assertNotIn("private url", json.dumps(body))

    def test_real_compatible_http_round_trip(self):
        port = self.bridge(backend="openai")
        code, data, _ = self.request(port, "POST", "/v1/extension/analyze", self.page())
        self.assertEqual(code, 200)
        self.assertEqual(data["backend"], "openai")
        self.assertIn("Compatible fixture", data["answer"])
        self.assertEqual(self.model.requests[-1][0], "/v1/chat/completions")

    def test_pairing_is_not_confused_with_model_readiness(self):
        port = self.bridge()
        self.model.shutdown(); self.model.server_close(); self.model_thread.join(timeout=3)
        code, status, _ = self.request(port, "GET", "/v1/extension/status")
        self.assertEqual(code, 200)  # correct token and exact origin, bridge is paired
        self.assertTrue(status["connected"])
        self.assertEqual(status["inference"]["status"], "endpoint_unavailable")
        # Avoid closing server twice in tearDown
        self.model = ThreadingHTTPServer(("127.0.0.1", 0), LocalModelFixture)
        self.model.requests = []
        self.model_thread = threading.Thread(target=self.model.serve_forever, daemon=True)
        self.model_thread.start()

    def test_unauthorized_cannot_reach_local_model(self):
        port = self.bridge()
        self.assertEqual(self.request(port, "POST", "/v1/extension/analyze", self.page(), token="wrong")[0], 403)
        self.assertEqual(self.request(port, "POST", "/v1/extension/analyze", self.page(), origin="https://attacker.invalid")[0], 403)
        self.assertEqual(self.model.requests, [])


if __name__ == "__main__":
    unittest.main()
