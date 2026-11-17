"""Behavioral regressions for chunked retrieval, benchmark honesty, and localhost API."""
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from svenbot.benchmark import load_prompts, run_benchmark, save_report
from svenbot.engine import Answer, Engine, Settings
from svenbot.server import handler_factory
from svenbot.store import MAX_CHUNK_CHARS, Store, workspace_key


class RetrievalTests(unittest.TestCase):
    def test_chunk_spans_are_source_lines_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines = [f"row{n} carefully explained details\n" for n in range(1, 100)]
            (root / "source.md").write_text("".join(lines))
            store = Store(root / "index.db")
            self.assertEqual(store.add_path(root / "source.md", root), (1, 0))
            hits = store.search(root, "row65", limit=5)
            self.assertGreaterEqual(len(hits), 1)
            for hit in hits:
                self.assertTrue(hit.line <= 65 <= hit.end_line)
                self.assertIn("row65", hit.excerpt)
                self.assertLessEqual(len(hit.excerpt), MAX_CHUNK_CHARS)
                self.assertEqual(hit.excerpt.splitlines()[0], lines[hit.line-1].strip())
                self.assertTrue(hit.chunk_id)
            store.close()

    def test_unchanged_files_skip_and_deleted_files_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "one.md").write_text("gammaalpha fact")
            (docs / "two.md").write_text("gammabeta fact")
            store = Store(root / "index.db")
            self.assertEqual(store.add_path(docs, root), (2, 0))
            original = store.search(root, "gammaalpha")[0].chunk_id
            self.assertEqual(store.add_path(docs, root), (0, 0))
            self.assertEqual(store.search(root, "gammaalpha")[0].chunk_id, original)
            (docs / "two.md").unlink()
            self.assertEqual(store.add_path(docs, root), (0, 0))
            self.assertEqual(store.search(root, "gammabeta"), [])
            store.close()

    def test_prune_is_directory_bound_and_no_hidden_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d1, d2 = root / "docs", root / "docs2"
            d1.mkdir(); d2.mkdir()
            (d1 / "a.md").write_text("oneonly")
            (d2 / "b.md").write_text("twoonly")
            (d1 / ".hidden").mkdir()
            (d1 / ".hidden" / "leak.md").write_text("shouldnotindex")
            (d1 / "api_token.json").write_text("shouldnotindexalso")
            store = Store(root / "index.db")
            store.add_path(root, root)
            self.assertEqual(store.search(root, "shouldnotindex"), [])
            self.assertEqual(store.search(root, "shouldnotindexalso"), [])
            (d1 / "a.md").unlink()
            store.add_path(d1, root)
            self.assertEqual(store.search(root, "oneonly"), [])
            self.assertEqual(store.search(root, "twoonly")[0].path, "docs2/b.md")
            store.close()

    def test_oversized_batch_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            for n in range(1001):
                (docs / f"doc{n:04}.md").write_text(f"document{n}")
            store = Store(root / "index.db")
            with self.assertRaisesRegex(ValueError, "Limit"):
                store.add_path(docs, root)
            self.assertEqual(store.search(root, "document0"), [])
            store.close()

    def test_v01_legacy_migration_preserves_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            cx = sqlite3.connect(db)
            cx.execute("CREATE VIRTUAL TABLE documents USING fts5(workspace UNINDEXED, path UNINDEXED, content)")
            cx.execute("INSERT INTO documents VALUES (?,?,?)", (workspace_key(tmp), "manual.md", "retained migration phrase"))
            cx.commit(); cx.close()
            store = Store(db)
            self.assertEqual(store.search(tmp, "retained")[0].path, "manual.md")
            store.close()
            store = Store(db)
            self.assertEqual(len(store.search(tmp, "retained")), 1)
            store.close()

    def test_purge_only_one_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / "a", root / "b"
            a.mkdir(); b.mkdir()
            (a / "a.md").write_text("secretalpha")
            (b / "b.md").write_text("secretbeta")
            store = Store(root / "db.sqlite")
            store.add_path(a, a); store.add_path(b, b)
            store.append_turn(workspace_key(a), "s", "question", "answer")
            self.assertEqual(store.clear_workspace(a), (1, 2))
            self.assertEqual(store.search(a, "secretalpha"), [])
            self.assertEqual(store.history(workspace_key(a), "s"), [])
            self.assertEqual(store.search(b, "secretbeta")[0].path, "b.md")
            store.close()


class StubEngine:
    def __init__(self):
        self.settings = Settings(backend="rules")
        self.reset_count = 0
        self.prompts = []

    def reset(self):
        self.reset_count += 1

    def ask(self, prompt, *, prior=None):
        self.prompts.append((prompt, prior))
        return Answer("fixed simulated answer", "rules")


class BenchmarkTests(unittest.TestCase):
    def test_load_fixture_and_reject_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture.jsonl"
            fixture.write_text('{"id":"a","prompt":"visible only in local fixture"}\n')
            self.assertEqual(load_prompts(fixture)[0]["id"], "a")
            fixture.write_text('{"id":"a","prompt":"x"}\n{"id":"a","prompt":"y"}\n')
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_prompts(fixture)

    def test_report_does_not_contain_prompt_or_response_and_counts_warmup(self):
        engine = StubEngine()
        secret = "DO NOT INCLUDE THIS PROMPT OR RESPONSE"
        report = run_benchmark(engine, [{"id": "p1", "category": "smoke", "prompt": secret}],
                               runs=3, warmup=2)
        self.assertEqual(engine.reset_count, 5)
        self.assertTrue(all(prior == [] for _, prior in engine.prompts))
        self.assertEqual(report["successful_samples"], 3)
        self.assertEqual(report["failed_samples"], 0)
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("fixed simulated answer", json.dumps(report))
        self.assertEqual(report["summary_by_backend"]["rules"]["samples"], 3)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results.json"
            save_report(report, output)
            self.assertEqual(json.loads(output.read_text())["schema_version"], 1)

    def test_errors_counted_without_exception_strings(self):
        engine = StubEngine()
        def failure(prompt, *, prior=None):
            raise ValueError("sensitive response contents")
        engine.ask = failure
        report = run_benchmark(engine, [{"id":"p1", "category":"smoke", "prompt":"secret"}],
                               runs=1, warmup=0)
        self.assertEqual(report["failed_samples"], 1)
        self.assertNotIn("sensitive", json.dumps(report))


class ServerSecurityTests(unittest.TestCase):
    def test_reject_dns_rebinding_browser_origins_and_simple_post(self):
        handler = handler_factory(Settings(backend="rules"), ":memory:")
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host = f"127.0.0.1:{server.server_port}"
                endpoint = "/v1/chat/completions"
                body = json.dumps({"model": "svenbot", "messages": [{"role": "user", "content": "hello"}]})
                def status(method, route, headers, payload=None):
                    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                    conn.request(method, route, body=payload, headers=headers)
                    response = conn.getresponse()
                    result = response.status
                    response.read(); conn.close()
                    return result
                self.assertEqual(status("GET", "/health", {"Host": "evil.example"}), 403)
                self.assertEqual(status("GET", "/health", {"Host": host, "Origin": "https://evil.example"}), 403)
                self.assertEqual(status("POST", endpoint, {"Host": host, "Content-Type":"text/plain"}, body), 415)
                self.assertEqual(status("GET", "/health", {"Host": host}), 200)
            finally:
                server.shutdown()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

class RouteTraceTests(unittest.TestCase):
    def test_fallback_route_is_explicit_and_contains_no_prompts(self):
        from svenbot.providers import BackendError
        with patch("svenbot.engine.chat_ollama", side_effect=BackendError("offline")):
            with patch("svenbot.engine.chat_openai", return_value="local reply"):
                answer = Engine(Settings()).ask("private user message")
        self.assertEqual(answer.backend, "openai")
        self.assertEqual([a.backend for a in answer.attempts], ["ollama", "openai"])
        self.assertEqual([a.status for a in answer.attempts], ["unavailable", "ok"])
        self.assertNotIn("private user message", repr(answer.attempts))
        self.assertTrue(all(a.elapsed_ms >= 0 for a in answer.attempts))

class AdditionalRegressions(unittest.TestCase):
    def test_single_extremely_long_line_is_split_and_attributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "huge.txt").write_text("prefix " + "x " * 1000 + "finalneedle")
            store = Store(root / "db.sqlite")
            self.assertEqual(store.add_path(root / "huge.txt", root), (1, 0))
            hits = store.search(root, "finalneedle")
            self.assertTrue(hits)
            self.assertEqual(hits[0].line, 1)
            self.assertEqual(hits[0].end_line, 1)
            self.assertLessEqual(len(hits[0].excerpt), MAX_CHUNK_CHARS)
            store.close()

    def test_bench_cli_writes_fixture_report_without_model(self):
        from svenbot.cli import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            fixture, destination = Path(tmp) / "prompts.jsonl", Path(tmp) / "report.json"
            fixture.write_text('{"id":"a","prompt":"local benchmark input"}\n')
            with patch("svenbot.cli.make_engine", return_value=(StubEngine(), None)):
                with redirect_stdout(StringIO()):
                    code = main(["bench", "--backend", "rules", "--prompts", str(fixture),
                                 "--output", str(destination), "--runs", "2", "--warmup", "0"])
            self.assertEqual(code, 0)
            result = json.loads(destination.read_text())
            self.assertEqual(result["successful_samples"], 2)
            self.assertNotIn("local benchmark input", destination.read_text())

    def test_purge_requires_explicit_yes(self):
        from svenbot.cli import main
        from contextlib import redirect_stderr
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stderr(StringIO()) as errors:
                code = main(["purge", "--workspace", tmp, "--db", str(Path(tmp) / "db.sqlite")])
            self.assertEqual(code, 1)
            self.assertIn("--yes", errors.getvalue())
