"""HTML contracts; the separate JS harness checks logic, not browser layout."""
import copy
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from scai.dashboard import render


class Element:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    @property
    def text(self):
        return ''.join(x if isinstance(x, str) else x.text for x in self.children)

    def find_all(self, tag=None, identifier=None, css_class=None):
        result = []
        for child in self.children:
            if isinstance(child, Element):
                if ((tag is None or child.tag == tag)
                        and (identifier is None or child.attrs.get('id') == identifier)
                        and (css_class is None or css_class in child.attrs.get('class', '').split())):
                    result.append(child)
                result.extend(child.find_all(tag, identifier, css_class))
        return result


class Document(HTMLParser):
    VOID = {'meta', 'input', 'link', 'br', 'hr', 'img', 'area', 'base', 'col', 'embed', 'param', 'source', 'track', 'wbr'}

    def __init__(self, page):
        super().__init__(convert_charrefs=True)
        self.root = Element('document')
        self.stack = [self.root]
        self.errors = []
        self.feed(page)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if self.stack[-1].tag != tag:
            self.errors.append(f'unbalanced closing tag: {tag}')
        else:
            self.stack.pop()

    def handle_data(self, text):
        self.stack[-1].children.append(text)

    def one(self, identifier):
        nodes = self.root.find_all(identifier=identifier)
        if len(nodes) != 1:
            raise AssertionError(f'expected one {identifier}, got {len(nodes)}')
        return nodes[0]


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.base = json.loads((cls.root / 'examples/base/results.json').read_text(encoding='utf-8'))
        cls.ai = json.loads((cls.root / 'examples/ai_response_codex.json').read_text(encoding='utf-8'))

    def render_html(self, result, ai=None):
        with tempfile.TemporaryDirectory(prefix='scai-ui-test-') as tmp:
            path = Path(tmp) / 'dashboard.html'
            render(result, path, ai)
            return path.read_text(encoding='utf-8')

    def payload(self, page):
        return json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>', page, re.S)[1])

    def test_payload_preserves_time_path_and_input(self):
        result = {'inventory': [{'sku': 'SKU001', 'warehouse': 'WH1', 'time_path': [
            {'day': 1, 'demand': 1.2345, 'arrival': 0, 'balance': -0.0001}]}]}
        original = copy.deepcopy(result)
        self.assertEqual(self.payload(self.render_html(result))['result'], original)
        self.assertEqual(result, original)

    def test_script_breakout_is_escaped_in_result_and_ai(self):
        attack = '</script><script>alert("x")</script>&中文'
        page = self.render_html({'sku': attack}, {'hypothesis': attack})
        self.assertNotIn(attack, page)
        self.assertEqual(len(re.findall(r'<script\b', page)), 2)
        self.assertEqual(self.payload(page), {'result': {'sku': attack}, 'ai': {'hypothesis': attack}})

    def test_ai_and_no_ai_payloads_are_supported(self):
        self.assertIsNone(self.payload(self.render_html({}))['ai'])
        ai = {'items': [], 'limitations': '待人工审核'}
        self.assertEqual(self.payload(self.render_html({}, ai))['ai'], ai)

    def test_single_file_has_no_external_runtime_resources(self):
        page = self.render_html({})
        self.assertNotRegex(page, r'<script\b[^>]*\bsrc\s*=')
        self.assertNotRegex(page, r'<link\b[^>]*\bhref\s*=')
        self.assertNotRegex(page, r'\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(')
        self.assertNotRegex(page, r'@import\b|url\(\s*[\'"]?https?://')

    def test_empty_inventory_and_trace_controls_are_embedded(self):
        page = self.render_html({'inventory': []})
        self.assertEqual(self.payload(page)['result']['inventory'], [])
        for identifier in ('balance-chart', 'flow-chart', 'day-select', 'trace', 'warehouse', 'sku', 'risk', 'download'):
            self.assertEqual(page.count(f'id="{identifier}"'), 1)

    def test_nonfinite_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            self.render_html({'balance': float('nan')})

    def test_secondary_panels_are_native_closed_details_with_actual_count(self):
        doc = Document(self.render_html(self.base))
        self.assertEqual(doc.errors, [])
        for identifier, title in [('evidence-details', '证据台账'), ('ai-details', 'AI建议与人工审核')]:
            panel = doc.one(identifier)
            self.assertEqual(panel.tag, 'details')
            self.assertNotIn('open', panel.attrs)
            summary = next(x for x in panel.children if isinstance(x, Element))
            self.assertEqual(summary.tag, 'summary')
            self.assertIn(title, summary.text)
        self.assertEqual(doc.one('evidence-count').text, f"{len(self.base['evidence'])} 条证据")

    def test_all_evidence_records_and_full_fields_are_accessible_in_original_order(self):
        doc = Document(self.render_html(self.base))
        panel = doc.one('evidence-details')
        cards = panel.find_all('article', css_class='evidence-item')
        self.assertEqual(len(cards), len(self.base['evidence']))
        raw = panel.find_all('pre', css_class='evidence-raw')
        self.assertEqual([json.loads(x.text) for x in raw], self.base['evidence'])
        for card, row in zip(cards, self.base['evidence']):
            with self.subTest(evidence_id=row['id']):
                self.assertEqual(card.find_all('h3')[0].text, row['id'])
                self.assertEqual(card.find_all(css_class='section-state')[0].text, f"优先级：{row['priority']}")
                self.assertEqual([x.text for x in card.find_all('dd')], [row['type'], row['sku'], row['warehouse']])
                self.assertEqual(json.loads(card.find_all('pre', css_class='metric-json')[0].text), row['metrics'])
                self.assertEqual(card.find_all('pre', css_class='source-text')[0].text, row['source'])
                self.assertEqual(card.find_all(css_class='evidence-meaning')[0].text, '解释与边界：' + row['meaning'])

    def test_no_ai_has_concise_closed_status_and_no_false_success_or_warning(self):
        doc = Document(self.render_html(self.base))
        self.assertEqual(doc.one('ai-status').text, '未导入AI草稿')
        self.assertNotIn('open', doc.one('ai-details').attrs)
        self.assertIn('尚未导入', doc.one('ai').text)
        self.assertNotIn('检查通过', doc.one('ai').text)
        self.assertEqual(doc.root.find_all(identifier='ai-warning'), [])
        self.assertEqual(doc.root.find_all(identifier='ai-raw'), [])

    def test_valid_ai_preserves_complete_draft_metrics_and_pending_boundary(self):
        before = copy.deepcopy(self.ai)
        doc = Document(self.render_html(self.base, self.ai))
        self.assertEqual(doc.one('ai-status').text, '4 条建议 · 待人工审核')
        self.assertEqual(json.loads(doc.one('ai-raw').text), self.ai)
        self.assertEqual(doc.root.find_all(identifier='ai-warning'), [])
        items = doc.one('ai').find_all('article', css_class='aiitem')
        self.assertEqual(len(items), len(self.ai['items']))
        for item, original in zip(items, self.ai['items']):
            for key in ('evidence_id', 'hypothesis', 'action', 'owner_role'):
                self.assertIn(original[key], item.text)
            self.assertEqual(json.loads(item.find_all('pre')[0].text), original['observed'])
        self.assertIn(self.ai['limitations'], doc.one('ai').text)
        for label in ('固定 AI 草稿', '不调用实时大模型', '不提供网页采购审批', 'response_sha256', 'validate-ai → review', '不产生批准'):
            self.assertIn(label, doc.one('ai-details').text)
        self.assertEqual(doc.one('ai-details').find_all('button'), [])
        self.assertEqual(doc.one('ai-details').find_all('input'), [])
        self.assertEqual(self.ai, before)

    def test_invalid_ai_warning_stays_outside_closed_panels_and_before_kpis(self):
        wrong_packet, unknown_id, changed_metric = [copy.deepcopy(self.ai) for _ in range(3)]
        wrong_packet['packet_sha256'] = 'wrong'
        unknown_id['items'][0]['evidence_id'] = 'UNKNOWN'
        changed_metric['items'][0]['observed']['first_shortage_day'] = 99
        for response in (wrong_packet, unknown_id, changed_metric, {}, False, {'items': None}, {'items': [None]}):
            with self.subTest(response=response):
                page = self.render_html(self.base, response)
                doc = Document(page)
                warning = doc.one('ai-warning')
                self.assertEqual(warning.attrs.get('role'), 'alert')
                parent = warning.parent
                while parent is not None:
                    self.assertNotEqual(parent.tag, 'details')
                    self.assertNotIn('hidden', parent.attrs)
                    parent = parent.parent
                self.assertLess(page.index('id="ai-warning"'), page.index('id="cards"'))
                self.assertIn('校验失败', doc.one('ai-status').text)
                self.assertNotIn('检查通过', doc.one('ai').text)
                self.assertEqual(json.loads(doc.one('ai-raw').text), response)
                self.assertEqual(doc.errors, [])

    def test_evidence_and_ai_text_cannot_create_markup_or_event_attributes(self):
        attack = '</pre></summary></details><img src=x onerror="alert(1)"><script>alert(2)</script>&\"\'中文\n'
        result = copy.deepcopy(self.base)
        row = {k: attack for k in ('id', 'type', 'priority', 'sku', 'warehouse', 'source', 'meaning')}
        row['metrics'] = {attack: [attack, 0, None]}
        result['evidence'] = [row]
        response = {'items': [{k: attack for k in ('evidence_id', 'hypothesis', 'action', 'owner_role')}], 'limitations': attack}
        response['items'][0]['observed'] = {attack: attack}
        page = self.render_html(result, response)
        doc = Document(page)
        self.assertEqual(doc.errors, [])
        self.assertEqual(doc.root.find_all('img'), [])
        self.assertEqual(len(doc.root.find_all('script')), 2)
        self.assertEqual(json.loads(doc.root.find_all(css_class='evidence-raw')[0].text), row)
        self.assertEqual(json.loads(doc.one('ai-raw').text), response)
        self.assertEqual(self.payload(page), {'result': result, 'ai': response})
        for element in doc.root.find_all():
            self.assertFalse(any(name.startswith('on') for name in element.attrs))

    def test_preformatted_metrics_keep_precision_zero_null_and_nested_values(self):
        metrics = {'large_integer': 2**80 + 1, 'decimal': 0.12345678901234566, 'zero': 0,
                   'float_zero': 0.0, 'negative_zero': -0.0, 'null': None, 'boolean': False,
                   'nested': {'long_field_' * 30: ['A&B', '', None]}}
        source = 'long-source-' * 150 + '.csv:2\n下一行 & <保留>'
        row = {'id': 'TEST', 'metrics': metrics, 'source': source, 'extra_future_field': {'retain': True}}
        result = {'evidence': [row]}
        page = self.render_html(result)
        doc = Document(page)
        pre = doc.root.find_all('pre', css_class='metric-json')[0]
        self.assertEqual(pre.text, json.dumps(metrics, ensure_ascii=False, indent=2))
        self.assertIn(str(2**80 + 1), pre.text)
        self.assertEqual(doc.root.find_all(css_class='source-text')[0].text, source)
        self.assertEqual(json.loads(doc.root.find_all(css_class='evidence-raw')[0].text), row)
        self.assertEqual(self.payload(page)['result'], result)

    def test_missing_fields_and_nulls_remain_distinct_without_dropping_records(self):
        rows = [{}, {'id': 'nullable', 'metrics': None, 'source': None, 'priority': 0},
                {'id': 'zeros', 'metrics': {'zero': 0}, 'source': '', 'meaning': ''}]
        doc = Document(self.render_html({'evidence': rows}))
        cards = doc.root.find_all(css_class='evidence-item')
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0].find_all(css_class='metric-json')[0].text, '未提供')
        self.assertEqual(cards[1].find_all(css_class='metric-json')[0].text, 'null')
        self.assertEqual(cards[1].find_all(css_class='source-text')[0].text, 'null')
        self.assertEqual(cards[2].find_all(css_class='source-text')[0].text, '')
        self.assertEqual([json.loads(x.text) for x in doc.root.find_all(css_class='evidence-raw')], rows)

    def test_empty_or_missing_evidence_is_explicitly_empty(self):
        for result in ({}, {'evidence': []}, {'evidence': None}):
            doc = Document(self.render_html(result))
            self.assertEqual(doc.one('evidence-count').text, '0 条证据')
            self.assertIn('没有证据记录', doc.one('evidence').text)
            self.assertEqual(doc.one('evidence').find_all('article'), [])

    def test_duplicate_ids_are_not_merged_or_reordered_by_rendering(self):
        rows = [{'id': 'same', 'metrics': {'value': n}} for n in (2, 1, 0)]
        doc = Document(self.render_html({'evidence': rows}))
        self.assertEqual([json.loads(x.text) for x in doc.root.find_all(css_class='evidence-raw')], rows)

    def test_template_markers_inside_data_are_not_interpolated(self):
        markers = '__PAYLOAD__ __EVIDENCE__ __AI_PANEL__ __AI_WARNING__'
        result = {'evidence': [{'id': markers, 'metrics': {markers: markers}, 'source': markers}]}
        response = {'items': [], 'limitations': markers}
        page = self.render_html(result, response)
        doc = Document(page)
        self.assertEqual(self.payload(page), {'result': result, 'ai': response})
        self.assertEqual(json.loads(doc.one('ai-raw').text), response)
        self.assertEqual(json.loads(doc.root.find_all(css_class='evidence-raw')[0].text), result['evidence'][0])
        self.assertEqual(len(doc.root.find_all('script')), 2)

    def test_full_demo_payloads_match_results_with_and_without_ai(self):
        stress = json.loads((self.root / 'examples/stress/results.json').read_text(encoding='utf-8'))
        for result, ai in ((self.base, None), (self.base, self.ai), (stress, None)):
            with self.subTest(factor=result['summary']['demand_factor'], ai=ai is not None):
                original = copy.deepcopy(result)
                page = self.render_html(result, ai)
                self.assertEqual(self.payload(page), {'result': original, 'ai': ai})
                self.assertEqual(result, original)
                self.assertEqual(Document(page).errors, [])
