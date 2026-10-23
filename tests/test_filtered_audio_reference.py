import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('filtered_reference', Path(__file__).resolve().parents[1]/'scripts/filtered_audio_reference.py')
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)


class FilteredAudioReferenceTests(unittest.TestCase):
    def test_authored_plans_cover_real_synthesis_and_filter_edges(self):
        plans = reference.plans()
        self.assertGreater(len(plans['psg']), 3262)
        self.assertEqual(len(plans['adpcm']), 17)
        self.assertEqual({op[1] for case in plans['adpcm'] for op in case['operations'] if op[0] == 'v'}, set(range(16)))
        self.assertTrue(any(case['id'] == 'unclipped-stereo' for case in plans['psg']))

    def test_serialize_counts_only_output_operations(self):
        text, spans = reference.serialize([dict(id='a', operations=[('r', 1), ('v', 3), ('a', 4095, 0), ('a', 2048, 1)])])
        self.assertEqual(spans, [dict(id='a', start=0, samples=2)])
        self.assertIn('v 3\n', text)

    def test_compare_detects_case_and_sample(self):
        spans = [dict(id='first', start=0, samples=1), dict(id='second', start=1, samples=1)]
        self.assertIsNone(reference.compare([[1, 2], [3, 4]], [[1, 2], [3, 4]], spans))
        self.assertEqual(reference.compare([[1, 2], [3, 5]], [[1, 2], [3, 4]], spans)['case'], 'second')

    def test_compare_rejects_bad_output_shape_and_values(self):
        spans = [dict(id='one', start=0, samples=1)]
        for malformed in ([], [[True, 0]], [[0, 32768]], [[0]], [None], [dict(left=0, right=0)]):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                reference.compare(malformed, [[0, 0]], spans)

    def test_preservation_revokes_pass_on_changed_or_removed_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'fixture';path.write_bytes(b'authored')
            bindings = dict(source={str(path): reference.sha(path)})
            report = dict(result='pass');reference.record_preservation(report, bindings)
            self.assertTrue(report['preservation']['source'])
            path.write_bytes(b'changed');reference.record_preservation(report, bindings)
            self.assertEqual(report['result'], 'failed-preservation')
            path.unlink();report = dict(result='pass');reference.record_preservation(report, bindings)
            self.assertEqual(report['result'], 'failed-preservation')

    def test_source_binding_checks_committed_blob_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary);(checkout/'src').mkdir()
            header = checkout/'src/filter.h';header.write_bytes(b'// authored header\n')
            def git(*args):
                return subprocess.run(['git', '-C', str(checkout), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '-q');git('add', 'src/filter.h')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                '-c', 'core.autocrlf=false', 'commit', '-qm', 'Authored fixture')
            with mock.patch.object(reference, 'COMMIT', git('rev-parse', 'HEAD')):
                self.assertEqual(reference.source_binding(checkout), {'src/filter.h': reference.sha(header)})
                header.write_bytes(b'// changed\n')
                with self.assertRaises(ValueError):reference.source_binding(checkout)
                header.unlink()
                with self.assertRaises(subprocess.CalledProcessError):reference.source_binding(checkout)

    def test_compile_sources_rejects_untracked_working_tree_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            names = ('src/audio.cpp', 'platforms/shared/dependencies/qon/qon.cpp',
                     'platforms/shared/dependencies/miniz/miniz.c',
                     'platforms/shared/dependencies/minivorbis/minivorbis.c')
            for name in names:
                path = checkout/name;path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'// authored fixture\n')
            binding = {name: reference.sha(checkout/name) for name in names}
            cpp, c = reference.compile_sources(checkout, binding)
            self.assertEqual(len(cpp), 2);self.assertEqual(len(c), 2)
            (checkout/'src/untracked.cpp').write_bytes(b'// unexpected input\n')
            with self.assertRaisesRegex(ValueError, 'Unexpected unpinned'):
                reference.compile_sources(checkout, binding)
            (checkout/'src/untracked.cpp').unlink()
            (checkout/'src/audio.cpp').write_bytes(b'// changed pinned input\n')
            with self.assertRaisesRegex(ValueError, 'missing, changed or unpinned'):
                reference.compile_sources(checkout, binding)
            (checkout/'src/audio.cpp').unlink()
            with self.assertRaisesRegex(ValueError, 'missing, changed or unpinned'):
                reference.compile_sources(checkout, binding)


if __name__ == '__main__':
    unittest.main()
