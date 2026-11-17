"""Loopback-only knowledge API privacy, read-only behavior, and HTML safety."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from svenbot.engine import Settings
from svenbot.server import handler_factory
from svenbot.store import Store


class KnowledgeAPITests(unittest.TestCase):
    def serve(self, settings, db):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_factory(settings, str(db)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return server

    @staticmethod
    def request(server, route, *, method='GET', body=None, headers=None):
        host = f'127.0.0.1:{server.server_port}'
        hdrs = {'Host': host}
        if headers: hdrs.update(headers)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        conn.request(method, route, body=body, headers=hdrs)
        result = conn.getresponse()
        raw = result.read()
        status = result.status
        content_type = result.getheader('Content-Type')
        conn.close()
        return status, raw, content_type

    def test_api_denies_index_access_without_explicit_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            srv = self.serve(Settings(backend='rules'), Path(tmp) / 'index.db')
            code, _, _ = self.request(srv, '/v1/local/library')
            self.assertEqual(code, 409)
            code, _, _ = self.request(srv, '/v1/local/search', method='POST',
                                      body=b'{"query":"hello"}', headers={'Content-Type':'application/json'})
            self.assertEqual(code, 409)
            self.assertFalse((Path(tmp) / 'index.db').exists())

    def test_library_and_search_do_not_invoke_model_or_mutate_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'receipts.html'
            source.write_text('<p>Invoice 4873 is paid.</p>')
            store = Store(root / 'index.db')
            store.add_path(source, root)
            before = store.list_files(root)
            store.close()
            srv = self.serve(Settings(backend='rules', workspace=str(root)), root / 'index.db')
            status, raw, mime = self.request(srv, '/v1/local/library')
            self.assertEqual(status, 200)
            self.assertIn('application/json', mime)
            self.assertEqual(json.loads(raw)['files'], before)
            status, raw, _ = self.request(srv, '/v1/local/search', method='POST',
                                          body=json.dumps({'query': 'Invoice'}),
                                          headers={'Content-Type': 'application/json'})
            self.assertEqual(status, 200)
            hits = json.loads(raw)['results']
            self.assertEqual(hits[0]['path'], 'receipts.html')
            self.assertIn('4873', hits[0]['excerpt'])
            check = Store(root / 'index.db')
            try:
                self.assertEqual(check.list_files(root), before)
            finally:
                check.close()

    def test_reject_cross_origin_invalid_queries_and_oversized_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            srv = self.serve(Settings(backend='rules', workspace=tmp), Path(tmp) / 'index.db')
            args = {'method':'POST', 'body':'{"query":"ok"}', 'headers':{'Content-Type':'application/json'}}
            for hdr in ({'Origin':'https://evil.example'}, {'Sec-Fetch-Site':'cross-site'}, {'Host':'spoofed.example'}):
                opts = {**args, 'headers': {**args['headers'], **hdr}}
                self.assertEqual(self.request(srv, '/v1/local/search', **opts)[0], 403)
            for body in ('{"query":""}', '{"query":123}', '{', json.dumps({'query':'x'*257})):
                self.assertEqual(self.request(srv, '/v1/local/search', method='POST', body=body,
                             headers={'Content-Type':'application/json'})[0], 400)
            self.assertEqual(self.request(srv, '/v1/local/search', method='POST', body='x'*4097,
                             headers={'Content-Type':'application/json'})[0], 400)
            self.assertEqual(self.request(srv, '/v1/local/search', method='POST', body='abc',
                             headers={'Content-Type':'text/plain'})[0], 415)
            self.assertEqual(self.request(srv, '/v1/local/search')[0], 404)

    def test_ui_assets_expose_knowledge_navigation_without_remote_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            srv = self.serve(Settings(backend='rules'), Path(tmp) / 'index.db')
            status, raw, _ = self.request(srv, '/')
            self.assertEqual(status, 200)
            html = raw.decode()
            self.assertIn('id="knowledge-panel"', html)
            self.assertIn('id="knowledge-top"', html)
            self.assertNotIn('<script src="https:', html)
            status, raw, _ = self.request(srv, '/app.js')
            self.assertEqual(status, 200)
            self.assertIn("textContent = item.excerpt", raw.decode())


if __name__ == '__main__':
    unittest.main()
