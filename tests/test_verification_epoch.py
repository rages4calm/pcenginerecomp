"""Authored operation-local derivation reuse and unchanged-byte guard tests."""
import json
import os
import unittest
from unittest.mock import patch

from pcerecomp import project, history
from pcerecomp.snapshots import SnapshotStore
from pcerecomp.verification_epoch import verified_input_epoch, current_epoch
from tests import test_project
from tests.test_history import capture


class VerificationEpochTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_project.ConsumerProjectTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def verify(self):
        return self.fixture.verify()

    def alter(self, path):
        before = path.stat()
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    def test_parsed_module_reused_only_within_scope_and_returned_views_detached(self):
        baseline = self.verify()
        with patch.object(project, '_module_manifest', wraps=project._module_manifest) as parse:
            with verified_input_epoch():
                first = self.verify()
                first['config']['runtime']['joypad'] = 6
                first['identities'].clear()
                with verified_input_epoch():
                    second = self.verify()
                self.assertEqual(second, baseline)
                self.assertEqual(self.verify(), baseline)
            self.assertEqual(parse.call_count, 1)
            self.assertEqual(self.verify(), baseline)
            self.assertEqual(parse.call_count, 2)
        self.assertIsNone(current_epoch())

    def test_same_timestamp_changed_payload_refuses_and_poisons_epoch(self):
        with self.assertRaises(ValueError):
            with verified_input_epoch():
                self.verify()
                self.alter(self.root/'program.bin')
                with self.assertRaises(ValueError):
                    self.verify()
                with self.assertRaisesRegex(ValueError, 'failed'):
                    self.verify()

    def test_success_exit_revalidates_descriptor_even_without_further_hits(self):
        with self.assertRaises(ValueError):
            with verified_input_epoch():
                self.verify()
                self.alter(self.fixture.descriptor)

    def test_nested_success_exit_also_seals_current_raw_inputs(self):
        with self.assertRaises(ValueError):
            with verified_input_epoch():
                self.verify()
                with verified_input_epoch():
                    self.alter(self.root/'program.bin')

    def test_sdk_added_member_and_same_timestamp_content_change_refuse(self):
        for added in (False, True):
            fixture = test_project.ConsumerProjectTests();fixture.setUp()
            try:
                with self.subTest(added=added), self.assertRaises(ValueError):
                    with verified_input_epoch():
                        fixture.verify()
                        if added:
                            (fixture.tool/'pcerecomp/new.py').write_bytes(b'# authored\n')
                        else:
                            self.alter(fixture.tool/'pcerecomp/logic.py')
                        fixture.verify()
            finally:
                fixture.doCleanups()

    def test_closed_capability_and_nested_exception_cannot_be_reused(self):
        with verified_input_epoch() as epoch:
            self.verify()
        with self.assertRaisesRegex(ValueError, 'closed'):
            epoch.revalidate()
        with self.assertRaisesRegex(ValueError, 'failed'):
            with verified_input_epoch():
                try:
                    with verified_input_epoch():
                        raise RuntimeError('authored failure')
                except RuntimeError:
                    pass
                self.verify()
        self.assertIsNone(current_epoch())

    def test_failed_first_admission_never_falls_back_inside_epoch(self):
        self.alter(self.root/'program.bin')
        with self.assertRaisesRegex(ValueError, 'failed'):
            with verified_input_epoch():
                with self.assertRaises(ValueError):
                    self.verify()
                self.verify()

    def history_closure(self):
        source = self.root/'capture.json'
        source.write_text(json.dumps(capture()), encoding='utf-8')
        return history.compose_history([source], self.root/'history')

    def test_retained_history_revalidator_rejects_raw_capture_and_new_member(self):
        for change in ('bytes', 'member'):
            admitted = self.history_closure()
            checked = self.verify()
            descriptor = SnapshotStore();descriptor.bind(self.fixture.descriptor)
            with self.subTest(change=change), self.assertRaises(ValueError):
                with verified_input_epoch() as epoch:
                    key = epoch.key(self.fixture.descriptor, True)
                    epoch.admit(key, checked, descriptor, [admitted.revalidate])
                    if change == 'bytes':
                        path = next((self.root/'history/captures').iterdir())
                        self.alter(path)
                    else:
                        (self.root/'history/captures/unlisted.json').write_bytes(b'{}')
                    epoch.lookup(key)
            # Retire only this test's authored graph before the next subcase.
            import shutil
            shutil.rmtree(self.root/'history')

    def test_adapter_closed_membership_is_revalidated(self):
        from tests import test_title_adapter
        fixture = test_title_adapter.ConsumerTitleContractTests();fixture.setUp()
        try:
            with self.assertRaises(ValueError):
                with verified_input_epoch():
                    project.verify(fixture.fixture.descriptor, allow_revision_override=True)
                    (fixture.root/'adapter/unbound.hpp').write_bytes(b'// authored\n')
                    project.verify(fixture.fixture.descriptor, allow_revision_override=True)
        finally:
            fixture.doCleanups()

    def test_actual_history_project_retains_closed_graph_without_rederivation(self):
        import tomllib
        from pcerecomp import emitter, prepare
        admitted = self.history_closure()
        output = self.root/'generated'
        emitter.emit_history(admitted.index_path, output)
        config = tomllib.loads(self.fixture.text)
        config['module'] = dict(source=dict(path='generated/module.cpp', sha256=project.sha256(output/'module.cpp')),
            manifest=dict(path='generated/module.json', sha256=project.sha256(output/'module.json')),
            observation_history=dict(path='history/history.json', sha256=admitted.index_sha256))
        self.fixture.descriptor.write_text(prepare._toml(config), encoding='utf-8', newline='\n')
        baseline = self.verify()
        with patch.object(project, '_module_observation_history', wraps=project._module_observation_history) as derive:
            with self.assertRaises(ValueError):
                with verified_input_epoch():
                    self.assertEqual(self.verify(), baseline)
                    self.assertEqual(self.verify(), baseline)
                    self.assertEqual(derive.call_count, 1)
                    (self.root/'history/catalogue/unlisted.json').write_bytes(b'{}')
                    self.verify()


if __name__ == '__main__':
    unittest.main()
