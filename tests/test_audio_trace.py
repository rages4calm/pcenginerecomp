"""Authored domain, provenance, malformed-file and first-difference controls."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.audio_trace import (MAX_FILE_BYTES, MAX_FRAMES, compare_traces,
                                   load_trace, main, validate_trace)


def authored(stage='psg-raw'):
    return dict(schema=1, format='pce-audio-trace-1',
        engine=dict(name='Authored engine', revision='1'*40, source_sha256='2'*64, binary_sha256='3'*64),
        fixture_sha256='4'*64, case='authored-odd-half',
        domain=dict(stage=stage, timing='gear-v1', source_rate=44100, output_rate=44100,
                    gain_divisor=3, latency_source_frames=0, resampler='identity-v1'),
        first_frame=1, samples=[[-1761, -1761], [1761, 1761], [0, 0]])


class AudioTraceTests(unittest.TestCase):
    def test_identical_samples_retain_distinct_engine_provenance(self):
        a, b = authored(), authored()
        b['engine'] = dict(name='Another engine', revision='5'*40, source_sha256='6'*64, binary_sha256='7'*64)
        result = compare_traces(a, b)
        self.assertTrue(result['equal'])
        self.assertEqual(result['matched_frames'], 3)
        self.assertNotEqual(result['expected_engine'], result['actual_engine'])
        self.assertIsNone(result['first_difference'])

    def test_identical_integers_in_different_signal_domains_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'domain'):
            compare_traces(authored(), authored('psg-hpf'))

    def test_timing_gain_phase_fixture_and_case_are_never_silently_normalized(self):
        for key in ('timing', 'gain_divisor', 'first_frame', 'fixture_sha256', 'case'):
            actual = authored()
            if key == 'timing': actual['domain'][key] = 'legacy-v1'
            elif key == 'gain_divisor': actual['domain'][key] = 1
            elif key == 'first_frame': actual[key] = 2
            elif key == 'fixture_sha256': actual[key] = '9'*64
            else: actual[key] = 'different-authored-case'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'comparison refused'):
                compare_traces(authored(), actual)

    def test_first_different_channel_and_global_frame_are_reported(self):
        a = authored(); a['first_frame'] = 701
        b = copy.deepcopy(a); b['samples'][1][1] = 1764
        result = compare_traces(a, b)
        self.assertFalse(result['equal'])
        self.assertEqual(result['matched_frames'], 1)
        self.assertEqual(result['first_difference'], dict(frame=702, channel=1, expected=1761, actual=1764))

    def test_frame_count_difference_is_not_truncated_away(self):
        for change in ('shorter', 'longer'):
            actual = authored()
            if change == 'shorter': actual['samples'].pop()
            else: actual['samples'].append([0, 0])
            result = compare_traces(authored(), actual)
            self.assertFalse(result['equal'])
            self.assertEqual(result['first_difference']['field'], 'frame-count')
            self.assertEqual(result['matched_frames'], 2 if change == 'shorter' else 3)

    def test_earlier_sample_difference_precedes_length_difference(self):
        b = authored(); b['samples'][0][0] = -1760; b['samples'].pop()
        result = compare_traces(authored(), b)
        self.assertEqual(result['first_difference'], dict(frame=1, channel=0, expected=-1761, actual=-1760))

    def test_signed_extremes_and_largest_frame_ordinal_are_preserved(self):
        value = authored(); value['samples'] = [[-32768, 32767]]; value['first_frame'] = 2**64-1
        self.assertIs(validate_trace(value), value)
        value['samples'].append([0, 0])
        with self.assertRaisesRegex(ValueError, 'overflow'): validate_trace(value)

    def test_boolean_and_float_numeric_fields_are_rejected(self):
        for path in (('schema',), ('first_frame',), ('domain','source_rate'), ('domain','output_rate'),
                     ('domain','gain_divisor'), ('domain','latency_source_frames'), ('samples',0,0)):
            for invalid in (True, False, 1.0):
                value = authored(); parent = value
                for key in path[:-1]: parent = parent[key]
                parent[path[-1]] = invalid
                with self.subTest(path=path, invalid=invalid), self.assertRaises(ValueError): validate_trace(value)

    def test_out_of_range_and_noninteger_samples_are_rejected(self):
        for invalid in (-32769, 32768, 2**64, '0', None, {}, []):
            value = authored(); value['samples'][0][0] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): validate_trace(value)

    def test_stereo_frames_and_nonempty_bounded_extent_are_required(self):
        for samples in ([], None, [0], [[0]], [[0,0,0]], [(0,0)], [[0,0]]*(MAX_FRAMES+1)):
            value = authored(); value['samples'] = samples
            with self.subTest(kind=type(samples)), self.assertRaises(ValueError): validate_trace(value)

    def test_unknown_missing_and_wrongly_typed_fields_are_rejected(self):
        for path in ((), ('engine',), ('domain',)):
            for change in ('missing', 'unknown', 'list'):
                value = authored(); parent = value
                for key in path: parent = parent[key]
                if change == 'missing': parent.pop(next(iter(parent)))
                elif change == 'unknown': parent['unexpected'] = 0
                elif path: value[path[0]] = []
                else: value = []
                with self.subTest(path=path, change=change), self.assertRaises(ValueError): validate_trace(value)

    def test_engine_and_fixture_identity_require_complete_lowercase_digests(self):
        for key in ('revision','source_sha256','binary_sha256','fixture_sha256'):
            for invalid in ('', 'A'*64, '../file', None, 0):
                value = authored(); parent = value if key=='fixture_sha256' else value['engine']; parent[key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError): validate_trace(value)

    def test_names_are_bounded_safe_identifiers(self):
        for invalid in ('', '../file', 'x'*97, 'path/name', None, True):
            value = authored(); value['case'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): validate_trace(value)

    def test_fir_domain_requires_exact_rate_latency_and_version(self):
        value = authored('resampled-filtered')
        value['domain'].update(output_rate=48000, latency_source_frames=31, resampler='fir64x160-q30-v1')
        self.assertIs(validate_trace(value), value)
        for field, invalid in (('output_rate',44100),('latency_source_frames',0),('resampler','identity-v1'),('gain_divisor',1)):
            changed = copy.deepcopy(value); changed['domain'][field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError): validate_trace(changed)
        with self.assertRaisesRegex(ValueError, 'domain'): compare_traces(authored('mixed-filtered'), value)

    def test_raw_48khz_and_unknown_filter_or_clock_are_refused(self):
        for field, invalid in (('stage','unknown'),('timing','arbitrary'),('output_rate',48000),
                               ('output_rate',46000),('latency_source_frames',1),('resampler','fir64x160-q30-v1'),('gain_divisor',2)):
            value = authored(); value['domain'][field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError): validate_trace(value)

    def test_mixed_domains_pin_the_declared_headroom(self):
        for stage in ('mixed-raw','mixed-filtered'):
            value = authored(stage); validate_trace(value); value['domain']['gain_divisor'] = 1
            with self.assertRaises(ValueError): validate_trace(value)

    def test_duplicate_keys_nan_utf8_and_malformed_json_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'audio.json'
            for data in (b'{"schema":1,"schema":1}', b'{"sample":NaN}', b'{"sample":Infinity}', b'\xff', b'{} trailing'):
                path.write_bytes(data)
                with self.subTest(data=data), self.assertRaises(ValueError): load_trace(path)

    def test_loader_enforces_byte_limit_while_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'audio.json'; path.write_text(json.dumps(authored()), encoding='utf8')
            with patch('pcerecomp.audio_trace.MAX_FILE_BYTES', 31), self.assertRaisesRegex(ValueError, 'byte bound'):
                load_trace(path)

    def test_cli_loads_actual_files_and_exclusively_writes_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b, out = (Path(directory)/name for name in ('a.json','b.json','comparison.json'))
            for path in (a,b): path.write_text(json.dumps(authored()), encoding='utf8')
            with redirect_stdout(io.StringIO()) as text:
                self.assertEqual(main([str(a),str(b),'--output',str(out)]), 0)
            self.assertEqual(json.loads(text.getvalue()), json.loads(out.read_text(encoding='utf8')))
            saved = out.read_bytes()
            with redirect_stdout(io.StringIO()): self.assertEqual(main([str(a),str(b),'--output',str(out)]), 2)
            self.assertEqual(out.read_bytes(), saved)
            changed = authored(); changed['samples'][0][0] += 1; b.write_text(json.dumps(changed), encoding='utf8')
            with redirect_stdout(io.StringIO()): self.assertEqual(main([str(a),str(b)]), 1)
            b.write_text(json.dumps(authored('psg-hpf')), encoding='utf8')
            with redirect_stdout(io.StringIO()) as text: self.assertEqual(main([str(a),str(b)]), 2)
            self.assertFalse(json.loads(text.getvalue())['compatible'])


if __name__ == '__main__':
    unittest.main()
