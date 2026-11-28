"""Authored known-vector geometry, independent pointer-byte literals."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("vector_fixture_test",ROOT/"examples/ram-cd-vectors/fixture.py")
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
class VectorFixtureTests(unittest.TestCase):
    def test_two_independent_pointer_words_and_real_jumps(self):
        raw=f.resident();self.assertEqual(len(raw),64)
        self.assertEqual(raw[32:37],bytes.fromhex("A2 02 7C 30 60"))
        self.assertEqual(raw[40:43],bytes.fromhex("6C 34 60"))
        self.assertEqual(raw[50:54],bytes.fromhex("28 60 2C 60"))
        self.assertEqual(raw[44:48],bytes.fromhex("62 82 C2 60"))
    def test_original_firmware_copies_exact_resident_bytes(self):
        image,_=f.firmware();self.assertEqual(len(image),262144)
        self.assertEqual(image[0x780:0x7C0],f.resident())
        self.assertEqual(image[8190:8192],bytes.fromhex("00 E7"))
    def test_both_original_disc_loads_preserve_separate_resident(self):
        for phase in (1,2):
            ram=f.expected_cd(phase);self.assertEqual(len(ram),65536)
            self.assertEqual(ram[:2048],f.sector(phase))
            self.assertEqual(ram[0x4000:0x4040],f.resident())
