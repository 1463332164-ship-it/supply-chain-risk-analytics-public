"""Published showcase contracts, independent of Git, network and local runs/."""
import hashlib
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from scai.ai import make_packet, response_sha256
from scai.data import fingerprint


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ShowcaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.folder = cls.root / 'examples/showcase'
        cls.meta = json.loads((cls.folder / 'showcase_metadata.json').read_text(encoding='utf-8'))
        cls.names = {'index.html', 'base.html', 'base_ai.html', 'combined.html'}
        cls.pages = {name: (cls.folder / name).read_text(encoding='utf-8') for name in cls.names}
        cls.payloads = {}
        for name in cls.names - {'index.html'}:
            matches = re.findall(r'<script id="payload" type="application/json">(.*?)</script>', cls.pages[name], re.S)
            if len(matches) != 1:
                raise AssertionError(f'{name}: expected exactly one payload')
            cls.payloads[name] = json.loads(matches[0])

    def test_current_html_hashes_use_declared_lf_publication_contract(self):
        self.assertEqual(self.meta['schema_version'], 2)
        self.assertEqual(set(self.meta['published_file_sha256']), self.names)
        self.assertIn('CRLF', self.meta['hash_contract']['published_file_sha256'])
        for name in self.names:
            with self.subTest(page=name):
                raw = (self.folder / name).read_bytes().replace(b'\r\n', b'\n')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), self.meta['published_file_sha256'][name])
                if name != 'index.html':
                    self.assertNotEqual(self.meta['pages'][name]['html_sha256'], self.meta['published_file_sha256'][name])

    def test_input_hashes_and_fingerprint_match_actual_simulated_csv(self):
        inputs = self.meta['input']
        self.assertEqual(inputs['origin'], 'synthetic')
        self.assertEqual(inputs['directory'], 'data/demo')
        self.assertEqual(set(inputs['file_sha256']), {f'data/demo/{name}' for name in ('demand.csv', 'inventory.csv', 'orders.csv', 'provenance.json')})
        for name, expected in inputs['file_sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((self.root / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(fingerprint(self.root / inputs['directory']), inputs['input_sha256'])

    def test_complete_payloads_match_public_reference_results(self):
        for name, payload in self.payloads.items():
            with self.subTest(page=name):
                fixture = 'stress' if name == 'combined.html' else 'base'
                reference = json.loads((self.root / f'examples/{fixture}/results.json').read_text(encoding='utf-8'))
                self.assertEqual(payload['result'], reference)
                raw = (json.dumps(payload['result'], ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), self.meta['pages'][name]['results_file_sha256'])

    def test_metadata_metrics_packet_and_ai_binding_match_complete_payload(self):
        for name, payload in self.payloads.items():
            with self.subTest(page=name):
                meta, result = self.meta['pages'][name], payload['result']
                self.assertEqual(len(result['inventory']), 90)
                self.assertEqual(meta['shortage_entities'], sum(row['first_shortage_day'] is not None for row in result['inventory']))
                self.assertEqual(meta['reorder_entities'], sum(row['reorder_suggestion_units'] > 0 for row in result['inventory']))
                self.assertEqual(meta['evidence_count'], len(result['evidence']))
                for key, value in meta['parameters'].items():
                    self.assertEqual(value, result['summary'][key])
                packet = make_packet(result, self.meta['input']['input_sha256'])
                self.assertEqual(packet['packet_sha256'], meta['packet_content_sha256'])
                response = payload['ai']
                self.assertEqual(meta['ai_items'], len(response['items']) if response else 0)
                if name == 'base_ai.html':
                    self.assertEqual(response, json.loads((self.root / 'examples/ai_response_codex.json').read_text(encoding='utf-8')))
                    self.assertEqual(response_sha256(packet, response), meta['response_content_sha256'])
                else:
                    self.assertIsNone(response)

    def test_navigation_stays_inside_complete_four_page_bundle(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                links = [attrs['href'] for tag, attrs in Tags(html).tags if tag == 'a' and 'href' in attrs]
                expected = self.names - {'index.html'} if name == 'index.html' else self.names
                self.assertEqual(set(links), expected)
                for target in links:
                    self.assertTrue((self.folder / target).is_file())

    def test_all_four_pages_need_no_external_runtime_resources(self):
        for name, html in self.pages.items():
            with self.subTest(page=name):
                tags = Tags(html).tags
                self.assertTrue(any(tag == 'meta' and attrs.get('name') == 'viewport' for tag, attrs in tags))
                for tag, attrs in tags:
                    self.assertFalse(tag == 'script' and 'src' in attrs)
                    self.assertFalse(tag == 'link' and 'href' in attrs)
                    self.assertFalse(tag in ('iframe', 'object', 'embed'))
                self.assertNotRegex(html, r'\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(')
                self.assertNotRegex(html, r'@import\b|url\(\s*[\'"]?https?://')


if __name__ == '__main__':
    unittest.main()
