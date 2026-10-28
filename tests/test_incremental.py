"""Managed rebuild admission and failure controls using authored files only."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import incremental as inc, project
from pcerecomp.emitter import emit_capture
from tests import test_project, test_capture


class ManagedRebuildTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_project.ConsumerProjectTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.descriptor = self.fixture.descriptor
        self.module = self.root/'emitted'
        emit_capture(test_capture.capture([test_capture.observation(0x4000, (0xea,))]),
                     self.module, partition_layout='stable')
        text = self.fixture.text.replace('path = "module.cpp"', 'path = "emitted/module.cpp"')
        text = text.replace('path = "module.json"', 'path = "emitted/module.json"')
        text = text.replace(project.sha256(self.root/'module.cpp'), project.sha256(self.module/'module.cpp'))
        text = text.replace(project.sha256(self.root/'module.json'), project.sha256(self.module/'module.json'))
        self.descriptor.write_text(text, encoding='utf-8')
        self.workspace = self.root/'managed'

    def checked(self):
        return project.verify(self.descriptor, allow_revision_override=True)

    def retained(self):
        """An authored retained-state fixture, not a claimed compiled package."""
        self.workspace.mkdir()
        module = self.workspace/'module'; module.mkdir()
        inc._sync(inc._module(self.checked()), module)
        output = self.workspace/'output'; output.mkdir()
        (output/'authored.obj').write_bytes(b'authored object sentinel')
        (output/'.ninja_deps').write_bytes(b'authored dependency sentinel')
        (self.workspace/'project.toml').write_text('schema = 1\n')
        history = self.workspace/'history/000000'; history.mkdir(parents=True)
        state = dict(schema=1, generation=0, build_tree=inc._snapshot(output),
                     module_tree=inc._snapshot(module),
                     descriptor_sha256=project.sha256(self.workspace/'project.toml'))
        project._write_new(history/'state.json', state)
        project._write_new(self.workspace/'current.json',
                           dict(generation=0, sha256=project.sha256(history/'state.json')))
        return state

    def test_only_stable_full_mapping_range_modules_admitted(self):
        checked = self.checked()
        manifest = self.module/'module.json'
        original = json.loads(manifest.read_text())
        for key, value in [('partition_layout', 'balanced'), ('partition_identity', 'pc_only'),
                           ('pc_bucket_size', True), ('pc_bucket_size', 128), ('partitioned', False)]:
            changed = dict(original, **{key: value})
            manifest.write_text(json.dumps(changed))
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                inc._module(checked)
        manifest.write_text(json.dumps(original))
        self.assertIn('module.cpp', inc._module(checked))

    def test_generated_descriptor_roundtrips_verified_contract(self):
        checked = self.checked()
        config = inc._config(checked, self.workspace, inc._module(checked))
        actual = tomllib.loads(inc._toml(config))
        self.assertEqual(config, actual)
        self.assertEqual(actual['payload']['path'], str(self.root/'program.bin'))
        self.assertEqual(actual['tool']['path'], str(self.fixture.tool))
        changed = copy.deepcopy(config)
        changed['module']['source']['sha256'] = 'a'*64
        self.assertEqual(inc._fixed_config(config), inc._fixed_config(changed))
        changed['runtime']['joypad'] = 6
        self.assertNotEqual(inc._fixed_config(config), inc._fixed_config(changed))

    def test_valid_unicode_paths_roundtrip_without_surrogate_escapes(self):
        config = dict(schema=1, asset=dict(path='authored/🎮/disc.bin', sha256='a'*64))
        self.assertEqual(tomllib.loads(inc._toml(config)), config)

    def test_official_run_refuses_interrupted_managed_generation(self):
        state = self.retained()
        receipt = dict(incremental=dict(workspace=str(self.workspace), generation=0))
        inc.validate_run(self.workspace/'output', receipt)
        receipt['incremental']['generation'] = 1
        with self.assertRaisesRegex(ValueError, 'not current'):
            inc.validate_run(self.workspace/'output', receipt)
        receipt['incremental']['generation'] = 0
        (self.workspace/'in-progress.json').write_text('{"generation":1}')
        with self.assertRaisesRegex(ValueError, 'Incomplete generation'):
            inc.validate_run(self.workspace/'output', receipt)

    def test_retained_object_dependency_and_module_edits_refused(self):
        self.retained()
        for path in (self.workspace/'output/authored.obj', self.workspace/'output/.ninja_deps',
                     self.workspace/'module/module.cpp', self.workspace/'project.toml'):
            before = path.read_bytes(); stamp = path.stat().st_mtime_ns
            path.write_bytes(before+b'!')
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, 'changed outside'):
                inc._state(self.workspace)
            path.write_bytes(before); os.utime(path, ns=(stamp, stamp))
        inc._state(self.workspace)

    def test_backdated_object_is_refused_even_if_bytes_unchanged(self):
        self.retained()
        path = self.workspace/'output/authored.obj'
        stamp = path.stat().st_mtime_ns
        os.utime(path, ns=(stamp-1000000000, stamp-1000000000))
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            inc._state(self.workspace)

    def test_extra_or_removed_build_files_are_refused(self):
        self.retained()
        extra = self.workspace/'output/extra.obj'; extra.write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            inc._state(self.workspace)
        extra.unlink()
        (self.workspace/'output/authored.obj').unlink()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            inc._state(self.workspace)

    def test_incomplete_generation_refused_without_repair(self):
        self.retained()
        marker = self.workspace/'in-progress.json'; marker.write_text('{"generation":1}')
        with self.assertRaisesRegex(ValueError, 'Incomplete generation'):
            inc._state(self.workspace)
        self.assertTrue(marker.exists())

    def test_pointer_and_history_corruption_refused(self):
        self.retained()
        pointer = self.workspace/'current.json'
        original = pointer.read_bytes()
        for value in ({'generation': True, 'sha256': '0'*64},
                      {'generation': '../outside', 'sha256': '0'*64},
                      {'generation': 0, 'sha256': '0'*64}):
            pointer.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                inc._state(self.workspace)
        pointer.write_bytes(original)
        (self.workspace/'history/000000/state.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            inc._state(self.workspace)

    def test_lock_excludes_second_producer_and_releases_on_failure(self):
        self.workspace.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'authored failure'):
            with inc._lock(self.workspace):
                with self.assertRaises(FileExistsError):
                    with inc._lock(self.workspace):
                        self.fail('Second writer entered')
                raise RuntimeError('authored failure')
        self.assertFalse((self.workspace/'producer.lock').exists())

    def test_sync_preserves_unchanged_timestamps_and_accounts_removed_files(self):
        source = self.root/'source'; source.mkdir()
        target = self.root/'target'; target.mkdir()
        for name, value in [('same.cpp', b'same'), ('changed.cpp', b'new')]:
            (source/name).write_bytes(value)
        for name, value in [('same.cpp', b'same'), ('changed.cpp', b'old'), ('removed.cpp', b'old')]:
            (target/name).write_bytes(value)
            os.utime(target/name, ns=(1000000000, 1000000000))
        old = {p.name: 1000000000 for p in target.iterdir()}
        report = inc._sync({p.name:p for p in source.iterdir()}, target, old=old, newer_than=1000000000)
        self.assertEqual(report, dict(changed=['changed.cpp'], unchanged=['same.cpp'], removed=['removed.cpp']))
        self.assertEqual((target/'same.cpp').stat().st_mtime_ns, 1000000000)
        self.assertGreater((target/'changed.cpp').stat().st_mtime_ns, 1000000000)
        self.assertEqual((target/'changed.cpp').read_bytes(), b'new')
        self.assertFalse((target/'removed.cpp').exists())

    def test_future_timestamp_rejects_sync(self):
        target = self.root/'target'; target.mkdir()
        source = self.root/'new.cpp'; source.write_text('authored')
        with self.assertRaisesRegex(ValueError, 'Clock resolution'):
            inc._sync({'new.cpp':source}, target, newer_than=time.time_ns()+10000000000)

    def test_existing_workspace_and_self_candidate_refused_before_compile(self):
        self.workspace.mkdir()
        with patch.object(inc, 'prepare') as compiler:
            with self.assertRaisesRegex(ValueError, 'Workspace exists'):
                inc.rebuild(self.descriptor, self.workspace, create=True, allow_revision_override=True)
            with self.assertRaisesRegex(ValueError, 'outside managed workspace'):
                inc.rebuild(self.descriptor, self.root, create=True, allow_revision_override=True)
            compiler.assert_not_called()

    def test_update_cannot_override_build_options(self):
        self.workspace.mkdir()
        with self.assertRaisesRegex(ValueError, 'original explicit build options'):
            inc.rebuild(self.descriptor, self.workspace, toolchain_root=self.root, allow_revision_override=True)

    def test_cli_refuses_missing_or_stale_workspace(self):
        with patch('sys.stderr'), self.assertRaises(SystemExit):
            inc.main(['create', str(self.descriptor), '--workspace', str(self.workspace)])
        with patch('sys.stderr'):
            self.assertEqual(inc.main(['update', str(self.descriptor), '--workspace', str(self.workspace),
                                       '--allow-revision-override']), 2)


if __name__ == '__main__':
    unittest.main()
