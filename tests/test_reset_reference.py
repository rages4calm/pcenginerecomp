import copy
import unittest
from scripts import reset_reference as reference


class ResetReferenceTests(unittest.TestCase):
    def test_authored_vectors_and_three_entry_programs(self):
        rom=reference.authored_rom()
        self.assertEqual(len(rom),262144)
        self.assertEqual(rom[8190:8192],b'\x00\xe0')
        self.assertEqual(rom[:70],rom[256:326])
        self.assertEqual(rom[:70],rom[4096:4166])
        self.assertEqual(rom[:14],bytes.fromhex('78 D8 A9 FF 53 01 A9 F8 53 02 A2 FF 9A D4'))

    def test_fixture_scope_and_finite_accounting(self):
        cases=reference.plans();text,spans=reference.serialize(cases)
        self.assertEqual(len(cases),38)
        self.assertEqual(sum(span['records'] for span in spans),29824)
        boots=[c for c in cases if c['id'].startswith('boot-')]
        self.assertEqual(len(boots),36)
        self.assertEqual({c['operations'][0][4] for c in boots},{0,165,255})
        self.assertEqual({c['operations'][0][3] for c in boots},{0xE000,0xE100,0xF000})
        self.assertNotIn('C:\\',text)

    def test_validator_rejects_bool_and_schema_drift(self):
        spans=[dict(records=1,start=0,id='negative')]
        good=[dict(kind='memory',values=[0,8191,255])]
        self.assertEqual(reference.validate(good,spans),good)
        for bad in ([dict(kind='memory',values=[0,8191,True])],
                    [dict(kind='memory',values=[0,8192,255])],
                    [dict(kind='memory',values=[255,0,255])],
                    [dict(kind='memory',values=[0,0,256])],
                    [dict(kind='memory',values=[0,0,0],extra=0)],[]):
            with self.subTest(bad=bad),self.assertRaises(ValueError):reference.validate(bad,spans)

    def test_speed_difference_is_specific_and_cumulative(self):
        spans=[dict(records=3,start=0,id='speed')]
        base=[0xE000,0,0,0,0,4,12,0,*([0]*8),0,255,0,0,0,0,0]
        gear=[dict(kind='cpu',values=list(base)) for _ in range(3)]
        gear[1]['values'][6:8]=[3,9]
        gear[2]['values'][6:8]=[3,15]
        tool=copy.deepcopy(gear)
        tool[1]['values'][7]=27;tool[2]['values'][7]=33
        mismatch,changes=reference.compare(tool,gear,spans)
        self.assertIsNone(mismatch)
        self.assertEqual(changes,[dict(case='speed',record=1,entry_divisor=12,next_divisor=3,tool_minus_gear_ticks=18,cumulative_difference=18)])
        tool[2]['values'][7]+=1
        self.assertEqual(reference.compare(tool,gear,spans)[0]['fields'],['ticks'])

    def test_register_mismatch_is_never_hidden_by_clock_projection(self):
        spans=[dict(records=1,start=0,id='register')]
        values=[0xE000,0,0,0,0,4,12,0,*([0]*8),0,255,0,0,0,0,0]
        gear=[dict(kind='cpu',values=values)];tool=copy.deepcopy(gear)
        tool[0]['values'][1]=1
        self.assertEqual(reference.compare(tool,gear,spans)[0]['fields'],['a'])

    def test_unknown_timing_delta_is_not_accepted(self):
        spans=[dict(records=1,start=0,id='no-transition')]
        values=[0xE000,0,0,0,0,4,12,0,*([0]*8),0,255,0,0,0,0,0]
        gear=[dict(kind='cpu',values=values)];tool=copy.deepcopy(gear);tool[0]['values'][7]=18
        self.assertEqual(reference.compare(tool,gear,spans)[0]['fields'],['ticks'])


if __name__=='__main__':unittest.main()
