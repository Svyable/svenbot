"""Svenbot Model Lab invariants: local-only, read-only, no model-text retention."""
import copy
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from svenbot.cli import main
from svenbot.model_lab import (
    SYSTEM_INSTRUCTION, evaluate_response, load_cases, messages_for,
    run_lab, save_lab_report,
)
from svenbot.providers import BackendError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'benchmarks' / 'browser-harness-20.jsonl'


class ModelLabContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.digest = load_cases(FIXTURE)

    def test_twenty_canonical_cases_have_expected_categories(self):
        from collections import Counter
        self.assertEqual(len(self.cases), 20)
        self.assertEqual(Counter(c['category'] for c in self.cases),
                         {'extract': 6, 'compare': 4, 'tool': 4, 'code': 4, 'adversarial': 2})
        self.assertEqual(len(self.digest), 64)
        packaged = ROOT / 'src' / 'svenbot' / 'fixtures' / 'browser-harness-20.jsonl'
        self.assertEqual(FIXTURE.read_bytes(), packaged.read_bytes())
        self.assertIn('UNTRUSTED', SYSTEM_INSTRUCTION)

    def test_correct_quotes_and_answer_contract(self):
        c = self.cases[0]
        raw = json.dumps({'answer': 'Reviewers selected Reader B.',
                          'citations': [{'source': 'A:3', 'quote': 'the team selected Reader B'}],
                          'proposal': None})
        score = evaluate_response(c, raw)
        self.assertTrue(score['passed'], score)
        self.assertTrue(all(score['checks'].values()))

    def test_fabricated_quote_wrong_source_extra_field_rejected(self):
        c = self.cases[0]
        base = {'answer': 'Reader B',
                'citations': [{'source': 'A:3', 'quote': 'the team selected Reader B'}],
                'proposal': None}
        for value in (
            {**base, 'citations': [{'source': 'A:3', 'quote': 'unrelated hallucinated text'}]},
            {**base, 'citations': [{'source': 'A:1', 'quote': 'The team evaluated three browser readers'}]},
            {**base, 'citations': [{'source': 'A:3', 'quote': 'the team selected Reader B'}], 'hidden_action': 'submit'},
            {**base, 'proposal': {'tool': 'delete_file', 'args': {'file': 'private'}}},
        ):
            self.assertFalse(evaluate_response(c, json.dumps(value))['passed'])

    def test_duplicate_source_citation_rejected(self):
        c = self.cases[0]
        raw = {'answer': 'Reader B', 'citations': [
            {'source': 'A:3', 'quote': 'the team selected Reader B'},
            {'source': 'A:3', 'quote': 'Final conclusion: the team'}], 'proposal': None}
        self.assertFalse(evaluate_response(c, json.dumps(raw))['checks']['exact_quotes'])

    def test_scored_tool_suggestion_is_never_executed(self):
        c = next(c for c in self.cases if c['id'] == 'tool-find-evidence')
        raw = {'answer': 'Find archival retention text.',
               'citations': [{'source': 'A:1', 'quote': 'archival retention section'}],
               'proposal': {'tool': 'find_text', 'args': {'query': 'archival retention'}}}
        self.assertTrue(evaluate_response(c, json.dumps(raw))['passed'])
        raw['proposal'] = {'tool': 'submit_form', 'args': {'url': 'https://example.invalid'}}
        self.assertFalse(evaluate_response(c, json.dumps(raw))['passed'])

    def test_prompt_injection_string_is_untrusted_evidence(self):
        c = next(c for c in self.cases if c['id'] == 'adversarial-fake-tool-call')
        clean = {'answer': 'The release tag is v2.8.',
                 'citations': [{'source': 'A:1', 'quote': 'Release tag: v2.8.'}],
                 'proposal': None}
        self.assertTrue(evaluate_response(c, json.dumps(clean))['passed'])
        clean['answer'] = 'v2.8 SECRET_LEAK'
        self.assertFalse(evaluate_response(c, json.dumps(clean))['passed'])
        self.assertIn('PAGE INSTRUCTION', messages_for(c)[1]['content'])

    def test_reject_duplicate_ids_invalid_tools_excessive_data(self):
        c = copy.deepcopy(self.cases[0])
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'bad.jsonl'
            p.write_text(json.dumps(c) + '\n' + json.dumps(c) + '\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate case'):
                load_cases(p)
            c['sources'].append(copy.deepcopy(c['sources'][0]))
            p.write_text(json.dumps(c) + '\n')
            with self.assertRaisesRegex(ValueError, 'duplicate or invalid'):
                load_cases(p)
            c['sources'].pop()
            c['expected']['proposal'] = {'tool': 'eval_js', 'args': {'script': 'alert(1)'}}
            p.write_text(json.dumps(c) + '\n')
            with self.assertRaisesRegex(ValueError, 'Disallowed'):
                load_cases(p)
            p.write_bytes(b'{' + b'x' * 500_000)
            with self.assertRaisesRegex(ValueError, '400 KB'):
                load_cases(p)

    def test_remote_is_denied_before_call(self):
        with self.assertRaises(BackendError):
            run_lab(self.cases[:1], self.digest, models=['inkling-2-mini'],
                    base_url='https://models.example.com')

    def test_uninstalled_models_are_not_pulled_in_dry_run(self):
        with patch('svenbot.model_lab.chat_ollama', side_effect=AssertionError('network called')):
            self.assertEqual(main(['model-lab', '--dry-run']), 0)

    def test_missing_model_and_output_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'Specify'):
            run_lab(self.cases[:1], self.digest, models=[])
        with self.assertRaisesRegex(ValueError, 'distinct'):
            run_lab(self.cases[:1], self.digest, models=['mini', 'mini'])
        with self.assertRaisesRegex(ValueError, 'invalid|Invalid'):
            run_lab(self.cases[:1], self.digest, models=[{'not': 'model'}])


class LocalProtocolTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        received = self.received

        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers['Content-Length'])
                payload = json.loads(self.rfile.read(length))
                received.append({'path': self.path, 'payload': payload})
                if self.path == '/api/chat':
                    name = payload['model']
                    if name == 'good-model':
                        is_price = 'maximum daily cost' in payload['messages'][-1]['content']
                        result = {'message': {'content': json.dumps({
                            'answer': '$240' if is_price else 'Reader B was selected',
                            'citations': ([{'source': 'A:1', 'quote': 'daily cap is $240'}] if is_price
                                          else [{'source': 'A:3', 'quote': 'the team selected Reader B'}]),
                            'proposal': None})}}
                    else:
                        result = {'message': {'content': 'not valid JSON'}}
                else:
                    result = {'choices': [{'message': {'content': json.dumps({
                        'answer': 'Reader B', 'citations': [
                            {'source': 'A:3', 'quote': 'the team selected Reader B'}],
                        'proposal': None})}}]}
                wire = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(wire)))
                self.end_headers()
                self.wfile.write(wire)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.cases, self.digest = load_cases(FIXTURE)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_ollama_wire_protocol_routing_scores_and_no_text_in_report(self):
        report = run_lab(self.cases[:2], self.digest,
                         models=['bad-model', 'good-model'], base_url=self.url,
                         runs=1, hardware='test CPU')
        self.assertEqual(len(self.received), 4)
        self.assertEqual([r['payload']['model'] for r in self.received], ['bad-model', 'bad-model', 'good-model', 'good-model'])
        self.assertTrue(all(r['path'] == '/api/chat' for r in self.received))
        self.assertTrue(all(r['payload']['stream'] is False for r in self.received))
        self.assertEqual(report['experimental_route_candidates']['extract']['model'], 'good-model')
        self.assertEqual([r['passed'] for r in report['samples']], [False, False, True, True])
        self.assertIn('No model prompts or generated responses', report['limitations'])
        s = json.dumps(report, ensure_ascii=False)
        self.assertNotIn('The team evaluated three', s)
        self.assertNotIn('the team selected Reader B', s)
        self.assertNotIn('not valid JSON', s)
        self.assertEqual(report['environment']['model_server_memory'], 'not_measured')

    def test_openai_wire_protocol(self):
        report = run_lab(self.cases[:1], self.digest, models=['good-model'],
                         backend='openai', base_url=self.url, runs=1)
        self.assertTrue(report['samples'][0]['passed'])
        self.assertEqual(self.received[0]['path'], '/v1/chat/completions')

    def test_atomic_report_permissions(self):
        report = run_lab(self.cases[:1], self.digest, models=['good-model'], base_url=self.url)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.json'
            save_lab_report(report, path)
            self.assertEqual(json.loads(path.read_text())['schema_version'], 1)
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_cli_renders_report_but_never_raw_response(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'bench.json'
            code = main(['model-lab', '--cases', str(FIXTURE), '--limit', '1',
                         '--model', 'good-model', '--ollama-url', self.url,
                         '--output', str(out), '--hardware', 'test-rig'])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertEqual(json.loads(out.read_text())['environment']['operator_hardware'], 'test-rig')


if __name__ == '__main__':
    unittest.main()
