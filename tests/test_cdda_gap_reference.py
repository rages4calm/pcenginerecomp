"""Authored qualifier controls, separate from actual reference execution."""
import copy
import unittest
from pcerecomp.project import ABI
from generate_cdda_gap_fixture import LAYOUTS,cases,authored_sources
from scripts.cdda_gap_reference import qualify,expected_port_hits

def admission():
    records={};captures={};work={}
    for tier in('gear','native','interpreter'):
        rows=[]
        for case in cases():
            state=case['state'];audio_state={'idle':1,'playing':0,'paused':2,'stopped':3,'seeking':0}[state]
            logical=[1,0,0,0,0,0,1]if state=='idle'else[audio_state,10,10,609,1 if tier!='gear'or state=='seeking'else 10,0,10]
            before=dict(ticks=1000,phase=8 if state=='seeking'else 0,signals=128 if state=='seeking'else 0,
                        logical=logical,seek_deadline=3000000 if state=='seeking'else 0,event=0,event_deadline=0)
            after=copy.deepcopy(before);after['ticks']=103000
            status=message=0
            if case['kind']=='gap':
                busy=bool(case['mode'])or state=='seeking';after.update(phase=8 if busy else 7,signals=128 if busy else 216)
                if busy and state!='seeking':status=message=999
            elif case['kind']=='program':after.update(phase=8,signals=128,logical=[2 if case['mode']==0 else 0,10,10,609,1,0,10],seek_deadline=3300000)
            else:
                after.update(phase=7,signals=216)
                if tier!='gear':status=message=2
            end=copy.deepcopy(after);end['ticks']=4000000
            if status!=999:end.update(phase=0,signals=0,seek_deadline=0)
            rows.append(dict(case=case['id'],kind=case['kind'],before=before,after=after,settled=end,status=status,message=message))
        records[tier]=rows;work[tier]=dict(schema=1,tier=tier,divisor=3,cases=len(cases()),port_calls=sum(expected_port_hits().values()))
        if tier!='gear':
            observations=authored_sources()
            for row in observations:row.update(native_hits=expected_port_hits()[row['pc']]if tier=='native'else 0,interpreted_hits=expected_port_hits()[row['pc']]if tier=='interpreter'else 0)
            captures[tier]=dict(schema=1,runtime_abi=ABI,capacity=16,complete=True,dropped_instructions=0,unreadable_instructions=0,retired_instructions=sum(expected_port_hits().values()),observations=observations)
    return dict(layout=dict(LAYOUTS[0]),speed=3,records=records,captures=captures,work=work)

class CddaGapReferenceTests(unittest.TestCase):
    def test_authored_matrix_has_all_gap_state_mode_controls(self):
        self.assertEqual(len(cases()),24)
        self.assertEqual(sum(c['kind']=='gap'for c in cases()),20)
        self.assertEqual({(x['kind'],x['first'])for x in LAYOUTS},{('virtual','data'),('stored','data'),('virtual','audio'),('stored','audio')})
        value=qualify(**admission());self.assertEqual(value['native'],149612)
        self.assertEqual(expected_port_hits(),{0x2800:68,0x2808:584,0x2810:99696,0x2818:49264})

    def test_gap_preservation_phase_completion_and_typed_rows_are_checked(self):
        for where,key,value in [('after','logical',[1,8,8,609,0,0,8]),('after','seek_deadline',42),('after','phase',7),('settled','phase',0),('after','ticks',True)]:
            data=admission();data['records']['native'][2][where][key]=value
            with self.subTest(where=where,key=key),self.assertRaises(ValueError):qualify(**data)
        data=admission();data['records']['gear'][0]['status']=False
        with self.assertRaises(ValueError):qualify(**data)

    def test_actual_full_source_and_per_site_counts_are_required(self):
        for key,value in [('pc',0x2801),('mpr',[255,248,129,129,247,255,247,0]),('physical',[0x1F0800,0x1F0801,0x1F0803]),('data',[0x8D,1,0x18]),('native_hits',69)]:
            data=admission();data['captures']['native']['observations'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualify(**data)
        data=admission();data['work']['gear']['port_calls']-=1
        with self.assertRaises(ValueError):qualify(**data)
        for value in(13,True,ABI+1):
            data=admission();data['captures']['native']['runtime_abi']=value
            with self.subTest(abi=value),self.assertRaises(ValueError):qualify(**data)

    def test_known_leadout_disagreement_is_retained(self):
        data=admission();index=next(i for i,c in enumerate(cases())if c['kind']=='leadout')
        data['records']['native'][index]['status']=0
        with self.assertRaises(ValueError):qualify(**data)

    def test_reachable_setup_is_not_arbitrary_injected_audio_state(self):
        for tier in('gear','native','interpreter'):
            data=admission();data['records'][tier][4]['before']['logical'][4]=99
            with self.subTest(tier=tier),self.assertRaises(ValueError):qualify(**data)

    def test_execution_and_layout_metadata_require_strict_integer_types(self):
        for key,value in [('schema',True),('divisor',3.0),('cases',24.0),('port_calls',149612.0)]:
            data=admission();data['work']['native'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualify(**data)
        for key in('start','leadout'):
            data=admission();data['layout'][key]=float(data['layout'][key])
            with self.subTest(key=key),self.assertRaises(ValueError):qualify(**data)

if __name__=='__main__':unittest.main()
