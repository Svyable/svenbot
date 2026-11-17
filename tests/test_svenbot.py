import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from svenbot.cli import main
from svenbot.engine import Engine, Settings
from svenbot.providers import BackendError, chat_ollama, chat_openai, validate_base_url
from svenbot.rules import RulesUnavailable
from svenbot.server import handler_factory
from svenbot.store import Store


class ProviderTests(unittest.TestCase):
    def test_remote_hosts_rejected(self):
        for uri in ("https://api.openai.com", "http://192.168.1.7:11434", "file:///tmp/model"):
            with self.assertRaises(BackendError, msg=uri):
                validate_base_url(uri)

    def test_password_and_query_rejected(self):
        for uri in ("http://u:p@localhost:11434", "http://localhost:11434/?key=secret"):
            with self.assertRaises(BackendError):
                validate_base_url(uri)

    def test_remote_opt_in(self):
        self.assertEqual(validate_base_url("https://example.com", True), "https://example.com")

    @patch("svenbot.providers.request_json")
    def test_ollama_payload(self, request):
        request.return_value = {"message": {"content": "  Hi there  "}}
        self.assertEqual(chat_ollama([{"role": "user", "content": "hello"}], model="test",
                                     base_url="http://127.0.0.1:11434"), "Hi there")
        self.assertEqual(request.call_args.args[1], "/api/chat")
        self.assertFalse(request.call_args.args[2]["stream"])

    @patch("svenbot.providers.request_json")
    def test_openai_payload(self, request):
        request.return_value = {"choices": [{"message": {"content": " yes "}}]}
        self.assertEqual(chat_openai([], model="test", base_url="http://localhost:8080"), "yes")
        self.assertEqual(request.call_args.args[1], "/v1/chat/completions")

    @patch("svenbot.providers.request_json", return_value={"message": None})
    def test_bad_backend_response_is_not_silently_suppressed(self, _):
        with self.assertRaises(BackendError):
            chat_ollama([], model="test", base_url="http://localhost:11434")


class EngineTests(unittest.TestCase):
    @patch("svenbot.engine.chat_openai", return_value="from llama.cpp")
    @patch("svenbot.engine.chat_ollama", side_effect=BackendError("ollama offline"))
    def test_auto_routes_to_openai(self, ollama, openai):
        engine = Engine(Settings())
        answer = engine.ask("hello")
        self.assertEqual(answer.backend, "openai")
        self.assertEqual(answer.text, "from llama.cpp")
        engine.ask("again")
        self.assertEqual(openai.call_args.args[0][1]["content"], "hello")
        self.assertEqual(openai.call_args.args[0][2]["content"], "from llama.cpp")
        self.assertEqual(ollama.call_count, 2)

    @patch("svenbot.engine.RulesEngine", side_effect=RulesUnavailable("missing"))
    @patch("svenbot.engine.chat_openai", side_effect=BackendError("unavailable"))
    @patch("svenbot.engine.chat_ollama", side_effect=BackendError("unavailable"))
    def test_auto_failure_is_explicit(self, *_):
        with self.assertRaisesRegex(BackendError, "No local backend available"):
            Engine(Settings()).ask("test")

    @patch("svenbot.engine.chat_openai", return_value="grounded answer")
    def test_index_sources_in_prompt(self, chat):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "facts.md").write_text("Parrots recognize voices in controlled studies.")
            store = Store(root / "index.db")
            store.add_path(root / "facts.md", root)
            engine = Engine(Settings(backend="openai", workspace=str(root)), store)
            answer = engine.ask("parrots")
            self.assertEqual(answer.sources[0].path, "facts.md")
            self.assertIn("UNTRUSTED REFERENCE EXCERPTS", chat.call_args.args[0][0]["content"])
            self.assertIn("[source 1]", chat.call_args.args[0][0]["content"])
            store.close()

    @patch("svenbot.engine.chat_ollama", return_value="first reply")
    def test_session_persists_and_resets(self, chat):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "state.db")
            engine = Engine(Settings(backend="ollama", session="one", workspace=temp), store)
            engine.ask("first question")
            self.assertEqual(len(store.history(str(Path(temp).resolve()), "one")), 2)
            new_engine = Engine(Settings(backend="ollama", session="one", workspace=temp), store)
            new_engine.ask("second question")
            self.assertEqual(chat.call_args.args[0][1]["content"], "first question")
            self.assertEqual(len(store.history(str(Path(temp).resolve()), "one")), 4)
            new_engine.reset()
            self.assertEqual(store.history(str(Path(temp).resolve()), "one"), [])
            store.close()

    @patch("svenbot.engine.chat_ollama", return_value="ok")
    def test_prior_avoids_mutating_session(self, chat):
        engine = Engine(Settings(backend="ollama"))
        engine.ask("recent", prior=[{"role": "user", "content": "previous"}])
        self.assertEqual(engine._history, [])
        self.assertEqual(chat.call_args.args[0][1]["content"], "previous")


class StoreTests(unittest.TestCase):
    def test_index_search_update_and_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data.md").write_text("Orchid alpha information\nSecond line")
            store = Store(root / "db.sqlite")
            self.assertEqual(store.add_path(root / "data.md", root), (1, 0))
            self.assertEqual(len(store.search(root, "orchid")), 1)
            self.assertEqual(len(store.search(root / "somewhere_else", "orchid")), 0)
            (root / "data.md").write_text("Celestial beta information")
            store.add_path(root / "data.md", root)
            self.assertEqual(store.search(root, "orchid"), [])
            self.assertEqual(store.search(root, "celestial")[0].path, "data.md")
            store.close()

    def test_directory_index_skips_hidden_secrets_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("Visible knowledge")
            (root / ".env").write_text("api_key=hidden")
            (root / "secret.pem").write_text("private key material")
            (root / "link.md").symlink_to(root / "README.md")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "ignored.md").write_text("skip me")
            store = Store(root / "db.sqlite")
            count, skipped = store.add_path(root, root)
            self.assertEqual(count, 1)
            self.assertGreaterEqual(skipped, 3)
            store.close()

    def test_outside_workspace_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "content.md").write_text("text")
            store = Store(root / "db.sqlite")
            with self.assertRaisesRegex(ValueError, "inside --workspace"):
                store.add_path(root / "content.md", root / "other")
            store.close()


class CLITests(unittest.TestCase):
    def test_invalid_question(self):
        with patch("svenbot.cli.make_engine", return_value=(Engine(Settings()), None)):
            from contextlib import redirect_stderr
            from io import StringIO
            err = StringIO()
            with redirect_stderr(err):
                self.assertEqual(main(["ask", "   "]), 1)
            self.assertIn("Prompt must not be empty", err.getvalue())

    def test_api_handler_is_available(self):
        self.assertTrue(issubclass(handler_factory(Settings(), ":memory:"), object))


if __name__ == "__main__":
    unittest.main()
