"""Input edits and output failures use disposable system-temp copies only."""
import csv
import errno
import hashlib
import io
import os
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import scai.__main__ as cli
import scai.data as data_module
import scai.output as output
from scai.ai import read_json, response_sha256
from scai.artifacts import verify_run
from scai.data import InputSnapshot, fingerprint, load_snapshot, read_snapshot

ROOT = Path(__file__).resolve().parents[1]


def bytes_in(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob('*') if p.is_file()}


def change_csv(folder, name):
    path = folder / f'{name}.csv'
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream))
    field = {'demand': 'demand_units', 'inventory': 'on_hand', 'orders': 'qty'}[name]
    col = rows[0].index(field)
    rows[1][col] = str(int(rows[1][col]) + 1000)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        csv.writer(stream).writerows(rows)


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='scai-safety-test-')
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.addCleanup(self.temp.cleanup)
        self.data = self.copy_data('input')

    def copy_data(self, name):
        target = self.root / name
        shutil.copytree(ROOT / 'data/demo', target)
        return target

    def invoke(self, *args):
        error = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(error):
            code = cli.main(list(map(str, args)))
        return code, error.getvalue()

    def assert_no_bundle(self, target):
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob(f'.{target.name}-*')), [])


class SnapshotTests(IsolatedCase):
    def test_digest_preserves_legacy_csv_byte_contract(self):
        snapshot = read_snapshot(self.data)
        expected = hashlib.sha256()
        for name in sorted(data_module.SCHEMAS):
            expected.update(name.encode())
            expected.update((self.data / f'{name}.csv').read_bytes())
        self.assertEqual(snapshot.sha256, expected.hexdigest())
        self.assertEqual(snapshot.sha256, read_json(ROOT / 'examples/base/results.json')['input_sha256'])
        self.assertEqual(load_snapshot(snapshot), data_module.load(self.data))

    def test_snapshot_is_immutable(self):
        snapshot = read_snapshot(self.data)
        with self.assertRaises(TypeError): snapshot.raw['inventory'] = b'changed'
        with self.assertRaises(FrozenInstanceError): snapshot.folder = self.root

    def test_provenance_and_extra_files_remain_outside_legacy_hash(self):
        snapshot = read_snapshot(self.data)
        (self.data / 'provenance.json').write_text('{"note":"test only"}', encoding='utf-8')
        (self.data / 'extra.csv').write_text('not an input', encoding='utf-8')
        snapshot.assert_unchanged()
        self.assertEqual(fingerprint(self.data), snapshot.sha256)

    def test_parsing_and_digest_use_old_snapshot_after_each_csv_is_changed(self):
        for name in data_module.SCHEMAS:
            with self.subTest(table=name):
                folder = self.copy_data(name)
                snapshot = read_snapshot(folder)
                parsed = load_snapshot(snapshot)
                digest = snapshot.sha256
                change_csv(folder, name)
                self.assertEqual(load_snapshot(snapshot), parsed)
                self.assertEqual(snapshot.sha256, digest)
                self.assertNotEqual(fingerprint(folder), digest)
                with self.assertRaisesRegex(ValueError, 'input files changed'):
                    snapshot.assert_unchanged()

    def test_changes_during_each_csv_capture_are_rejected(self):
        real_read = Path.read_bytes
        for name in data_module.SCHEMAS:
            with self.subTest(table=name):
                folder = self.copy_data(name)
                touched = False
                def read_then_edit(path):
                    nonlocal touched
                    raw = real_read(path)
                    if path == folder / f'{name}.csv' and not touched:
                        touched = True
                        change_csv(folder, name)
                    return raw
                with patch.object(Path, 'read_bytes', read_then_edit):
                    with self.assertRaisesRegex(ValueError, 'input files changed'):
                        read_snapshot(folder)
                self.assertTrue(touched)

    def test_cross_file_update_during_capture_is_rejected(self):
        real_read = Path.read_bytes
        touched = False
        def update_all_after_demand(path):
            nonlocal touched
            raw = real_read(path)
            if path == self.data / 'demand.csv' and not touched:
                touched = True
                for name in data_module.SCHEMAS: change_csv(self.data, name)
            return raw
        with patch.object(Path, 'read_bytes', update_all_after_demand):
            with self.assertRaisesRegex(ValueError, 'input files changed'):
                read_snapshot(self.data)
        self.assertTrue(touched)

    def test_csv_edit_during_parsing_blocks_run(self):
        real_number = data_module.number
        for name in data_module.SCHEMAS:
            with self.subTest(table=name):
                folder = self.copy_data(name)
                target = self.root / f'out-{name}'
                touched = False
                def number_then_edit(*args, **kwargs):
                    nonlocal touched
                    value = real_number(*args, **kwargs)
                    if not touched:
                        touched = True
                        change_csv(folder, name)
                    return value
                with patch('scai.data.number', side_effect=number_then_edit):
                    code, error = self.invoke('analyze', '--data', folder, '--out', target)
                self.assertEqual(code, 2, error)
                self.assertIn('input files changed', error)
                self.assertTrue(touched)
                self.assert_no_bundle(target)

    def test_csv_edit_after_analysis_cannot_bind_new_fingerprint(self):
        real_analyze = cli.analyze
        for name in data_module.SCHEMAS:
            with self.subTest(table=name):
                folder = self.copy_data(name)
                target = self.root / f'out-{name}'
                observed = []
                def analyze_then_edit(*args, **kwargs):
                    result = real_analyze(*args, **kwargs)
                    observed.append(result[0]['inventory'][0]['on_hand'])
                    change_csv(folder, name)
                    return result
                with patch('scai.__main__.analyze', side_effect=analyze_then_edit):
                    code, error = self.invoke('analyze', '--data', folder, '--out', target)
                self.assertEqual(observed, [32])
                if name == 'inventory':
                    self.assertEqual(data_module.load(folder)[0]['inventory'][0]['on_hand'], 1032)
                self.assertEqual(code, 2, error)
                self.assertIn('input files changed', error)
                self.assert_no_bundle(target)

    def test_csv_edit_while_hashing_cannot_rebind_snapshot(self):
        original_digest = InputSnapshot.sha256.fget
        for name in data_module.SCHEMAS:
            with self.subTest(table=name):
                folder = self.copy_data(name)
                target = self.root / f'out-{name}'
                expected = fingerprint(folder)
                def hash_then_edit(snapshot):
                    digest = original_digest(snapshot)
                    self.assertEqual(digest, expected)
                    change_csv(folder, name)
                    return digest
                with patch.object(InputSnapshot, 'sha256', new=property(hash_then_edit)):
                    code, error = self.invoke('analyze', '--data', folder, '--out', target)
                self.assertEqual(code, 2, error)
                self.assertIn('input files changed', error)
                self.assert_no_bundle(target)

    def test_csv_edit_during_render_blocks_publication(self):
        real_render = cli.render
        for name in data_module.SCHEMAS:
            with self.subTest(table=name):
                folder = self.copy_data(name)
                target = self.root / f'out-{name}'
                def render_then_edit(*args, **kwargs):
                    real_render(*args, **kwargs)
                    change_csv(folder, name)
                with patch('scai.__main__.render', side_effect=render_then_edit):
                    code, error = self.invoke('analyze', '--data', folder, '--out', target)
                self.assertEqual(code, 2, error)
                self.assertIn('input files changed', error)
                self.assert_no_bundle(target)

    def test_verify_run_rejects_edit_during_snapshot_validation(self):
        run = self.root / 'run'
        cli.run(self.data, run)
        def parse_then_edit(snapshot):
            result = load_snapshot(snapshot)
            change_csv(self.data, 'inventory')
            return result
        with patch('scai.artifacts.load_snapshot', side_effect=parse_then_edit):
            with self.assertRaisesRegex(ValueError, 'input files changed'):
                verify_run(run, self.data)

    def test_edit_after_last_observation_cannot_rebind_published_results(self):
        real_rename = output._rename_new_directory
        for name in data_module.SCHEMAS:
            with self.subTest(table=name):
                folder = self.copy_data(name)
                target = self.root / f'out-{name}'
                digest = fingerprint(folder)
                def change_at_publish(source, destination):
                    change_csv(folder, name)  # Beyond the final input observation.
                    real_rename(source, destination)
                with patch('scai.output._rename_new_directory', side_effect=change_at_publish):
                    code, error = self.invoke('analyze', '--data', folder, '--out', target)
                self.assertEqual(code, 0, error)
                for filename in ('results.json', 'ai_packet.json'):
                    self.assertEqual((target / filename).read_bytes(),
                                     (ROOT / 'examples/base' / filename).read_bytes())
                self.assertEqual(read_json(target / 'run_manifest.json')['input_sha256'], digest)
                self.assertNotEqual(fingerprint(folder), digest)
                with self.assertRaisesRegex(ValueError, 'run input fingerprint mismatch'):
                    verify_run(target, folder)

    def test_unchanged_baseline_result_and_packet_are_byte_identical(self):
        before = bytes_in(self.data)
        target = self.root / 'base'
        cli.run(self.data, target)
        for name in ('results.json', 'ai_packet.json'):
            self.assertEqual((target / name).read_bytes(), (ROOT / 'examples/base' / name).read_bytes())
        verify_run(target, self.data)
        self.assertEqual(bytes_in(self.data), before)


class OutputSafetyTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        before = bytes_in(self.data)
        self.addCleanup(lambda: self.assertEqual(bytes_in(self.data), before))

    def command(self, command, target):
        args = [command, '--out', target]
        if command == 'analyze': args += ['--data', self.data]
        return self.invoke(*args)

    def test_existing_directory_and_old_review_are_preserved(self):
        target = self.root / 'existing'
        target.mkdir()
        (target / 'human_review.json').write_bytes(b'OLD REVIEW SENTINEL')
        (target / 'results.json').write_bytes(b'OLD RESULTS SENTINEL')
        before = bytes_in(target)
        for command in ('generate', 'analyze'):
            code, error = self.command(command, target)
            self.assertEqual(code, 2, error)
            self.assertIn('refusing overwrite', error)
            self.assertEqual(bytes_in(target), before)

    def test_existing_empty_directory_is_refused(self):
        target = self.root / 'empty'
        target.mkdir()
        for command in ('generate', 'analyze'):
            code, error = self.command(command, target)
            self.assertEqual(code, 2, error)
            self.assertIn('refusing overwrite', error)
            self.assertEqual(list(target.iterdir()), [])

    def test_existing_file_is_refused(self):
        target = self.root / 'file'
        target.write_bytes(b'USER FILE')
        for command in ('generate', 'analyze'):
            code, error = self.command(command, target)
            self.assertEqual(code, 2, error)
            self.assertEqual(target.read_bytes(), b'USER FILE')

    def test_generate_new_seed_cannot_replace_input(self):
        code, error = self.invoke('generate', '--out', self.data, '--seed', 9)
        self.assertEqual(code, 2, error)
        self.assertIn('refusing overwrite', error)

    def test_input_output_overlap_and_normalized_paths_are_rejected(self):
        for target in (self.data, self.data / 'child', self.root,
                       self.data / '..' / 'input' / 'child'):
            with self.subTest(target=target):
                code, error = self.command('analyze', target)
                self.assertEqual(code, 2, error)
                self.assertIn('output conflicts with an input path', error)
        self.assertFalse((self.data / 'child').exists())

    def test_render_failure_leaves_no_final_or_staging_files(self):
        target = self.root / 'render-failure'
        with patch('scai.__main__.render', side_effect=OSError('injected render failure')):
            code, error = self.command('analyze', target)
        self.assertEqual(code, 2, error)
        self.assertIn('injected render failure', error)
        self.assert_no_bundle(target)

    def test_analysis_manifest_write_failure_leaves_no_final_bundle(self):
        target = self.root / 'manifest-failure'
        real_dump = cli.dump
        def fail_manifest(path, value):
            if path.name == 'run_manifest.json': raise OSError('injected manifest write failure')
            real_dump(path, value)
        with patch('scai.__main__.dump', side_effect=fail_manifest):
            code, error = self.command('analyze', target)
        self.assertEqual(code, 2, error)
        self.assertIn('injected manifest write failure', error)
        self.assert_no_bundle(target)

    def test_generation_csv_write_failure_leaves_no_final_bundle(self):
        target = self.root / 'csv-failure'
        real_write = data_module.write_csv
        def fail_second(path, *args, **kwargs):
            if Path(path).name == 'inventory.csv': raise OSError('injected CSV write failure')
            return real_write(path, *args, **kwargs)
        with patch('scai.data.write_csv', side_effect=fail_second):
            code, error = self.command('generate', target)
        self.assertEqual(code, 2, error)
        self.assertIn('injected CSV write failure', error)
        self.assert_no_bundle(target)

    def test_generation_provenance_write_failure_leaves_no_final_bundle(self):
        target = self.root / 'provenance-failure'
        with patch('scai.data.dump', side_effect=OSError('injected provenance failure')):
            code, error = self.command('generate', target)
        self.assertEqual(code, 2, error)
        self.assert_no_bundle(target)

    def test_generated_data_validation_failure_leaves_no_final_bundle(self):
        target = self.root / 'validation-failure'
        with patch('scai.data.load', side_effect=ValueError('injected validation failure')):
            code, error = self.command('generate', target)
        self.assertEqual(code, 2, error)
        self.assert_no_bundle(target)

    def test_invalid_input_creates_no_output_parent(self):
        target = self.root / 'not-created' / 'output'
        code, error = self.invoke('analyze', '--data', self.root / 'missing', '--out', target)
        self.assertEqual(code, 2, error)
        self.assertFalse(target.parent.exists())

    def test_new_target_created_during_build_is_preserved(self):
        for command in ('generate', 'analyze'):
            target = self.root / command
            real_build = data_module._generate if command == 'generate' else cli.render
            def build_then_create(*args, **kwargs):
                real_build(*args, **kwargs)
                target.mkdir()
                (target / 'other-process').write_bytes(b'OTHER PROCESS')
            hook = 'scai.data._generate' if command == 'generate' else 'scai.__main__.render'
            with patch(hook, side_effect=build_then_create):
                code, error = self.command(command, target)
            self.assertEqual(code, 2, error)
            self.assertIn('refusing overwrite', error)
            self.assertEqual(bytes_in(target), {'other-process': b'OTHER PROCESS'})
            self.assertEqual(list(target.parent.glob(f'.{target.name}-*')), [])

    def test_empty_target_created_after_final_check_is_not_replaced(self):
        real_rename = output._rename_new_directory
        for command in ('generate', 'analyze'):
            target = self.root / command
            def race_at_rename(source, destination):
                destination.mkdir()  # AFTER check_new_output, before the OS call.
                return real_rename(source, destination)
            with patch('scai.output._rename_new_directory', side_effect=race_at_rename):
                code, error = self.command(command, target)
            self.assertEqual(code, 2, error)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(list(target.parent.glob(f'.{target.name}-*')), [])

    def test_rename_failure_leaves_no_final_bundle(self):
        for command in ('generate', 'analyze'):
            target = self.root / command
            with patch('scai.output._rename_new_directory', side_effect=OSError('injected rename failure')):
                code, error = self.command(command, target)
            self.assertEqual(code, 2, error)
            self.assert_no_bundle(target)

    def test_output_argument_is_required_for_generate_and_analyze(self):
        for command in ('generate', 'analyze'):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                cli.main([command])
            self.assertEqual(exc.exception.code, 2)

    def test_fresh_generate_analyze_validate_and_pending_review(self):
        generated, run, ai, reviewed = [self.root / n for n in ('generated', 'run', 'ai', 'reviewed')]
        response = ROOT / 'examples/ai_response_codex.json'
        self.assertEqual(self.invoke('generate', '--out', generated)[0], 0)
        self.assertEqual(bytes_in(generated), bytes_in(self.data))
        self.assertEqual(self.invoke('analyze', '--data', generated, '--out', run)[0], 0)
        self.assertEqual((run / 'results.json').read_bytes(), (ROOT / 'examples/base/results.json').read_bytes())
        _, packet = verify_run(run, generated)
        self.assertEqual(self.invoke('validate-ai', '--run', run, '--data', generated,
                                     '--response', response, '--out', ai)[0], 0)
        template = read_json(ai / 'review_template.json')
        self.assertEqual(template['schema_version'], 2)
        self.assertEqual(template['response_sha256'], response_sha256(packet, read_json(response)))
        self.assertEqual(self.invoke('review', '--run', run, '--data', generated,
                                     '--response', response, '--decisions', ai / 'review_template.json',
                                     '--out', reviewed)[0], 0)
        self.assertEqual(read_json(reviewed / 'human_review.json')['approved_count'], 0)
        self.assertEqual(bytes_in(generated), bytes_in(self.data))


class PathAndPublishTests(IsolatedCase):
    def test_windows_case_alias_or_normalized_posix_path_cannot_overlap(self):
        alias = Path(str(self.data).swapcase()) if os.name == 'nt' else self.data / '..' / 'input'
        with self.assertRaisesRegex(ValueError, 'output conflicts'):
            output.check_new_output(alias / 'new', [self.data])

    def test_real_directory_alias_is_rejected_for_input_and_output(self):
        alias = self.root / 'alias'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(self.data), str(alias))
            self.assertTrue(alias.is_junction())
        else:
            alias.symlink_to(self.data, target_is_directory=True)
            self.assertTrue(alias.is_symlink())
        with self.assertRaisesRegex(ValueError, 'symbolic links/reparse points'):
            read_snapshot(alias)
        for target in (alias, alias / 'new', alias / '..' / 'new'):
            with self.assertRaisesRegex(ValueError, 'symbolic links/reparse points'):
                output.check_new_output(target)
        self.assertFalse((self.data / 'new').exists())

    def test_symbolic_link_metadata_including_dangling_target_is_rejected(self):
        target = self.root / 'dangling-link'
        real_stat = Path.lstat
        def link_stat(path):
            if path == target: return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return real_stat(path)
        with patch.object(Path, 'lstat', link_stat):
            with self.assertRaisesRegex(ValueError, 'symbolic links/reparse points'):
                output.check_new_output(target)

    def test_existing_destinations_are_refused_by_native_rename(self):
        source = self.root / 'stage'
        source.mkdir()
        (source / 'new').write_bytes(b'NEW')
        for kind in ('empty', 'nonempty', 'file'):
            target = self.root / kind
            if kind == 'file': target.write_bytes(b'OLD')
            else:
                target.mkdir()
                if kind == 'nonempty': (target / 'old').write_bytes(b'OLD')
            before = target.read_bytes() if kind == 'file' else bytes_in(target)
            with self.assertRaises(OSError): output._rename_new_directory(source, target)
            self.assertEqual(target.read_bytes() if kind == 'file' else bytes_in(target), before)
            self.assertEqual((source / 'new').read_bytes(), b'NEW')

    def test_posix_adapters_request_exclusive_rename(self):
        for platform, symbol, expected in [('linux', 'renameat2', (-100, b'stage', -100, b'target', 1)),
                                            ('darwin', 'renamex_np', (b'stage', b'target', 4))]:
            rename = Mock(return_value=0)
            libc = SimpleNamespace(**{symbol: rename})
            with patch('scai.output.os.name', 'posix'), patch('scai.output.sys.platform', platform), \
                    patch('scai.output.ctypes.CDLL', return_value=libc):
                output._rename_new_directory('stage', 'target')
            rename.assert_called_once_with(*expected)

    def test_unsupported_exclusive_rename_does_not_fall_back(self):
        with patch('scai.output.os.name', 'posix'), patch('scai.output.sys.platform', 'linux'), \
                patch('scai.output.ctypes.CDLL', return_value=SimpleNamespace()), \
                patch('scai.output.os.rename') as fallback:
            with self.assertRaises(OSError) as exc: output._rename_new_directory('stage', 'target')
            self.assertEqual(exc.exception.errno, errno.ENOTSUP)
            fallback.assert_not_called()

    def test_native_exclusive_rename_error_is_propagated(self):
        libc = SimpleNamespace(renameat2=Mock(return_value=-1))
        with patch('scai.output.os.name', 'posix'), patch('scai.output.sys.platform', 'linux'), \
                patch('scai.output.ctypes.CDLL', return_value=libc), \
                patch('scai.output.ctypes.get_errno', return_value=errno.EEXIST):
            with self.assertRaises(FileExistsError): output._rename_new_directory('stage', 'target')
