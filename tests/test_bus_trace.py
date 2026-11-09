"""Authored software-access contracts and adversarial first-difference controls."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from pcerecomp import bus_trace as bus


def records(name='authored-A'):
    initial = dict(pc=0xE000, a=0, x=1, y=2, sp=255, p=0x34,
        mpr=[0,248,2,3,4,5,6,7], physical_pc=0xE000,
        clock_divisor=3, ticks=9, wram_sha256='a'*64)
    first = copy.deepcopy(initial)
    first.update(pc=0xE003, physical_pc=0xE003, a=7, ticks=15)
    second = copy.deepcopy(first)
    second.update(pc=0xE004, physical_pc=0xE004, sp=254, ticks=24, wram_sha256='b'*64)
    header = dict(type='header', schema=1, format=bus.FORMAT,
        engine=dict(name=name, revision='1'*40, source_sha256='2'*64, binary_sha256='3'*64),
        fixture_sha256='4'*64, case='authored.stack-01', clock='master-ticks',
        profile=bus.PROFILE, phase=bus.PHASE, call_model='aggregate',
        capabilities={key:key in ('mapped','fixed_vdc','data','irq','tier_counters')
                      for key in bus.CAPABILITIES},
        limits=dict(calls=2, events=10, retired=2, wall_ms=1000))
    def begin(ordinal, state, encoded):
        return dict(type='call-begin', ordinal=ordinal, entry=copy.deepcopy(state),
                    source=bus.source_identity(state['pc'], state['mpr'], encoded))
    def access(ordinal, call, ticks, direction, logical, value):
        return dict(type='access', ordinal=ordinal, call_ordinal=call, ticks=ticks,
            direction=direction, phase=direction+'-return', space='mapped', logical=logical,
            mpr=list(initial['mpr']), physical=(initial['mpr'][logical>>13]<<13)|(logical&8191),
            value=value, purpose=None, dummy=None)
    def end(ordinal, state):
        return dict(type='call-end', ordinal=ordinal, kind='execution-call', state=state,
                    retired=1, native=0, interpreted=1, irq=0)
    return [header, dict(type='initial', state=initial), begin(1,initial,b'\xad\x00\x20'),
        access(1,1,12,'read',0x2000,7), end(1,first), begin(2,first,b'\x48'),
        access(2,2,18,'write',0x21FF,7), end(2,second),
        dict(type='final',calls=2,retired=2,events=2,stop='call-limit',complete=True,
             state=copy.deepcopy(second))]


def parsed(rows=None):
    return bus.parse_trace(bus.encode_records(records() if rows is None else rows))


class BusTraceTests(unittest.TestCase):
    def assert_bad(self, rows):
        with self.assertRaises(ValueError):
            parsed(rows)

    def cli(self, argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = bus.main([str(value) for value in argv])
        return code, out.getvalue(), err.getvalue()

    def test_source_identity_payload_independently_assembled(self):
        # Includes wrap from $FFFF to $0000, where a different MPR applies.
        mapping = [0xF8,1,2,3,4,5,6,7]
        payload = (b'pce-bus-source-1\0\xff\xff' + bytes(mapping) + b'\x02' +
                   b'\xff\xff\x00\x00\xA9' + b'\x00\x00\x1f\x00\x42')
        identity = bus.source_identity(65535,mapping,b'\xA9\x42')
        self.assertEqual(identity,dict(kind='dispatch-entry-candidate',length=2,
                                      sha256=hashlib.sha256(payload).hexdigest()))
        changed = list(mapping); changed[3] ^= 1
        self.assertNotEqual(identity,bus.source_identity(65535,changed,b'\xA9\x42'))
        self.assertNotEqual(identity,bus.source_identity(65535,mapping,b'\xA9\x43'))
        for pc,mpr,encoded in [(True,mapping,b'\xea'),(0,[False]*8,b'\xea'),
                               (0,mapping,b''),(0,mapping,b'12345678'),(0,mapping,[234])]:
            with self.subTest(pc=pc,mpr=mpr,encoded=encoded), self.assertRaises(ValueError):
                bus.source_identity(pc,mpr,encoded)

    def test_complete_trace_load_and_code_free_identity(self):
        raw = bus.encode_records(records())
        trace = bus.parse_trace(raw)
        self.assertEqual(trace.sha256,hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(trace.calls),2)
        self.assertEqual(len(trace.events),2)
        self.assertEqual(trace.calls[0]['entry']['source']['length'],3)
        self.assertNotIn('encoded',trace.calls[0]['entry']['source'])
        self.assertNotIn('mpr_latch',trace.initial)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace';path.write_bytes(raw)
            self.assertEqual(bus.load_trace(path),trace)

    def test_exact_equal_preserves_independent_engine_and_limits(self):
        left,right=records(),records('authored-B')
        right[0]['engine'].update(revision='5'*40,source_sha256='6'*64,binary_sha256='7'*64)
        right[0]['limits']['wall_ms']=2000
        result=bus.compare_traces(parsed(left),parsed(right))
        self.assertTrue(result['equal'])
        self.assertEqual(result['matched_events'],2)
        self.assertIsNone(result['first_difference'])
        self.assertNotEqual(result['expected_engine'],result['actual_engine'])
        self.assertNotEqual(result['execution_limits']['expected'],result['execution_limits']['actual'])

    def test_same_pc_changed_encoded_source_is_not_equal(self):
        rows=records();rows[2]['source']=bus.source_identity(0xE000,rows[2]['entry']['mpr'],b'\xad\x01\x20')
        result=bus.compare_traces(parsed(),parsed(rows))
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference']['field'],'record.source.sha256')
        self.assertEqual(result['first_difference']['ordinal'],1)

    def test_access_mapping_is_actual_access_time_not_entry_mpr(self):
        rows=records();rows[3]['mpr'][1]=249;rows[3]['physical']=0x1F2000
        self.assertEqual(parsed(rows).events[0]['mpr'][1],249)
        result=bus.compare_traces(parsed(),parsed(rows))
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference']['field'],'record.mpr')
        rows[3]['physical']=0x1F0000
        self.assert_bad(rows)

    def test_direction_value_phase_and_timing_are_observed(self):
        for field,value,expected in [('value',8,'record.value'),('ticks',13,'record.ticks'),
                                      ('direction','write','record.direction')]:
            with self.subTest(field=field):
                rows=records();rows[3][field]=value
                if field=='direction':rows[3]['phase']='write-return'
                result=bus.compare_traces(parsed(),parsed(rows))
                self.assertFalse(result['equal'])
                self.assertEqual(result['first_difference']['field'],expected)
                self.assertEqual(result['first_difference']['ordinal'],2)
        rows=records();rows[3]['phase']='write-return';self.assert_bad(rows)

    def test_equal_tick_repeated_access_order_is_not_sorted_or_coalesced(self):
        rows=records();extra=copy.deepcopy(rows[3]);extra.update(ordinal=2,value=8)
        rows.insert(4,extra);rows[7]['ordinal']=3;rows[-1]['events']=3
        other=copy.deepcopy(rows);other[3]['value'],other[4]['value']=8,7
        result=bus.compare_traces(parsed(rows),parsed(other))
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference']['expected'],7)
        self.assertEqual(len(parsed(rows).events),3)

    def test_structural_correspondence_keeps_real_timing_difference_failed(self):
        rows=records();rows[3]['ticks']=13
        result=bus.compare_traces(parsed(),parsed(rows),structural=True)
        self.assertFalse(result['equal'])
        self.assertTrue(result['structural_correspondence']['matched'])
        self.assertFalse(result['structural_correspondence']['timing_equal'])
        self.assertEqual(result['structural_correspondence']['timing_differences'][0]['actual'],13)
        rows[3]['value']=8
        result=bus.compare_traces(parsed(),parsed(rows),structural=True)
        self.assertFalse(result['structural_correspondence']['matched'])

    def test_elapsed_profile_only_removes_epoch_and_retains_raw_times(self):
        rows=records()
        for row in rows:
            for field in ('state','entry'):
                if field in row:row[field]['ticks']+=90
            if row['type']=='access':row['ticks']+=90
        a,b=parsed(),parsed(rows)
        self.assertFalse(bus.compare_traces(a,b)['equal'])
        result=bus.compare_traces(a,b,profile='elapsed-origin-v1')
        self.assertTrue(result['equal'])
        self.assertEqual(result['clock_origins'],dict(expected=9,actual=99))
        rows[3]['ticks']+=1
        result=bus.compare_traces(a,parsed(rows),profile='elapsed-origin-v1')
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference']['expected_elapsed'],3)
        self.assertEqual(result['first_difference']['actual_elapsed'],4)
        self.assertEqual(result['first_difference']['actual'],103)

    def test_zero_retirement_irq_or_continuation_call_is_not_an_opcode(self):
        rows=records();final=rows.pop();entry=copy.deepcopy(final['state']);state=copy.deepcopy(entry)
        state.update(pc=0xF000,physical_pc=0xF000,ticks=45)
        rows.extend([dict(type='call-begin',ordinal=3,entry=entry,
                         source=bus.source_identity(entry['pc'],entry['mpr'],b'\xea')),
            dict(type='call-end',ordinal=3,kind='execution-call',state=state,
                 retired=0,native=0,interpreted=0,irq=1)])
        final.update(calls=3,state=copy.deepcopy(state));rows.append(final);rows[0]['limits']['calls']=3
        trace=parsed(rows)
        self.assertEqual(trace.final['calls'],3)
        self.assertEqual(trace.final['retired'],2)
        self.assertEqual(trace.calls[-1]['end']['retired'],0)
        self.assertEqual(trace.calls[-1]['entry']['source']['kind'],'dispatch-entry-candidate')

    def test_zero_clock_guard_return_is_not_given_invented_cycles(self):
        rows=records();rows=rows[:3]+[dict(type='call-end',ordinal=1,kind='execution-call',
            state=copy.deepcopy(rows[1]['state']),retired=0,native=0,interpreted=0,irq=0),
            dict(type='final',calls=1,retired=0,events=0,stop='source-mismatch',complete=False,
                 state=copy.deepcopy(rows[1]['state']))]
        trace=parsed(rows)
        self.assertEqual(trace.calls[0]['end']['state']['ticks'],9)
        result=bus.compare_traces(trace,trace)
        self.assertFalse(result['compatible'])
        self.assertFalse(result['equal'])

    def test_tier_provenance_is_not_guest_equivalence_or_unknown_equality(self):
        native=records()
        for row in native:
            if row['type']=='call-end':row.update(native=1,interpreted=0)
        result=bus.compare_traces(parsed(),parsed(native))
        self.assertTrue(result['equal'])
        self.assertFalse(result['counter_observations']['native']['equal'])
        missing=records();missing[0]['capabilities'].update(tier_counters=False,irq=False)
        for row in missing:
            if row['type']=='call-end':row.update(native=None,interpreted=None,irq=None)
        result=bus.compare_traces(parsed(),parsed(missing))
        self.assertTrue(result['equal'])
        self.assertIsNone(result['counter_observations']['native']['equal'])
        self.assertFalse(result['counter_observations']['irq']['compared'])
        self.assertFalse(result['counter_observations']['irq']['both_observed'])

    def test_observed_irq_delta_difference_is_not_ignored(self):
        rows=records();rows[4]['irq']=1
        result=bus.compare_traces(parsed(),parsed(rows))
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference']['field'],'record.irq')

    def test_named_mapped_scope_retains_calls_closure_and_capability_provenance(self):
        rows=records();rows[0]['call_model']='split'
        rows[0]['capabilities']['fixed_vdc']=False
        rows[-1]['stop']='retirement-limit'
        self.assertFalse(bus.compare_traces(parsed(),parsed(rows))['compatible'])
        result=bus.compare_traces(parsed(),parsed(rows),scope='mapped-callback-v1')
        self.assertTrue(result['equal'])
        self.assertNotEqual(result['call_models']['expected'],result['call_models']['actual'])
        self.assertNotEqual(result['closure_policies']['expected'],result['closure_policies']['actual'])
        self.assertFalse(result['observation_capabilities']['actual']['fixed_vdc'])
        rows[3]['ticks']+=1
        result=bus.compare_traces(parsed(),parsed(rows),scope='mapped-callback-v1',structural=True)
        self.assertFalse(result['equal'])
        self.assertTrue(result['structural_correspondence']['matched'])
        self.assertEqual(result['first_difference']['field'],'record.ticks')
        rows=records();rows[6].update(space='fixed-vdc',logical=None,mpr=None,physical=2)
        result=bus.compare_traces(parsed(rows),parsed(rows),scope='mapped-callback-v1')
        self.assertFalse(result['compatible'])
        self.assertFalse(result['equal'])
        with self.assertRaises(ValueError):bus.compare_traces(parsed(),parsed(),scope='ignore-io')

    def test_fixed_vdc_is_a_physical_port_without_fake_logical_mapping(self):
        rows=records();rows[6].update(space='fixed-vdc',logical=None,mpr=None,physical=2)
        self.assertEqual(parsed(rows).events[1]['physical'],2)
        for field,value in [('logical',0),('mpr',[0]*8),('physical',0x80000002),
                             ('physical',1),('direction','read')]:
            with self.subTest(field=field,value=value):
                changed=copy.deepcopy(rows);changed[6][field]=value
                if field=='direction':changed[6]['phase']='read-return'
                self.assert_bad(changed)
        rows[0]['capabilities']['fixed_vdc']=False;self.assert_bad(rows)

    def test_compatibility_requires_fixture_case_profile_phase_and_capability(self):
        for field,value in [('fixture_sha256','9'*64),('case','other'),('call_model','split')]:
            with self.subTest(field=field):
                rows=records();rows[0][field]=value
                result=bus.compare_traces(parsed(),parsed(rows))
                self.assertFalse(result['compatible'])
                self.assertEqual(result['first_difference']['field'],'header.'+field)
        rows=records();rows[0]['capabilities']['fixed_vdc']=False
        result=bus.compare_traces(parsed(),parsed(rows))
        self.assertFalse(result['compatible'])
        self.assertEqual(result['first_difference']['field'],'header.capabilities.fixed_vdc')

    def test_every_closed_record_refuses_unknown_or_missing_keys(self):
        base=records()
        for index in range(len(base)):
            for mode in ('extra','missing'):
                with self.subTest(index=index,mode=mode):
                    rows=copy.deepcopy(base)
                    if mode=='extra':rows[index]['extra']=0
                    else:del rows[index][next(key for key in rows[index] if key!='type')]
                    self.assert_bad(rows)
        for key in ('engine','capabilities','limits'):
            rows=records();rows[0][key]['extra']=0;self.assert_bad(rows)
        rows=records();rows[2]['source']['extra']=0;self.assert_bad(rows)

    def test_header_metadata_capabilities_and_limits_strict_types(self):
        mutations=[('schema',True),('format','other'),('clock','cycles'),('profile','pins'),
                   ('phase','before-read'),('call_model',[]),('case','../private')]
        for key,value in mutations:
            with self.subTest(key=key):
                rows=records();rows[0][key]=value;self.assert_bad(rows)
        for cap in bus.CAPABILITIES:
            rows=records();rows[0]['capabilities'][cap]=1;self.assert_bad(rows)
        for cap in ('fetch','purpose','dummy','idle','mpr_latch'):
            rows=records();rows[0]['capabilities'][cap]=True;self.assert_bad(rows)
        for cap in ('mapped','data'):
            rows=records();rows[0]['capabilities'][cap]=False;self.assert_bad(rows)
        for field in ('calls','events','retired','wall_ms'):
            for value in (True,0,-1,1.5,2**64):
                rows=records();rows[0]['limits'][field]=value;self.assert_bad(rows)

    def test_source_identity_keys_types_and_ranges_are_strict(self):
        for field,value in [('kind','opcode'),('length',True),('length',0),('length',8),
                             ('sha256','A'*64),('sha256','a'*63),('sha256',None)]:
            with self.subTest(field=field,value=value):
                rows=records();rows[2]['source'][field]=value;self.assert_bad(rows)

    def test_unreadable_entry_source_is_explicit_and_never_completed_equality(self):
        rows=records();rows[2]['source']=None
        self.assert_bad(rows)
        rows[-1].update(complete=False,stop='source-mismatch')
        value=parsed(rows)
        self.assertIsNone(value.calls[0]['entry']['source'])
        self.assertEqual(value.final['events'],2)
        self.assertFalse(bus.compare_traces(value,value)['equal'])
        rows[-1]['stop']='fault';self.assert_bad(rows)

    def test_state_mapping_chain_and_access_timestamp_window(self):
        for index,field,value in [(2,'pc',0xE001),(4,'physical_pc',1),(5,'a',8),
                                  (7,'ticks',17),(-1,'a',1)]:
            rows=records();target=rows[index]['entry' if index in (2,5) else 'state']
            target[field]=value;self.assert_bad(rows)
        for ticks in (True,-1,8,16,2**64):
            rows=records();rows[3]['ticks']=ticks;self.assert_bad(rows)
        for key,value in [('value',True),('value',256),('logical',65536),('mpr',[0]*7),
                          ('purpose','stack'),('dummy',False),('space','idle')]:
            rows=records();rows[3][key]=value;self.assert_bad(rows)

    def test_call_and_event_ordinals_counters_and_retirements_are_actual(self):
        for index,key,value in [(2,'ordinal',0),(2,'ordinal',True),(3,'ordinal',2),
            (3,'call_ordinal',2),(4,'ordinal',2),(4,'retired',False),(4,'native',1),
            (4,'interpreted',None),(4,'irq',None),(4,'kind','opcode'),(-1,'events',3),
            (-1,'calls',3),(-1,'retired',3),(-1,'complete',1),(-1,'stop','completed')]:
            with self.subTest(index=index,key=key,value=value):
                rows=records();rows[index][key]=value;self.assert_bad(rows)
        for key in ('calls','events','retired'):
            rows=records();rows[0]['limits'][key]=1;self.assert_bad(rows)

    def test_call_nesting_and_closure_are_required(self):
        base=records()
        for index in (1,2,3,4,5,6,7,8):
            rows=copy.deepcopy(base);del rows[index]
            if index in (3,6):rows[-1]['events']-=1
            if index in (3,6):
                # Removing an actual access is valid only if ordinals/counters
                # are deliberately rebuilt; missing ordinal is not accepted.
                if index==6:continue
            self.assert_bad(rows)
        rows=records();rows.insert(3,copy.deepcopy(rows[2]));self.assert_bad(rows)
        rows=records();rows.insert(2,copy.deepcopy(rows[3]));self.assert_bad(rows)
        rows=records();rows.append(copy.deepcopy(rows[-1]));self.assert_bad(rows)
        for length in range(len(base)):
            self.assert_bad(base[:length])

    def test_diagnostic_stop_is_preserved_and_never_completed_equality(self):
        for stop in ('wall-limit','fault','source-mismatch','cancelled'):
            rows=records();rows[-1].update(complete=False,stop=stop)
            value=parsed(rows)
            self.assertEqual(value.final['stop'],stop)
            self.assertFalse(bus.compare_traces(value,value)['equal'])
        rows=records();rows[-1].update(complete=False,stop='event-limit')
        self.assert_bad(rows)
        rows[0]['limits']['events']=2
        self.assertFalse(bus.compare_traces(parsed(rows),parsed(rows))['compatible'])
        rows=records();rows[-1]['stop']='retirement-limit';self.assertEqual(parsed(rows).final['retired'],2)

    def test_checkpoint_origin_is_exact_validated_provenance_not_current_counters(self):
        rows=records();origin=dict(sha256='f'*64,ticks=9,frame=30,native_steps=500,interpreter_steps=700)
        rows[0]['checkpoint_origin']=origin
        trace=parsed(rows)
        self.assertEqual(trace.final['retired'],2)
        self.assertEqual(bus.compare_traces(trace,trace)['checkpoint_origins']['expected'],origin)
        for key,value in [('ticks',10),('native_steps',True),('frame',-1),('sha256','A'*64),('extra',1)]:
            changed=copy.deepcopy(rows);changed[0]['checkpoint_origin'][key]=value;self.assert_bad(changed)

    def test_duplicate_nonfinite_utf8_truncation_and_unknown_input_types(self):
        raw=bus.encode_records(records())
        for data in (raw.replace(b'"schema":1',b'"schema":1,"schema":1',1),
            raw.replace(b'"value":7',b'"value":1e9999',1),
            raw.replace(b'"value":7',b'"value":NaN',1),b'\xff\n',b'\xef\xbb\xbf'+raw,
            raw[:-1],raw+b'\n',b'{}\n',b'[]\n',raw+b'{}\n'):
            with self.subTest(data=data[:45]),self.assertRaises(ValueError):bus.parse_trace(data)
        for data in ('text',bytearray(raw),None):
            with self.assertRaises(ValueError):bus.parse_trace(data)

    def test_protocol_bounds_and_unknown_options(self):
        raw=bus.encode_records(records())
        for kw in [dict(max_records=8),dict(max_line_bytes=10),dict(max_file_bytes=len(raw)-1),
                   dict(max_records=True),dict(max_records=bus.MAX_RECORDS+1),dict(unknown=1)]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):bus.parse_trace(raw,**kw)
        self.assertEqual(bus.parse_trace(raw,max_records=9,max_file_bytes=len(raw)),parsed())
        for kw in (dict(profile='ignore-timing'),dict(structural=1)):
            with self.assertRaises(ValueError):bus.compare_traces(parsed(),parsed(),**kw)

    def test_structurally_different_record_types_report_instead_of_crashing(self):
        rows=records();del rows[6];rows[-1]['events']=1
        result=bus.compare_traces(parsed(),parsed(rows),structural=True)
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference']['field'],'record.type')

    def test_cli_exit_codes_exclusive_reports_and_private_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);left=base/'left';right=base/'right';out=base/'report'
            raw=bus.encode_records(records());left.write_bytes(raw);right.write_bytes(raw)
            code,text,error=self.cli([left,right]);self.assertEqual((code,error),(0,''))
            self.assertTrue(json.loads(text)['equal'])
            rows=records();rows[3]['value']=8;right.write_bytes(bus.encode_records(rows))
            code,text,error=self.cli([left,right,'--out',out]);self.assertEqual((code,text,error),(1,'',''))
            saved=out.read_bytes();self.assertFalse(json.loads(saved)['equal'])
            for target in (out,left,right,base):
                code,text,error=self.cli([left,right,'--out',target]);self.assertEqual((code,text),(2,''))
                self.assertNotIn(directory,error)
                self.assertEqual(left.read_bytes(),raw)
            self.assertEqual(out.read_bytes(),saved)
            alias=base/'hard-link';os.link(left,alias)
            self.assertEqual(self.cli([left,right,'--out',alias])[0],2)
            self.assertEqual(left.read_bytes(),raw)
            code,text,error=self.cli([base/'missing',right]);self.assertEqual((code,text),(2,''))
            self.assertNotIn(directory,error)
            rows=records();rows[0]['case']='other';right.write_bytes(bus.encode_records(rows))
            self.assertEqual(self.cli([left,right])[0],2)


if __name__=='__main__':
    unittest.main()
