"""Authored validator controls; these rows are not emulator execution evidence."""
import copy
import unittest
from scripts import vdc_latch_checkpoint_reference as reference


def admission(case):
    rows=[]
    for offset in reference.OFFSETS:
        ticks=case['write']+offset;edge=case['edge'];mwr=edge.startswith('mwr-');queue=case['queue']
        row=[0]*38;row[:4]=[ticks,ticks%reference.LINE,(ticks//reference.LINE)%262,(ticks//reference.LINE)%262]
        h=ticks%reference.LINE;line=(ticks//reference.LINE)%262
        row[4]=3 if h<96 else 0 if h<192 else 1 if h<1152 else 2
        row[5]=0 if line<16 or line==16 and h<1092 or line==261 and h>=1092 else 1 if line<256 or line==256 and h<1092 else 2 if line<258 or line==258 and h<1092 else 3
        row[6:11]=[128 if mwr or edge=='burst-frame'else 192,17 if mwr else 0,0 if edge=='burst-frame'else 128,0,1 if edge=='burst-frame'else 0]
        row[11:19]=[int(bool(queue&1)),int(bool(queue&2)),24 if queue&1 else 21,0,0x1900,0x1800,0x1234,0]
        row[22:]=[0 if edge=='burst-frame'else 1]*16
        if edge=='burst-frame' and (offset>reference.FRAME or case['delta']<0 and offset==reference.FRAME):row[22:]=[1]*16
        if edge=='cr-hds'and ticks>=case['latch']and case['delta']<0:row[8]=192
        if mwr and ticks>=case['latch']and case['delta']<0:row[9]=17
        if edge=='burst-frame'and ticks>=case['latch']and case['delta']<0:row[10]=0
        if offset>=4095:row[11:13]=[0,0];row[15:19]=[0x1901 if queue&1 else 0x1900,0x1801 if queue&2 else 0x1800,0x5678 if queue&1 else 0x1234,0xABCD if queue&2 else 0]
        rows.append(row)
    common=dict(case=case['id'],scope='authored validator data; no opcode retirements',native=0,interpreted=0,rows=rows)
    gear=copy.deepcopy(common)
    if case['edge']=='burst-frame':
        for offset,row in zip(reference.OFFSETS,gear['rows']):
            if not(offset>reference.FRAME or case['delta']<0 and offset==reference.FRAME):row[22:]=[256]*16
    created=copy.deepcopy(common)|dict(checkpoint_sha256='a'*64,final_payload_sha256='b'*64)
    return dict(case=case,gear=gear,created=created,resumed=copy.deepcopy(created),payload_digest='a'*64,final_digest='b'*64)


class VdcLatchCheckpointReferenceTests(unittest.TestCase):
    def test_case_schedule_is_canonical_and_strictly_typed(self):
        source=admission(reference.cases()[0])
        for field,value in [('id','invented'),('edge','other'),('delta',-2),('queue',True),('latch',source['case']['latch']+3),('write',float(source['case']['write']))]:
            bad=copy.deepcopy(source);bad['case'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):reference.qualify(**bad)
        for change in ('extra','missing'):
            bad=copy.deepcopy(source)
            if change=='extra':bad['case']['unexpected']=0
            else:bad['case'].pop('latch')
            with self.subTest(change=change),self.assertRaises(ValueError):reference.qualify(**bad)
        source=admission(next(c for c in reference.cases()if c['delta']==0))
        source['case']['delta']=False
        with self.assertRaises(ValueError):reference.qualify(**source)

    def test_all_36_authored_admissions_and_scope(self):
        cases=reference.cases();self.assertEqual(len(cases),36);self.assertEqual(len({c['id']for c in cases}),36)
        for case in cases:
            with self.subTest(case=case['id']):
                result=reference.qualify(**admission(case));self.assertEqual(result['rows'],19)
                self.assertEqual((result['native'],result['interpreted']),(0,0))

    def test_counts_types_scope_and_complete_fields_are_strict(self):
        source=admission(reference.cases()[0])
        for field,value in [('native',1),('interpreted',True),('scope','native executed'),('case','other')]:
            bad=copy.deepcopy(source);bad['created'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):reference.qualify(**bad)
        for operation in ('extra','missing','short-row','short-extent','boolean'):
            bad=copy.deepcopy(source)
            if operation=='extra':bad['gear']['invented']=0
            if operation=='missing':bad['gear'].pop('scope')
            if operation=='short-row':bad['gear']['rows'][0].pop()
            if operation=='short-extent':bad['gear']['rows'].pop()
            if operation=='boolean':bad['gear']['rows'][0][2]=True
            with self.subTest(operation=operation),self.assertRaises(ValueError):reference.qualify(**bad)

    def test_independent_clocks_latches_queue_and_pixels_refuse_corruption(self):
        for case in reference.cases():
            source=admission(case)
            for ordinal,column in [(0,0),(0,1),(0,2),(0,6),(0,7),(0,8),(0,9),(0,11),(0,12),(0,13),(0,15),(0,17),(0,22),(16,16),(16,18)]:
                bad=copy.deepcopy(source)
                # Both toolkit processes agree with a corrupted value. Gear and
                # the separate explicit literals must still catch that error.
                for engine in ('created','resumed'):bad[engine]['rows'][ordinal][column]^=1
                with self.subTest(case=case['id'],row=ordinal,col=column),self.assertRaises(ValueError):reference.qualify(**bad)

    def test_payload_digests_and_fresh_process_equality_are_bound(self):
        source=admission(reference.cases()[0])
        for key in ('payload_digest','final_digest'):
            bad=copy.deepcopy(source);bad[key]='c'*64
            with self.subTest(key=key),self.assertRaises(ValueError):reference.qualify(**bad)
        for key in ('checkpoint_sha256','final_payload_sha256'):
            bad=copy.deepcopy(source);bad['resumed'][key]='A'*64
            with self.subTest(key=key),self.assertRaises(ValueError):reference.qualify(**bad)
        bad=copy.deepcopy(source);bad['resumed']['rows'][7][20]=1
        with self.assertRaises(ValueError):reference.qualify(**bad)

    def test_declared_burst_history_allowance_is_value_and_time_bounded(self):
        case=next(c for c in reference.cases()if c['edge']=='burst-frame'and c['delta']==0)
        source=admission(case)
        result=reference.qualify(**source);self.assertEqual(len(result['declared_index_differences']),18)
        for engine,ordinal,value in [('gear',0,257),('created',0,256),('gear',18,256),('created',18,0)]:
            bad=copy.deepcopy(source);bad[engine]['rows'][ordinal][22]=value
            with self.subTest(engine=engine,row=ordinal,value=value),self.assertRaises(ValueError):reference.qualify(**bad)
        for ordinal,column in [(0,4),(0,5),(0,8),(0,10),(18,10),(18,15)]:
            bad=copy.deepcopy(source);bad['gear']['rows'][ordinal][column]^=1
            with self.subTest(row=ordinal,column=column),self.assertRaises(ValueError):reference.qualify(**bad)
