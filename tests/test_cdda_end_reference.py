"""Authored qualifier controls; these are not independent emulator evidence."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from pcerecomp.project import ABI
from generate_cdda_end_fixture import EDGES,cases,authored_sources
from scripts.cdda_end_reference import qualify,audit_admission,expected_port_hits

HZ=21477273
def edge(n):return(n*HZ+44099)//44100
def next_edge(tick):return edge(tick*44100//HZ+1)

def admission():
    records={};captures={};work={}
    for tier in('gear','native','interpreter'):
        rows=[]
        for case in cases():
            mode,end=case['mode'],case['end'];start=0 if case['state']=='paused'else 310
            before_tick=1000+case['offset'];admitted_tick=edge(before_tick*44100//HZ+210)
            ready_tick=200000 if case['state']=='paused'else admitted_tick;first=ready_tick*44100//HZ+1
            deadline=0 if tier=='gear'else edge(first+587-start);fraction=0 if tier=='gear'else 48
            def point(tick,frame,state=0,current=10,stop=end,dl=deadline,frac=fraction,phase=None):
                phase=(7 if state==3 and mode==2 else 0 if mode==3 else 8)if phase is None else phase
                signals=216 if phase==7 else 128 if phase==8 else 0
                value=0 if not frame else((current-10)*31+(frame-1)*17)%60000-30000
                return dict(frame=frame,left=value,right=-value,next_edge=next_edge(tick),delay=0,sector_deadline=dl,sector_fraction=frac,
                            raw=dict(ticks=tick,phase=phase,signals=signals,logical=[state,10,current,stop,10 if tier=='gear'else 1,{1:1,2:2,3:0}[mode],current],seek_deadline=0,event=0,event_deadline=0))
            before=point(before_tick,0 if case['state']=='paused'else 100,state=2 if case['state']=='paused'else 0,stop=609,phase=0)
            admitted=point(admitted_tick,start);ready=point(ready_tick,start)
            if case['state']=='paused':admitted['delay']=ready_tick-admitted_tick
            frame=start;sector=10;finished=False;control_state=0;control_sector=10;held=0;last_latch=0;right_latch=False
            def clock(tick):
                nonlocal deadline,fraction,control_state,control_sector
                while deadline and deadline<=tick:
                    control_sector+=1
                    if control_sector>end:
                        if mode==1:control_sector=10
                        else:control_state=3;deadline=0;break
                    fraction+=48;delta=286363
                    if fraction>=75:fraction-=75;delta+=1
                    deadline+=delta
            edges=[]
            for i in range(EDGES):
                tick=edge(first+i);pre_frame=frame
                clock(tick-1);pre_state=(3 if finished else 0)if tier=='gear'else control_state
                value=0 if finished else((sector-10)*31+frame*17)%60000-30000
                if not finished:
                    frame+=1
                    if frame==588:
                        frame=0
                        if sector>=end:
                            if mode==1:sector=10
                            else:finished=True
                        else:sector+=1
                clock(tick)
                state=(3 if finished else 0)if tier=='gear'else control_state
                current=(max(10,end)+1 if finished else sector)if tier=='gear'else control_sector
                phase=7 if state==3 and mode==2 else 0 if mode==3 else 8;signals=216 if phase==7 else 128 if phase==8 else 0
                if tick-last_latch>=700:last_latch=tick;right_latch=not right_latch;held=(-value if right_latch else value)&65535
                edges.append([tick,frame,value,-value,state,current,phase,signals,held,pre_state,pre_frame])
            settled=point(edges[-1][0]+45,frame,state,current,dl=deadline,frac=fraction)
            rows.append(dict(case=case['id'],before=before,admitted=admitted,ready=ready,edges=edges,settled=settled))
        records[tier]=rows;work[tier]=dict(schema=1,tier=tier,divisor=3,cases=len(cases()),port_calls=sum(expected_port_hits().values()))
        if tier!='gear':
            observations=authored_sources()
            for item in observations:item.update(native_hits=expected_port_hits()[item['pc']]if tier=='native'else 0,interpreted_hits=expected_port_hits()[item['pc']]if tier=='interpreter'else 0)
            captures[tier]=dict(schema=1,runtime_abi=ABI,capacity=16,complete=True,dropped_instructions=0,unreadable_instructions=0,retired_instructions=work[tier]['port_calls'],observations=observations)
    return dict(speed=3,records=records,captures=captures,work=work)

class CddaEndReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.good=admission()

    def test_matrix_and_actual_translated_port_counts(self):
        self.assertEqual(len(cases()),36)
        self.assertEqual({(c['state'],c['end'],c['mode'],c['offset'])for c in cases()},
                         {(state,end,mode,phase)for state in('paused','playing')for end in(9,10,11)for mode in(1,2,3)for phase in(0,244)})
        result=qualify(**self.good);self.assertEqual(result['native'],365670)
        self.assertEqual(expected_port_hits(),{0x2800:126,0x2808:1116,0x2810:150096,0x2818:73932,0x2820:46800,0x2828:46800,0x2830:46800})

    def test_written_reloaded_pcm_cursor_clock_latch_and_controller_negative_copies(self):
        # Every individual raw field has an independently checked consequence.
        with TemporaryDirectory()as temporary:
            for column,bad in enumerate((1,2,0,0,3,42,0,0,0,3,42)):
                data=copy.deepcopy(self.good);data['records']['gear'][0]['edges'][0][column]=bad
                path=Path(temporary)/f'edge-{column}.json';path.write_text(json.dumps(data),encoding='utf8')
                with self.subTest(column=column),self.assertRaises(ValueError):audit_admission(path)

    def test_written_reloaded_source_and_metadata_negative_copies(self):
        mutations=[('pc',0x2801),('mpr',[255,248,129,129,247,255,247,0]),('physical',[0x1F0800,0x1F0801,0x1F0803]),('data',[0x8D,1,0x18]),('native_hits',999)]
        with TemporaryDirectory()as temporary:
            for key,bad in mutations:
                data=copy.deepcopy(self.good);data['captures']['native']['observations'][0][key]=bad
                path=Path(temporary)/(key+'.json');path.write_text(json.dumps(data),encoding='utf8')
                with self.subTest(key=key),self.assertRaises(ValueError):audit_admission(path)
        for key,bad in(('schema',True),('divisor',12),('cases',35),('port_calls',365669)):
            data=copy.deepcopy(self.good);data['work']['gear'][key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):qualify(**data)
        for abi in(ABI-1,ABI+1,True):
            data=copy.deepcopy(self.good);data['captures']['native']['runtime_abi']=abi
            with self.subTest(abi=abi),self.assertRaises(ValueError):qualify(**data)

    def test_admission_has_real_setup_and_current_sector_remainder(self):
        for path,bad in((('ready','frame'),588),(('before','frame'),101),(('admitted','delay'),True)):
            data=copy.deepcopy(self.good);data['records']['gear'][0][path[0]][path[1]]=bad
            with self.subTest(path=path),self.assertRaises(ValueError):qualify(**data)
        data=copy.deepcopy(self.good);data['records']['gear'][0]['admitted']['raw']['logical'][3]=10
        with self.assertRaises(ValueError):qualify(**data)
        data=copy.deepcopy(self.good);data['records']['native'][0]['ready']['sector_deadline']=1
        with self.assertRaises(ValueError):qualify(**data)

if __name__=='__main__':unittest.main()
