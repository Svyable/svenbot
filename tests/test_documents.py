"""Real-world document ingestion and zero-persistence single-file Q&A regressions."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from svenbot.cli import main
from svenbot.documents import DocumentError, extract
from svenbot.engine import Engine, Settings
from svenbot.providers import BackendError
from svenbot.store import Store


def docx(*paragraphs):
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>' + ''.join('<w:p><w:r><w:t>' + text + '</w:t></w:r></w:p>' for text in paragraphs)
           + '</w:body></w:document>')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('word/document.xml', xml)
    return data.getvalue()


class ExtractionTests(unittest.TestCase):
    def test_office_document_paragraphs_and_no_xml_noise(self):
        text = extract('report.docx', docx('Revenue rose 21%', 'Operating costs fell'))
        self.assertEqual(text, 'Revenue rose 21%\nOperating costs fell')

    def test_html_ignores_scripts_styles_and_templates(self):
        raw = (b'<html><style>SECRETSTYLES</style><script>SECRETJS</script>'
               b'<h1>Annual notes</h1><p>Net income &amp; forecasts</p>'
               b'<template>SECRETTEMPLATE</template></html>')
        result = extract('notes.HTML', raw)
        self.assertIn('Annual notes', result)
        self.assertIn('Net income & forecasts', result)
        self.assertNotIn('SECRET', result)

    def test_csv_tsv_sanitized_fields_preserve_record_coordinates(self):
        csv_text = extract('inventory.csv', b'SKU,Quantity,Item\nA3,18,"Clamps, red"\n')
        self.assertIn('Record 1: SKU: A3 | Quantity: 18 | Item: Clamps, red', csv_text)
        tab_text = extract('inventory.tsv', b'SKU\tItem\nB7\tBrake pads\n')
        self.assertIn('Record 1: SKU: B7 | Item: Brake pads', tab_text)

    def test_pdf_is_explicitly_optional_and_page_provenance_is_visible(self):
        class FakePage:
            def __init__(self, t): self.t = t
            def extract_text(self): return self.t
        class FakeReader:
            is_encrypted = False
            def __init__(self, stream, strict): self.pages = [FakePage('Findings 2031'), FakePage('Appendix')]
        with patch.dict(sys.modules, {'pypdf': types.SimpleNamespace(PdfReader=FakeReader)}):
            text = extract('report.pdf', b'%PDF-1.4')
        self.assertIn('[PDF page 1]\nFindings 2031', text)
        self.assertIn('[PDF page 2]\nAppendix', text)
        with patch.dict(sys.modules, {'pypdf': None}):
            with self.assertRaisesRegex(DocumentError, 'svenbot\\[documents\\]'):
                extract('report.pdf', b'%PDF-1.4')

    def test_document_parser_limits_and_bomb(self):
        with self.assertRaisesRegex(DocumentError, '8 MB'):
            extract('huge.html', b'x' * 8_000_001)
        oversized = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p>' + 'x'*3_000_001 + '</w:p></w:document>'
        z = io.BytesIO()
        with zipfile.ZipFile(z, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr('word/document.xml', oversized)
        with self.assertRaisesRegex(DocumentError, 'limit'):
            extract('bomb.docx', z.getvalue())

    def test_directory_index_skips_malformed_office_without_transaction_break(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ok.docx').write_bytes(docx('Pipeline milestone agreed'))
            (root / 'broken.docx').write_bytes(b'not a zip')
            store = Store(root / 'store.sqlite')
            self.assertEqual(store.add_path(root, root)[0], 1)
            hits = store.search(root, 'milestone')
            self.assertEqual(hits[0].path, 'ok.docx')
            store.close()


class KnowledgeLibraryTests(unittest.TestCase):
    def test_index_list_forget_are_workspace_scoped_and_leave_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a, b = base / 'a', base / 'b'
            a.mkdir(); b.mkdir()
            source_a, source_b = a / 'plan.html', b / 'plan.html'
            source_a.write_text('<p>Alpha workstream</p>')
            source_b.write_text('<p>Beta workstream</p>')
            store = Store(base / 'index.sqlite')
            store.add_path(source_a, a)
            store.add_path(source_b, b)
            rows = store.list_files(a)
            self.assertEqual([row['path'] for row in rows], ['plan.html'])
            self.assertEqual(len(rows[0]['sha256']), 64)
            self.assertGreater(rows[0]['chunks'], 0)
            self.assertTrue(store.forget_file(a, 'plan.html'))
            self.assertFalse(store.forget_file(a, 'plan.html'))
            self.assertTrue(source_a.is_file())
            self.assertEqual(store.search(a, 'Alpha'), [])
            self.assertTrue(store.search(b, 'Beta'))
            for path in ('../plan.html', '/etc/passwd', './plan.html', r'..\secret'):
                with self.assertRaises(ValueError, msg=path):
                    store.forget_file(a, path)
            store.close()

    def test_in_memory_database_never_creates_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            try:
                os.chdir(tmp)
                store = Store(':memory:')
                store.append_turn('one', 's', 'question', 'answer')
                self.assertEqual(len(store.history('one', 's')), 2)
                store.close()
                self.assertFalse((Path(tmp) / ':memory:').exists())
            finally:
                os.chdir(previous)

    def test_cli_library_json_and_forget_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'notes.md').write_text('A local private note')
            db = root / 'index.db'
            store = Store(db); store.add_path(root / 'notes.md', root); store.close()
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(['library', '--workspace', tmp, '--db', str(db), '--json']), 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data['files'][0]['path'], 'notes.md')
            with redirect_stderr(err):
                self.assertEqual(main(['forget', 'notes.md', '--workspace', tmp, '--db', str(db)]), 1)
            self.assertIn('--yes', err.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['forget', 'notes.md', '--workspace', tmp, '--db', str(db), '--yes']), 0)
            self.assertTrue((root / 'notes.md').exists())

    @patch('svenbot.engine.chat_openai', return_value='The revenue rose 21%. [source 1]')
    def test_ask_file_uses_ephemeral_index_and_provenance(self, chat):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'finance.docx'
            source.write_bytes(docx('Revenue rose 21% in 2025', 'Costs declined'))
            output, err = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(err):
                status = main(['ask-file', str(source), 'What happened to revenue?',
                               '--backend', 'openai', '--model', 'local'])
            self.assertEqual(status, 0)
            self.assertIn('The revenue rose', output.getvalue())
            self.assertIn('ephemeral index', err.getvalue())
            system = chat.call_args.args[0][0]['content']
            self.assertIn('finance.docx', system)
            self.assertIn('Revenue rose 21%', system)
            self.assertEqual(list(Path(tmp).iterdir()), [source])

    @patch('svenbot.engine.RulesEngine')
    @patch('svenbot.engine.chat_openai', side_effect=BackendError('offline'))
    @patch('svenbot.engine.chat_ollama', side_effect=BackendError('offline'))
    def test_ask_file_never_falls_back_to_ungrounded_rules(self, ollama, openai, rules):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'memo.txt'; source.write_text('Board decision is final')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(['ask-file', str(source), 'decision', '--backend', 'auto',
                                       '--model', 'already-set']), 1)
            rules.assert_not_called()


class SecurityAndLifecycleTests(unittest.TestCase):
    def test_explicit_pdf_without_parser_explains_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'contract.pdf').write_bytes(b'%PDF placeholder for missing parser')
            with patch.dict(sys.modules, {'pypdf': None}):
                store = Store(root / 'data.db')
                try:
                    with self.assertRaisesRegex(DocumentError, r'svenbot\[documents\]'):
                        store.add_path(root / 'contract.pdf', root)
                finally:
                    store.close()

    def test_indexing_document_replaces_stale_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'report.csv'; source.write_text('Item,Count\nGears,100\n')
            store = Store(root / 'data.db')
            try:
                self.assertEqual(store.add_path(source, root), (1, 0))
                self.assertEqual(store.add_path(source, root), (0, 0))
                self.assertTrue(store.search(root, 'Gears'))
                source.write_text('Item,Count\nBolts,400\n')
                self.assertEqual(store.add_path(source, root), (1, 0))
                self.assertFalse(store.search(root, 'Gears'))
                self.assertTrue(store.search(root, 'Bolts'))
            finally:
                store.close()

    def test_terminal_output_never_interprets_control_sequences(self):
        from svenbot.cli import emit
        from svenbot.engine import Answer
        output = io.StringIO()
        with redirect_stdout(output):
            emit(Answer('hello\x1b[31msecret\x00', 'ollama'), False)
        self.assertNotIn('\x1b', output.getvalue())
        self.assertNotIn('\x00', output.getvalue())
        self.assertIn('hello', output.getvalue())


if __name__ == '__main__':
    unittest.main()
