"""Independent authored VRAM latch fixture and strict observation schema."""
import unittest
from scripts import vram_latch_reference as r


class VramLatchReferenceTests(unittest.TestCase):
    def test_seed_and_guest_cover_high_reads_and_aliases(self):
        self.assertEqual([r.pattern(i)for i in(0,1,32767)],[42300,42357,54644])
        image,ops=r.firmware();self.assertEqual(len(image),262144);self.assertEqual(image[8190:8192],b'\0\xE1')
        self.assertIn(b'\xAD\x03\x80',image);self.assertIn(b'\x13\xFF\x23\xFF',image)
        self.assertGreater(len(ops),100)
    def test_read_latch_and_ignored_write_are_distinct(self):
        model=r.Model();self.assertEqual(model.word(0x8000),0)
        value=model.word(123);self.assertEqual(model.word(65535),value)
        model.reg(0,0x8000);model.reg(2,0x1234)
        self.assertEqual(model.latch,value);self.assertEqual(model.r[0],0x8001)
    def test_dma_skipped_destination_does_not_sample_source(self):
        model=r.Model();value=model.word(123);model.reg(16,0);model.reg(17,0x8000);model.reg(18,0);model.dots(4)
        self.assertEqual(model.latch,value);self.assertEqual(model.r[16:19],[1,0x8001,65535])
    def test_schema_rejects_bool_shape_and_changed_word(self):
        cases=[dict(id='authored',operations=[('r',0),('q',0x8000)])]
        rows=[dict(kind='word',values=[0x8000,0])];self.assertEqual(r.literal_checks(rows,cases),2)
        rows[0]['values'][1]=True
        with self.assertRaises(ValueError):r.validate_records(rows,cases)
        rows[0]['values'][1]=1
        with self.assertRaises(ValueError):r.literal_checks(rows,cases)
    def test_actual_retirement_counts_and_finite_cases(self):
        cases=r.plans();self.assertEqual(len(cases),31)
        self.assertEqual(len(cases[0]['operations']),65537)
        self.assertEqual(sum(op[1]for c in cases for op in c['operations']if op[0]=='i'),2*len(r.firmware()[1]))


if __name__=='__main__':unittest.main()
