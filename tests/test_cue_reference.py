import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from cue_fixture import definitions, expected, write_case, composite_identity, raw_sector, audio_sector
from scripts.cue_reference import difference, stream_expectations, compare_stream


class CueReferenceTests(unittest.TestCase):
    def test_literal_geometry(self):
        cases = definitions()
        self.assertEqual(len(cases), 6)
        self.assertEqual([c['leadout'] for c in cases], [6, 8, 12, 12, 8, 9])
        self.assertEqual(cases[2]['tracks'], [[0, 4], [4, 0], [8, 0], [10, 4]])
        self.assertEqual(cases[3]['tracks'], [[0, 4], [8, 0]])
        self.assertEqual(cases[4]['tracks'], [[0, 4], [4, 0]])

    def test_payload_shapes_and_signed_endianness(self):
        self.assertEqual(len(raw_sector(1, 0)), 2352)
        samples = audio_sector(1, 0)
        self.assertEqual(len(samples), 1176)
        self.assertIn(-32768, samples)
        self.assertIn(32767, samples)
        self.assertIn(-1, samples)
        self.assertIn(1, samples)

    def test_gap_expected_values_are_independent(self):
        stored = expected(definitions()[2])['observations']
        playback = {r['lba']: r['playable'] for r in stored if r['op'] == 'p'}
        self.assertFalse(playback[2])
        self.assertFalse(playback[3])
        self.assertTrue(playback[7])
        virtual = expected(definitions()[3])['observations']
        self.assertEqual([r['op'] for r in virtual if r['lba'] == 6], ['p'])
        self.assertFalse(next(r['playable'] for r in virtual if r['lba'] == 6))

    def test_typed_comparator_rejects_bool_counter(self):
        self.assertIsNotNone(difference({'n': True}, {'n': 1}))
        self.assertIsNotNone(difference({'v': [1]}, {'v': [1, 2]}))
        self.assertIsNotNone(difference({'v': 1, 'extra': 0}, {'v': 1}))
        self.assertIsNone(difference(expected(definitions()[0]), expected(definitions()[0])))

    def test_compound_identity_relocation_and_bin_mutation(self):
        case = definitions()[3]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a = write_case(root / 'a', case)
            b = write_case(root / 'b', case)
            self.assertEqual(composite_identity(a, case), composite_identity(b, case))
            original = composite_identity(a, case)
            target = a.parent / 'audio.bin'
            payload = bytearray(target.read_bytes())
            payload[-1] ^= 1
            target.write_bytes(payload)
            self.assertNotEqual(composite_identity(a, case), original)
            self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest())

    def test_compound_identity_exact_cue_bytes(self):
        case = definitions()[0]
        with tempfile.TemporaryDirectory() as temporary:
            cue = write_case(Path(temporary) / 'image', case)
            original = composite_identity(cue, case)
            cue.write_bytes(cue.read_bytes().replace(b'\n', b'\r\n'))
            self.assertNotEqual(composite_identity(cue, case), original)

    def test_stream_tiers_and_independent_bytes(self):
        requests = stream_expectations(definitions()[2])
        self.assertEqual([(r['lba'], r['count']) for r in requests], [(0, 2), (10, 2)])
        request = requests[0]
        actual = dict(sectors=request['sectors'], status_port=216, status=0,
                      message_port=248, final_port=0, guard_misses=0,
                      sectors_read=2, read_errors=0, data_bytes_acked=4096,
                      native_steps=100, interpreter_steps=0)
        self.assertIsNone(compare_stream(actual, request, 'native'))
        self.assertIsNotNone(compare_stream(actual, request, 'interpreter'))
        changed = copy.deepcopy(actual)
        changed['sectors'][0] = 'ff' + changed['sectors'][0][2:]
        self.assertIsNotNone(compare_stream(changed, request, 'native'))
        changed = dict(actual, native_steps=True)
        self.assertIsNotNone(compare_stream(changed, request, 'native'))
        changed = dict(actual, interpreter_steps=1)
        self.assertIsNotNone(compare_stream(changed, request, 'native'))


if __name__ == '__main__':
    unittest.main()
