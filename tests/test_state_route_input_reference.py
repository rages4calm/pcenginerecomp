import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from state_route_input_fixture import plans, program, expected, expected_hits, serialize, validate_events
from scripts.state_route_input_reference import validate_capture, validate_execution
from pcerecomp.project import ABI


class InputRouteReferenceTests(unittest.TestCase):
    def test_matrix_has_exact_clocks_and_source_work(self):
        cases=plans();self.assertEqual(len(cases),24)
        self.assertEqual(len({c['id'] for c in cases}),24)
        for case in cases:
            delay=case['delay'];self.assertEqual(case['instructions'],96+16*delay)
            self.assertEqual(case['ticks'],(408+32*delay)*case['divisor'])
            self.assertEqual(sum(expected_hits(case).values()),case['instructions'])
            self.assertEqual(len(expected_hits(case)),case['instructions'])
            self.assertEqual(len(serialize(case).splitlines()),4)
            self.assertEqual(len(expected(case)[-1]['values']),64)

    def test_held_intent_does_not_relatch_until_guest_write(self):
        for case in plans():
            events=expected(case);self.assertGreater(validate_events(events,case),0)
            phase=case['phase']
            for index,mask in case['injections']:
                before=events[index]['values'];previous=events[index-1]['values']
                self.assertEqual(before[21],mask)  # held field
                self.assertEqual(before[20],previous[26])  # stale pre latch
            ram=events[-1]['values']
            # Poll 2 samples I when injected before its write. Injection after
            # the write leaves its buttons stale, even when held already changed.
            self.assertEqual(ram[0x22],0xFE if phase in ('before-load','before-write') else 0xFF)
            self.assertEqual(ram[0x32],0xFD)
            self.assertEqual(ram[0x34],0xFE)
            self.assertEqual(ram[0x36],0xFF)

    def test_literal_checker_refuses_changed_clocks_masks_and_latches(self):
        case=plans()[0];events=expected(case)
        for field in (1,2,11,14,19,20,21,25,26):
            changed=copy.deepcopy(events);changed[0]['values'][field]+=1
            with self.assertRaises(ValueError):validate_events(changed,case)
        changed=copy.deepcopy(events);changed[0]['values'][0]=True
        with self.assertRaises(ValueError):validate_events(changed,case)

    def test_actual_execution_validator_requires_exact_tiers_and_port_counts(self):
        case=plans()[0]
        for native in (False,True):
            work=dict(runtime_abi=ABI,native_steps=case['instructions'] if native else 0,
                      interpreter_steps=0 if native else case['instructions'],guard_misses=0,joypad_reads=24,joypad_writes=16)
            validate_execution(work,case,native)
            for key in work:
                changed=dict(work);changed[key]+=1
                with self.assertRaises(ValueError):validate_execution(changed,case,native)

    def test_actual_capture_validator_requires_full_identity_and_hit_counts(self):
        case=plans()[0]
        for native in (False,True):
            observations=[dict(pc=pc,mpr=list(mpr),physical=list(physical),data=list(data),
                               native_hits=hits if native else 0,interpreted_hits=0 if native else hits)
                          for (pc,mpr,physical,data),hits in expected_hits(case).items()]
            capture=dict(schema=1,runtime_abi=ABI,capacity=65536,complete=True,dropped_instructions=0,
                         unreadable_instructions=0,retired_instructions=case['instructions'],observations=observations)
            validate_capture(capture,case,native)
            for field in ('pc','mpr','physical','data','native_hits','interpreted_hits'):
                changed=copy.deepcopy(capture);first=changed['observations'][0]
                if isinstance(first[field],list):first[field][0]^=1
                else:first[field]+=1
                with self.assertRaises(ValueError):validate_capture(changed,case,native)


if __name__=='__main__':unittest.main()
