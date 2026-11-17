"""Temporary browser documents: extraction, token isolation, streaming and privacy."""
from __future__ import annotations

import base64
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from svenbot.document_sessions import (
    DOCUMENT_TTL_SECONDS, MAX_DOCUMENTS, DocumentVault, DocumentError,
)
from svenbot.engine import Settings
from svenbot.server import handler_factory


def encoded(text):
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


class VaultTests(unittest.TestCase):
    def test_document_expires_and_clear_does_not_reuse_handle(self):
        now = [1000]
        vault = DocumentVault(clock=lambda: now[0])
        handle, doc = vault.upload('safe.html', encoded('<p>Flowering orchid facts.</p>'))
        self.assertEqual(doc.content, 'Flowering orchid facts.')
        self.assertEqual(vault.get(handle).name, 'safe.html')
        self.assertTrue(vault.clear(handle))
        self.assertIsNone(vault.get(handle))
        other, _ = vault.upload('safe.html', encoded('<p>Some details.</p>'))
        self.assertNotEqual(handle, other)
        now[0] += DOCUMENT_TTL_SECONDS + 1
        self.assertIsNone(vault.get(other))
        self.assertFalse(vault.clear(other))

    def test_capacity_is_bounded_but_expiry_releases_space(self):
        now = [50]
        vault = DocumentVault(clock=lambda: now[0])
        for i in range(MAX_DOCUMENTS):
            vault.upload(f'doc{i}.html', encoded('Example data'))
        with self.assertRaisesRegex(DocumentError, 'Four temporary documents'):
            vault.upload('extra.html', encoded('An extra'))
        now[0] += DOCUMENT_TTL_SECONDS + 1
        self.assertTrue(vault.upload('new.html', encoded('Allowed again'))[0])

    def test_reject_path_and_control_character_filenames(self):
        vault = DocumentVault()
        for name in ('../notes.html', 'C:\\notes.html', '.hidden.html', 'demo\x1b.html', 'a\n.html', 'evil\u202ehtml.pdf', 'x' * 121):
            with self.subTest(name=name), self.assertRaises(DocumentError):
                vault.upload(name, encoded('<p>text</p>'))

    def test_reject_malformed_data_and_large_or_empty_documents(self):
        vault = DocumentVault()
        for content in ('!', encoded(''), 'x' * 1_400_000, 'AAAA===='):
            with self.subTest(sample=content[:12]), self.assertRaises(DocumentError):
                vault.upload('doc.html', content)
        with self.assertRaisesRegex(DocumentError, '180,000'):
            vault.upload('big.html', encoded('Z' * 180_001))

    def test_html_scripts_are_not_included_in_extracted_text(self):
        vault = DocumentVault()
        _, doc = vault.upload('doc.html', encoded('<script>alert(1)</script><p>Actual invoice 7301</p>'))
        self.assertIn('invoice 7301', doc.content)
        self.assertNotIn('alert(1)', doc.content)


class BrowserDocumentAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def serve(self, settings=None):
        srv = ThreadingHTTPServer(('127.0.0.1', 0), handler_factory(settings or Settings(backend='ollama'),
                                                                    str(Path(self.temp.name)/'index.sqlite')))
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(srv.shutdown)
        return srv

    @staticmethod
    def request(server, route, payload=None, *, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        default_headers = {'Content-Type': 'application/json',
                           'Host': f'127.0.0.1:{server.server_port}'}
        default_headers.update(headers or {})
        raw = json.dumps(payload).encode('utf-8') if isinstance(payload, dict) else payload
        conn.request('POST', route, body=raw, headers=default_headers)
        response = conn.getresponse()
        content = response.read()
        code = response.status
        conn.close()
        try:
            data = json.loads(content)
        except (ValueError, UnicodeError):
            data = content.decode('utf-8', 'replace')
        return code, data

    def upload(self, srv, body='<p>Quarterly invoice 7301 was approved.</p>'):
        return self.request(srv, '/v1/local/document',
                            {'filename': 'invoice.html', 'content_base64': encoded(body)})

    def test_upload_clear_unknown_and_no_disk_persistence(self):
        srv = self.serve()
        code, data = self.upload(srv)
        self.assertEqual(code, 201)
        self.assertEqual(data['stored'], 'server_memory_only')
        self.assertEqual(data['expires_in_seconds'], DOCUMENT_TTL_SECONDS)
        self.assertFalse((Path(self.temp.name) / 'index.sqlite').exists())
        token = data['document_id']
        code, clear = self.request(srv, '/v1/local/document/clear', {'document_id': token})
        self.assertEqual((code, clear['cleared']), (200, True))
        code, clear = self.request(srv, '/v1/local/document/clear', {'document_id': token})
        self.assertEqual((code, clear['cleared']), (200, False))
        self.assertFalse((Path(self.temp.name) / 'index.sqlite').exists())

    @patch('svenbot.engine.chat_ollama', return_value='Invoice approved [source 1]')
    def test_document_question_uses_only_temporary_sources(self, model):
        srv = self.serve(Settings(backend='ollama',workspace=self.temp.name))
        code, uploaded = self.upload(srv)
        self.assertEqual(code, 201)
        code, result = self.request(srv, '/v1/chat/completions', {
            'model':'svenbot', 'stream':False,
            'document_id':uploaded['document_id'],
            'messages':[{'role':'user', 'content':'What happened to invoice 7301?'}]
        })
        self.assertEqual(code, 200)
        self.assertIn('invoice 7301', model.call_args.args[0][0]['content'])
        self.assertEqual(result['svenbot_sources'][0]['path'], 'invoice.html')
        self.assertEqual(result['choices'][0]['message']['content'], 'Invoice approved [source 1]')
        self.assertFalse((Path(self.temp.name) / 'index.sqlite').exists())

    @patch('svenbot.engine.stream_ollama', return_value=iter(['Approved ', 'for Q4']))
    def test_document_stream_annotated_and_terminated(self, model):
        srv = self.serve()
        _, uploaded = self.upload(srv)
        code, response = self.request(srv, '/v1/chat/completions', {
            'model':'svenbot', 'stream':True, 'document_id':uploaded['document_id'],
            'messages':[{'role':'user','content':'invoice approved'}]
        })
        self.assertEqual(code, 200)
        self.assertIn('data: [DONE]', response)
        self.assertIn('svenbot_sources', response)
        self.assertIn('Approved ', response)
        self.assertIn('for Q4', response)
        self.assertIn('invoice 7301', model.call_args.args[0][0]['content'])

    @patch('svenbot.engine.chat_ollama', return_value='Not saved')
    def test_document_clear_revokes_capability_and_no_stale_fallback(self, model):
        srv = self.serve()
        _, uploaded = self.upload(srv)
        token = uploaded['document_id']
        self.request(srv, '/v1/local/document/clear', {'document_id': token})
        code, result = self.request(srv, '/v1/chat/completions', {
            'model':'svenbot','document_id':token,
            'messages':[{'role':'user','content':'What does it say?'}]
        })
        self.assertEqual(code, 404)
        model.assert_not_called()

    def test_rules_only_backend_cannot_respond_to_document(self):
        srv = self.serve(Settings(backend='rules'))
        _, doc = self.upload(srv)
        code, resp = self.request(srv, '/v1/chat/completions', {
            'document_id':doc['document_id'],'messages':[{'role':'user','content':'explain'}]
        })
        self.assertEqual(code, 503)
        self.assertIn('requires a local LLM', resp['error'])

    def test_remote_configuration_denies_upload_and_doc_completion(self):
        srv = self.serve(Settings(backend='ollama',allow_remote=True))
        code, resp = self.upload(srv)
        self.assertEqual(code, 403)
        self.assertIn('--allow-remote', resp['error'])
        code, _ = self.request(srv, '/v1/chat/completions', {
            'document_id':'fake','messages':[{'role':'user','content':'test'}]
        })
        self.assertEqual(code, 403)

    def test_bad_base64_size_mime_origin_and_host_are_rejected(self):
        srv = self.serve()
        request = {'filename':'invoice.html','content_base64':encoded('Hello')}
        for headers, expected in [({'Origin':'https://attacker.invalid'},403),
                                  ({'Sec-Fetch-Site':'cross-site'},403),
                                  ({'Host':'untrusted.example'},403),
                                  ({'Content-Type':'text/plain'},415)]:
            code, _ = self.request(srv, '/v1/local/document', request, headers=headers)
            self.assertEqual(code, expected)
        for value in ('%invalid!', 'x' * 1_340_000):
            code, _ = self.request(srv, '/v1/local/document',
                                   {'filename':'invoice.html','content_base64':value})
            self.assertEqual(code, 400)

    @patch('svenbot.engine.chat_ollama', return_value='Constrained response')
    def test_document_tokens_do_not_cross_pollinate_or_read_workspace(self, model):
        root = Path(self.temp.name)
        (root / 'secret.md').write_text('Workspace-only sapphire expression')
        from svenbot.store import Store
        store = Store(root / 'index.sqlite')
        store.add_path(root / 'secret.md', root)
        store.close()
        srv = self.serve(Settings(backend='ollama', workspace=str(root)))
        _, first = self.upload(srv, '<p>Document alpha has green-orchid data.</p>')
        _, second = self.upload(srv, '<p>Document beta has blue-parrot data.</p>')
        for token, expected, absent in [
            (first['document_id'], 'green-orchid', 'blue-parrot'),
            (second['document_id'], 'blue-parrot', 'green-orchid'),
        ]:
            code, data = self.request(srv, '/v1/chat/completions', {
                'document_id':token, 'messages':[{'role':'user','content':'summarize'}]
            })
            self.assertEqual(code, 200)
            system = model.call_args.args[0][0]['content']
            self.assertIn(expected, system)
            self.assertNotIn(absent, system)
            self.assertNotIn('sapphire', system)
            self.assertEqual(data['svenbot_sources'][0]['path'], 'invoice.html')

    @patch('svenbot.engine.chat_ollama', return_value='Cannot be reached')
    def test_null_document_handle_fails_closed_instead_of_retrieving_library(self, model):
        srv = self.serve(Settings(backend='ollama',workspace=self.temp.name))
        code, data = self.request(srv, '/v1/chat/completions', {
            'document_id':None, 'messages':[{'role':'user','content':'sensitive'}]
        })
        self.assertEqual(code, 404)
        model.assert_not_called()

    @patch('svenbot.engine.chat_ollama', return_value='Contextual response')
    def test_request_history_passed_through_but_not_persisted(self, model):
        srv = self.serve(Settings(backend='ollama', workspace=self.temp.name, session='private'))
        _, uploaded = self.upload(srv)
        code, _ = self.request(srv, '/v1/chat/completions', {
            'document_id':uploaded['document_id'],
            'messages':[{'role':'user','content':'Earlier question'},
                        {'role':'assistant','content':'Earlier answer'},
                        {'role':'user','content':'Explain the invoice'}]
        })
        self.assertEqual(code, 200)
        payload = model.call_args.args[0]
        self.assertEqual(payload[1]['content'], 'Earlier question')
        self.assertEqual(payload[2]['content'], 'Earlier answer')
        self.assertFalse((Path(self.temp.name) / 'index.sqlite').exists())

    def test_no_document_is_promoted_to_persistent_knowledge(self):
        srv = self.serve(Settings(backend='ollama',workspace=self.temp.name))
        code, doc = self.upload(srv)
        self.assertEqual(code, 201)
        conn = http.client.HTTPConnection('127.0.0.1', srv.server_port, timeout=5)
        conn.request('GET', '/v1/local/library', headers={'Host':f'127.0.0.1:{srv.server_port}'})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read())['files'], [])
        conn.close()
        self.assertIn('document_id', doc)

    def test_browser_assets_include_explicit_document_flow_and_no_remote_scripts(self):
        srv = self.serve()
        conn = http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=5)
        conn.request('GET','/',headers={'Host':f'127.0.0.1:{srv.server_port}'})
        resp = conn.getresponse(); raw = resp.read().decode(); conn.close()
        self.assertIn('id="document-input"',raw)
        self.assertIn('id="document-clear"',raw)
        self.assertNotIn('https://',raw)
        conn = http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=5)
        conn.request('GET','/app.js',headers={'Host':f'127.0.0.1:{srv.server_port}'})
        resp = conn.getresponse(); script = resp.read().decode(); conn.close()
        self.assertIn('content_base64', script)
        self.assertIn('source_override', Path(__file__).parents[1].joinpath('src/svenbot/engine.py').read_text())
        self.assertNotIn('innerHTML',script)


if __name__ == '__main__':
    unittest.main()
