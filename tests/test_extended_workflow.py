"""Pure authored plan and bounded process-evidence tests; no large compiler build."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('extended_capture_example',
    ROOT / 'examples/extended-capture/workflow.py')
EXAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXAMPLE)


class ExtendedAuthoredPlanTests(unittest.TestCase):
    def test_exact_authored_work_ram_program(self):
        code = EXAMPLE.payload_bytes()
        self.assertEqual(len(code), 8192)
        self.assertEqual(code[0], 0xD4)
        self.assertEqual(code[1:8185], b'\xEA' * 8184)
        self.assertEqual(code[8185:], bytes.fromhex('E8 8A 53 80 4C 00 40'))
        self.assertEqual(EXAMPLE.PHYSICAL_LOAD, 0x1F0000)
        self.assertEqual(EXAMPLE.PC, 0x4000)

    def test_extended_plan_has_real_full_map_variants_and_tam_fetch_boundary(self):
        rows = EXAMPLE.expected_observations()
        self.assertEqual(len(rows), 73701)
        self.assertEqual(sum(item['interpreted_hits'] for item in rows), 73701)
        self.assertEqual(sum(item['native_hits'] for item in rows), 0)
        keys = {(item['pc'], tuple(item['mpr']), tuple(item['data'])) for item in rows}
        self.assertEqual(len(keys), 73701)
        self.assertEqual(rows, sorted(rows, key=lambda item: (item['mpr'], item['pc'], item['data'])))
        contexts = {}
        source = EXAMPLE.payload_bytes()
        for item in rows:
            contexts.setdefault(item['mpr'][7], []).append(item)
            offset = item['pc'] - 0x4000
            self.assertEqual(item['data'], list(source[offset:offset + len(item['data'])]))
            self.assertEqual(item['physical'], list(range(0x1F0000 + offset,
                                                        0x1F0000 + offset + len(item['data']))))
            self.assertEqual(item['mpr'][:7], [248] * 7)
        self.assertEqual(set(contexts), {248, *range(1, 10)})
        self.assertEqual(len(contexts[248]), 8188)
        self.assertNotIn(0x5FFD, {item['pc'] for item in contexts[248]})
        self.assertEqual([len(contexts[value]) for value in range(1, 9)], [8189] * 8)
        self.assertEqual([(item['pc'], item['data']) for item in contexts[9]],
                         [(0x5FFD, [0x4C, 0, 0x40])])

    def test_legacy_prefix_loss_is_separate_from_complete_native_expectation(self):
        legacy = EXAMPLE.expected_observations(legacy=True)
        self.assertEqual(len(legacy), 65536)
        self.assertEqual(73701 - len(legacy), 8165)
        self.assertEqual(len([item for item in legacy if item['mpr'][7] == 8]), 25)
        self.assertNotIn(9, {item['mpr'][7] for item in legacy})
        # The program changes context through guest TAM, never by a host patch.
        native = EXAMPLE.expected_observations(native=True)
        self.assertEqual(len(native), 73701)
        self.assertTrue(all(item['native_hits'] == 1 and item['interpreted_hits'] == 0 for item in native))

    def test_literal_cpu_ticks_and_native_guard_requirements(self):
        expected = dict(pc=16384, a=9, x=9, y=0, sp=255, p=4,
            mpr=[248, 248, 248, 248, 248, 248, 248, 9], cycles=147456, ticks=442368,
            native_steps=0, interpreter_steps=73701)
        self.assertEqual(EXAMPLE.expected_state(), expected)
        EXAMPLE.check_state(expected)
        native = dict(expected, native_steps=73701, interpreter_steps=0, guard_misses=0)
        EXAMPLE.check_state(native, native=True)
        for key, value in (('ticks', 442386), ('cycles', 147455), ('pc', True),
                           ('mpr', [248] * 8), ('guard_misses', 1)):
            changed = dict(native, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                EXAMPLE.check_state(changed, native=True)

    def test_capture_checker_refuses_missing_last_context_and_wrong_tiers(self):
        value = dict(schema=2, capacity=131072, complete=True, dropped_instructions=0,
            unreadable_instructions=0, retired_instructions=73701,
            observations=EXAMPLE.expected_observations(native=True))
        EXAMPLE.check_capture(value, native=True)
        bad = dict(value, observations=value['observations'][:-1])
        with self.assertRaises(ValueError):
            EXAMPLE.check_capture(bad, native=True)
        value['observations'][0]['native_hits'] = 0
        value['observations'][0]['interpreted_hits'] = 1
        with self.assertRaises(ValueError):
            EXAMPLE.check_capture(value, native=True)

    def test_process_failure_retains_exact_output_without_success_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = [sys.executable, '-c', "import sys; print('authored failure'); sys.stderr.write('diagnostic'); sys.exit(7)"]
            with self.assertRaisesRegex(ValueError, 'retained'):
                EXAMPLE._process(root, 'failed', argv, 10)
            receipt = json.loads((root / 'failed-process.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['exit_code'], 7)
            self.assertFalse(receipt['timed_out'])
            self.assertEqual((root / 'failed.stdout').read_text(encoding='utf-8'), 'authored failure\n')
            self.assertEqual((root / 'failed.stderr').read_text(encoding='utf-8'), 'diagnostic')
            self.assertEqual(receipt['stdout_sha256'], EXAMPLE.sha256(root / 'failed.stdout'))
            with patch.object(EXAMPLE.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'must be new'):
                    EXAMPLE._process(root, 'failed', argv, 10)
                run.assert_not_called()

    def test_process_timeout_preserves_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            error = subprocess.TimeoutExpired(['authored'], 1, output=b'partial output', stderr=b'partial error')
            with patch.object(EXAMPLE.subprocess, 'run', side_effect=error):
                with self.assertRaises(ValueError):
                    EXAMPLE._process(root, 'timeout', ['authored'], 1)
            receipt = json.loads((root / 'timeout-process.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['exit_code'], -1)
            self.assertTrue(receipt['timed_out'])
            self.assertEqual((root / 'timeout.stdout').read_bytes(), b'partial output')
            self.assertEqual((root / 'timeout.stderr').read_bytes(), b'partial error')


if __name__ == '__main__':
    unittest.main()
