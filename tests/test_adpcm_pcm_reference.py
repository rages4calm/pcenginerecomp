"""Authored rejection fixtures for the version-specific independent reader."""
import copy
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.adpcm_pcm_reference import authored_ram, parse_state, HEADER_SIZE, initial_line, compare_checkpoint, source_files


def fixture():
    ram = authored_ram()
    data = bytearray(13)+ram+bytearray(63)+bytearray(16)+bytearray(HEADER_SIZE)
    data[0] = 1
    struct.pack_into('<I', data, 1, 0x12345678)
    struct.pack_into('<Q', data, 5, 123456)
    tail = 13+65536
    period = (21477273*65536+16050)//32100
    data[tail+16] = 15
    struct.pack_into('<i', data, tail+17, period)
    struct.pack_into('<h', data, tail+36, 2048)
    struct.pack_into('<f', data, tail+59, 1)
    header = len(data)-HEADER_SIZE
    struct.pack_into('<III', data, header, 0x82190619, 44, len(data))
    struct.pack_into('<I', data, header+152, 0x12345678)
    data[header+165:header+171] = b'1.8.4\0'
    public = dict(read_address='0000', write_address='0000', address='0000',
                  length=0, control='00', dma='00', playing=False,
                  frame_samples=0, status_register='00', frequency_khz=32.1)
    return data, ram, public, tail, header


class AdpcmStateReaderTests(unittest.TestCase):
    def test_source_layouts_and_exact_identity(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pin = {'src__authored.h': hashlib.sha256(b'authored\n').hexdigest()}
            for name in ('src__authored.h', 'authored.h'):
                with self.subTest(layout=name), patch('scripts.adpcm_pcm_reference.SOURCE_SHA', pin):
                    path = root/name; path.write_bytes(b'authored\n')
                    self.assertEqual(source_files(root), {'src__authored.h': path.resolve()})
                    path.write_bytes(b'changed\n')
                    with self.assertRaisesRegex(ValueError, 'identity'): source_files(root)
                    path.unlink()
            with patch('scripts.adpcm_pcm_reference.SOURCE_SHA', pin):
                with self.assertRaisesRegex(ValueError, 'identity'): source_files(root)

    def test_authored_marker_and_valid_widths(self):
        data, ram, public, _, _ = fixture()
        self.assertEqual(len(ram), 65536)
        self.assertEqual(ram, authored_ram())
        state = parse_state(data, ram, public)
        self.assertEqual((state['predictor'], state['index'], state['master_ticks']), (2048, 0, 123456))
        self.assertEqual(initial_line(state), f"15 0 0 0 0 0 0 2048 0 0 123456 0 0\n")

    def test_unknown_format_identity_and_header_rejected(self):
        for mutation in ('magic', 'version', 'size', 'build', 'cd', 'crc', 'screenshot', 'truncated', 'marker'):
            with self.subTest(mutation=mutation):
                data, ram, public, _, header = fixture()
                if mutation == 'magic': data[header] ^= 1
                elif mutation == 'version': struct.pack_into('<I', data, header+4, 43)
                elif mutation == 'size': struct.pack_into('<I', data, header+8, len(data)-1)
                elif mutation == 'build': data[header+165] = ord('2')
                elif mutation == 'cd': data[0] = 0
                elif mutation == 'crc': data[header+152] ^= 1
                elif mutation == 'screenshot': data[header+156] = 1
                elif mutation == 'truncated': data = data[:-1]
                elif mutation == 'marker': data[99] ^= 1
                with self.assertRaises(ValueError): parse_state(data, ram, public)

    def test_ambiguous_marker_rejected(self):
        data, ram, public, _, header = fixture()
        data[header:header] = ram
        struct.pack_into('<I', data, len(data)-HEADER_SIZE+8, len(data))
        with self.assertRaisesRegex(ValueError, 'ambiguous'): parse_state(data, ram, public)

    def test_scalar_ranges_widths_and_nonfinite_filters_rejected(self):
        mutations = ((27, '<B', 2), (36, '<h', -1), (36, '<h', 4096), (38, '<B', 49),
                     (39, '<i', -1), (17, '<i', 1), (32, '<I', 131072),
                     (43, '<i', 2049), (2, '<i', -1), (47, '<f', float('nan')))
        for offset, fmt, value in mutations:
            with self.subTest(offset=offset, value=value):
                data, ram, public, tail, _ = fixture()
                struct.pack_into(fmt, data, tail+offset, value)
                with self.assertRaises(ValueError): parse_state(data, ram, public)

    def test_all_public_bindings_rejected_on_disagreement(self):
        values = dict(read_address='0001', write_address='0001', address='0001', length=1,
                      control='01', dma='01', playing=True, frame_samples=1, status_register='01',
                      frequency_khz=1)
        for key, value in values.items():
            with self.subTest(key=key):
                data, ram, public, _, _ = fixture()
                bad = copy.deepcopy(public); bad[key] = value
                with self.assertRaises(ValueError): parse_state(data, ram, bad)

    def test_public_frequency_requires_finite_numeric_value(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, False, '32.1', None, {}, 0, -1, 10**1000):
            data, ram, public, _, _ = fixture()
            public['frequency_khz'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): parse_state(data, ram, public)

    def test_high_low_nibble_and_predictor_limits_are_accepted(self):
        for output in (0, 4095):
            for nibble in (False, True):
                data, ram, public, tail, _ = fixture()
                struct.pack_into('<h', data, tail+36, output)
                data[tail+31] = int(nibble)
                data[tail+38] = 48
                state = parse_state(data, ram, public)
                self.assertEqual((state['predictor'], state['index'], state['nibble']), (output, 48, nibble))

    def test_exact_playing_phase_and_all_decoder_fields_are_required(self):
        data, ram, public, _, _ = fixture()
        state = parse_state(data, ram, public)
        self.assertEqual(compare_checkpoint(state, state), 0)
        for key in ('predictor', 'index', 'control', 'rate', 'phase', 'period', 'read_address', 'length',
                    'playing', 'pending', 'nibble', 'end', 'half'):
            bad = state | {key: int(state[key])+1}
            with self.subTest(key=key), self.assertRaises(ValueError): compare_checkpoint(bad, state)

    def test_finite_stop_requires_exact_two_independent_residues(self):
        data, ram, public, _, _ = fixture()
        anchor = parse_state(data, ram, public) | dict(length=1, control=0x60, phase=983040)
        wanted = anchor | dict(predictor=2141, index=16, phase=55846, read_address=0,
                               length=0, end=True, half=True, playing=False, pending=False, nibble=False)
        gear = wanted | dict(phase=186918)
        self.assertEqual(compare_checkpoint(gear, wanted, anchor), 131072)
        for bad in (gear | dict(phase=186919), gear | dict(phase=55846), gear | dict(playing=True),
                    gear | dict(length=1), gear | dict(pending=True), gear | dict(end=False),
                    gear | dict(half=False), gear | dict(nibble=True), gear | dict(predictor=2140)):
            with self.subTest(bad=bad), self.assertRaises(ValueError): compare_checkpoint(bad, wanted, anchor)
        with self.assertRaises(ValueError): compare_checkpoint(gear, wanted | dict(phase=55847), anchor)
        with self.assertRaises(ValueError): compare_checkpoint(gear, wanted, anchor | dict(length=2))


if __name__ == '__main__':
    unittest.main()
