"""Authored synchronous return candidates and conservative stack frontiers."""
import json
import subprocess
import sys
import unittest

from pcerecomp import discovery
import test_discovery as helpers
from test_discovery import seed

MPR = (0, 248, 0, 0, 0, 0, 0, 0)


class CallDiscoveryTests(unittest.TestCase):
    setUp = helpers.DiscoveryTests.setUp
    inputs = helpers.DiscoveryTests.inputs
    pcs = helpers.DiscoveryTests.pcs
    reasons = helpers.DiscoveryTests.reasons
    rewrite_report = helpers.DiscoveryTests.rewrite_report

    def graph(self, patches, *, roots=None, ranges=None, name='graph', size=8192, **options):
        rom = bytearray([0xEA] * size)
        for offset, code in patches:
            raw = bytes.fromhex(code)
            rom[offset:offset + len(raw)] = raw
        self.inputs(roots=roots or [seed(size=3, mpr=MPR)], rom=rom)
        return discovery.discover_roots(self.seeds, self.image, self.root/name,
            rom_ranges=ranges or [(offset, len(bytes.fromhex(code))) for offset, code in patches],
            call_depth_limit=options.pop('call_depth_limit', 8), **options)

    def test_nested_jsr_bsr_and_balanced_register_stack_recover_continuations(self):
        result = self.graph([(0, '20 10 E0 A9 2A 80 FE'),
                             (0x10, '48 DA 44 0C FA 68 60'), (0x20, '5A 7A 60')])
        self.assertEqual(self.pcs(result), {0xE000,0xE003,0xE005,0xE010,0xE011,
            0xE012,0xE014,0xE015,0xE016,0xE020,0xE021,0xE022})
        self.assertEqual(result.report['unresolved'], [])
        self.assertEqual(result.report['summary']['resolved_returns'], 2)
        self.assertEqual(result.report['summary']['calls_with_candidate_returns'], 2)
        leaf = next(n for n in result.report['nodes'] if n['pc'] == 0xE020)
        self.assertEqual(leaf['stack_bytes'], 6)
        self.assertEqual([f['stored_return_word'] for f in leaf['call_stack']], [0xE002,0xE013])
        self.assertEqual(result.report['analysis_policy'], discovery.CALL_POLICY)
        self.assertFalse(result.report['execution_evidence'])
        self.assertFalse(result.report['routine_closure'])
        discovery.load_discovery(result.report_path, self.image).revalidate()

    def test_same_callee_different_callers_keep_facts_and_deduplicate_compiled_roots(self):
        result = self.graph([(0, 'A9 08 20 20 E0 53 80 80 FE'),
                             (0x10, 'A9 10 20 20 E0 53 80 80 FE'), (0x20, '60')],
            roots=[seed(size=2,mpr=MPR),seed(0x10,size=2,mpr=MPR)])
        returns = [n for n in result.report['nodes'] if n['pc'] == 0xE020]
        self.assertEqual({n['register_facts']['a'] for n in returns}, {8,16})
        self.assertEqual(len(returns), 2)
        self.assertEqual(sum(r['pc'] == 0xE020 for r in result.declarations.roots), 1)
        self.assertEqual(result.report['overlaps'], [])
        self.assertEqual(result.report['summary']['call_states'], 10)
        self.assertEqual(result.report['summary']['candidate_roots'], 9)
        self.assertEqual({n['mpr'][7] for n in result.report['nodes'] if n['pc'] == 0xE007}, {8})
        self.assertEqual({n['mpr'][7] for n in result.report['nodes'] if n['pc'] == 0xE017}, {16})

    def test_return_uses_current_mapping_not_caller_mapping(self):
        mapped = (0,248,0,0,0,0,0,1)
        result = self.graph([(0, '20 10 E0'), (0x10, 'A9 01 53 80'),
                             (0x2014, '60'), (0x2003, '80 FE')], size=16384)
        continuation = next(r for r in result.declarations.roots if r['pc'] == 0xE003)
        self.assertEqual(continuation['mpr'], list(mapped))
        self.assertEqual(continuation['rom_offsets'], [0x2003,0x2004])
        self.assertEqual(result.report['unresolved'], [])

    def test_base_wram_alias_changes_keep_same_protected_stack(self):
        result = self.graph([(0, '20 10 E0 80 FE'), (0x10, 'A9 FB 53 02 60')])
        continuation = next(r for r in result.declarations.roots if r['pc'] == 0xE003)
        self.assertEqual(continuation['mpr'][1], 251)
        self.assertEqual(result.report['unresolved'], [])

    def test_unsafe_stack_effects_stop_and_do_not_invent_caller_continuation(self):
        cases = [('48 60', 'unbalanced_return'), ('68 60','stack_frame_pop'),
            ('28 60','stack_frame_pop'), ('FA 60','stack_frame_pop'), ('7A 60','stack_frame_pop'),
            ('9A 60','stack_pointer_change'), ('A9 00 53 02 60','stack_mapping_change'),
            ('8D 80 21 60','stack_write_barrier'), ('8D 80 41 60','stack_write_barrier'),
            ('91 00 60','stack_write_barrier'), ('9D 00 20 60','stack_write_barrier'),
            ('73 00 20 00 20 01 00 60','stack_write_barrier')]
        alias = list(MPR); alias[2] = 249
        for index, (code, reason) in enumerate(cases):
            result = self.graph([(0,'20 10 E0 80 FE'),(0x10,code)],
                roots=[seed(size=3,mpr=alias)],name='unsafe-'+str(index))
            with self.subTest(code=code):
                self.assertNotIn(0xE003,self.pcs(result))
                self.assertIn(reason,self.reasons(result))
                self.assertIn('unresolved_call_return',self.reasons(result))

    def test_known_index_and_nonstack_stores_are_allowed(self):
        result = self.graph([(0,'20 10 E0 80 FE'),
            (0x10,'A2 01 9D FF 1F A0 02 99 00 20 85 10 07 10 03 00 60')])
        self.assertIn(0xE003,self.pcs(result))
        self.assertEqual(result.report['unresolved'], [])

    def test_known_index_stack_alias_and_index_wrap_are_checked_physically(self):
        for index, code in enumerate(('A2 01 9D FF 20 60','A0 01 99 FF 20 60')):
            result = self.graph([(0,'20 10 E0 80 FE'),(0x10,code)],name='index-'+str(index))
            self.assertIn('stack_write_barrier',self.reasons(result))
            self.assertNotIn(0xE003,self.pcs(result))

    def test_unsupported_stack_mapping_is_explicit(self):
        result = self.graph([(0,'20 10 E0 80 FE'),(0x10,'60')],roots=[seed(size=3)])
        self.assertEqual(self.pcs(result), {0xE000})
        self.assertEqual(self.reasons(result), {'unsupported_stack_mapping'})

    def test_empty_frame_rts_rti_brk_remain_unresolved(self):
        for index,(code,reason) in enumerate((('60','dynamic_return'),('40','interrupt_return'),
                                             ('00 EA','interrupt_vector'))):
            result=self.graph([(0,code)],roots=[seed(size=len(bytes.fromhex(code)),mpr=MPR)],name='stop-'+str(index))
            self.assertEqual(self.reasons(result),{reason})

    def test_recursive_depth_bound_is_a_frontier(self):
        result=self.graph([(0,'20 00 E0')],call_depth_limit=3)
        self.assertEqual(len(result.report['nodes']),4)
        self.assertEqual(len(result.declarations.roots),1)
        self.assertIn('call_depth_limit',self.reasons(result))
        self.assertTrue(result.report['summary']['limit_reached'])
        self.assertEqual(result.report['summary']['resolved_returns'],0)

    def test_stack_capacity_counts_local_pushes_and_nested_call_bytes(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'48 80 FD')],instruction_limit=1000)
        self.assertIn('stack_capacity',self.reasons(result))
        self.assertEqual(max(n['stack_bytes'] for n in result.report['nodes']),256)
        self.assertNotIn(0xE003,self.pcs(result))

    def test_pop_local_data_makes_a_unknown_rather_than_restore_guessed_value(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'A9 01 48 68 53 80 60')])
        self.assertIn('mapping_change',self.reasons(result))
        self.assertNotIn(0xE003,self.pcs(result))

    def test_vector_policy_composes_without_changing_dynamic_jump_or_return(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'6C 00 E1'),(0x20,'60'),(0x100,'20 E0')],
            ranges=[(0,5),(0x10,3),(0x20,1)],rom_vector_ranges=[(0x100,2)])
        self.assertEqual(result.report['analysis_policy'],discovery.CALL_POLICY)
        self.assertEqual(result.report['summary']['resolved_vectors'],1)
        self.assertIn(0xE003,self.pcs(result))
        self.assertEqual(result.report['unresolved'],[])

    def test_limits_apply_to_call_states_and_contexts(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'60')],instruction_limit=2)
        self.assertEqual(self.pcs(result),{0xE000,0xE010})
        self.assertIn('instruction_limit',self.reasons(result))
        self.assertEqual(result.report['summary']['resolved_returns'],1)

    def test_candidate_return_does_not_hide_nonreturning_or_unsafe_path(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'D0 01 60 48 60')])
        self.assertIn(0xE003,self.pcs(result))
        self.assertEqual(result.report['summary']['calls_with_candidate_returns'],1)
        self.assertIn('unbalanced_return',self.reasons(result))

    def test_return_metadata_rederived_not_trusted_after_rehash(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'60')])
        original=result.report_path.read_bytes()
        for mutate in (lambda r:r['nodes'][-1]['call_stack'][0].__setitem__('resume_pc',0xE004),
                       lambda r:r['nodes'][-1].__setitem__('stack_bytes',3),
                       lambda r:r['summary'].__setitem__('resolved_returns',99),
                       lambda r:r['edges'].clear()):
            self.rewrite_report(result,mutate)
            with self.assertRaisesRegex(ValueError,'recomputed'):
                discovery.load_discovery(result.report_path,self.image)
            result.report_path.write_bytes(original)

    def test_invalid_policy_options_refuse_before_output(self):
        for index,depth in enumerate((0,65,-1,True,1.5,'2')):
            with self.subTest(depth=depth),self.assertRaises(ValueError):
                self.graph([(0,'20 10 E0'),(0x10,'60')],name='invalid-'+str(index),call_depth_limit=depth)
            self.assertFalse((self.root/('invalid-'+str(index))).exists())

    def test_default_graph_bytes_unchanged_after_call_policy_run(self):
        self.graph([(0,'20 10 E0 80 FE'),(0x10,'60')])
        first=discovery.discover_roots(self.seeds,self.image,self.root/'old-first',rom_ranges=[(0,5),(0x10,1)])
        second=discovery.discover_roots(self.seeds,self.image,self.root/'old-second',rom_ranges=[(0,5),(0x10,1)])
        self.assertEqual(first.report_path.read_bytes(),second.report_path.read_bytes())
        self.assertEqual(self.pcs(first),{0xE000,0xE010})
        self.assertEqual(self.reasons(first),{'dynamic_return','dynamic_return_site'})
        self.assertNotIn('call_depth_limit',first.report['options'])

    def test_cli_call_depth_and_verification(self):
        self.graph([(0,'20 10 E0 80 FE'),(0x10,'60')])
        args=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),
            '--image',str(self.image),'--rom-range','0:5','--rom-range','16:1',
            '--call-depth','4','--out',str(self.root/'cli')]
        result=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        admitted=discovery.load_discovery(self.root/'cli',self.image)
        self.assertEqual(admitted.report['options']['call_depth_limit'],4)

    def test_wrapped_call_instruction_and_wrapped_rts_continuation(self):
        mapping=list(MPR);mapping[0]=0
        result=self.graph([(0x1FFE,'20 10'),(0,'E0 80 FE'),(0x10,'60')],
            roots=[seed(pc=0xFFFE,mpr=mapping,offsets=[0x1FFE,0x1FFF,0])])
        self.assertEqual(self.pcs(result),{0xFFFE,0xE010,1})
        leaf=next(n for n in result.report['nodes'] if n['pc']==0xE010)
        self.assertEqual(leaf['call_stack'][0]['stored_return_word'],0)
        self.assertEqual(leaf['call_stack'][0]['resume_pc'],1)
        self.assertEqual(result.report['unresolved'],[])

    def test_outer_local_push_survives_nested_return_and_balances_afterward(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'48 20 20 E0 68 60'),(0x20,'60')])
        self.assertEqual(result.report['summary']['resolved_returns'],2)
        self.assertIn(0xE003,self.pcs(result))
        node=next(n for n in result.report['nodes'] if n['pc']==0xE014)
        self.assertEqual(node['stack_bytes'],3)
        self.assertEqual(len(node['call_stack']),1)

    def test_general_wram_aliasing_cannot_be_hidden_in_a_different_logical_page(self):
        mapping=list(MPR);mapping[5]=250
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'8D A0 A1 60')],roots=[seed(size=3,mpr=mapping)])
        self.assertIn('stack_write_barrier',self.reasons(result))
        self.assertNotIn(0xE003,self.pcs(result))

    def test_conflicting_join_retracts_optimistic_callee_mapping_and_return(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'D0 04 A9 08 80 02 A9 10 53 80 60')])
        self.assertIn('mapping_change',self.reasons(result))
        self.assertNotIn(0xE003,self.pcs(result))
        self.assertFalse(any(n['mpr'][7] in (8,16) for n in result.report['nodes']))

    def test_sibling_seed_has_no_protected_return_frame(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'60')],
            roots=[seed(size=3,mpr=MPR),seed(0x10,mpr=MPR)])
        self.assertIn(0xE003,self.pcs(result))
        self.assertIn('dynamic_return',self.reasons(result))
        self.assertEqual(len([n for n in result.report['nodes'] if n['pc']==0xE010]),2)
        self.assertEqual(result.report['overlaps'],[])

    def test_old_policy_cannot_accept_new_stack_metadata_or_options(self):
        result=self.graph([(0,'20 10 E0 80 FE'),(0x10,'60')])
        self.rewrite_report(result,lambda r:r.__setitem__('analysis_policy',discovery.POLICY))
        with self.assertRaisesRegex(ValueError,'options'):
            discovery.load_discovery(result.report_path,self.image)


if __name__ == '__main__':
    unittest.main()
