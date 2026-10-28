"""Authored admission fixtures for the real per-retirement span reference."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import native_span_reference as span
from scripts import stable_context_reference as context
from generate_context_fixture import expected_rows
from pcerecomp.emitter import emit_capture
from pcerecomp.project import ABI


def capture(native):
    observations=[dict(pc=pc,mpr=list(mpr),physical=list(physical),data=list(data),
        native_hits=hits if native else 0,interpreted_hits=0 if native else hits)
        for (pc,mpr,physical,data),hits in context.expected_sources().items()]
    return dict(schema=1,runtime_abi=ABI,capacity=1024,complete=True,
        dropped_instructions=0,unreadable_instructions=0,retired_instructions=80,
        observations=observations)


def work(native,limit):
    # Authored work/schema vectors only. Actual executable-produced reports are
    # separately required by the CLI; these do not claim guest execution.
    batches=[]
    for _ in range(2):
        left=40
        while left:
            count=min(limit,left);batches.append(count);left-=count
    guards=sum((2+len(key[3]))*hits for key,hits in context.expected_sources().items())
    value=dict(native=80 if native else 0,interpreted=0 if native else 80,
        limit=limit,calls=len(batches),attempts=80,after=80,max_batch=max(batches),
        guards=guards if native else 0,literal_checks=1600,batches=batches,
        generated_calls=len(batches) if native else 0,
        local_continuations=80-len(batches) if native else 0)
    return 'SPAN_WORK '+json.dumps(value)


def arguments():
    raw=json.dumps([dict(kind='cpu',values=row)for divisor in(3,12)
                    for row in expected_rows(divisor,spread=True)])
    bootstrap=capture(False);digest=hashlib.sha256(json.dumps(bootstrap).encode()).hexdigest()
    with tempfile.TemporaryDirectory()as temporary:
        manifest=emit_capture(bootstrap,Path(temporary)/'module',digest,
                              partition_layout='stable',native_span=True)
    cases=[dict(limit=limit,raw=raw,capture=capture(True),work=work(True,limit))for limit in span.LIMITS]
    return dict(gear_raw=raw,bootstrap_raw=raw,bootstrap_work=work(False,1),
        bootstrap_capture=bootstrap,native_cases=cases,manifest=manifest,
        bootstrap_capture_sha256=digest)


class NativeSpanReferenceTests(unittest.TestCase):
    def test_all_declared_limits_share_independent_retirement_and_source_expectations(self):
        result=span.qualify(**arguments())
        self.assertEqual(result['records_per_engine'],80)
        self.assertEqual(result['native_instructions'],320)
        self.assertEqual(result['literal_checks'],9600)
        self.assertEqual(result['source_identities'],26)
        self.assertEqual(result['executed_parts'],10)
        self.assertEqual([row['limit']for row in result['native']],[1,2,16,256])

    def test_missing_reordered_duplicate_or_wrong_typed_limit_rejected(self):
        original=arguments()
        for action in('missing','duplicate','reordered','bool'):
            changed=copy.deepcopy(original);cases=changed['native_cases']
            if action=='missing':cases.pop()
            elif action=='duplicate':cases[2]=copy.deepcopy(cases[1])
            elif action=='reordered':cases.reverse()
            else:cases[0]['limit']=True
            with self.subTest(action=action),self.assertRaises(ValueError):span.qualify(**changed)

    def test_span_work_counters_and_partition_corruptions_rejected(self):
        original=work(True,16)
        mutations={
            'callbacks':lambda r:r.update(after=79),
            'calls':lambda r:r.update(calls=r['calls']+1),
            'native':lambda r:r.update(native=79),
            'fallback':lambda r:r.update(interpreted=1),
            'guard':lambda r:r.update(guards=r['guards']-1),
            'literal':lambda r:r.update(literal_checks=1599),
            'batch_sum':lambda r:r['batches'].__setitem__(0,15),
            'batch_bool':lambda r:r['batches'].__setitem__(0,True),
            'batch_max':lambda r:r.update(max_batch=15),
            'over_limit':lambda r:r['batches'].__setitem__(0,17),
            'generated_calls':lambda r:r.update(generated_calls=r['generated_calls']+1),
            'no_local_work':lambda r:r.update(local_continuations=0),
            'invented_local_work':lambda r:r.update(local_continuations=80),
            'wrong_limit':lambda r:r.update(limit=2),
            'bool':lambda r:r.update(attempts=True),
        }
        for name,mutate in mutations.items():
            value=json.loads(original[len('SPAN_WORK '):]);mutate(value)
            with self.subTest(name=name),self.assertRaises(ValueError):
                span.work('SPAN_WORK '+json.dumps(value),True,16)

    def test_reset_case_boundaries_and_single_step_reference_rejected_if_changed(self):
        value=json.loads(work(True,16)[len('SPAN_WORK '):])
        value['batches']=[16,16,16,16,16];value['calls']=value['generated_calls']=5
        value['local_continuations']=75
        with self.assertRaisesRegex(ValueError,'reset CPU case'):
            span.work('SPAN_WORK '+json.dumps(value),True,16)
        value=json.loads(work(True,1)[len('SPAN_WORK '):]);value['generated_calls']=79
        with self.assertRaises(ValueError):span.work('SPAN_WORK '+json.dumps(value),True,1)
        value=json.loads(work(False,1)[len('SPAN_WORK '):]);value['generated_calls']=1
        with self.assertRaises(ValueError):span.work('SPAN_WORK '+json.dumps(value),False,1)

    def test_exact_span_capability_and_state_source_tamper_rejected(self):
        original=arguments()
        for marker in(None,{'schema':1,'protocol':'wrong'},{'schema':True,'protocol':'per_instruction_v1'}):
            changed=copy.deepcopy(original);changed['manifest']['native_span']=marker
            with self.subTest(marker=marker),self.assertRaises(ValueError):span.qualify(**changed)
        for source in('raw','capture'):
            for limit in range(4):
                changed=copy.deepcopy(original);case=changed['native_cases'][limit]
                if source=='raw':
                    rows=json.loads(case['raw']);rows[0]['values'][15]^=1;case['raw']=json.dumps(rows)
                else:case['capture']['observations'][0]['mpr'][7]^=1
                with self.subTest(source=source,limit=limit),self.assertRaises(ValueError):span.qualify(**changed)


if __name__=='__main__':unittest.main()
