"""Authored oracle plans and comparisons must fail closed on missing evidence."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.psg_reference import GEAR_FILES, bind_sources, compare, plans, record_preservation, serialize, sha


class PsgReferenceTests(unittest.TestCase):
    def test_authored_plans_are_deterministic_complete_and_positive_clocked(self):
        cases = plans()
        text, spans = serialize(cases)
        self.assertEqual((text, spans), serialize(plans()))
        self.assertEqual(len(cases), len({case['id'] for case in cases}))
        self.assertEqual(3262, len(cases))
        self.assertEqual(49258, sum(span['samples'] for span in spans))
        periods = set()
        for case in cases:
            self.assertEqual('r', case['operations'][0][0])
            if case['id'].startswith('wave-'):
                periods.add(int(case['id'].split('-')[3]))
            for op in case['operations']:
                if op[0] == 's':
                    self.assertGreater(op[1], 0)
                elif op[0] == 'w':
                    self.assertIn(op[1], range(16)); self.assertIn(op[2], range(256))
        self.assertTrue({0, 1, 2, 3, 4, 5, 6, 4095}.issubset(periods))
        self.assertTrue(any(case['id'].startswith('noise-') for case in cases))
        self.assertTrue(any(case['id'].startswith('lfo-') for case in cases))
        self.assertTrue(any(case['id'].startswith('six-channel-') for case in cases))

    def test_gain_plans_cover_all_channels_dac_profiles_and_codes(self):
        cases = [case for case in plans() if case['id'].startswith('dda-gain-')]
        self.assertEqual(768, len(cases))
        self.assertEqual({(center, channel) for center in range(2) for channel in range(6)},
                         {(int(c['id'].split('-')[2]), int(c['id'].split('-')[3])) for c in cases})
        for case in cases:
            self.assertEqual(list(range(32)), [op[2] for op in case['operations'] if op[:2] == ('w', 6)])

    def test_identical_complete_samples_pass(self):
        record = [23, -19, [0]*6, [1, 1]]
        self.assertIsNone(compare([record], [record], [dict(id='one', start=0, samples=1)]))

    def test_pcm_wave_phase_and_noise_mismatches_are_localized(self):
        expected = [[23, -19, [0]*6, [1, 1]], [3, 9, [7]*6, [17, 43]]]
        for path in ((0,), (1,), (2, 0), (2, 5), (3, 0), (3, 1)):
            actual = copy.deepcopy(expected)
            if len(path) == 1:
                actual[1][path[0]] += 1
            else:
                actual[1][path[0]][path[1]] += 1
            mismatch = compare(actual, expected, [dict(id='first', start=0, samples=1),
                                                   dict(id='second', start=1, samples=1)])
            self.assertEqual(('second', 0), (mismatch['case'], mismatch['sample']))
            self.assertEqual(actual[1], mismatch['actual'])
            self.assertEqual(expected[1], mismatch['expected'])

    def test_missing_and_extra_samples_are_rejected_on_either_side(self):
        record = [0, 0, [0]*6, [1, 1]]
        spans = [dict(id='one', start=0, samples=1)]
        for actual, expected in (([], [record]), ([record], []),
                                 ([record]*2, [record]), ([record], [record]*2)):
            with self.assertRaisesRegex(ValueError, 'sample count'):
                compare(actual, expected, spans)

    def test_malformed_records_are_rejected_even_when_equal(self):
        for record in ([0, 0], [True, 0, [0]*6, [1, 1]], [32768, 0, [0]*6, [1, 1]],
                       [0, 0, [32]*6, [1, 1]], [0, 0, [0]*5, [1, 1]],
                       [0, 0, [0]*6, [1, 1 << 18]], [0, 0, [0]*6, [1]]):
            with self.assertRaisesRegex(ValueError, 'Malformed'):
                compare([record], [record], [dict(id='one', start=0, samples=1)])

    def test_exact_pinned_sources_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('scripts.psg_reference.sha', side_effect=lambda path: GEAR_FILES[path.name]):
                self.assertEqual(GEAR_FILES, bind_sources(Path(directory)))
            with patch('scripts.psg_reference.sha', return_value='0'*64):
                with self.assertRaisesRegex(ValueError, 'pinned'):
                    bind_sources(Path(directory))
        self.assertEqual(8, len(GEAR_FILES))
        self.assertTrue(all(len(value) == 64 for value in GEAR_FILES.values()))

    def test_probe_mutation_or_removal_invalidates_successful_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory)/'authored-probe'
            probe.write_bytes(b'authored executable identity')
            original = sha(probe)
            with patch('scripts.psg_reference.bind_sources', return_value=GEAR_FILES):
                intact = dict(result='pass', probe_sha256=original)
                record_preservation(intact, Path(directory), GEAR_FILES, probe)
                self.assertEqual('pass', intact['result'])
                self.assertTrue(intact['probe_unchanged'])
                probe.write_bytes(b'changed after successful comparison')
                changed = dict(result='pass', probe_sha256=original)
                record_preservation(changed, Path(directory), GEAR_FILES, probe)
                self.assertEqual('failed-preservation', changed['result'])
                self.assertFalse(changed['probe_unchanged'])
                probe.unlink()
                missing = dict(result='pass', probe_sha256=original)
                record_preservation(missing, Path(directory), GEAR_FILES, probe)
                self.assertEqual('failed-preservation', missing['result'])

    def test_reference_mutation_invalidates_successful_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory)/'authored-probe'
            probe.write_bytes(b'authored executable identity')
            report = dict(result='pass', probe_sha256=sha(probe))
            with patch('scripts.psg_reference.bind_sources', side_effect=ValueError('changed source')):
                record_preservation(report, Path(directory), GEAR_FILES, probe)
            self.assertEqual('failed-preservation', report['result'])
            self.assertFalse(report['oracle_sources_unchanged'])
            self.assertTrue(report['probe_unchanged'])


if __name__ == '__main__':
    unittest.main()
