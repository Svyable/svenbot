"""Synthetic HTML + real Chromium DOM extraction QA, no extension installation.

This does NOT certify unmanaged Chrome MV3 permission or live model inference.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page()
        html = ['<!doctype html><title>Privacy and evidence</title><main><article>',
                '<h1>Longitudinal study</h1>',
                '<p>Public evidence about research outcomes and methods. '
                '<span aria-hidden="true">HIDDEN_ACCOUNT_NUMBER_456123</span>'
                'Observed outcomes require independent verification.</p>',
                '<p>Public conclusion includes a <span hidden>INVISIBLE_PERSONAL_SECRET</span>'
                ' documented limitation of the published analysis.</p>',
                '<p class="secret" style="display:none">CSS_PRIVATE_SECRET</p>',
                '<details><p>DISCLOSURE_SECRET is not visible in closed details</p></details>',
                '<form><input type="password" value="FORM_PASSWORD_SECRET"></form>']
        for n in range(240):
            html.append(f'<p>Section {n}: evidence collection and testing included a separate evaluation of cohort {n}.</p>')
        html.extend(['<h2>Conclusions</h2>',
                     '<p>Most important closing caveat: the large-scale replication is not complete and uncertainty remains.</p>',
                     '</article></main>'])
        page.set_content(''.join(html))
        page.add_script_tag(content=(ROOT/'companion/reader.js').read_text())
        report = page.evaluate('extractVisiblePage()')
        assert len(report['blocks']) == 60, report['capture']
        assert report['capture']['sampled'] is True
        assert report['total_characters'] <= 29000
        merged = ' '.join(b['text'] for b in report['blocks'])
        assert 'closing caveat' in merged
        assert 'Section 120:' in merged or 'Section 119:' in merged or 'Section 121:' in merged or 'Section 122:' in merged
        for secret in ['HIDDEN_ACCOUNT_NUMBER', 'INVISIBLE_PERSONAL_SECRET', 'CSS_PRIVATE_SECRET',
                       'DISCLOSURE_SECRET', 'FORM_PASSWORD_SECRET']:
            assert secret not in str(report), secret
        assert report['blocks'][0]['id'] == 'B1'
        browser.close()
        print('PASS: real Chromium synthetic DOM: long-page coverage, nested privacy suppression and bounded capture')


if __name__ == '__main__':
    main()
