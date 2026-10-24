"""Authored cartridge conversion, compatibility mapping and snapshot checks."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.cartridge import Cartridge, bank_map, decode
from pcerecomp.cli import main
from pcerecomp.analysis import Snapshot, analyze


def rom(banks=1, program=bytes.fromhex('A9 FF 53 01 EA')):
    raw = bytearray(b''.join(bytes([bank])*8192 for bank in range(banks)))
    raw[256:256+len(program)] = program
    raw[8190:8192] = bytes((0, 0xE1))
    return bytes(raw)


class CartridgeTests(unittest.TestCase):
    def test_selected_special_mapping_has_literal_boundary_values(self):
        offsets = (0, 31, 32, 47, 48, 63, 64, 79, 80, 95, 96, 127)
        for count, expected in (
                (48, (0, 31, 0, 15, 16, 31, 32, 47, 32, 47, 32, 47)),
                (64, (0, 31, 32, 47, 48, 63, 32, 47, 48, 63, 32, 63)),
                (96, (0, 31, 32, 47, 48, 63, 64, 79, 80, 95, 64, 95))):
            self.assertEqual(tuple(bank_map(count*8192)[offset] for offset in offsets), expected)
        for count in range(1, 129):
            mapped = bank_map(count*8192)
            self.assertEqual(len(mapped), 128)
            self.assertTrue(all(0 <= bank < count for bank in mapped))
            if count not in (48, 64, 96):
                self.assertEqual(mapped, tuple(bank % count for bank in range(128)))

    def test_decoder_reverses_each_byte_without_reordering_bytes(self):
        source = bytes(range(256))*32
        actual = decode(source, encoding='bit-reversed')
        for value in range(256):
            expected = sum(weight for bit, weight in enumerate((128, 64, 32, 16, 8, 4, 2, 1))
                           if value & (1 << bit))
            self.assertEqual(actual[value], expected)
        self.assertEqual(decode(actual, encoding='bit-reversed'), source)
        self.assertEqual(actual[:4], bytes((0, 128, 64, 192)))

    def test_opaque_header_is_explicit_and_not_part_of_conversion(self):
        source = bytes(range(256))*32
        header = bytes((0xA6,))*512
        self.assertEqual(decode(header+source, 'copier512'), source)
        self.assertEqual(decode(header+source, 'copier512', 'bit-reversed'), decode(source, encoding='bit-reversed'))
        with self.assertRaises(ValueError):
            decode(header+source)
        with self.assertRaises(ValueError):
            decode(source, 'copier512')

    def test_size_and_interpretation_fail_explicitly(self):
        for size in (0, 1, 8191, 8193, 1048577, 1049088):
            with self.subTest(size=size), self.assertRaises(ValueError):
                decode(bytes(size))
        for size in (True, 0, -8192, 8192.0, 1048576+8192):
            with self.assertRaises(ValueError):
                bank_map(size)
        for header, encoding in (('auto', 'linear'), ('none', 'usa'), (True, 'linear')):
            with self.assertRaises(ValueError):
                decode(bytes(8192), header, encoding)

    def test_raw_and_decoded_identities_are_separate_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'authored.pce'
            source = rom()
            header = bytes((0x93,))*512
            path.write_bytes(header+source)
            card = Cartridge(path, 'copier512')
            report = card.report()
            self.assertEqual(report['file_sha256'], hashlib.sha256(header+source).hexdigest())
            self.assertEqual(report['decoded_rom_sha256'], hashlib.sha256(source).hexdigest())
            self.assertEqual((report['rom_bytes'], report['reset_pc']), (8192, 0xE100))
            self.assertEqual(len(card.mapped_rom()), 1048576)
            self.assertEqual(path.read_bytes(), header+source)
            path.write_bytes(header+source+b'\0')
            with self.assertRaisesRegex(ValueError, 'changed'):
                card.mapped_rom()

    def test_private_snapshot_starts_at_vector_and_retains_mapping_barrier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, output = root/'authored.pce', root/'new-snapshot'
            path.write_bytes(rom(48))
            before = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['hucard', str(path), '--out', str(output)]), 0)
            snapshot = Snapshot.load(output/'snapshot.toml')
            self.assertEqual((snapshot.mpr, snapshot.entries), ((0,)*8, (0xE100,)))
            self.assertEqual(snapshot.memory[0x40000], 0)  # bank20 aliases first chip
            self.assertEqual(snapshot.memory[0x80000], 32) # bank40 selects second chip
            result = analyze(snapshot)
            self.assertEqual([item['mnemonic'] for item in result['instructions']], ['LDA', 'TAM'])
            self.assertTrue(result['unresolved'])
            report = json.loads((output/'cartridge.json').read_text())
            self.assertEqual((report['runtime_abi'], report['profile']), (18, 'base'))
            self.assertEqual(report['mapped_rom_sha256'], hashlib.sha256((output/'mapped-rom.bin').read_bytes()).hexdigest())
            self.assertEqual(path.read_bytes(), before)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['hucard', str(path), '--out', str(output)]), 2)
            self.assertEqual(path.read_bytes(), before)

    def test_snapshot_conversion_flags_match_decoded_source_and_no_invalid_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, output = root/'authored.pce', root/'new-snapshot'
            expected = rom()
            encoded = decode(expected, encoding='bit-reversed')
            path.write_bytes(bytes(512)+encoded)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['hucard', str(path), '--out', str(output),
                                       '--rom-header', 'copier512', '--rom-encoding', 'bit-reversed']), 0)
            self.assertEqual((output/'mapped-rom.bin').read_bytes()[:8192], expected)
            path.write_bytes(b'invalid')
            rejected = root/'invalid-output'
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['hucard', str(path), '--out', str(rejected)]), 2)
            self.assertFalse(rejected.exists())
