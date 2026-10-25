"""Authored independent BRAM expected bytes and strict reference observations."""
import unittest
from scripts import bram_reference as r


class BramReferenceTests(unittest.TestCase):
    def test_full_seed_and_written_pattern(self):
        self.assertEqual(len(r.seed()),2048);self.assertEqual(len(r.written()),2048)
        self.assertEqual([r.seed()[i] for i in (0,255,256,2047)],[49,36,86,39])
        self.assertEqual([r.written()[i] for i in (0,255,256,2047)],[165,90,128,89])
    def test_real_guest_uses_aliases_gates_and_all_pages(self):
        image,prefix,body=r.firmware();self.assertEqual(len(image),262144)
        self.assertEqual(image[8190:8192],b'\x00\xE1');self.assertEqual((prefix,body),(31,10259))
        for address in (0x1807,0x1803,0x9807,0x4000,0x6000,0x4800,0x7FFF):
            self.assertIn(bytes((0xAD,address&255,address>>8)),image)
        for page in range(8): self.assertIn(bytes((0x9D,0,0x40+page)),image)
    def test_record_rejects_count_and_boolean(self):
        cases=[dict(operations=[('x',)])]
        with self.assertRaisesRegex(ValueError,'count'):r.validate_records([],cases)
        values=list(r.seed());values[0]=True
        with self.assertRaisesRegex(ValueError,'type/shape'):r.validate_records([dict(kind='export',values=values)],cases)
    def test_literal_rejects_changed_saved_byte(self):
        cases=[dict(operations=[('r',0),('x',)])]
        rows=[dict(kind='export',values=list(r.seed()))]
        self.assertEqual(r.literal_checks(rows,cases),2048)
        rows[0]['values'][-1]^=1
        with self.assertRaisesRegex(ValueError,'literal'):r.literal_checks(rows,cases)
    def test_finite_retirement_and_export_counts(self):
        cases=r.plans();self.assertEqual(len(cases),2)
        self.assertEqual(sum(o[1] for c in cases for o in c['operations'] if o[0]=='i'),20642)
        self.assertEqual(sum(o[0]=='x' for c in cases for o in c['operations']),4)


if __name__=='__main__':unittest.main()
