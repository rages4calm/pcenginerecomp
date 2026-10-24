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

    def test_mirror_cases_switch_guest_fetch_mapping_without_changing_original(self):
        original=reference.authored_rom();mirror=reference.mirror_rom()
        self.assertEqual(mirror[0x1800:0x1809],bytes.fromhex('A9 20 53 80 A9 5A 1A 80 FD'))
        self.assertEqual(mirror[:0x1800],original[:0x1800])
        self.assertEqual(mirror[0x1809:],original[0x1809:])
        cases=reference.mirror_plans();_,spans=reference.serialize(cases)
        self.assertEqual(len(cases),12)
        self.assertEqual(sum(s['records'] for s in spans),120)
        self.assertEqual(sum(op[1] for case in cases for op in case['operations'] if op[0]=='i'),96)
        self.assertEqual({case['operations'][0][3] for case in cases},{0xF800})

    @staticmethod
    def execution(cases,native,guards=False):
        from pcerecomp.project import ABI
        counts=[sum(op[1] for op in case['operations'] if op[0]=='i') for case in cases]
        return dict(runtime_abi=ABI,native_only=native,interpreter_fallback=False,cases=len(cases),
                    native_steps=sum(counts) if native else 0,interpreter_steps=0 if native else sum(counts),
                    guard_checks=4*len(cases) if guards else 0,restored_source_mutations=2*len(cases) if guards else 0,
                    per_case=[[n,0] if native else [0,n] for n in counts])

    def test_execution_accounting_requires_actual_tier_per_case(self):
        for cases,retired in ((reference.plans(),1224),(reference.mirror_plans(),96)):
            for native in (False,True):
                execution=self.execution(cases,native,native)
                self.assertEqual(reference.validate_execution_report(execution,cases,native,native),execution)
                self.assertEqual(execution['native_steps']+execution['interpreter_steps'],retired)

    def test_execution_accounting_rejects_fallback_loss_and_wrong_guards(self):
        cases=reference.mirror_plans();good=self.execution(cases,True,True)
        mutations=[('interpreter_fallback',True),('native_only',False),('runtime_abi',16),
                   ('cases',True),('native_steps',95),('interpreter_steps',1),('guard_checks',47),
                   ('restored_source_mutations',23),('per_case',[[7,1]]*12)]
        for key,value in mutations:
            bad=copy.deepcopy(good);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):reference.validate_execution_report(bad,cases,True,True)

    @staticmethod
    def capture(pc=0xF804,mpr7=0x20,raw=(169,90),hits=1,native=False):
        from pcerecomp.project import ABI
        mpr=[0]*7+[mpr7]
        return dict(schema=1,runtime_abi=ABI,capacity=65536,dropped_instructions=0,
                    unreadable_instructions=0,retired_instructions=hits,complete=True,observations=[
                        dict(pc=pc,mpr=mpr,physical=[(mpr7<<13)|((pc+i)&8191) for i in range(len(raw))],
                             data=list(raw),native_hits=hits if native else 0,interpreted_hits=0 if native else hits)])

    def test_actual_capture_requires_complete_current_abi_and_single_tier(self):
        good=self.capture(native=True,hits=3)
        self.assertEqual(reference.validate_actual_capture(good,3,True),good)
        for mutate in (
            lambda c:c.update(runtime_abi=16),
            lambda c:c.update(complete=False,dropped_instructions=1,retired_instructions=4),
            lambda c:c['observations'][0].update(native_hits=2,interpreted_hits=1),
            lambda c:c['observations'][0].update(physical=[0x1804,0x1805])):
            bad=copy.deepcopy(good);mutate(bad)
            with self.assertRaises(ValueError):reference.validate_actual_capture(bad,bad['retired_instructions'],True)
        with self.assertRaises(ValueError):reference.validate_actual_capture(good,2,True)

    def test_authored_union_conserves_actual_identity_hits_and_mpr(self):
        first=self.capture(hits=2);second=self.capture(hits=3)
        union=reference.compose_authored_captures([first,second])
        self.assertEqual(union['retired_instructions'],5)
        self.assertEqual(len(union['observations']),1)
        self.assertEqual(union['observations'][0]['interpreted_hits'],5)
        self.assertEqual(first['observations'][0]['interpreted_hits'],2)
        for distinct in (self.capture(mpr7=0,hits=3),self.capture(raw=(169,91),hits=3)):
            union=reference.compose_authored_captures([first,distinct])
            self.assertEqual(union['retired_instructions'],5)
            self.assertEqual(len(union['observations']),2)
        # A different unused mapping byte is still a distinct dispatch identity.
        distinct=copy.deepcopy(second);distinct['observations'][0]['mpr'][0]=248
        self.assertEqual(len(reference.compose_authored_captures([first,distinct])['observations']),2)

    def test_union_rejects_native_hits_or_invalid_input_count(self):
        with self.assertRaises(ValueError):reference.compose_authored_captures([self.capture()])
        with self.assertRaises(ValueError):reference.compose_authored_captures([self.capture(),self.capture(native=True)])

    def test_private_wrapper_has_distinct_native_target_and_no_stub(self):
        from pathlib import Path
        root=Path(__file__).resolve().parent.parent
        bootstrap=reference.native_build_files(root,root/'tests/reset_oracle_probe.cpp')
        native=reference.native_build_files(root,root/'tests/reset_oracle_probe.cpp',root/'authored-module')
        self.assertIn('runtime/src/no_module.cpp',bootstrap)
        self.assertNotIn('add_executable(native-reset-probe',bootstrap)
        native_target=native[native.index('add_executable(native-reset-probe'):]
        self.assertNotIn('no_module.cpp',native_target)
        self.assertIn('PCE_RESET_NATIVE_ONLY=1',native_target)
        self.assertIn('target_link_libraries(native-reset-probe PRIVATE ${_module} pce-runtime)',native_target)


if __name__=='__main__':unittest.main()
