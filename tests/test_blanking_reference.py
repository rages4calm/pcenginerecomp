"""Independent literal admissions for authored reference frames, not hardware proof."""
import copy
import hashlib
import unittest
from scripts import blanking_reference as reference


def frame(case,engine):
    # Independent color literals: red backdrop, green border, black third value.
    if engine=='beetle':
        color=0x07E0 if case['cr']in (0,64) else 0xF800
        return dict(width=256,height=243,center_rows=[color]*243,markers=dict(disabled=27,reenabled=28))
    color=[0,0,0]if case['cr']==0 else [255,0,0]
    return dict(width=256,height=242,center_rows=[color.copy()for _ in range(242)],markers=dict(disabled=27,reenabled=28))


class BlankingReferenceTests(unittest.TestCase):
    def test_canonical_cases_separate_stable_burst_and_midframe_disable(self):
        cases=reference.cases()
        self.assertEqual([x['cr']for x in cases],[0,64,128,192,128])
        self.assertEqual([x['midframe']for x in cases],[False]*4+[True])
        self.assertEqual(len({x['id']for x in cases}),5)

    def test_roms_are_authored_deterministic_distinct_with_explicit_vectors(self):
        images=[reference.authored_rom(case)for case in reference.cases()]
        self.assertEqual(len(set(images)),5)
        for case,image in zip(reference.cases(),images):
            self.assertEqual(image,reference.authored_rom(case))
            self.assertEqual(len(image),262144)
            self.assertEqual(image[8190:8192],b'\0\xe0')
            self.assertIn(bytes.fromhex('A9 38 8D 04 04'),image[:1024])
            self.assertIn(bytes.fromhex('A9 C0 8D 04 04'),image[:1024])
            self.assertEqual(image[1024:8190],bytes([0xEA])*(8190-1024))
        self.assertEqual([hashlib.sha256(x).hexdigest()for x in images[:4]],[
            '5afc1ba15c846238190dff8056ff6596a56b260ca7d4c4a439429a66541e9070',
            '3a397fd32d100246aeaa1946de6619ead44e6cefedc7654b843115b0bed47692',
            '4a841a2f3d0dcfe31ea44e58388920d873cad5349846840b450a6d4607246714',
            '16ff750eb7a8793051d5640932a0bd738d2092b47303ccf1a7a0743dd4d6f93c'])
        self.assertEqual(images[-1].count(bytes.fromhex('03 05 13 8C 23 00')),2)
        self.assertEqual(images[-1].count(bytes.fromhex('03 05 13 0C 23 00')),1)
        for instruction in ('A9 00 8D 40 20','A9 00 8D 41 20','E6 40','E6 41'):
            self.assertEqual(images[-1].count(bytes.fromhex(instruction)),1)

    def test_fixture_refuses_unknown_or_inexact_case_types(self):
        for changed in (dict(id='other',cr=0,midframe=False),
                        dict(id='stable-00',cr=False,midframe=False),
                        dict(id='stable-00',cr=0,midframe=0)):
            with self.subTest(case=changed),self.assertRaises(ValueError):reference.authored_rom(changed)

    def test_all_literal_core_profiles_pass_without_mutation(self):
        for case in reference.cases():
            for engine in ('beetle','gear'):
                value=frame(case,engine);original=copy.deepcopy(value)
                reference.admit_frame(case,value,engine)
                self.assertEqual(value,original)

    def test_palette_selector_confusion_is_refused_for_each_engine(self):
        case=reference.cases()[0]
        for engine,bad in (('beetle',0),('beetle',0xF800),('gear',[0,255,0]),('gear',[255,0,0])):
            value=frame(case,engine);value['center_rows'][80]=bad
            with self.subTest(engine=engine,bad=bad),self.assertRaises(ValueError):reference.admit_frame(case,value,engine)

    def test_midframe_current_cr_zero_is_not_treated_as_latched_burst(self):
        case=reference.cases()[-1]
        for engine in ('beetle','gear'):
            for markers in (None,{},dict(disabled=0,reenabled=28),dict(disabled=28,reenabled=0),
                            dict(disabled=True,reenabled=28),dict(disabled=10,reenabled=28)):
                value=frame(case,engine);value['markers']=markers
                with self.subTest(engine=engine,markers=markers),self.assertRaises(ValueError):
                    reference.admit_frame(case,value,engine)
        for engine,bad in (('beetle',0x07E0),('gear',[0,0,0])):
            value=frame(case,engine);value['center_rows'][180]=bad
            with self.subTest(engine=engine),self.assertRaises(ValueError):reference.admit_frame(case,value,engine)

    def test_complete_row_types_and_geometry_are_required(self):
        case=reference.cases()[2]
        for key,value in (('width',255),('height',242),('center_rows',[0xF800]*242),('center_rows',[False]*243)):
            changed=frame(case,'beetle');changed[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):reference.admit_frame(case,changed,'beetle')
        bad=frame(case,'gear');bad['center_rows'][80]=[255,0,False]
        with self.assertRaises(ValueError):reference.admit_frame(case,bad,'gear')
        with self.assertRaises(ValueError):reference.admit_frame(case,frame(case,'gear'),'unknown')

    def test_two_disagreements_remain_visible_and_other_cases_cannot_drift(self):
        cases=reference.cases()
        beetle=[dict(case=c,beetle=frame(c,'beetle'))for c in cases]
        gear=[dict(case=c,frame=frame(c,'gear'))for c in cases]
        report=reference.compare_frames(beetle,gear)
        self.assertFalse(report['all_cases_equal'])
        self.assertEqual([x['case']for x in report['disagreements']],['stable-00','stable-40'])
        self.assertEqual(report['active_probe_case_agreement'],3)
        wrong=copy.deepcopy(gear);wrong[-1]['frame']['center_rows'][80]=[0,255,0]
        with self.assertRaises(ValueError):reference.compare_frames(beetle,wrong)
        with self.assertRaises(ValueError):reference.compare_frames(beetle[:-1],gear)


if __name__=='__main__':unittest.main()
