"""Authored host/consumer span contracts and actual headless/SDL captures."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import project
from pcerecomp.emitter import emit_capture
from tests import test_project
from tests.test_capture import capture, observation
from scripts.build_config import cmake_cache

ROOT = Path(__file__).resolve().parent.parent


class SpanConsumerContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_project.ConsumerProjectTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def test_manifest_and_runtime_capability_are_checked_independently(self):
        f = self.fixture
        original = json.loads((f.root/'module.json').read_text())
        def write(manifest, limit):
            (f.root/'module.json').write_text(json.dumps(manifest))
            f.descriptor.write_text(f.text.replace(f.manifest_sha256, project.sha256(f.root/'module.json'))
                                   .replace('video = "continuous"', f'video = "continuous"\nnative_span = {limit}'))
        for limit in (0, 257, 'true', '1.5'):
            write(original, limit)
            with self.subTest(limit=limit), self.assertRaises(ValueError): f.verify()
        write(original, 1); checked = f.verify()
        self.assertIn('--native-span', project.command_for(checked, Path('authored')))
        write(original, 16)
        with self.assertRaisesRegex(ValueError, 'opted-in'): f.verify()
        valid = dict(original, native_span=dict(schema=1, protocol='per_instruction_v1'),
                     partition_layout='stable', partition_identity='full_mpr_logical_pc_range_v1', pc_bucket_size=256)
        write(valid, 16); f.verify()
        for key, value in (('schema', True), ('schema', 2), ('protocol', 'unknown')):
            changed = copy.deepcopy(valid); changed['native_span'][key] = value; write(changed, 1)
            with self.subTest(key=key), self.assertRaises(ValueError): f.verify()

    def test_report_rejects_missing_support_work_limit_and_continuation_claims(self):
        f = self.fixture
        (f.root/'module.json').write_text(json.dumps(dict(native_span=dict(schema=1, protocol='per_instruction_v1'))))
        checked = dict(config=dict(runtime=dict(native_span=16)), files=dict(module_manifest=f.root/'module.json'))
        metadata = dict(schema=1, protocol='per_instruction_v1', supported=True, limit=16,
            batches=13, generated_calls=13, native_completed=200, interpreted_completed=0,
            local_continuations=187, max_completed=16)
        result = dict(native_steps=200, interpreter_steps=0, native_dispatch=metadata)
        self.assertTrue(project._native_dispatch_provenance(checked, result)['valid'])
        for key, value in (('supported', False), ('limit', 15), ('native_completed', 199),
                           ('interpreted_completed', 1), ('generated_calls', 12), ('batches', 12),
                           ('local_continuations', 201), ('max_completed', 17), ('schema', True)):
            changed = copy.deepcopy(result); changed['native_dispatch'][key] = value
            with self.subTest(key=key): self.assertFalse(project._native_dispatch_provenance(checked, changed)['valid'])
        self.assertFalse(project._native_dispatch_provenance(checked, {})['valid'])
        changed = copy.deepcopy(result)
        changed['native_dispatch'].update(generated_calls=0, local_continuations=200)
        self.assertFalse(project._native_dispatch_provenance(checked, changed)['valid'])


@unittest.skipUnless(shutil.which('cmake') and shutil.which('ninja') and
                     (shutil.which('clang++') or shutil.which('g++')), 'CMake/Ninja/C++ required')
class NativeSpanHostTests(unittest.TestCase):
    def test_same_binary_caps_preserve_actual_source_captures_and_host_results(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        cache = cmake_cache(ROOT/'build', os.environ.get('PCE_TEST_CMAKE_CACHE'))
        sdk = None
        if cache:
            for line in cache.read_text().splitlines():
                if line.startswith('SDL3_DIR:'): sdk = line.split('=', 1)[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); module = root/'module'
            emit_capture(capture([observation(0x4000, (0xa9, 41)), observation(0x4002, (0xaa,)),
                                  observation(0x4003, (0xe8,)), observation(0x4004, (0x80, 0xfd))]),
                         module, partition_layout='stable', native_span=True)
            (root/'program.bin').write_bytes(bytes([0xa9, 41, 0xaa, 0xe8, 0x80, 0xfd]))
            cmake = ['cmake_minimum_required(VERSION 3.20)', 'project(AuthoredSpan LANGUAGES CXX)',
                f'set(PCE_BUILD_DESKTOP {"ON" if sdk else "OFF"} CACHE BOOL "" FORCE)',
                f'add_subdirectory("{ROOT.as_posix()}" tool)',
                'pce_add_consumer(span-head MODULE module/module.cpp MANIFEST module/module.json)']
            if sdk: cmake.append('pce_add_consumer(span-window MODULE module/module.cpp MANIFEST module/module.json DESKTOP)')
            (root/'CMakeLists.txt').write_text('\n'.join(cmake)+'\n')
            command = ['cmake', '-S', str(root), '-B', str(root/'build'), '-G', 'Ninja',
                       '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER='+compiler]
            if sdk: command.append('-DSDL3_DIR='+sdk)
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
            built = subprocess.run(['cmake', '--build', str(root/'build'), '--parallel', '2'],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout+built.stderr)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software', SDL_AUDIODRIVER='dummy')
            for target in ('span-head', 'span-window') if sdk else ('span-head',):
                binary = root/'build'/(target+('.exe' if os.name=='nt' else ''))
                reference = reference_capture = None
                for cap in (None, 1, 16, 256):
                    output = root/f'{target}-{cap}.json'
                    args = [str(binary), str(root/'program.bin'), '1048576', '16384',
                        '255,248,128,129,130,131,132,0', '200', '100000', 'native',
                        '--code-capture', str(output), '--capture-limit', '64', '--audio-output', 'off']
                    if cap is not None: args += ['--native-span', str(cap)]
                    if target == 'span-window': args += ['--hidden', 'on', '--unthrottled', 'on']
                    run = subprocess.run(args, capture_output=True, text=True, env=env, timeout=10)
                    self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
                    state = json.loads(run.stdout); observed = json.loads(output.read_text())
                    self.assertEqual((state['a'], state['x'], state['pc'], state['ticks'],
                                      state['native_steps'], state['interpreter_steps']), (41, 140, 16387, 1794, 200, 0))
                    if cap is None:
                        self.assertNotIn('native_dispatch', state); reference = state; reference_capture = observed
                    else:
                        checked = dict(config=dict(runtime=dict(native_span=cap)), files=dict(module_manifest=module/'module.json'))
                        self.assertTrue(project._native_dispatch_provenance(checked, state)['valid'], state['native_dispatch'])
                        stats = state.pop('native_dispatch'); calls = (200+cap-1)//cap
                        self.assertEqual((stats['batches'], stats['generated_calls'], stats['local_continuations']),
                                         (calls, calls, 200-calls))
                        self.assertEqual(state, reference); self.assertEqual(observed, reference_capture)
                for bad in ('0', '257', '-1', 'true', '1.5'):
                    rejected = subprocess.run([str(binary), str(root/'program.bin'), '1048576', '16384',
                        '255,248,128,129,130,131,132,0', '200', '100000', 'native', '--native-span', bad],
                        capture_output=True, text=True, env=env, timeout=10)
                    self.assertNotEqual(rejected.returncode, 0)
            original_manifest = (module/'module.json').read_bytes()
            for key, value in (('protocol', 'unknown'), ('schema', True), ('extra', 'unknown')):
                invalid = json.loads(original_manifest); invalid['native_span'][key] = value
                (module/'module.json').write_text(json.dumps(invalid))
                refused = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(refused.returncode, 0, refused.stdout+refused.stderr)
            (module/'module.json').write_bytes(original_manifest)


if __name__ == '__main__': unittest.main()
