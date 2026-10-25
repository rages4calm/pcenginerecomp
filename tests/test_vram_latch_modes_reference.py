import unittest
from scripts.vram_latch_modes_reference import literal_record,validate,CASES

class VramModesReferenceTests(unittest.TestCase):
    def test_selected_low_and_high_planes(self):
        self.assertEqual(literal_record(0,0,0x0080),bytes([113]+[0]*7+[128,0]))
        self.assertEqual(literal_record(0,1,0xFF7F),bytes([113]+[0]*7+[128,0]))

    def test_high_descriptor_uses_fetched_bat_not_prior_latch(self):
        self.assertEqual(literal_record(1,0,0),literal_record(1,1,65535))
        self.assertEqual(literal_record(1,0,0)[-2:],b'\0\x78')

    def test_bounded_record_extent(self):
        for raw in (b'',bytes(CASES*10-1),bytes(CASES*10+1)):
            with self.assertRaises(ValueError):validate(raw)

    def test_incorrect_selected_pixels_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'literal differs'):validate(bytes(CASES*10))
