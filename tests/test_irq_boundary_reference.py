"""Authored evidence-journal checks; no emulator checkout or game data needed."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.irq_trace import parse_trace
from scripts.irq_boundary_reference import qualify_journal, qualify_gear_journal


class JournalChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'calls.jsonl'
        state=dict(pc=0xE000,a=0,x=0,y=0,sp=0,p=4,mpr=[0]*8,mpr_latch=None,
            physical_pc=0,clock_divisor=12,ticks=0,wram_sha256=hashlib.sha256(bytes(8192)).hexdigest())
        after=copy.deepcopy(state);after.update(pc=0xE001,physical_pc=1,ticks=24)
        self.state,self.after=state,after
        header=dict(type='header',schema=2,format='pce-cpu-trace-2',
            engine=dict(name='authored-journal',revision='a'*40,source_sha256='b'*64,binary_sha256='c'*64),
            fixture_sha256='d'*64,case='synthetic-one-NOP',clock='master-ticks',
            phase='retirement-boundary-after-irq',unavailable_fields=['mpr_latch'],call_model='split-irq')
        self.trace=parse_trace(self.encoded([header,dict(type='initial',state=state),
            dict(type='event',ordinal=1,kind='opcode',entry=state,state=after,irq_vector=None),
            dict(type='instruction',ordinal=1,event_start=1,event_end=1,entry_pc=0xE000,
                entry_mpr=[0]*8,state=after,irq_count=0,irq_vector=None),
            dict(type='final',executed=1,events=1,stop='instruction-limit',complete=True,state=after)]))
        reset=dict(irq_sample=32,irq_low=32,irq_enabled_mask=0,i_flag_sample=0,
            pi_mask_cache=4294967295,in_block_move=0,runrunrun=0,overclock=1,
            emulate_wai=False,raw_pc=0,p=0,ticks=0)
        ready=dict(reset,irq_sample=0,irq_low=0,irq_enabled_mask=7,pi_mask_cache=0,
                   runrunrun=-1,raw_pc=0xE000,p=4)
        done=dict(ready,raw_pc=0xE001,ticks=24,i_flag_sample=4)
        self.rows=[dict(type='header',schema=1,format='pce-beetle-call-journal-1',
                       decision='original-runsub-irq-pipeline-v1'),
            dict(type='call',ordinal=1,phase='reset',opcode_ordinal=0,kind='reset',
                irq_vector=None,entry=reset,state=ready),
            dict(type='call',ordinal=2,phase='measured',opcode_ordinal=1,kind='opcode',
                irq_vector=None,entry=ready,state=done),
            dict(type='final',calls=2,measured_instructions=1,primer_instructions=0,
                measured_events=1,complete=True)]

    @staticmethod
    def encoded(rows):return ('\n'.join(json.dumps(row)for row in rows)+'\n').encode()

    def check(self,rows=None):
        self.path.write_bytes(self.encoded(self.rows if rows is None else rows))
        return qualify_journal(self.path,self.trace,0)

    def test_original_reset_bit_and_opcode_are_not_two_retirements(self):
        self.assertGreater(self.check(),0)

    def test_false_event_decision_and_irq_vector_are_refused(self):
        for mutate in (lambda r:r[2].update(kind='irq-entry',irq_vector=0xFFFA),
                       lambda r:r[1]['entry'].update(irq_sample=0x100,irq_low=0x100)):
            rows=copy.deepcopy(self.rows);mutate(rows)
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):self.check(rows)

    def test_malformed_attachment_phase_and_lost_final_call_are_refused(self):
        mutations=[lambda r:r[2].update(opcode_ordinal=2),
                   lambda r:r[2].update(phase='primer'),
                   lambda r:r[-1].update(measured_events=2),
                   lambda r:r.pop(1)]
        for mutate in mutations:
            rows=copy.deepcopy(self.rows);mutate(rows)
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):self.check(rows)

    def test_pipeline_bool_width_and_final_bool_are_not_integer_evidence(self):
        mutations=[lambda r:r[2]['entry'].update(ticks=False),
                   lambda r:r[2]['state'].update(p=256),
                   lambda r:r[2]['state'].update(raw_pc=2**32),
                   lambda r:r[-1].update(measured_instructions=True)]
        for mutate in mutations:
            rows=copy.deepcopy(self.rows);mutate(rows)
            with self.subTest(mutation=mutate),self.assertRaises(ValueError):self.check(rows)

    def test_duplicate_json_and_nonfinite_pipeline_values_are_refused(self):
        for raw in (self.encoded(self.rows).replace(b'"schema": 1',b'"schema": 1,"schema": 1',1),
                    self.encoded(self.rows).replace(b'"ticks": 24',b'"ticks": NaN',1)):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):qualify_journal(self.path,self.trace,0)

    def test_final_retirement_cannot_omit_pending_original_call(self):
        for pending in (dict(irq_low=4,i_flag_sample=0),
                        dict(irq_sample=0x20),dict(in_block_move=1)):
            rows=copy.deepcopy(self.rows);rows[-2]['state'].update(pending)
            with self.subTest(pending=pending),self.assertRaisesRegex(ValueError,'final retirement boundary'):
                self.check(rows)

    def gear_fixture(self):
        state=copy.deepcopy(self.state);after=copy.deepcopy(self.after)
        state['mpr_latch']=after['mpr_latch']=0
        self.path.write_bytes(self.encoded([dict(phase='measured',ordinal=1,original_calls=1,
            entry=state,state=after,original_trace=[dict(type='cpu',pc=0xE000,bank=0,bytes=[0xEA])])]))
        h=copy.deepcopy(self.trace.header);h.update(call_model='aggregate',unavailable_fields=[])
        trace=parse_trace(self.encoded([h,dict(type='initial',state=state),
            dict(type='event',ordinal=1,kind='opcode',entry=state,state=after,irq_vector=None),
            dict(type='instruction',ordinal=1,event_start=1,event_end=1,entry_pc=0xE000,
                entry_mpr=[0]*8,state=after,irq_count=0,irq_vector=None),
            dict(type='final',executed=1,events=1,stop='instruction-limit',complete=True,state=after)]))
        case=dict(primer_steps=0,steps=1,source_hits=[dict(pc=0xE000,mpr=[0]*8,physical=[0],data=[0xEA],hits=1)])
        return trace,case

    def test_original_gear_cpu_source_is_independently_bound(self):
        trace,case=self.gear_fixture();self.assertGreater(qualify_gear_journal(self.path,trace,case),0)
        case['source_hits'][0]['data']=[0x78]
        with self.assertRaisesRegex(ValueError,'source/hits'):qualify_gear_journal(self.path,trace,case)

    def test_original_gear_wrong_aggregate_count_or_fabricated_irq_is_refused(self):
        for mutation in ('calls','irq'):
            trace,case=self.gear_fixture();rows=[json.loads(line)for line in self.path.read_text().splitlines()]
            if mutation=='calls':rows[0]['original_calls']=2
            else:rows[0]['original_trace'].append(dict(type='TRACE_CPU_IRQ',cycle=12,pc=0xE001,vector=0xFFFA))
            self.path.write_bytes(self.encoded(rows))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):qualify_gear_journal(self.path,trace,case)

    def test_original_gear_in_range_callback_clock_and_return_pc_are_exact(self):
        trace,case=self.gear_fixture()
        rows=[json.loads(line)for line in self.path.read_text().splitlines()]
        rows[0]['original_trace'].append(dict(type='TRACE_CPU_IRQ',cycle=0,pc=0xE001,vector=0xFFFA))
        body=[trace.header,dict(type='initial',state=trace.initial),*trace.events,*trace.instructions,trace.final]
        body[2]=dict(body[2],irq_vector=0xFFFA)
        body[3]=dict(body[3],irq_count=1,irq_vector=0xFFFA)
        traced=parse_trace(self.encoded(body))
        self.path.write_bytes(self.encoded(rows))
        self.assertGreater(qualify_gear_journal(self.path,traced,case),0)
        for field,value in (('cycle',1),('pc',0xE002)):
            changed=copy.deepcopy(rows);changed[0]['original_trace'][1][field]=value
            self.path.write_bytes(self.encoded(changed))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'callback timestamp/return PC'):
                qualify_gear_journal(self.path,traced,case)


if __name__=='__main__':unittest.main()
