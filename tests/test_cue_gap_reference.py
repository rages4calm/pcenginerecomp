"""Independent literal contract and rejection controls for CUE gap observers."""
import copy
import json
import unittest
from scripts.cue_gap_reference import definitions,expected,operations,read_rows,validate,negative_controls


class CueGapReferenceTests(unittest.TestCase):
    def case(self,name):return next(c for c in definitions() if c['id']==name)

    def test_literal_split_timeline_keeps_all_three_gap_kinds_separate(self):
        case=self.case('split-post-pre-trailing')
        self.assertEqual(case['tracks'],[[0,0],[6,0],[15,0]])
        self.assertEqual(case['leadout'],20)
        self.assertEqual([r[0] for r in case['mapping']],[0,1,2,6,7,8,9,15,16,17])
        self.assertEqual(case['gear_leadout'],18)
        self.assertNotIn('POSTGAP',case['gear_cue'])
        self.assertIn('PREGAP 00:00:03',case['gear_cue'])
        self.assertIn('PREGAP 00:00:05',case['gear_cue'])

    def test_stored_bytes_survive_adjacent_virtual_postgap(self):
        case=self.case('shared-stored-with-postgap')
        self.assertEqual(case['tracks'],[[0,0],[5,0],[8,0]])
        self.assertEqual(case['gear_cue'],None)
        rows=expected(case,[('a',4),('m',4),('m',2),('a',2)])
        self.assertTrue(rows[0]['ok'])
        self.assertEqual(rows[0]['samples'],rows[1]['samples'])
        self.assertTrue(any(rows[0]['samples']))
        self.assertEqual(rows[2]['samples'],[0]*1176)
        self.assertEqual(rows[3],dict(kind='audio',lba=2,ok=False,error='unavailable_audio'))

    def test_data_gap_rejection_is_distinct_from_audio_payload_and_leadout(self):
        rows=expected(self.case('mixed-data-audio-postgap'),[('d',3),('d',6),('d',10),('a',0),('m',0)])
        self.assertEqual([r.get('error') for r in rows[:4]],['unrecoverable_data','wrong_data_track','out_of_range','unavailable_audio'])
        self.assertEqual(rows[4]['samples'],[0]*1176)

    def test_trailing_cue_gap_is_real_time_with_no_raw_payload(self):
        case=self.case('final-postgap-only')
        self.assertEqual(case['leadout'],5)
        self.assertEqual(case['gear_leadout'],2)
        for lba in (2,3,4):
            audio,pcm=expected(case,[('a',lba),('m',lba)])
            self.assertFalse(audio['ok']);self.assertEqual(pcm['samples'],[0]*1176)

    def test_msf_carry_is_independent_literal(self):
        case=self.case('msf-gap-boundary')
        self.assertEqual(case['tracks'],[[0,0],[79,0]])
        self.assertEqual(case['leadout'],81)
        self.assertIn('PREGAP 00:01:01',case['gear_cue'])

    def test_beetle_scope_uses_raw_reads_not_tool_refusal_labels(self):
        for case in definitions():
            ops=operations(case,'beetle')
            self.assertTrue(all(op[0] in ('t','d','a','m') for op in ops))
            self.assertTrue(all(row.get('ok') is not False for row in expected(case,ops,'beetle')))

    def test_gear_scope_has_no_fabricated_gap_pcm_or_postgap_parse(self):
        for case in definitions():
            if case['gear_cue'] is not None:
                self.assertNotIn('POSTGAP',case['gear_cue'])
                self.assertNotIn('m',[op[0] for op in operations(case,'gear')])

    def test_all_complete_literal_plans_are_bounded_and_typed(self):
        for case in definitions():
            ops=operations(case);self.assertLess(len(ops),4096)
            self.assertEqual(len({r[0] for r in case['mapping']}),len(case['mapping']))
            rows=expected(case,ops)
            self.assertGreater(validate(read_rows('\n'.join(map(json.dumps,rows))),rows),len(rows))

    def test_rejects_wrong_geometry_payload_gap_pcm_and_types(self):
        case=self.case('final-postgap-only');wanted=expected(case,[('t',),('a',0),('m',2),('p',2)])
        for mutate in (lambda r:r[0].update(leadout=2),lambda r:r[0]['tracks'][0].__setitem__(0,1),
                       lambda r:r[1]['samples'].__setitem__(0,999),lambda r:r[2]['samples'].__setitem__(11,1),
                       lambda r:r[3].update(value=0),lambda r:r.pop()):
            bad=copy.deepcopy(wanted);mutate(bad)
            with self.assertRaises(ValueError):validate(bad,wanted)

    def test_jsonl_duplicate_nonfinite_and_partial_rows_refuse(self):
        for text in ('{"kind":"toc","kind":"pcm"}','{"value":NaN}','{"value":Infinity}','{"kind":','\n'):
            with self.subTest(text=text),self.assertRaises(ValueError):read_rows(text)

    def test_material_control_matrix_rejects_each_mutation(self):
        rows=[row for case in definitions() for row in expected(case,operations(case))]
        controls=negative_controls(rows,rows)
        self.assertEqual(len(controls),13)
        self.assertTrue(all(r['rejected'] for r in controls))


if __name__=='__main__':unittest.main()
