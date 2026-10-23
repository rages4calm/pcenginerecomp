"""Authored adapter failure/fixture checks; external execution is explicit."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest
from scripts import cdda_latch_reference as ref


class CddaLatchReferenceTests(unittest.TestCase):
    def test_monotone_cases_and_reset(self):
        cases=ref.plans();self.assertEqual(len({c['id'] for c in cases}),len(cases))
        for case in cases:
            self.assertEqual(case['operations'][0],('r',));prior=0
            for op in case['operations'][1:]:
                self.assertIn(op[0],('w','a','s'));self.assertGreaterEqual(op[1],prior,case['id']);prior=op[1]

    def test_real_admission_boundaries_and_ignored_high_write(self):
        ops=ref.plans()[0]['operations']
        for at in (0,699,700,1399,1400,2099,2100):self.assertIn(('s',at),ops)
        self.assertIn(('w',1400,6,255),ops)
        self.assertLess(ops.index(('w',1400,6,255)),ops.index(('w',1400,5,0)))

    def test_every_payload_value_and_fixed_spacing(self):
        ops=ref.plans()[1]['operations'];writes=[op for op in ops if op[0]=='w']
        self.assertEqual([op[3] for op in writes],list(range(256)))
        self.assertEqual([op[1] for op in writes],[700*i for i in range(1,257)])

    def test_fixture_signed_channels_and_data_geometry(self):
        with tempfile.TemporaryDirectory() as name:
            cue,binary=ref.write_fixture(Path(name));raw=binary.read_bytes()
            self.assertEqual(len(raw),2352*16)
            self.assertEqual(struct.unpack('<hhhh',raw[:8]),(-32768,32767,1,0))
            self.assertIn('TRACK 02 MODE1/2352',cue.read_text())
            self.assertIn('INDEX 01 00:00:08',cue.read_text())

    def test_serialization_counts_and_contiguous_spans(self):
        text,spans=ref.serialize(ref.plans())
        self.assertEqual(sum(s['checkpoints'] for s in spans),sum(x.startswith('s ') for x in text.splitlines()))
        for a,b in zip(spans,spans[1:]):self.assertEqual(a['start']+a['checkpoints'],b['start'])

    def row(self):return dict(time=700,lo=255,hi=255,channel=0,bram_before=128,bram_after=0,left=-32768,right=-1)

    def test_every_comparison_field_matters(self):
        for field in ref.FIELDS:
            a,b=self.row(),self.row();b[field]+=2 if field=='channel' else 1
            if field in ('lo','hi'):b[field]=254
            if field=='bram_before':b[field]=0
            if field=='bram_after':b[field]=128
            self.assertEqual(ref.compare([a],[b],[dict(id='x',start=0,checkpoints=1)])['field'],field)

    def test_bad_lengths_fields_values_rejected(self):
        span=[dict(id='x',start=0,checkpoints=1)]
        with self.assertRaises(ValueError):ref.compare([],[],span)
        for field,value in (('lo',256),('hi',-1),('channel',1),('bram_before',1),('bram_after',2),('left',32768),('right',-32769),('time',True)):
            row=self.row();row[field]=value
            with self.assertRaises(ValueError):ref.compare([row],[row],span)
        row=self.row();row['extra']=0
        with self.assertRaises(ValueError):ref.compare([row],[row],span)

    def test_identical_rows_pass_without_mutation(self):
        a,b=self.row(),self.row();prior=copy.deepcopy(a)
        self.assertIsNone(ref.compare([a],[b],[dict(id='x',start=0,checkpoints=1)]));self.assertEqual(a,prior)


if __name__=='__main__':unittest.main()
