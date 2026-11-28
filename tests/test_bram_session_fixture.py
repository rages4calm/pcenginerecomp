"""Independent literal boundaries for the authored save-session firmware."""
import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bram_session_fixture',ROOT/'examples/bram-session/fixture.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class BramSessionFixtureTests(unittest.TestCase):
    def test_optional_two_kib_seed_has_literal_filesystem_bounds(self):
        self.assertEqual(len(fixture.FORMATTED),2048)
        self.assertEqual(fixture.FORMATTED[:8],bytes((72,85,66,77,0,136,16,128)))
        self.assertEqual(fixture.FORMATTED[8:],bytes(2040))
        self.assertEqual(hashlib.sha256(fixture.FORMATTED).hexdigest(),'7e631b4e463a04481939fde974cd341a1478af8c1f75350fd73c94a3430a0887')
        self.assertEqual(int.from_bytes(fixture.FORMATTED[4:6],'little'),0x8800)
        self.assertEqual(int.from_bytes(fixture.FORMATTED[6:8],'little'),0x8010)

    def test_authored_reset_image_has_only_its_bounded_program_and_vector(self):
        raw=fixture.firmware();code,labels=fixture.program()
        self.assertEqual(len(raw),262144)
        self.assertEqual(raw[8190:8192],bytes((0,226)))
        self.assertEqual(raw[512],0x78)
        self.assertEqual(raw[512:512+len(code)],code)
        self.assertEqual(raw[:512]+raw[512+len(code):8190]+raw[8192:],bytes(262144-len(code)-2))
        self.assertLess(labels['gate'],labels['done'])
        self.assertIn(bytes.fromhex('73 00 40 00 28 00 08'),code)
        self.assertIn(bytes.fromhex('73 00 40 00 30 00 08'),code)

    def test_guest_mutations_have_independent_exact_expected_image(self):
        seed=bytes(2048);expected=bytearray(2048);expected[16]=90;expected[2047]=165
        self.assertEqual(fixture.expected_output(seed),bytes(expected))
        patterned=bytes((index*37+61)&255 for index in range(2048))
        self.assertEqual(fixture.saved_pattern(),patterned)
        changed=fixture.expected_output(patterned)
        self.assertEqual(changed[:16],patterned[:16])
        self.assertEqual(changed[17:2047],patterned[17:2047])
        self.assertEqual((changed[16],changed[2047]),(215,189))
        self.assertEqual(fixture.expected_output(changed),patterned)
        for bad in (bytes(),bytes(2047),bytes(2049),bytearray(2048),None):
            with self.subTest(value=type(bad).__name__),self.assertRaises(ValueError):fixture.expected_output(bad)
