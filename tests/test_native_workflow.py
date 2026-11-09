"""Authored writable-code workflow through genuine captures and native build/run."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_workflow_example', ROOT/'examples/native-workflow/workflow.py')
EXAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXAMPLE)
HEADLESS = Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless.exe' if os.name == 'nt' else 'pce-headless')))


class AuthoredPlanTests(unittest.TestCase):
    def test_explicit_plan_preserves_same_pc_variants_and_full_mpr_identity(self):
        for steps in (200, 202):
            rows = EXAMPLE.expected_observations(steps)
            self.assertEqual(len(rows), 27)
            self.assertEqual(sum(row['interpreted_hits'] for row in rows), steps)
            self.assertEqual(len({tuple(row['mpr']) for row in rows}), 5)
            ram = [row for row in rows if row['pc'] == 0x2200]
            self.assertEqual([row['data'] for row in ram], [[0xA9, 0x11], [0xA9, 0x2A]])
            self.assertEqual(ram[0]['mpr'], ram[1]['mpr'])
            self.assertEqual(ram[0]['physical'], [0x1F0200, 0x1F0201])
            self.assertEqual(EXAMPLE.expected_state(steps)['ticks'], 2238+(steps-200)*9)

    def test_card_and_ram_literals_are_authored_and_bounded(self):
        card = EXAMPLE.card_bytes()
        self.assertEqual(len(card), 262144)
        self.assertEqual(card[0x100:0x106], bytes.fromhex('A9 11 8D 30 20 60'))
        self.assertEqual(card[0x1FFE:0x2000], bytes.fromhex('00 E0'))
        self.assertEqual(EXAMPLE.expected_ram()[0x30:0x33], bytes.fromhex('2A 11 2A'))
        self.assertEqual(EXAMPLE.expected_ram()[0x1FD:0x200], bytes.fromhex('FF 27 E0'))
        with self.assertRaises(ValueError): EXAMPLE.expected_observations(201)
        with self.assertRaises(ValueError): EXAMPLE.check_state(dict(pc=0))


@unittest.skipUnless(HEADLESS.is_file(), 'Build headless runner or set PCE_TEST_HEADLESS')
class ActualNativeWorkflowTests(unittest.TestCase):
    def test_genuine_windows_prepare_build_native_execution_ram_and_guard_refusal(self):
        from pcerecomp.emitter import emit_observation_profile
        from pcerecomp.history import load_history
        from pcerecomp.observations import load_observation_profile
        if not shutil.which('cmake'):
            self.skipTest('CMake required for actual official native build')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'workflow'
            EXAMPLE.capture(root, HEADLESS)
            original = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
            prepared = EXAMPLE.prepare(root)
            self.assertFalse(prepared['execution_evidence'])
            history = load_history(root/'history/history.json')
            self.assertEqual(history.accounting['historical_totals']['interpreted_hits'], 402)
            self.assertEqual(history.accounting['selected_historical_totals']['interpreted_hits'], 200)
            self.assertEqual(len(history.input_metadata), 2)
            profile, digest = load_observation_profile(root/'baseline-profile.json')
            emit_observation_profile(profile, root/'inline-module', digest, partition_layout='stable')
            expected_sources = {p.name: p.read_bytes() for p in (root/'inline-module').glob('*.cpp')}
            self.assertEqual(expected_sources, {p.name: p.read_bytes() for p in (root/'consumer/module').glob('*.cpp')})
            args = []
            # Reuse the required-check runner's selected compiler/make program.
            cache = HEADLESS.parent/'CMakeCache.txt'
            if cache.is_file():
                for line in cache.read_text(encoding='utf-8').splitlines():
                    if line.startswith(('CMAKE_CXX_COMPILER:', 'CMAKE_MAKE_PROGRAM:')):
                        key, value = line.split('=', 1)
                        args.append('-D'+key.split(':', 1)[0]+'='+value)
            result = EXAMPLE.qualify(root, generator='Ninja' if shutil.which('ninja') or any('MAKE_PROGRAM=' in a and 'ninja' in a.lower() for a in args) else None,
                                     cmake_args=args)
            self.assertTrue(result['run']['qualified'])
            from pcerecomp.project import prepare_launch
            plan=prepare_launch(root/'consumer/project.toml',root/'consumer-build')
            self.assertFalse(plan['execution_evidence'])
            launched=subprocess.run(plan['command'],capture_output=True,text=True,check=True,timeout=15)
            EXAMPLE.check_state(json.loads(launched.stdout),native=True)
            endpoint = EXAMPLE.probe(root)
            self.assertEqual(endpoint['results']['normal']['ram_bytes_checked'], 8192)
            self.assertEqual(endpoint['results']['guard']['retired_after_mutation'], 0)
            self.assertEqual(endpoint['results']['guard']['guard_misses'], 1)
            history.revalidate()
            self.assertEqual(original, {name: (root/name).read_bytes() for name in original})

    def test_changed_process_output_refuses_before_profile_or_native_emission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'workflow'
            EXAMPLE.capture(root, HEADLESS)
            (root/'capture-200.stdout').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'process output changed'):
                EXAMPLE.prepare(root)
            self.assertFalse((root/'baseline-profile.json').exists())
            self.assertFalse((root/'consumer').exists())


if __name__ == '__main__':
    unittest.main()
