"""Pairwise page evidence: permissions, provenance, bounds and no remote mutations."""
from __future__ import annotations

import hashlib
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from svenbot.engine import Answer, Settings
from svenbot.extension_bridge import handler_factory, select_comparison

EXTENSION_ID = 'abcdefghijklmnopabcdefghijklmnop'
TOKEN = 'comparison-fixture-' + 't'*50


def comparison():
    return {'question': 'Compare the experiment results and differences.', 'pages': [
        {'title': 'Paper A', 'blocks': [
            {'id':'B1', 'text':'The experiment found an improvement in measured performance.'},
            {'id':'B2', 'text':'Uncertainty remains due to limited sampling.'}]},
        {'title': 'Paper B', 'blocks': [
            {'id':'B1', 'text':'The experiment found no statistically significant improvement.'},
            {'id':'B2', 'text':'The authors repeated trials with more subjects.'}]},
    ]}


class ComparisonValidationTests(unittest.TestCase):
    def test_separate_provenance_and_hashes(self):
        prompt,hits,refs = select_comparison(comparison())
        self.assertIn('Page A and Page B', prompt)
        self.assertEqual([x['page'] for x in refs],['A','A','B','B'])
        self.assertEqual([h.path for h in hits], ['selected-browser-page-A']*2 + ['selected-browser-page-B']*2)
        self.assertEqual([x['page_title'] for x in refs], ['Paper A','Paper A','Paper B','Paper B'])
        self.assertEqual([x['block_id'] for x in refs], ['B1','B2','B1','B2'])
        for hit,ref in zip(hits,refs):
            self.assertEqual(ref['text'], hit.excerpt)
            self.assertEqual(ref['sha256'], hit.chunk_id)
            self.assertEqual(hit.chunk_id,hashlib.sha256(hit.excerpt.encode('utf-8')).hexdigest())

    def test_fail_closed_for_malformed_pages(self):
        base = comparison()
        cases = [
            {'question':'x','pages':[]},
            {'question':'x','pages':[base['pages'][0]]},
            {'question':'x','pages':[base['pages'][0]]*3},
            {'question':'x','pages':[base['pages'][0],{'title':'empty','blocks':[]}]},
            {'question':'x','pages':[base['pages'][0],{'title':'B','blocks':[{'id':'B1','text':'x'*801}]}]},
            {'question':'x','pages':[base['pages'][0],{'title':'B','blocks':[{'id':'B1','text':'aaa','url':'https://secret'}]}]},
            {'question':'x','pages':base['pages'], 'execute':'click'},
            {'question':'x'*1001,'pages':base['pages']},
            {'question':'x','pages':'not-a-list'},
        ]
        for case in cases:
            with self.subTest(case=str(case)[:65]),self.assertRaises(ValueError):
                select_comparison(case)


class ComparisonHttpTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1',0),handler_factory(Settings(backend='ollama',model='fixture'),EXTENSION_ID,TOKEN))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=3)

    def request(self, method='POST', path='/v1/extension/compare', payload=None, *, token=TOKEN, origin=None):
        con=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        headers={'Host':f'127.0.0.1:{self.server.server_port}',
                 'Origin':origin or 'chrome-extension://'+EXTENSION_ID,
                 'X-Svenbot-Token':token,'Content-Type':'application/json'}
        body=json.dumps(comparison() if payload is None else payload)
        con.request(method,path,body=body,headers=headers)
        r=con.getresponse(); code=r.status; headers=dict(r.getheaders()); raw=r.read();con.close()
        return code,headers,json.loads(raw) if raw else None

    @patch('svenbot.extension_bridge.Engine.ask',return_value=Answer('A and B citations [source 1] [source 3]','ollama'))
    def test_compare_over_real_http_with_mock_model(self,ask):
        code,h,result=self.request()
        self.assertEqual(code,200)
        self.assertEqual(h['Access-Control-Allow-Origin'],'chrome-extension://'+EXTENSION_ID)
        self.assertEqual(result['mode'],'comparison')
        self.assertEqual(len(result['references']),4)
        self.assertEqual([r['page'] for r in result['references']],['A','A','B','B'])
        self.assertIn('User question:',ask.call_args.args[0])
        self.assertEqual(ask.call_args.kwargs['prior'],[])
        self.assertEqual(ask.call_args.kwargs['source_override'][2].path,'selected-browser-page-B')
        self.assertNotIn('http://',json.dumps(result))

    @patch('svenbot.extension_bridge.Engine.ask')
    def test_rejects_wrong_origin_token_oversize_and_mutations_without_inference(self,ask):
        self.assertEqual(self.request(token='wrong')[0],403)
        self.assertEqual(self.request(origin='https://attacker.example')[0],403)
        self.assertEqual(self.request(payload={'do':'click'})[0],400)
        self.assertEqual(self.request(payload={'question':'x','pages':comparison()['pages']*3})[0],400)
        self.assertEqual(self.request(payload='x'*130000)[0],400)
        self.assertEqual(self.request(path='/v1/extension/click')[0],404)
        ask.assert_not_called()

    def test_allowed_preflight_and_denied_bad_origin(self):
        port=self.server.server_port
        for origin,expected in [(f'chrome-extension://{EXTENSION_ID}',204),('https://evil.example',403)]:
            con=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
            con.request('OPTIONS','/v1/extension/compare',headers={
                'Host':f'127.0.0.1:{port}','Origin':origin,
                'Access-Control-Request-Method':'POST',
                'Access-Control-Request-Headers':'content-type,x-svenbot-token'})
            r=con.getresponse();self.assertEqual(r.status,expected);r.read();con.close()


if __name__=='__main__':unittest.main()
