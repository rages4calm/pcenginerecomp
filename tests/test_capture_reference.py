"""Protocol decoding checks for the independent authored capture probe."""
import unittest
from scripts.capture_reference import trace_ticks
from generate_capture_reference_fixture import capture, plans, ram_image, rom_image


class CaptureReferenceTests(unittest.TestCase):
    def test_cross_page_and_wrap_are_independently_mapped(self):
        records = capture()['observations']
        cross = next(r for r in records if r['pc'] == 0x3FFF)
        wrap = next(r for r in records if r['pc'] == 0xFFFF)
        self.assertEqual(cross['physical'], [0x1F1FFF, 0x2000])
        self.assertEqual(wrap['physical'], [0x1F1FFF, 0x2000])
        self.assertEqual(cross['data'], [0x69, 0x21])
        self.assertEqual(wrap['data'], [0xA9, 0x21])

    def test_fixture_bytes_match_every_observation(self):
        rom = rom_image()
        for p in plans():
            ram = ram_image(p)
            for i, value in enumerate(p['data']):
                logical = (p['pc']+i)&65535
                address = (p['mpr'][logical>>13]<<13)|(logical&8191)
                self.assertEqual(ram[address-0x1F0000] if address>=0x1F0000 else rom[address],value)

    def test_trace_decoding_validates_bank_and_pc(self):
        trace = dict(overrun=False,count=3,lines=['@12 CPU F8:3FFF ADC', '@27 CPU F8:2600 TMA', '@39 CPU F8:2602 NOP'])
        mapping = [0,0xF8,1,2,3,4,5,0]
        self.assertEqual(trace_ticks(trace,[0x3FFF,0x2600,0x2602],[mapping]*3),[15,12])
        for change in (dict(overrun=True),dict(count=2),dict(lines=trace['lines'][:2]),
                       dict(lines=['@12 CPU 01:3FFF ADC']+trace['lines'][1:]),
                       dict(lines=['@30 CPU F8:3FFF ADC']+trace['lines'][1:])):
            with self.assertRaises(RuntimeError):
                trace_ticks(trace|change,[0x3FFF,0x2600,0x2602],[mapping]*3)
