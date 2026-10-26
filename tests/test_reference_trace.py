"""Authored trace contracts, malformed receipts and first-divergence checks."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.reference_trace import (MAX_FILE_BYTES, MAX_LINE_BYTES, MAX_RECORDS,
    STATE_FIELDS, compare_traces, load_trace, main, parse_trace)


def records(name='authored-A', *, unavailable=False):
    initial = dict(pc=0xE000, a=0, x=1, y=2, sp=255, p=0x34,
        mpr=[0,248,2,3,4,5,6,7], mpr_latch=None if unavailable else 0xA7,
        physical_pc=0xE000, clock_divisor=3, ticks=9, wram_sha256='a'*64)
    first = copy.deepcopy(initial)
    first.update(pc=0xE002, physical_pc=0xE002, a=8, ticks=15)
    second = copy.deepcopy(first)
    second.update(pc=0xE004, physical_pc=0x10004, ticks=30)
    second['mpr'][7] = 8
    return [dict(type='header', schema=1, format='pce-cpu-trace-1',
            engine=dict(name=name,revision='1'*40,source_sha256='2'*64,binary_sha256='3'*64),
            fixture_sha256='4'*64, case='authored.TAM-01', clock='master-ticks',
            phase='instruction-boundary', unavailable_fields=['mpr_latch'] if unavailable else []),
        dict(type='initial',state=initial),
        dict(type='instruction',ordinal=1,entry_pc=0xE000,entry_mpr=list(initial['mpr']),state=first),
        dict(type='instruction',ordinal=2,entry_pc=0xE002,entry_mpr=list(first['mpr']),state=second),
        dict(type='final',executed=2,stop='instruction-limit',complete=True)]


def encoded(value):
    return b''.join(json.dumps(row,separators=(',',':')).encode('utf-8')+b'\n' for row in value)


def trace(value=None):
    return parse_trace(encoded(records() if value is None else value))


class ReferenceTraceTests(unittest.TestCase):
    def test_complete_trace_and_fresh_file_loader(self):
        data=encoded(records())
        value=parse_trace(data)
        self.assertEqual(value.sha256,hashlib.sha256(data).hexdigest())
        self.assertEqual(value.initial['p'],0x34)  # Raw B/T bits must survive.
        self.assertEqual(value.instructions[-1]['state']['mpr'][7],8)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'authored.jsonl';path.write_bytes(data)
            self.assertEqual(load_trace(path),value)

    def test_identical_state_different_engine_identities_remain_visible(self):
        a,b=records(),records('authored-B')
        b[0]['engine'].update(revision='5'*40,source_sha256='6'*64,binary_sha256='7'*64)
        result=compare_traces(trace(a),trace(b))
        self.assertTrue(result['equal'])
        self.assertTrue(result['initial_matched'])
        self.assertEqual(result['matched_instructions'],2)
        self.assertIsNone(result['first_difference'])
        self.assertNotEqual(result['expected_engine'],result['actual_engine'])
        self.assertEqual(result['checked_state_fields'],list(STATE_FIELDS))
        self.assertEqual(result['unchecked_state_fields'],[])

    def test_initial_seed_difference_is_ordinal_zero_without_normalization(self):
        changed=records();changed[1]['state']['a']=99
        result=compare_traces(trace(),trace(changed))
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference'],dict(ordinal=0,field='state.a',expected=0,actual=99))
        self.assertFalse(result['initial_matched'])
        self.assertEqual(result['matched_instructions'],0)

    def test_first_instruction_difference_and_matched_prefix(self):
        changed=records();changed[3]['state']['wram_sha256']='b'*64
        result=compare_traces(trace(),trace(changed))
        self.assertEqual(result['matched_instructions'],1)
        self.assertEqual(result['first_difference'],dict(ordinal=2,field='state.wram_sha256',expected='a'*64,actual='b'*64))

    def test_every_observed_state_field_participates_in_exact_comparison(self):
        for field in STATE_FIELDS:
            with self.subTest(field=field):
                changed=records();state=changed[3]['state']
                if field=='mpr':
                    state['mpr'][3]^=1
                elif field=='pc':
                    state['pc']+=1;state['physical_pc']+=1
                elif field=='physical_pc':
                    state['mpr'][7]^=1;state['physical_pc']^=8192
                elif field=='clock_divisor':state[field]=12
                elif field=='wram_sha256':state[field]='b'*64
                else:state[field]^=1
                result=compare_traces(trace(),trace(changed))
                self.assertFalse(result['equal'])
                self.assertEqual(result['first_difference']['ordinal'],2)

    def test_different_extent_reports_first_absent_instruction(self):
        shorter=records();del shorter[3];shorter[-1]['executed']=1
        result=compare_traces(trace(),trace(shorter))
        self.assertEqual(result['matched_instructions'],1)
        self.assertEqual(result['first_difference'],dict(ordinal=2,field='instruction.present',expected=True,actual=False))

    def test_case_or_fixture_mismatch_is_incompatible(self):
        for field,value in [('case','other-case'),('fixture_sha256','b'*64)]:
            with self.subTest(field=field):
                changed=records();changed[0][field]=value
                result=compare_traces(trace(),trace(changed))
                self.assertFalse(result['compatible'])
                self.assertEqual(result['first_difference']['field'],'header.'+field)
                self.assertIsNone(result['first_difference']['ordinal'])

    def test_null_latch_is_explicit_and_exact_comparison_does_not_hide_it(self):
        unavailable=trace(records('beetle-authored',unavailable=True))
        result=compare_traces(trace(),unavailable)
        self.assertFalse(result['equal'])
        self.assertEqual(result['first_difference'],dict(ordinal=0,field='state.mpr_latch',expected=167,actual=None))
        self.assertNotIn('mpr_latch',result['checked_state_fields'])
        self.assertEqual(result['unchecked_state_fields'][0]['field'],'mpr_latch')

    def test_architectural_profile_excludes_only_latch_with_explicit_reason(self):
        result=compare_traces(trace(),trace(records(unavailable=True)),profile='architectural-v1')
        self.assertTrue(result['equal'])
        self.assertEqual(result['comparison_state_fields'],[field for field in STATE_FIELDS if field!='mpr_latch'])
        self.assertEqual(result['unchecked_state_fields'][0]['field'],'mpr_latch')
        self.assertIn('no TAM/TMA latch parity',result['unchecked_state_fields'][0]['reason'])
        changed=records(unavailable=True);changed[3]['state']['p']^=16
        result=compare_traces(trace(),trace(changed),profile='architectural-v1')
        self.assertEqual(result['first_difference']['field'],'state.p')
        changed=records(unavailable=True);changed[3]['state']['ticks']+=3
        result=compare_traces(trace(),trace(changed),profile='architectural-v1')
        self.assertEqual(result['first_difference']['field'],'state.ticks')

    def test_both_unavailable_do_not_claim_latch_value_evidence(self):
        result=compare_traces(trace(records(unavailable=True)),trace(records(unavailable=True)))
        self.assertTrue(result['equal'])
        self.assertNotIn('mpr_latch',result['checked_state_fields'])
        self.assertTrue(result['unchecked_state_fields'])

    def test_elapsed_profile_preserves_raw_origins_and_excludes_only_epoch_offset(self):
        changed=records(unavailable=True)
        for row in changed[1:-1]:row['state']['ticks']+=100
        actual=trace(changed)
        self.assertEqual(compare_traces(trace(),actual)['first_difference']['ordinal'],0)
        self.assertEqual(compare_traces(trace(),actual,profile='architectural-v1')['first_difference']['field'],'state.ticks')
        result=compare_traces(trace(),actual,profile='architectural-elapsed-v1')
        self.assertTrue(result['equal'])
        self.assertEqual(result['clock_origins'],dict(expected=9,actual=109))
        self.assertEqual(result['clock_comparison_policy'],'elapsed-from-initial-state')
        self.assertEqual(actual.initial['ticks'],109)
        self.assertEqual(actual.instructions[-1]['state']['ticks'],130)
        self.assertEqual(result['checked_state_fields'],[field for field in STATE_FIELDS if field!='mpr_latch'])

    def test_elapsed_profile_still_reports_instruction_timing_and_speed_differences(self):
        changed=records(unavailable=True)
        for row in changed[1:-1]:row['state']['ticks']+=100
        changed[3]['state']['ticks']+=3
        result=compare_traces(trace(),trace(changed),profile='architectural-elapsed-v1')
        self.assertEqual(result['matched_instructions'],1)
        self.assertEqual(result['first_difference'],dict(ordinal=2,field='state.ticks',expected=30,
            actual=133,expected_elapsed=21,actual_elapsed=24))
        changed[3]['state']['ticks']-=3;changed[3]['state']['clock_divisor']=12
        result=compare_traces(trace(),trace(changed),profile='architectural-elapsed-v1')
        self.assertEqual(result['first_difference']['field'],'state.clock_divisor')

    def test_elapsed_profile_does_not_hide_initial_register_seed_differences(self):
        changed=records(unavailable=True);changed[1]['state']['p']^=4
        result=compare_traces(trace(),trace(changed),profile='architectural-elapsed-v1')
        self.assertEqual(result['first_difference']['ordinal'],0)
        self.assertEqual(result['first_difference']['field'],'state.p')

    def test_unavailable_declaration_and_values_must_match(self):
        for unavailable,value in [(False,None),(True,0)]:
            bad=records(unavailable=unavailable);bad[1]['state']['mpr_latch']=value
            with self.subTest(unavailable=unavailable),self.assertRaises(ValueError):trace(bad)
        for value in [['ticks'],['mpr_latch','mpr_latch'],None,'mpr_latch']:
            bad=records();bad[0]['unavailable_fields']=value
            with self.assertRaises(ValueError):trace(bad)

    def test_noncontiguous_ordinals_and_final_count_are_rejected(self):
        for ordinal in (0,1,3,True,2.0):
            bad=records();bad[3]['ordinal']=ordinal
            with self.subTest(ordinal=ordinal),self.assertRaises(ValueError):trace(bad)
        for count in (0,1,3,True,2.0):
            bad=records();bad[-1]['executed']=count
            with self.subTest(count=count),self.assertRaises(ValueError):trace(bad)

    def test_entry_state_chain_requires_full_pc_and_mapping(self):
        for key in ('entry_pc','entry_mpr'):
            bad=records()
            if key=='entry_pc':bad[3][key]+=1
            else:bad[3][key][0]^=1
            with self.subTest(key=key),self.assertRaises(ValueError):trace(bad)

    def test_clock_regression_and_zero_elapsed_instruction_are_rejected(self):
        for ticks in (0,9,True,15.0,2**64):
            bad=records();bad[2]['state']['ticks']=ticks
            with self.subTest(ticks=ticks),self.assertRaises(ValueError):trace(bad)

    def test_physical_pc_must_follow_mapping_and_wrap(self):
        bad=records();bad[3]['state']['physical_pc']=0xE004
        with self.assertRaises(ValueError):trace(bad)
        value=records();state=value[3]['state'];state.update(pc=0,physical_pc=0)
        self.assertEqual(trace(value).instructions[-1]['state']['pc'],0)

    def test_hash_revision_and_case_validation(self):
        for field,invalid in [('revision','a'*39),('revision','G'*40),
                              ('source_sha256','a'*63),('binary_sha256','A'*64),
                              ('source_sha256',True)]:
            bad=records();bad[0]['engine'][field]=invalid
            with self.subTest(field=field,invalid=invalid),self.assertRaises(ValueError):trace(bad)
        for invalid in ('../private','space case','é','', 'a'*97):
            bad=records();bad[0]['case']=invalid
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):trace(bad)
        for field,invalid in [('fixture_sha256','z'*64),('schema',True),('clock','cpu-cycles'),('phase','before-opcode')]:
            bad=records();bad[0][field]=invalid
            with self.assertRaises(ValueError):trace(bad)

    def test_integer_fields_reject_booleans_floats_and_ranges(self):
        for field,invalid in [('a',True),('x',-1),('y',256),('sp',1.0),('p',None),
                              ('pc',65536),('physical_pc',2**21),('mpr_latch',256),
                              ('clock_divisor',True),('clock_divisor',6)]:
            bad=records();bad[1]['state'][field]=invalid
            with self.subTest(field=field),self.assertRaises(ValueError):trace(bad)
        for invalid in ([0]*7,[0]*7+[True],[0]*7+[256],None):
            bad=records();bad[1]['state']['mpr']=invalid
            with self.assertRaises(ValueError):trace(bad)

    def test_unknown_missing_and_wrong_record_fields_are_rejected(self):
        for index,key in [(0,'private_path'),(1,'registers'),(2,'opcode_bytes'),(4,'error')]:
            bad=records();bad[index][key]=0
            with self.subTest(index=index),self.assertRaises(ValueError):trace(bad)
        for field in STATE_FIELDS:
            bad=records();del bad[1]['state'][field]
            with self.subTest(field=field),self.assertRaises(ValueError):trace(bad)
        bad=records();bad[0]['engine']['path']='private'
        with self.assertRaises(ValueError):trace(bad)

    def test_truncated_wrong_order_and_postfinal_records_are_rejected(self):
        source=records()
        for bad in ([],source[:1],source[:2],source[:-1],source[1:],
                    [source[0],source[2],source[-1]],source+[source[-1]]):
            with self.assertRaises(ValueError):trace(bad)
        for field,value in [('complete',False),('complete',1),('stop','fault')]:
            bad=records();bad[-1][field]=value
            with self.assertRaises(ValueError):trace(bad)

    def test_duplicate_keys_nan_invalid_utf8_and_blank_lines_are_rejected(self):
        data=encoded(records())
        bads=[data.replace(b'"schema":1',b'"schema":1,"schema":1',1),
              data.replace(b'"a":0',b'"a":0,"a":0',1),
              data.replace(b'"a":0',b'"a":NaN',1),
              data.replace(b'"a":0',b'"a":Infinity',1),
              b'\xff\n',data+b'\n',data[:-2],b'[]\n',b'\xef\xbb\xbf'+data]
        for bad in bads:
            with self.assertRaises(ValueError):parse_trace(bad)

    def test_total_record_line_and_byte_limits_have_exact_boundaries(self):
        data=encoded(records());line=max(map(len,data.splitlines(keepends=True)))
        self.assertEqual(parse_trace(data,max_records=5,max_line_bytes=line,max_file_bytes=len(data)),trace())
        for options in (dict(max_records=4),dict(max_line_bytes=line-1),dict(max_file_bytes=len(data)-1)):
            with self.subTest(options=options),self.assertRaises(ValueError):parse_trace(data,**options)
        for key,limit in [('max_records',MAX_RECORDS),('max_line_bytes',MAX_LINE_BYTES),('max_file_bytes',MAX_FILE_BYTES)]:
            for invalid in (True,0,-1,limit+1):
                with self.subTest(key=key,invalid=invalid),self.assertRaises(ValueError):parse_trace(data,**{key:invalid})

    def test_zero_instruction_trace_and_unterminated_final_line(self):
        source=records();source=[source[0],source[1],dict(type='final',executed=0,stop='instruction-limit',complete=True)]
        value=parse_trace(encoded(source).rstrip(b'\n'))
        self.assertEqual(len(value.instructions),0)
        self.assertTrue(compare_traces(value,value)['equal'])

    def test_unsupported_profile_and_nonvalidated_inputs_are_rejected(self):
        for profile in ('ignore-clocks','',None,True):
            with self.assertRaises(ValueError):compare_traces(trace(),trace(),profile=profile)
        with self.assertRaises(ValueError):compare_traces(records(),trace())
        with self.assertRaises(ValueError):parse_trace('not bytes')

    def test_cli_report_contains_no_input_paths_and_exit_codes_are_meaningful(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=root/'expected.jsonl';b=root/'actual.jsonl';out=root/'report.json'
            a.write_bytes(encoded(records()));b.write_bytes(encoded(records('different-engine')))
            with redirect_stdout(io.StringIO()):self.assertEqual(main([str(a),str(b),'--out',str(out)]),0)
            report=out.read_text();self.assertNotIn(directory,report)
            changed=records();changed[3]['state']['a']^=1;b.write_bytes(encoded(changed))
            stream=io.StringIO()
            with redirect_stdout(stream):self.assertEqual(main([str(a),str(b)]),1)
            self.assertEqual(json.loads(stream.getvalue())['first_difference']['ordinal'],2)
            stream=io.StringIO()
            with redirect_stdout(stream):self.assertEqual(main([str(a),str(root/'missing')]),2)
            self.assertNotIn(directory,stream.getvalue())
            self.assertEqual(json.loads(stream.getvalue())['error'],'Trace file operation failed')
            stream=io.StringIO()
            with redirect_stdout(stream):self.assertEqual(main([str(a),str(a),'--out',str(out)]),2)


if __name__=='__main__':
    unittest.main()
