"""Authored typed-report/controller tests; mocked subprocesses are not native proof."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import checkpoint_inspection as inspection


def sha(data):
    return hashlib.sha256(data).hexdigest()


def runtime(checkpoint_sha='a'*64, *, reference=False, host_sha='e'*64):
    cpu = {key: 0 for key in (*inspection.CPU_BYTES, *inspection.CPU_WORDS, *inspection.CPU_COUNTS)}
    cpu.update(sp=255, p=4, pc=0x4000, mpr=[255, 248, 128, 129, 130, 131, 132, 0],
        clock_divisor=3, ticks=300, cycles=100, native_steps=0 if reference else 17,
        interpreter_steps=17 if reference else 0)
    host = {key: 0 for key in inspection.HOST_COUNTS}
    host.update(scripted=[0]*5, remote=[0]*5)
    return dict(schema=1, format=inspection.RUNTIME_FORMAT, runtime_abi=inspection.project.ABI,
        checkpoint_schema=1, diagnostic_only=True, executed=False, restored=False,
        network_started=False, presentation_started=False, native_steps=0, interpreter_steps=0,
        checkpoint_identity='f'*64, checkpoint_sha256=checkpoint_sha,
        core_sha256=('d' if reference else 'c')*64, host_sha256=host_sha,
        tier_neutral_core_sha256='b'*64, cpu=cpu, host=host, frame=0, raster_frames=1,
        pending_pcm_frames=41, guest_input=dict(enabled=True, pressed=[0]*5), adapter=None)


class TypedInspectionReportTests(unittest.TestCase):
    def test_preserves_raw_tier_counts_and_state_without_claiming_execution(self):
        value = runtime(); before = copy.deepcopy(value)
        self.assertIs(inspection._runtime_receipt(value, 'a'*64), value)
        self.assertEqual(value, before)
        self.assertEqual(value['cpu']['native_steps'], 17)
        self.assertEqual(value['native_steps'], 0)
        self.assertEqual(value['pending_pcm_frames'], 41)

    def test_every_top_level_field_is_required_and_unknown_fields_refused(self):
        values = [None, [], {}, dict(runtime(), unknown=True)]
        for key in runtime():
            value = runtime(); del value[key]; values.append(value)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                inspection._runtime_receipt(value, 'a'*64)

    def test_all_cpu_host_and_input_fields_are_closed_and_required(self):
        for section in ('cpu', 'host', 'guest_input'):
            for key in runtime()[section]:
                value = runtime(); del value[section][key]
                with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                    inspection._runtime_receipt(value, 'a'*64)
            value = runtime(); value[section]['invented'] = 0
            with self.assertRaises(ValueError): inspection._runtime_receipt(value, 'a'*64)

    def test_strict_boolean_integer_and_digest_types(self):
        for key, item in (('schema', True), ('runtime_abi', True), ('checkpoint_schema', True),
                ('diagnostic_only', 1), ('executed', 0), ('restored', 0), ('network_started', 0),
                ('presentation_started', 0), ('native_steps', False), ('interpreter_steps', False),
                ('frame', False), ('raster_frames', False), ('pending_pcm_frames', False)):
            value = runtime(); value[key] = item
            with self.subTest(key=key), self.assertRaises(ValueError): inspection._runtime_receipt(value, 'a'*64)
        for key in ('checkpoint_identity', 'checkpoint_sha256', 'core_sha256', 'host_sha256', 'tier_neutral_core_sha256'):
            for item in (None, False, 'A'*64, 'x'*64, 'a'*63):
                value = runtime(); value[key] = item
                with self.subTest(key=key, item=item), self.assertRaises(ValueError):
                    inspection._runtime_receipt(value, 'a'*64)

    def test_ranges_and_new_execution_claims_refuse(self):
        for key, item in (('schema', 2), ('runtime_abi', 0), ('checkpoint_schema', 0),
                ('format', 'other'), ('diagnostic_only', False), ('executed', True), ('restored', True),
                ('network_started', True), ('presentation_started', True), ('native_steps', 1),
                ('interpreter_steps', 1), ('checkpoint_sha256', 'b'*64), ('frame', -1),
                ('pending_pcm_frames', 1 << 64)):
            value = runtime(); value[key] = item
            with self.subTest(key=key), self.assertRaises(ValueError): inspection._runtime_receipt(value, 'a'*64)
        for key in inspection.CPU_COUNTS:
            for item in (-1, 1 << 64, True, '0'):
                value = runtime(); value['cpu'][key] = item
                with self.subTest(key=key, item=item), self.assertRaises(ValueError):
                    inspection._runtime_receipt(value, 'a'*64)
        for section, key, item in (('cpu', 'pc', 65536), ('cpu', 'a', 256), ('cpu', 'clock_divisor', 4),
                ('cpu', 'mpr', [0]*7), ('cpu', 'mpr', [0]*7+[256]), ('host', 'scripted', [0]*4),
                ('host', 'remote', [0]*4+[4096]), ('host', 'next_poll', -1),
                ('guest_input', 'enabled', 1), ('guest_input', 'pressed', [0]*4+[True])):
            value = runtime(); value[section][key] = item
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                inspection._runtime_receipt(value, 'a'*64)

    def test_adapter_envelope_has_independent_binding_and_state_digest(self):
        value = runtime(); value['checkpoint_schema'] = 2
        with self.assertRaises(ValueError): inspection._runtime_receipt(value, 'a'*64)
        value['adapter'] = dict(binding_sha256='1'*64, state_sha256='2'*64, state_bytes=72)
        inspection._runtime_receipt(value, 'a'*64)
        for key, item in (('binding_sha256', 'A'*64), ('state_sha256', None), ('state_bytes', True), ('state_bytes', 4161)):
            altered = copy.deepcopy(value); altered['adapter'][key] = item
            with self.subTest(key=key), self.assertRaises(ValueError): inspection._runtime_receipt(altered, 'a'*64)
        value['checkpoint_schema'] = 1
        with self.assertRaises(ValueError): inspection._runtime_receipt(value, 'a'*64)


class InspectionControllerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('sdk', 'consumer', 'build', 'bin', 'inputs'): (self.root/name).mkdir()
        self.descriptor = self.root/'consumer/project.toml'; self.descriptor.write_text('authored', encoding='utf-8')
        self.build = self.root/'build'; self.binary = self.root/'bin/authored.exe'; self.binary.write_bytes(b'not an executable')
        self.checkpoint = self.root/'inputs/native.pcec'; self.checkpoint.write_bytes(b'authored opaque native checkpoint')
        self.cp_sha = sha(self.checkpoint.read_bytes()); self.original = self.checkpoint.read_bytes()
        self.reference = self.root/'inputs/reference.pcec'; self.reference.write_bytes(b'authored opaque reference checkpoint')
        self.reference_sha = sha(self.reference.read_bytes())
        self.reports = {self.cp_sha: runtime(self.cp_sha), self.reference_sha: runtime(self.reference_sha, reference=True)}
        self.checked = dict(tool_root=self.root/'sdk', config={}, files=dict(module_manifest=self.root/'consumer/module.json'))
        self.built = dict(binary_sha256=sha(self.binary.read_bytes()), output_files={'authored.exe': sha(self.binary.read_bytes())})
        self.package = self.checked, self.built, self.binary, 'a'*64
        for target, value in (('_source', self.package), ('project.command_for', ['authored-runner']),
                              ('project._binding', dict(context='authored-producer'))):
            mock = patch('pcerecomp.checkpoint_inspection.'+target, return_value=value)
            setattr(self, target.replace('.', '_'), mock.start()); self.addCleanup(mock.stop)
        self.child_mock = patch('pcerecomp.checkpoint_inspection.subprocess.run', side_effect=self.child)
        self.run = self.child_mock.start(); self.addCleanup(self.child_mock.stop)
        self.output = self.root/'inspection'

    def child(self, command, **kwargs):
        digest = command[command.index('--checkpoint-report-sha')+1]
        kwargs['stdout'].write(json.dumps(self.reports[digest]).encode())
        self.assertEqual(kwargs['env']['SDL_VIDEODRIVER'], 'dummy')
        self.assertEqual(kwargs['env']['SDL_AUDIODRIVER'], 'dummy')
        return subprocess.CompletedProcess(command, 0)

    def inspect(self, **kwargs):
        return inspection.inspect_checkpoint(self.descriptor, self.build, self.checkpoint, self.output,
                                             expected_checkpoint_sha256=self.cp_sha, **kwargs)

    def pair(self):
        left, right = self.root/'left', self.root/'right'
        inspection.inspect_checkpoint(self.descriptor, self.build, self.checkpoint, left,
            expected_checkpoint_sha256=self.cp_sha, reference_enabled=True)
        inspection.inspect_checkpoint(self.descriptor, self.build, self.reference, right,
            expected_checkpoint_sha256=self.reference_sha, reference_enabled=True)
        return left, right

    def compare(self, left, right, *, output=None, **kwargs):
        return inspection.compare_checkpoint_inspections(left, right, output or self.root/'comparison',
            expected_left_receipt_sha256=sha((left/'receipt.json').read_bytes()),
            expected_right_receipt_sha256=sha((right/'receipt.json').read_bytes()), **kwargs)

    def test_success_preserves_source_and_records_typed_cpu_mpr_without_new_work(self):
        report = self.inspect(reference_enabled=True)
        self.assertTrue(report['passed']); self.assertFalse(report['execution_evidence'])
        self.assertFalse(report['migration_admitted']); self.assertFalse(report['game_save_validated'])
        self.assertEqual(report['runtime']['cpu']['mpr'], self.reports[self.cp_sha]['cpu']['mpr'])
        self.assertEqual(report['runtime']['cpu']['native_steps'], 17)
        self.assertEqual(report['runtime']['native_steps'], 0)
        self.assertEqual(self.checkpoint.read_bytes(), self.original)
        self.assertEqual(json.loads((self.output/'receipt.json').read_bytes()), report)
        self.assertFalse(list(self.output.glob('*.pending')))

    def test_digest_required_reference_type_and_existing_output_fail_before_child(self):
        with self.assertRaises(TypeError): inspection.inspect_checkpoint(self.descriptor, self.build, self.checkpoint, self.output)
        for value in ('', None, 'A'*64):
            with self.assertRaises(ValueError):
                inspection.inspect_checkpoint(self.descriptor, self.build, self.checkpoint, self.output, expected_checkpoint_sha256=value)
        for value in (0, 1, 'on', None):
            with self.assertRaises(ValueError): self.inspect(reference_enabled=value)
        self.output.mkdir(); (self.output/'foreign').write_bytes(b'keep')
        with self.assertRaises(ValueError): self.inspect()
        self.run.assert_not_called(); self.assertEqual((self.output/'foreign').read_bytes(), b'keep')

    def test_wrong_checkpoint_digest_and_protected_output_fail_before_child(self):
        with self.assertRaises(ValueError):
            inspection.inspect_checkpoint(self.descriptor, self.build, self.checkpoint, self.output, expected_checkpoint_sha256='0'*64)
        self.output = self.root/'consumer/forbidden'
        with self.assertRaises(ValueError): self.inspect()
        self.run.assert_not_called(); self.assertFalse(self.output.exists())

    def test_failure_child_and_missing_or_invalid_json_are_not_passes(self):
        for label, child in (('exit', lambda c, **k: subprocess.CompletedProcess(c, 2)),
                ('empty', lambda c, **k: subprocess.CompletedProcess(c, 0)),
                ('malformed', lambda c, **k: (k['stdout'].write(b'{"schema":1,"schema":1}'), subprocess.CompletedProcess(c, 0))[1])):
            self.output = self.root/label; self.run.side_effect = child
            with self.subTest(label=label), self.assertRaises((ValueError, OSError)): self.inspect()
            self.assertFalse(json.loads((self.output/'receipt.json').read_bytes())['passed'])

    def test_guest_execution_server_or_adapter_claim_refuses(self):
        for label in ('guest', 'server', 'adapter'):
            self.output = self.root/label
            def child(command, **kwargs):
                value = runtime(self.cp_sha)
                if label == 'guest': value['native_steps'] = 1
                if label == 'server': kwargs['stderr'].write(b'PCE_DEV_PORT=1234\n')
                if label == 'adapter':
                    value['checkpoint_schema'] = 2
                    value['adapter'] = dict(binding_sha256='1'*64, state_sha256='2'*64, state_bytes=72)
                kwargs['stdout'].write(json.dumps(value).encode())
                return subprocess.CompletedProcess(command, 0)
            self.run.side_effect = child
            with self.subTest(label=label), self.assertRaises(ValueError): self.inspect()
            self.assertFalse(json.loads((self.output/'receipt.json').read_bytes())['passed'])

    def test_same_length_timestamp_restored_checkpoint_change_refuses_final_seal(self):
        before = self.checkpoint.stat()
        def child(command, **kwargs):
            result = self.child(command, **kwargs)
            data = bytearray(self.original); data[-1] ^= 1; self.checkpoint.write_bytes(data)
            os.utime(self.checkpoint, ns=(before.st_atime_ns, before.st_mtime_ns))
            return result
        self.run.side_effect = child
        with self.assertRaises(ValueError): self.inspect()
        self.assertFalse(json.loads((self.output/'receipt.json').read_bytes())['passed'])

    def test_changed_producer_refuses_final_seal(self):
        changed = copy.deepcopy(self.built); changed['output_files']['authored.exe'] = '0'*64
        self._source.side_effect = [self.package, (self.checked, changed, self.binary, 'a'*64)]
        with self.assertRaises(ValueError): self.inspect()
        self.assertFalse(json.loads((self.output/'receipt.json').read_bytes())['passed'])

    def test_output_lost_or_replaced_never_gets_recreated_or_foreign_receipt(self):
        for replace in (False, True):
            self.output = self.root/('replaced' if replace else 'missing')
            def child(command, **kwargs):
                kwargs['stdout'].close(); kwargs['stderr'].close()
                self.output.rename(self.root/('retired-'+str(replace)))
                if replace:
                    self.output.mkdir(); (self.output/'foreign').write_bytes(b'keep')
                return subprocess.CompletedProcess(command, 0)
            self.run.side_effect = child
            with self.subTest(replace=replace), self.assertRaises((ValueError, OSError)): self.inspect()
            if replace: self.assertEqual([p.name for p in self.output.iterdir()], ['foreign'])
            else: self.assertFalse(self.output.exists())

    def test_exact_inequality_is_a_performed_comparison_and_tier_policy_is_explicit(self):
        left, right = self.pair()
        exact = self.compare(left, right)
        self.assertTrue(exact['passed']); self.assertFalse(exact['equal'])
        self.assertEqual(exact['components'], dict(core=False, host=True))
        self.assertEqual(exact['projected_fields'], [])
        tier = self.compare(left, right, output=self.root/'tier', policy='tier-counters')
        self.assertTrue(tier['passed']); self.assertTrue(tier['equal'])
        self.assertEqual(tier['projected_fields'], list(inspection.TIER_COUNTERS))
        self.assertEqual(tier['counters']['left']['native_steps'], 17)
        self.assertEqual(tier['counters']['right']['interpreter_steps'], 17)
        self.assertFalse(tier['migration_admitted']); self.assertFalse(tier['execution_evidence'])
        self.assertEqual(self.run.call_count, 6)  # two retained plus two fresh per comparison

    def test_host_and_nonprojected_core_differences_remain_unequal(self):
        self.reports[self.reference_sha]['host_sha256'] = '1'*64
        self.reports[self.reference_sha]['tier_neutral_core_sha256'] = '2'*64
        self.reports[self.reference_sha]['cpu']['guard_misses'] = 1
        left, right = self.pair()
        report = self.compare(left, right, policy='tier-counters')
        self.assertTrue(report['passed']); self.assertFalse(report['equal'])
        self.assertEqual(report['components'], dict(core=False, host=False))

    def test_same_file_exact_comparison_passes_without_changing_source(self):
        self.inspect(); report = self.compare(self.output, self.output)
        self.assertTrue(report['equal']); self.assertEqual(self.checkpoint.read_bytes(), self.original)

    def test_required_receipt_hashes_unknown_policy_and_existing_output_refuse(self):
        left, right = self.pair(); output = self.root/'comparison'
        with self.assertRaises(TypeError): inspection.compare_checkpoint_inspections(left, right, output)
        with self.assertRaises(ValueError): self.compare(left, right, policy='ignore-anything')
        with self.assertRaises(ValueError):
            inspection.compare_checkpoint_inspections(left, right, output,
                expected_left_receipt_sha256='0'*64, expected_right_receipt_sha256=sha((right/'receipt.json').read_bytes()))
        output.mkdir(); (output/'foreign').write_bytes(b'keep')
        with self.assertRaises(ValueError): self.compare(left, right)
        self.assertEqual((output/'foreign').read_bytes(), b'keep')

    def test_retained_receipt_runtime_and_checkpoint_tamper_refuse(self):
        for target in ('receipt.json', 'runtime.json', 'checkpoint'):
            left, right = self.pair()
            expected = sha((left/'receipt.json').read_bytes())
            path = self.checkpoint if target == 'checkpoint' else left/target
            original = path.read_bytes(); path.write_bytes(original[:-1]+bytes([original[-1]^1]))
            try:
                with self.subTest(target=target), self.assertRaises((ValueError, OSError)):
                    inspection.compare_checkpoint_inspections(left, right, self.root/('compare-'+target.replace('.', '-')),
                        expected_left_receipt_sha256=expected, expected_right_receipt_sha256=sha((right/'receipt.json').read_bytes()))
            finally:
                path.write_bytes(original)
                # Keep each genuine closed pair rather than overwriting it.
                left.rename(self.root/('kept-left-'+target)); right.rename(self.root/('kept-right-'+target))

    def test_consistent_forged_hash_is_refused_by_fresh_typed_reinspection(self):
        left, right = self.pair(); forged = self.root/'forged'; shutil.copytree(left, forged)
        metadata = json.loads((forged/'runtime.json').read_bytes()); metadata['tier_neutral_core_sha256'] = '3'*64
        (forged/'runtime.json').write_text(json.dumps(metadata), encoding='utf-8')
        receipt = json.loads((forged/'receipt.json').read_bytes()); receipt['runtime'] = metadata
        receipt['runtime_receipt_sha256'] = sha((forged/'runtime.json').read_bytes())
        (forged/'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Fresh typed inspection disagrees'): self.compare(forged, right)
        failed = json.loads((self.root/'comparison/receipt.json').read_bytes())
        self.assertFalse(failed['passed']); self.assertNotIn('equal', failed)
        self.assertEqual(json.loads((left/'runtime.json').read_bytes())['tier_neutral_core_sha256'], 'b'*64)

    def test_consistent_cross_producer_identity_is_refused_before_fresh_process(self):
        self.reports[self.reference_sha]['checkpoint_identity'] = '0'*64
        left, right = self.pair(); count = self.run.call_count
        with self.assertRaisesRegex(ValueError, 'one exact producer'): self.compare(left, right)
        self.assertEqual(self.run.call_count, count)
        self.assertFalse((self.root/'comparison').exists())

    def test_comparison_input_change_during_fresh_reinspection_never_passes(self):
        left, right = self.pair(); original_child = self.child
        def child(command, **kwargs):
            result = original_child(command, **kwargs)
            path = left/'receipt.json'; data = path.read_bytes(); path.write_bytes(data+b' ')
            return result
        self.run.side_effect = child
        with self.assertRaises(ValueError): self.compare(left, right)
        failed = json.loads((self.root/'comparison/receipt.json').read_bytes())
        self.assertFalse(failed['passed']); self.assertNotIn('equal', failed)

    def test_failed_final_publication_removes_stale_equality_claim(self):
        left, right = self.pair()
        original_publish = inspection._publish_receipt
        def publish(path, identity, report):
            if report['format'] == inspection.COMPARISON_FORMAT and report['passed']:
                raise OSError('authored publication refusal')
            return original_publish(path, identity, report)
        with patch('pcerecomp.checkpoint_inspection._publish_receipt', side_effect=publish):
            with self.assertRaises(OSError): self.compare(left, right, policy='tier-counters')
        failed = json.loads((self.root/'comparison/receipt.json').read_bytes())
        self.assertFalse(failed['passed']); self.assertNotIn('equal', failed)


class ExactProducerTests(unittest.TestCase):
    def test_own_sdk_is_required_even_if_claimed_source_hash_matches(self):
        own = dict(revision='a'*40, source_sha256='b'*64, source_files=1)
        with patch.object(inspection.project, 'source_identity', return_value=own):
            for root, identity in ((inspection.ROOT/'foreign', own),
                    (inspection.ROOT, dict(own, revision='c'*40))):
                package = (dict(tool_root=root, tool_identity=identity), {}, Path('authored'), 'd'*64)
                with self.subTest(root=root, identity=identity), patch.object(inspection.project, '_verified_package', return_value=package):
                    with self.assertRaises(ValueError): inspection._source(Path('descriptor'), Path('build'))


class InspectionCliTests(unittest.TestCase):
    inspect_args = ['inspect', 'descriptor.toml', '--build', 'build', '--checkpoint', 'own.pcec',
                    '--checkpoint-sha256', 'a'*64, '--out', 'new-inspection']
    compare_args = ['compare', '--left', 'left', '--right', 'right', '--out', 'new-comparison',
                    '--left-receipt-sha256', 'a'*64, '--right-receipt-sha256', 'b'*64]

    def test_valid_inequality_has_distinct_shell_exit_from_equal_and_refused(self):
        for equal, code in ((False, 1), (True, 0)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(equal=equal), redirect_stdout(stdout), redirect_stderr(stderr), \
                    patch.object(inspection, 'compare_checkpoint_inspections', return_value=dict(passed=True, equal=equal)):
                self.assertEqual(inspection.main(self.compare_args), code)
            self.assertEqual(json.loads(stdout.getvalue()), dict(passed=True, equal=equal))
            self.assertEqual(stderr.getvalue(), '')

    def test_refused_input_and_invalid_title_setting_exit_two_without_pass_json(self):
        for args, error in ((self.compare_args, ValueError('authored changed source')),
                (self.inspect_args, subprocess.TimeoutExpired('authored diagnostic', 180))):
            target = 'compare_checkpoint_inspections' if args[0] == 'compare' else 'inspect_checkpoint'
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(args=args), redirect_stdout(stdout), redirect_stderr(stderr), \
                    patch.object(inspection, target, side_effect=error):
                self.assertEqual(inspection.main(args), 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('Checkpoint diagnostic refused:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(inspection, 'inspect_checkpoint') as child:
            self.assertEqual(inspection.main(self.inspect_args+['--title-setting', 'gold=1.5']), 2)
        child.assert_not_called(); self.assertEqual(stdout.getvalue(), '')

    def test_successful_inspection_exit_zero_and_operator_interrupt_propagates(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch.object(inspection, 'inspect_checkpoint', return_value=dict(passed=True)):
            self.assertEqual(inspection.main(self.inspect_args), 0)
        self.assertEqual(json.loads(stdout.getvalue()), dict(passed=True))
        with patch.object(inspection, 'inspect_checkpoint', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): inspection.main(self.inspect_args)


if __name__ == '__main__': unittest.main()
