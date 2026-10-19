"""Release regressions use synthetic opinions and disposable workspace folders."""
import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scai.ai import (read_json, review, review_template, response_sha256, make_packet,
                     validate_response, bind_pending_review, inspect_review_record)
from scai.artifacts import verify_run, file_sha256, normalize_parameters, publish_bundle
from scai.data import dump, generate
from scai.__main__ import main

ROOT = Path(__file__).resolve().parents[1]


class ReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.packet = read_json(ROOT / 'examples/base/ai_packet.json')
        self.response = read_json(ROOT / 'examples/ai_response_codex.json')
        self.decisions = review_template(self.packet, self.response)

    def legacy(self):
        return {k: copy.deepcopy(self.decisions[k]) for k in ('packet_sha256', 'decisions')}

    def test_all_states_reject_nonstring_identity_and_reason(self):
        for state in ('pending', 'approve', 'reject'):
            for field in ('reviewer', 'reason'):
                for value in (None, 0, 1.5, True, False, [], {}, ['text']):
                    with self.subTest(state=state, field=field, value=value):
                        d = copy.deepcopy(self.decisions)
                        d['decisions'][0].update(decision=state, reviewer='测试人员', reason='仅测试')
                        d['decisions'][0][field] = value
                        with self.assertRaisesRegex(ValueError, f'{field} must be a string'):
                            review(self.packet, self.response, d)

    def test_empty_strings_only_allowed_for_pending(self):
        for state in ('pending', 'approve', 'reject'):
            for field in ('reviewer', 'reason'):
                d = copy.deepcopy(self.decisions)
                d['decisions'][0].update(decision=state, reviewer='测试人员', reason='仅测试')
                d['decisions'][0][field] = ' \t\n'
                if state == 'pending':
                    self.assertEqual(review(self.packet, self.response, d)['approved_count'], 0)
                else:
                    with self.assertRaisesRegex(ValueError, f'{field} required'):
                        review(self.packet, self.response, d)

    def test_record_item_and_version_schemas_are_strict(self):
        for value in (None, [], 'text', 12):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'must be an object'):
                review(self.packet, self.response, value)
        for item in (None, [], 'text', {}, {**self.decisions['decisions'][0], 'extra': 1}):
            d = copy.deepcopy(self.decisions)
            d['decisions'][0] = item
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, 'invalid review item fields'):
                review(self.packet, self.response, d)
        for version in (None, True, 2.0, 3, '2'):
            d = copy.deepcopy(self.decisions)
            d['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                review(self.packet, self.response, d)
        for field, value in [('extra', 1), ('response_sha256', None)]:
            d = copy.deepcopy(self.decisions)
            d[field] = value
            with self.assertRaises(ValueError): review(self.packet, self.response, d)

    def test_each_business_response_change_breaks_existing_binding(self):
        self.assertEqual(review(self.packet, self.response, self.decisions)['approved_count'], 0)
        for field, value in [('action', '另一项核查建议'), ('hypothesis', '待核实：另一种可能原因'),
                             ('owner_role', '仓储'), ('observed', None), ('limitations', '模拟；待人工审核；尚未执行')]:
            response = copy.deepcopy(self.response)
            if field == 'observed':
                # Retain a valid subset of the original metrics so rejection proves binding.
                observed = response['items'][0]['observed']
                self.assertGreater(len(observed), 1)
                observed.pop(next(iter(observed)))
            elif field == 'limitations': response[field] = value
            else: response['items'][0][field] = value
            validate_response(self.packet, response)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'response_sha256 mismatch'):
                review(self.packet, response, self.decisions)
        response = copy.deepcopy(self.response)
        response['items'].reverse()
        with self.assertRaisesRegex(ValueError, 'response_sha256 mismatch'):
            review(self.packet, response, self.decisions)

    def test_format_and_object_key_order_do_not_change_response_digest(self):
        reordered = json.loads(json.dumps(self.response, ensure_ascii=False, sort_keys=True, indent=4))
        self.assertEqual(response_sha256(self.packet, reordered), self.decisions['response_sha256'])
        self.assertEqual(review(self.packet, reordered, self.decisions)['binding_status'], 'response_bound')

    def test_legacy_records_are_viewable_but_not_formal_bound_reviews(self):
        for state in ('pending', 'approve', 'reject'):
            legacy = self.legacy()
            legacy['decisions'][0].update(decision=state, reviewer='TEST_ONLY', reason='test only')
            before = copy.deepcopy(legacy)
            self.assertEqual(inspect_review_record(legacy)['binding_status'], 'legacy_unbound')
            with self.assertRaisesRegex(ValueError, 'legacy_unbound'):
                review(self.packet, self.response, legacy)
            self.assertEqual(legacy, before)

    def test_explicit_pending_migration_preserves_text_and_input(self):
        legacy = self.legacy()
        legacy['decisions'][0].update(reviewer='测试人员', reason='证据不足，保留待核查')
        before = copy.deepcopy(legacy)
        migrated = bind_pending_review(self.packet, self.response, legacy)
        self.assertEqual(legacy, before)
        self.assertEqual(migrated['decisions'], legacy['decisions'])
        self.assertEqual(review(self.packet, self.response, migrated)['approved_count'], 0)
        for state in ('approve', 'reject'):
            legacy['decisions'][0]['decision'] = state
            with self.assertRaisesRegex(ValueError, 'cannot be automatically bound'):
                bind_pending_review(self.packet, self.response, legacy)

    def test_old_float_packet_hash_rule_still_valid(self):
        result = read_json(ROOT / 'examples/base/results.json')
        result['summary']['demand_factor'] = 1.0
        old_packet = make_packet(result, result['input_sha256'])
        self.assertNotEqual(old_packet['packet_sha256'], self.packet['packet_sha256'])
        response = copy.deepcopy(self.response)
        response['packet_sha256'] = old_packet['packet_sha256']
        self.assertEqual(validate_response(old_packet, response)['checked_items'], 4)

    def test_parameter_validation_does_not_normalize_arbitrary_values(self):
        self.assertEqual(normalize_parameters(1.25, 7), (1.25, 7))
        for factor, delay in [(True, 0), ('1', 0), (float('inf'), 0), (1, True), (1, 1.5), (1, '7')]:
            with self.subTest(factor=factor, delay=delay), self.assertRaises(ValueError):
                normalize_parameters(factor, delay)


class RunSafetyTests(unittest.TestCase):
    def setUp(self):
        # Parent is workspace root, not a pre-existing runs directory.
        self.temp = tempfile.TemporaryDirectory(dir=ROOT, prefix='.test-release-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'input'
        shutil.copytree(ROOT / 'examples/base', self.input)
        self.data = ROOT / 'data/demo'
        self.response = ROOT / 'examples/ai_response_codex.json'
        self.out = self.root / 'output'
        self.decisions = self.root / 'decisions.json'
        packet = read_json(self.input / 'ai_packet.json')
        dump(self.decisions, review_template(packet, read_json(self.response)))
        verify_run(self.input, self.data)  # Ensure each negative test starts from a valid run.

    def cli(self, command='validate-ai', extra=()):
        args = [command, '--run', str(self.input), '--data', str(self.data),
                '--response', str(self.response), '--out', str(self.out)]
        if command == 'review': args.extend(['--decisions', str(self.decisions)])
        error = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(error):
            code = main([*args, *extra])
        return code, error.getvalue()

    def update_hash(self, name):
        manifest = read_json(self.input / 'run_manifest.json')
        manifest['output_sha256'][name] = file_sha256(self.input / name)
        dump(self.input / 'run_manifest.json', manifest)

    def assert_rejected(self, message, command='validate-ai'):
        code, error = self.cli(command)
        self.assertEqual(code, 2, error)
        self.assertIn(message, error)
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.glob('.output-*')), [])

    def test_valid_old_manifest_verifies_inputs_and_new_output(self):
        before = {p.name: p.read_bytes() for p in self.input.iterdir() if p.is_file()}
        code, error = self.cli()
        self.assertEqual(code, 0, error)
        self.assertEqual(read_json(self.out / 'ai_validation.json')['input_verification'], 'actual_csv_fingerprint_verified')
        self.assertEqual(read_json(self.out / 'review_template.json')['schema_version'], 2)
        self.assertEqual({p.name: p.read_bytes() for p in self.input.iterdir() if p.is_file()}, before)

    def test_missing_manifest_rejected_without_output(self):
        (self.input / 'run_manifest.json').rename(self.input / 'manifest.saved')
        self.assert_rejected('missing run_manifest.json')

    def test_missing_required_file_rejected_without_output(self):
        (self.input / 'inventory_risks.csv').rename(self.input / 'inventory.saved')
        self.assert_rejected('missing inventory_risks.csv')

    def test_incomplete_manifest_requires_new_run(self):
        manifest = read_json(self.input / 'run_manifest.json')
        del manifest['output_sha256']['results.json']
        dump(self.input / 'run_manifest.json', manifest)
        self.assert_rejected('missing required output hashes')

    def test_time_path_tampering_rejected_by_full_file_hash(self):
        result = read_json(self.input / 'results.json')
        result['inventory'][-1]['time_path'][0]['balance'] += 1
        # This modification is NOT represented in the selected packet.
        self.assertEqual(make_packet(result, result['input_sha256']), read_json(self.input / 'ai_packet.json'))
        dump(self.input / 'results.json', result)
        self.assert_rejected('run hash mismatch: results.json')

    def test_packet_file_tampering_rejected(self):
        packet = read_json(self.input / 'ai_packet.json')
        packet['summary']['demand_factor'] = 1.25
        dump(self.input / 'ai_packet.json', packet)
        self.assert_rejected('run hash mismatch: ai_packet.json')

    def test_updated_hash_still_checks_scenario_parameters(self):
        result = read_json(self.input / 'results.json')
        result['summary']['demand_factor'] = 1.25
        dump(self.input / 'results.json', result)
        self.update_hash('results.json')
        self.assert_rejected('run scenario parameters mismatch')

    def test_manifest_parameter_mismatch(self):
        manifest = read_json(self.input / 'run_manifest.json')
        manifest['parameters']['delay_days'] = 7
        dump(self.input / 'run_manifest.json', manifest)
        self.assert_rejected('run scenario parameters mismatch')

    def test_updated_hash_still_rebuilds_packet(self):
        result = read_json(self.input / 'results.json')
        result['evidence'][0]['meaning'] = 'Changed evidence description'
        dump(self.input / 'results.json', result)
        self.update_hash('results.json')
        self.assert_rejected('results/packet content mismatch')

    def test_real_changed_input_is_rejected(self):
        self.data = self.root / 'other-data'
        generate(self.data, seed=9)
        self.assert_rejected('run input fingerprint mismatch')

    def test_manifest_input_hash_mismatch(self):
        manifest = read_json(self.input / 'run_manifest.json')
        manifest['input_sha256'] = '0' * 64
        dump(self.input / 'run_manifest.json', manifest)
        self.assert_rejected('run input fingerprint mismatch')

    def test_existing_outputs_never_overwritten_for_both_commands(self):
        self.out.mkdir()
        names = ('ai_validation.json', 'ai_draft.json', 'review_template.json', 'dashboard_ai.html', 'human_review.json')
        for name in names: (self.out / name).write_bytes(b'EXISTING USER CONTENT')
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        for command in ('validate-ai', 'review'):
            code, error = self.cli(command)
            self.assertEqual(code, 2)
            self.assertIn('refusing overwrite', error)
            self.assertEqual({p.name: p.read_bytes() for p in self.out.iterdir()}, before)

    def test_empty_existing_directory_is_also_refused(self):
        self.out.mkdir()
        code, error = self.cli()
        self.assertEqual(code, 2)
        self.assertIn('refusing overwrite', error)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_input_output_path_overlap_rejected(self):
        for target in (self.input, self.input / 'child', self.root, self.decisions, self.data / 'new-review'):
            with self.subTest(target=target):
                self.out = target
                code, error = self.cli('review')
                self.assertEqual(code, 2)
                self.assertIn('output conflicts with an input path', error)

    def test_render_failure_leaves_no_partial_final_bundle(self):
        with patch('scai.__main__.render', side_effect=ValueError('injected render failure')):
            self.assert_rejected('injected render failure')

    def test_report_write_failure_leaves_no_partial_final_bundle(self):
        from scai.data import dump as real_dump
        def fail_second(path, value):
            if Path(path).name == 'response_snapshot.json': raise OSError('injected disk failure')
            real_dump(path, value)
        with patch('scai.__main__.dump', side_effect=fail_second):
            self.assert_rejected('injected disk failure', 'review')

    def test_target_created_during_staging_is_preserved(self):
        def build(stage):
            (stage / 'new.txt').write_text('new', encoding='utf-8')
            self.out.mkdir()
            (self.out / 'sentinel').write_bytes(b'OTHER OUTPUT')
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
            publish_bundle(self.out, [self.input], build)
        self.assertEqual((self.out / 'sentinel').read_bytes(), b'OTHER OUTPUT')
        self.assertFalse((self.out / 'new.txt').exists())

    def test_review_checks_run_before_saving(self):
        result = read_json(self.input / 'results.json')
        result['inventory'][0]['time_path'].pop()
        dump(self.input / 'results.json', result)
        self.assert_rejected('run hash mismatch: results.json', 'review')

    def test_explicit_migration_uses_new_files_and_preserves_source_bytes(self):
        legacy = {k: read_json(self.decisions)[k] for k in ('packet_sha256', 'decisions')}
        legacy['decisions'][0].update(reviewer='TEST_ONLY', reason='pending example')
        raw = json.dumps(legacy, ensure_ascii=False, indent=4).encode('utf-8-sig')
        self.decisions.write_bytes(raw)
        code, error = self.cli(extra=['--pending-decisions', str(self.decisions)])
        self.assertEqual(code, 0, error)
        self.assertEqual(self.decisions.read_bytes(), raw)
        self.assertEqual((self.out / 'legacy_decisions_snapshot.json').read_bytes(), raw)
        self.assertEqual(read_json(self.out / 'migration.json')['source_sha256'], file_sha256(self.decisions))
        template = read_json(self.out / 'review_template.json')
        self.assertEqual(template['decisions'], legacy['decisions'])
        old_out = self.out
        self.decisions = old_out / 'review_template.json'
        self.out = self.root / 'reviewed'
        code, error = self.cli('review')
        self.assertEqual(code, 0, error)
        self.assertEqual(read_json(self.out / 'human_review.json')['approved_count'], 0)

    def test_cli_refuses_legacy_formal_review_and_approval_migration(self):
        legacy = {k: read_json(self.decisions)[k] for k in ('packet_sha256', 'decisions')}
        dump(self.decisions, legacy)
        self.assert_rejected('legacy_unbound', 'review')
        legacy['decisions'][0].update(decision='approve', reviewer='TEST_ONLY', reason='not a real approval')
        dump(self.decisions, legacy)
        code, error = self.cli(extra=['--pending-decisions', str(self.decisions)])
        self.assertEqual(code, 2)
        self.assertIn('cannot be automatically bound', error)
        self.assertFalse(self.out.exists())

    def test_invalid_response_does_not_create_output(self):
        response = read_json(self.response)
        response['items'][0]['observed']['invented'] = 999
        self.response = self.root / 'invalid-response.json'
        dump(self.response, response)
        self.assert_rejected('unsupported numeric claim')
