"""Static context output stays distinct from observed execution evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit


def fixture():
    return Snapshot((0,)*8, {0: 0xA9, 1: 1, 2: 0x53, 3: 4,
                             0x2004: 0xEA, 0x2005: 0x60}, (0x4000,), 'authored-context-emitter')


class ContextEmissionTests(unittest.TestCase):
    def test_static_contexts_have_direct_bodies_and_runtime_guards(self):
        report = analyze(fixture(), follow_mappings=True)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            manifest = emit(report, out)
            code = (out/'module.cpp').read_text(encoding='utf-8')
            self.assertEqual((manifest['analysis_schema'], manifest['mapping_contexts'],
                              manifest['native_instructions_emitted']), (2, 2, 4))
            self.assertIs(manifest['execution_evidence'], False)
            self.assertNotIn('code_capture_sha256', manifest)
            self.assertNotIn('interpret', code)
            self.assertIn('s.mpr[2]=s.a;', code)
            self.assertIn('switch(mapping)', code)
            self.assertIn('bus.peek(8196)', code)
            self.assertLess(code.index('bus.peek(0)'), code.index('bus.begin_instruction(s)'))
            self.assertLess(code.index('s.ticks >= deadline'), code.index('switch(mapping)'))
            self.assertEqual(json.loads((out/'module.json').read_text()), manifest)
            with self.assertRaisesRegex(ValueError, 'exists'):
                emit(report, out)

    def test_order_independent_output(self):
        report = analyze(fixture(), follow_mappings=True)
        other = copy.deepcopy(report)
        other['instructions'].reverse()
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/'a', Path(directory)/'b'
            self.assertEqual(emit(report, first), emit(other, second))
            self.assertEqual((first/'module.cpp').read_bytes(), (second/'module.cpp').read_bytes())

    def test_context_identity_and_metadata_tampering_rejected_before_write(self):
        report = analyze(fixture(), follow_mappings=True)
        mutations = [
            lambda row: row.update(mpr=[0]*7),
            lambda row: row.update(pc=True),
            lambda row: row.update(physical=[True, 1]),
            lambda row: row.update(physical=[0, 99]),
            lambda row: row.update(data=[0xA9]),
            lambda row: row.update(mnemonic='NOP'),
            lambda row: row.update(mode='abs'),
            lambda row: row.update(target=True),
            lambda row: row.update(native_supported=1),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                changed = copy.deepcopy(report)
                mutation(changed['instructions'][0])
                with self.assertRaises(ValueError):
                    emit(changed, Path(directory))
                self.assertFalse((Path(directory)/'module.cpp').exists())

    def test_duplicate_and_unsupported_policy_refused(self):
        report = analyze(fixture(), follow_mappings=True)
        with tempfile.TemporaryDirectory() as directory:
            report['instructions'].append(report['instructions'][0])
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                emit(report, Path(directory))
            report['analysis_policy'] = 'assume_all_mappings'
            with self.assertRaisesRegex(ValueError, 'policy'):
                emit(report, Path(directory))

    def test_cli_explicit_mode_and_context_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segments = []
            for index, (physical, data) in enumerate(((0, bytes.fromhex('A9 01 53 04')),
                                                     (0x2004, bytes.fromhex('EA 60')))):
                filename = f'{index}.bin'
                (root/filename).write_bytes(data)
                segments.append(f'[[segments]]\nphysical={physical}\nfile="{filename}"\n'
                                f'sha256="{hashlib.sha256(data).hexdigest()}"\n')
            snapshot = root/'snapshot.toml'
            snapshot.write_text('schema=1\nmpr=[0,0,0,0,0,0,0,0]\nentry_points=[16384]\n'
                                + ''.join(segments), encoding='utf-8')
            def call(*args):
                return subprocess.run([sys.executable, '-m', 'pcerecomp', *args],
                                      capture_output=True, text=True, timeout=20)
            legacy = call('analyze', str(snapshot), '--out', str(root/'legacy.json'))
            self.assertEqual(legacy.returncode, 0, legacy.stderr)
            self.assertEqual(json.loads((root/'legacy.json').read_text())['schema'], 1)
            current = call('analyze', str(snapshot), '--follow-mappings', '--context-limit', '2',
                           '--listing', '--out', str(root/'context.json'))
            self.assertEqual(current.returncode, 0, current.stderr)
            self.assertIn('MPR=00,00,01,00,00,00,00,00', current.stdout)
            emitted = call('emit', str(snapshot), '--follow-mappings', '--out', str(root/'module'))
            self.assertEqual(emitted.returncode, 0, emitted.stderr)
            self.assertEqual(json.loads(emitted.stdout)['mapping_contexts'], 2)
            rejected = call('analyze', str(snapshot), '--context-limit', '2', '--out', str(root/'bad.json'))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn('requires --follow-mappings', rejected.stderr)
            self.assertFalse((root/'bad.json').exists())
