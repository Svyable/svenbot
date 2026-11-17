"""End-to-end streaming protocol, interruption and browser trust-boundary tests."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from svenbot.cli import parser
from svenbot.engine import Answer, Engine, Settings, StreamPart
from svenbot.providers import BackendError, stream_ollama, stream_openai
from svenbot.server import handler_factory
from svenbot.store import Store


def fake_response(chunks, *, close=True):
    def reply(*_, **__):
        for c in chunks:
            if isinstance(c, BaseException):
                raise c
            yield c
    return reply


class ProviderStreamingTests(unittest.TestCase):
    @patch('svenbot.providers._stream_lines')
    def test_ollama_deltas_complete(self, lines):
        lines.return_value = iter([
            '{"message":{"content":"Hello "},"done":false}',
            '{"message":{"content":"world"},"done":false}',
            '{"done":true}',
        ])
        self.assertEqual(list(stream_ollama([{'role': 'user', 'content': 'x'}], model='local',
                                            base_url='http://localhost:11434')), ['Hello ', 'world'])
        self.assertEqual(lines.call_args.args[1], '/api/chat')
        self.assertTrue(lines.call_args.args[2]['stream'])

    @patch('svenbot.providers._stream_lines')
    def test_ollama_truncated_stream_fails_closed(self, lines):
        lines.return_value = iter(['{"message":{"content":"partial"},"done":false}'])
        stream = stream_ollama([], model='local', base_url='http://localhost:11434')
        self.assertEqual(next(stream), 'partial')
        with self.assertRaisesRegex(BackendError, 'ended before completion'):
            next(stream)

    @patch('svenbot.providers._stream_lines')
    def test_ollama_upstream_error_rejected(self, lines):
        lines.return_value = iter(['{"error":"private data should not leak"}'])
        with self.assertRaisesRegex(BackendError, 'streaming error') as exc:
            list(stream_ollama([], model='local', base_url='http://localhost:11434'))
        self.assertNotIn('private data', str(exc.exception))

    @patch('svenbot.providers._stream_lines')
    def test_openai_multiline_sse_heartbeat_and_done(self, lines):
        lines.return_value = iter([
            ': keepalive', '',
            'data: {"choices":[{"delta":{"content":"a"}}]}', '',
            'event: message',
            'data: {"choices":[{"delta":{"content":"b"}}]}', '',
            'data: [DONE]', '',
        ])
        self.assertEqual(list(stream_openai([], model='local', base_url='http://127.0.0.1:8080')),
                         ['a', 'b'])
        self.assertEqual(lines.call_args.args[1], '/v1/chat/completions')

    @patch('svenbot.providers._stream_lines')
    def test_openai_missing_done_fails(self, lines):
        lines.return_value = iter(['data: {"choices":[{"delta":{"content":"not done"}}]}', ''])
        with self.assertRaisesRegex(BackendError, r'without \[DONE\]'):
            list(stream_openai([], model='local', base_url='http://127.0.0.1:8080'))

    @patch('svenbot.providers._stream_lines')
    def test_malformed_sse_fails(self, lines):
        lines.return_value = iter(['data: {"choices":[]}', ''])
        with self.assertRaises(BackendError):
            list(stream_openai([], model='local', base_url='http://127.0.0.1:8080'))


class EngineStreamTests(unittest.TestCase):
    @patch('svenbot.engine.stream_openai', fake_response(['second provider']))
    @patch('svenbot.engine.stream_ollama', fake_response([BackendError('offline')]))
    def test_fallback_before_first_token(self):
        parts = list(Engine(Settings()).stream('hello'))
        self.assertEqual([p.backend for p in parts], ['openai', 'openai'])
        self.assertEqual(parts[0].text, 'second provider')
        self.assertTrue(parts[-1].done)
        self.assertEqual([p.status for p in parts[-1].attempts], ['unavailable', 'ok'])

    @patch('svenbot.engine.stream_openai')
    @patch('svenbot.engine.stream_ollama', fake_response(['partial', BackendError('private failure')]))
    def test_no_fallback_after_first_token_or_partial_history(self, openai):
        engine = Engine(Settings())
        stream = engine.stream('private prompt')
        self.assertEqual(next(stream).text, 'partial')
        with self.assertRaisesRegex(BackendError, 'answer not saved') as exc:
            next(stream)
        self.assertNotIn('private failure', str(exc.exception))
        self.assertEqual(engine._history, [])
        openai.assert_not_called()

    @patch('svenbot.engine.stream_ollama', fake_response(['hello ', 'world']))
    def test_completed_stream_commits_whole_reply(self):
        engine = Engine(Settings(backend='ollama'))
        parts = list(engine.stream('one'))
        self.assertTrue(parts[-1].done)
        self.assertEqual(engine._history, [{'role': 'user', 'content': 'one'},
                                           {'role': 'assistant', 'content': 'hello world'}])

    @patch('svenbot.engine.stream_ollama', fake_response(['partial']))
    def test_closing_stream_does_not_save_incomplete_reply(self):
        engine = Engine(Settings(backend='ollama'))
        iterator = engine.stream('one')
        self.assertEqual(next(iterator).text, 'partial')
        iterator.close()
        self.assertEqual(engine._history, [])

    @patch('svenbot.engine.stream_ollama', fake_response(['hello']))
    def test_caller_supplied_history_is_not_persisted(self):
        engine = Engine(Settings(backend='ollama'))
        list(engine.stream('one', prior=[{'role': 'user', 'content': 'previous'}]))
        self.assertEqual(engine._history, [])

    @patch('svenbot.engine.stream_ollama', fake_response(['persist me']))
    def test_sqlite_history_only_saved_on_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'db.sqlite')
            engine = Engine(Settings(backend='ollama', session='demo', workspace=temp), store)
            iterator = engine.stream('first')
            next(iterator)
            self.assertEqual(store.history(engine.workspace, 'demo'), [])
            list(iterator)
            self.assertEqual(len(store.history(engine.workspace, 'demo')), 2)
            store.close()

    @patch('svenbot.engine.stream_ollama', fake_response(['x' * 128_001]))
    def test_oversized_reply_is_not_committed(self):
        engine = Engine(Settings(backend='ollama'))
        with self.assertRaises(BackendError):
            list(engine.stream('x'))
        self.assertEqual(engine._history, [])


class FixtureEngine:
    def __init__(self, *_):
        pass

    def ask(self, *_, **__):
        return Answer('complete', 'rules')

    def stream(self, *_, **__):
        yield StreamPart('Hello ', 'rules')
        yield StreamPart('world', 'rules')
        yield StreamPart('', 'rules', done=True)


class ServerStreamingTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch('svenbot.server.Engine', FixtureEngine)
        self.patch.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_factory(Settings(backend='rules'), ':memory:'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f'127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.patch.stop()

    def request(self, method, path, *, headers=None, payload=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        hdr = {'Host': self.host}
        hdr.update(headers or {})
        conn.request(method, path, body=payload, headers=hdr)
        resp = conn.getresponse()
        status, head, raw = resp.status, dict(resp.getheaders()), resp.read()
        conn.close()
        return status, head, raw

    def body(self, stream=True):
        return json.dumps({'model': 'svenbot', 'stream': stream,
                           'messages': [{'role': 'user', 'content': 'hello'}]})

    def test_local_ui_is_served_without_external_assets(self):
        for path, mime in [('/', 'text/html'), ('/app.js', 'text/javascript'),
                           ('/style.css', 'text/css')]:
            status, head, raw = self.request('GET', path)
            self.assertEqual(status, 200, path)
            self.assertIn(mime, head['Content-Type'])
            self.assertTrue(raw)
            self.assertIn("script-src 'self'", head['Content-Security-Policy'])
            self.assertNotIn('unsafe-inline', head['Content-Security-Policy'])
        status, _, page = self.request('GET', '/')
        self.assertNotIn(b'http://cdn.', page)
        self.assertIn(b'Stay local.', page)

    def test_sse_protocol_contains_done_and_backend(self):
        status, head, raw = self.request('POST', '/v1/chat/completions',
                                         headers={'Content-Type': 'application/json',
                                                  'Origin': f'http://{self.host}',
                                                  'Sec-Fetch-Site': 'same-origin'},
                                         payload=self.body())
        self.assertEqual(status, 200)
        self.assertIn('text/event-stream', head['Content-Type'])
        self.assertIn(b'"content": "Hello "', raw)
        self.assertIn(b'"svenbot_backend": "rules"', raw)
        self.assertIn(b'"finish_reason": "stop"', raw)
        self.assertTrue(raw.endswith(b'data: [DONE]\n\n'))

    def test_non_streaming_compatibility(self):
        status, _, raw = self.request('POST', '/v1/chat/completions',
                                      headers={'Content-Type': 'application/json'},
                                      payload=self.body(stream=False))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['choices'][0]['message']['content'], 'complete')

    def test_cross_site_requests_remain_forbidden(self):
        for headers in [
            {'Origin': 'https://evil.example'},
            {'Origin': 'null'},
            {'Origin': f'http://{self.host}', 'Sec-Fetch-Site': 'cross-site'},
            {'Host': 'evil.example'},
        ]:
            status, _, _ = self.request('POST', '/v1/chat/completions',
                                        headers={'Content-Type': 'application/json', **headers},
                                        payload=self.body())
            self.assertEqual(status, 403, headers)

    def test_reject_invalid_stream_flag_and_mime(self):
        body = json.dumps({'stream': 'true', 'messages': [{'role': 'user', 'content': 'x'}]})
        self.assertEqual(self.request('POST', '/v1/chat/completions',
                                      headers={'Content-Type': 'application/json'}, payload=body)[0], 400)
        self.assertEqual(self.request('POST', '/v1/chat/completions',
                                      headers={'Content-Type': 'text/plain'}, payload=self.body())[0], 415)

    @patch('svenbot.server.Engine')
    def test_partial_stream_error_is_not_misrepresented_as_done(self, factory):
        class Broken:
            def stream(self, *_, **__):
                yield StreamPart('part', 'ollama')
                raise BackendError('prompt and secret endpoint')
        factory.return_value = Broken()
        status, _, raw = self.request('POST', '/v1/chat/completions',
                                      headers={'Content-Type': 'application/json'}, payload=self.body())
        self.assertEqual(status, 200)
        self.assertIn(b'event: error', raw)
        self.assertNotIn(b'data: [DONE]', raw)
        self.assertNotIn(b'prompt and secret endpoint', raw)


class CLIFeatureTests(unittest.TestCase):
    def test_web_chat_and_ask_commands_exist(self):
        self.assertEqual(parser().parse_args(['web']).port, 8765)
        self.assertTrue(parser().parse_args(['ask', 'hello', '--stream']).stream)
        self.assertTrue(parser().parse_args(['chat', '--no-stream']).no_stream)

    def test_static_files_ship_as_package_resources(self):
        for file in ('index.html', 'app.js', 'style.css'):
            self.assertTrue(resources.files('svenbot').joinpath('ui', file).read_bytes())


if __name__ == '__main__':
    unittest.main()

class LiveLoopbackFixtureTests(unittest.TestCase):
    """Actual HTTP transport (a fake local server, never an internet endpoint)."""
    def setUp(self):
        self.requests = []
        received = self.requests
        class Upstream(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_POST(self):
                size = int(self.headers.get('Content-Length', '0'))
                payload = json.loads(self.rfile.read(size))
                received.append((self.path, payload))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', 'https://example.com/steal')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                if self.path == '/overflow':
                    raw = b'x' * 66000
                elif self.path == '/api/chat':
                    raw = (b'{"message":{"content":"real "},"done":false}\n'
                           b'{"message":{"content":"loopback"},"done":false}\n'
                           b'{"done":true}\n')
                else:
                    raw = (b'data: {"choices":[{"delta":{"content":"local"}}]}\n\n'
                           b'data: [DONE]\n\n')
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson' if self.path == '/api/chat'
                                 else 'text/event-stream')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_genuine_ollama_transport_and_engine_history(self):
        engine = Engine(Settings(backend='ollama', ollama_url=self.base))
        parts = list(engine.stream('run the fixture'))
        self.assertEqual(''.join(p.text for p in parts), 'real loopback')
        self.assertTrue(parts[-1].done)
        self.assertEqual(engine._history[-1]['content'], 'real loopback')
        self.assertEqual(self.requests[0][0], '/api/chat')
        self.assertTrue(self.requests[0][1]['stream'])

    def test_genuine_openai_sse_transport(self):
        self.assertEqual(list(stream_openai([{'role': 'user', 'content': 'x'}],
                                            model='test', base_url=self.base)), ['local'])
        self.assertEqual(self.requests[-1][0], '/v1/chat/completions')

    def test_stream_line_is_bounded_and_redirect_never_followed(self):
        from svenbot.providers import _stream_lines
        with self.assertRaisesRegex(BackendError, 'size limits'):
            list(_stream_lines(self.base, '/overflow', {}, timeout=2, allow_remote=False))
        with self.assertRaisesRegex(BackendError, 'redirect'):
            list(_stream_lines(self.base, '/redirect', {}, timeout=2, allow_remote=False))
