"""First-run discovery contract: read-only, bounded, honest and predictable."""
import contextlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from svenbot import discovery
from svenbot.cli import main, make_engine, parser
from svenbot.engine import Settings
from svenbot.providers import BackendError
from svenbot.server import handler_factory


class ParsingTests(unittest.TestCase):
    def test_sorts_smallest_and_deduplicates(self):
        models = discovery.parse_ollama_tags({'models': [
            {'name': 'big:latest', 'size': 7_000_000_000},
            {'name': 'tiny:latest', 'size': 50, 'details': {'parameter_size': '0.5B', 'quantization_level': 'Q4'}},
            {'name': 'big:latest', 'size': 7_000_000_000},
            {'name': 'unmetered:latest', 'size': None},
        ]})
        self.assertEqual([m.name for m in models], ['tiny:latest', 'big:latest', 'unmetered:latest'])
        self.assertEqual(discovery.recommend_installed(models).name, 'tiny:latest')
        self.assertEqual(models[0].parameter_size, '0.5B')

    def test_malicious_names_and_values_are_ignored_not_echoed(self):
        models = discovery.parse_ollama_tags({'models': [
            {'name': 'bad\x1b[31m', 'size': 100},
            {'name': '--evil;curl example', 'size': 100},
            {'name': 'bad\nnewline', 'size': 100},
            {'name': 'fine/model:tag', 'size': -1},
            {'name': 'bool:size', 'size': True},
            {'name': 'weird:size', 'size': 1.3},
            {'name': 'normal', 'size': 100, 'details': {'parameter_size': '\x1b[31m'}},
        ]})
        self.assertEqual([m.name for m in models], ['normal', 'bool:size', 'fine/model:tag', 'weird:size'])
        self.assertTrue(all(m.disk_bytes is None for m in models[1:]))
        self.assertIsNone(models[0].parameter_size)

    def test_refuses_malformed_and_unbounded_tag_lists(self):
        for bad in ({}, {'models': {}}, {'models': [None] * (discovery.MAX_MODELS + 1)}):
            with self.assertRaises(BackendError):
                discovery.parse_ollama_tags(bad)

    def test_advisory_skips_obvious_embedding_only_names(self):
        models = [discovery.InstalledModel('nomic-embed-text:latest', 100),
                  discovery.InstalledModel('phi:latest', 1_000_000)]
        self.assertEqual(discovery.recommend_installed(models).name, 'phi:latest')
        self.assertIsNone(discovery.recommend_installed(models[:1]))

    def test_unknown_disk_size_never_beats_measured_size(self):
        models = [discovery.InstalledModel('unknown', None), discovery.InstalledModel('known', 1_000_000)]
        self.assertEqual(discovery.recommend_installed(models, budget=1).name, 'known')
        self.assertIsNone(discovery.recommend_installed([]))

    @patch('svenbot.discovery.container_memory_limit_bytes', return_value=4 * 1024**3)
    @patch('svenbot.discovery.physical_memory_bytes', return_value=64 * 1024**3)
    def test_container_limit_not_host_memory(self, *_):
        self.assertEqual(discovery.memory_budget_bytes(), 4 * 1024**3)


class ModelsEndpoint(BaseHTTPRequestHandler):
    paths = []

    def do_GET(self):
        self.paths.append(('GET', self.path))
        if self.path == '/api/tags':
            data = {'models': [{'name': 'two:latest', 'size': 2_000_000_000,
                                'details': {'parameter_size': '2B', 'quantization_level': 'Q4_0'}},
                               {'name': 'one:latest', 'size': 500_000_000}]}
        elif self.path == '/v1/models':
            data = {'data': [{'id': 'server-model'}]}
        else:
            self.send_error(404)
            return
        raw = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.paths.append(('POST', self.path))
        self.send_error(405)

    def log_message(self, *_):
        pass


class LocalProbeTests(unittest.TestCase):
    def setUp(self):
        ModelsEndpoint.paths = []
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ModelsEndpoint)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_local_discovery_performs_only_gets(self):
        report = discovery.survey(self.url, self.url)
        self.assertEqual(report['backends'], {'ollama': 'ready', 'openai': 'ready'})
        self.assertEqual(report['suggested_ollama_model'], 'one:latest')
        self.assertEqual(report['compatible_models'], ['server-model'])
        self.assertEqual(ModelsEndpoint.paths, [('GET', '/api/tags'), ('GET', '/v1/models')])
        self.assertNotIn('fit', report['recommendation_basis'])

    def test_cli_setup_json_without_downloading(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = main(['setup', '--ollama-url', self.url, '--openai-url', self.url, '--json'])
        self.assertEqual(result, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data['suggested_ollama_model'], 'one:latest')
        self.assertTrue(all(method == 'GET' for method, _ in ModelsEndpoint.paths))

    def test_cli_models_renders_installed_models(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = main(['models', '--ollama-url', self.url])
        self.assertEqual(result, 0)
        self.assertIn('one:latest', out.getvalue())
        self.assertIn('GiB on disk', out.getvalue())

    def test_cli_discovers_instead_of_hardcoding_llama32(self):
        args = parser().parse_args(['ask', 'hello', '--backend', 'ollama', '--ollama-url', self.url])
        engine, store = make_engine(args)
        self.assertIsNone(store)
        self.assertIsNone(engine.settings.model)
        self.assertEqual(engine.settings.ollama_suggested_model, 'one:latest')
        self.assertEqual(ModelsEndpoint.paths, [('GET', '/api/tags')])

    def test_auto_fallback_uses_openai_alias_not_suggested_ollama_tag(self):
        args = parser().parse_args(['ask', 'hello', '--backend', 'auto', '--ollama-url', self.url])
        engine, _ = make_engine(args)
        with patch('svenbot.engine.chat_ollama', side_effect=BackendError('offline')) as ollama:
            with patch('svenbot.engine.chat_openai', return_value='ok') as openai:
                self.assertEqual(engine.ask('hello').backend, 'openai')
        self.assertEqual(ollama.call_args.kwargs['model'], 'one:latest')
        self.assertEqual(openai.call_args.kwargs['model'], 'local')

    def test_explicit_model_never_probes(self):
        args = parser().parse_args(['ask', 'hello', '--backend', 'ollama', '--ollama-url', self.url,
                                    '--model', 'custom:latest'])
        engine, store = make_engine(args)
        self.assertEqual(engine.settings.model, 'custom:latest')
        self.assertEqual(ModelsEndpoint.paths, [])

    def test_block_remote_probe_even_when_local_server_is_not_reachable(self):
        with self.assertRaises(BackendError):
            discovery.list_ollama_models('https://ollama.example')
        self.assertEqual(discovery.survey('https://ollama.example', 'https://llamacpp.example')['backends'],
                         {'ollama': 'unavailable', 'openai': 'unavailable'})

    def test_status_api_requires_same_origin_and_is_read_only(self):
        status_handler = handler_factory(Settings(ollama_url=self.url, openai_url=self.url), ':memory:')
        with ThreadingHTTPServer(('127.0.0.1', 0), status_handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                addr = f'127.0.0.1:{server.server_port}'
                def request(headers):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    connection.request('GET', '/v1/local/status', headers=headers)
                    resp = connection.getresponse()
                    status, body = resp.status, resp.read()
                    connection.close()
                    return status, body
                status, raw = request({'Host': addr})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw)['suggested_ollama_model'], 'one:latest')
                self.assertEqual(request({'Host': 'evil.example'})[0], 403)
                self.assertEqual(request({'Host': addr, 'Origin': 'https://evil.example'})[0], 403)
                self.assertTrue(all(method == 'GET' for method, _ in ModelsEndpoint.paths))
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_browser_launch_is_explicit_opt_in(self):
        self.assertFalse(parser().parse_args(['web']).open_browser)
        self.assertTrue(parser().parse_args(['web', '--open-browser']).open_browser)

    def test_unknown_compatible_models_not_misreported_as_ollama(self):
        report = discovery.survey('http://127.0.0.1:1', self.url)
        self.assertEqual(report['backends']['ollama'], 'unavailable')
        self.assertEqual(report['backends']['openai'], 'ready')
        self.assertIsNone(report['suggested_ollama_model'])


if __name__ == '__main__':
    unittest.main()
