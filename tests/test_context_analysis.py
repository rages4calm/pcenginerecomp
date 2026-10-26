"""Authored multi-bank programs for conservative context-aware discovery."""
import json
import unittest

from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.isa import physical


MPR = tuple(range(8))


def snapshot(programs, entries=(0xE000,), mpr=MPR):
    memory = {}
    for pc, data, mapping in programs:
        for offset, value in enumerate(data):
            address = physical(pc + offset, mapping)
            if address in memory and memory[address] != value:
                raise AssertionError('Conflicting authored source bytes')
            memory[address] = value
    return Snapshot(mpr, memory, entries, 'authored-context-analysis')


def mapped(page, bank, initial=MPR):
    result = list(initial)
    result[page] = bank
    return tuple(result)


def keys(report):
    return {(row['pc'], tuple(row['mpr'])) for row in report['instructions']}


class ContextAnalysisTests(unittest.TestCase):
    def test_default_report_remains_exact_schema_one(self):
        source = snapshot([(0xE000, [0xA9, 8, 0x53, 128], MPR)])
        expected = dict(schema=1, snapshot_sha256='authored-context-analysis', mpr=MPR,
            entry_points=(0xE000,), instructions=[
                dict(pc=0xE000, physical=(0xE000, 0xE001), data=(0xA9, 8),
                     mnemonic='LDA', mode='imm', target=None, native_supported=True),
                dict(pc=0xE002, physical=(0xE002, 0xE003), data=(0x53, 128),
                     mnemonic='TAM', mode='imm', target=None, native_supported=True)],
            edges=[dict(**{'from':0xE000, 'to':0xE002}, kind='fallthrough')],
            unresolved=[dict(pc=0xE002, reason='mapping_change', resume_pc=0xE004, mask=128)],
            summary=dict(instructions=2, native_supported=2, unresolved=1, execution_evidence=False))
        self.assertEqual(analyze(source), expected)
        self.assertEqual(json.dumps(analyze(source)), json.dumps(expected))
        self.assertEqual(analyze(source, follow_mappings=False, context_limit=1), expected)

    def test_immediate_self_remap_fetches_next_instruction_in_new_bank(self):
        new = mapped(7, 8)
        result = analyze(snapshot([(0xE000, [0xA9, 8, 0x53, 128], MPR),
                                   (0xE004, [0x60], new)]), follow_mappings=True)
        self.assertEqual(keys(result), {(0xE000,MPR),(0xE002,MPR),(0xE004,new)})
        last = next(row for row in result['instructions'] if row['pc'] == 0xE004)
        self.assertEqual(last['physical'], (0x10004,))
        edge = next(edge for edge in result['edges'] if edge['kind'] == 'mapping_change')
        self.assertEqual(edge['from'], dict(pc=0xE002,mpr=list(MPR)))
        self.assertEqual(edge['to'], dict(pc=0xE004,mpr=list(new)))
        self.assertEqual(result['summary']['contexts'], 2)
        self.assertEqual(result['analysis_policy'], 'proven_mpr_constants')

    def test_multibit_tam_and_tma_or_current_full_mapping(self):
        middle = mapped(2, 9, mapped(0, 9))
        final = mapped(7, 9, middle)
        result = analyze(snapshot([(0xE000,[0xA9,9,0x53,5,0x43,5,0x53,128],MPR),
                                   (0xE008,[0x60],final)]), follow_mappings=True)
        self.assertIn((0xE004,middle), keys(result))
        self.assertIn((0xE008,final), keys(result))
        # Distinct selected MPRs 1 OR 2 = 3; this is not highest-bit selection.
        third = mapped(7, 3)
        report = analyze(snapshot([(0xE000,[0x43,6,0x53,128],MPR),
                                   (0xE004,[0x60],third)]),follow_mappings=True)
        self.assertIn((0xE004,third), keys(report))

    def test_zero_mask_preserves_mapping_even_when_a_is_unknown(self):
        result = analyze(snapshot([(0xE000,[0x53,0,0x60],MPR)]),follow_mappings=True)
        self.assertEqual(keys(result), {(0xE000,MPR),(0xE002,MPR)})
        self.assertFalse(any(row['reason']=='mapping_change' for row in result['unresolved']))

    def test_unknown_a_nonzero_tam_is_explicitly_unresolved(self):
        result = analyze(snapshot([(0xE000,[0x53,128],MPR)]),follow_mappings=True)
        self.assertEqual(keys(result), {(0xE000,MPR)})
        self.assertEqual(result['unresolved'][0]['reason'], 'mapping_change')

    def test_tma_zero_does_not_invent_a_latch_value(self):
        result = analyze(snapshot([(0xE000,[0xA9,8,0x43,0,0x53,128],MPR)]),follow_mappings=True)
        self.assertEqual(keys(result), {(0xE000,MPR),(0xE002,MPR),(0xE004,MPR)})
        self.assertTrue(any(row['reason']=='mapping_change' for row in result['unresolved']))

    def test_clear_transfer_and_swap_facts(self):
        programs = ([0x62], [0xA2,8,0x8A], [0xA0,8,0x98],
                    [0xA9,8,0xAA,0x62,0x8A], [0xA9,8,0xA8,0x62,0x98],
                    [0xA2,8,0x22], [0xA0,8,0x42], [0xA2,8,0x02,0x98])
        for prefix in programs:
            with self.subTest(prefix=prefix):
                bank = 0 if prefix == [0x62] else 8
                target = 0xE000+len(prefix)+2
                result = analyze(snapshot([(0xE000,prefix+[0x53,128],MPR),
                    (target,[0x60],mapped(7,bank))]),follow_mappings=True)
                self.assertIn((target,mapped(7,bank)),keys(result))

    def test_ram_load_alu_stack_and_block_results_are_unknown(self):
        for operation in ([0xA5,0], [0x69,1], [0x29,255], [0x68],
                          [0x73,0,0x20,0,0x21,1,0]):
            with self.subTest(operation=operation):
                code = [0xA9,8]+operation+[0x53,128]
                result = analyze(snapshot([(0xE000,code,MPR)]),follow_mappings=True)
                self.assertTrue(any(row['reason']=='mapping_change' and row['pc']==0xE000+len(code)-2
                                    for row in result['unresolved']))

    def test_tam_operand_is_fetched_before_page_remapping(self):
        new = mapped(1,9)
        result = analyze(snapshot([(0x1FFD,[0xA9,9,0x53,2],MPR),
                                   (0x2001,[0x60],new)], entries=(0x1FFD,)),follow_mappings=True)
        tam = next(row for row in result['instructions'] if row['pc']==0x1FFF)
        self.assertEqual(tam['physical'],(0x1FFF,0x2000))
        self.assertEqual(tam['data'],(0x53,2))
        self.assertIn((0x2001,new),keys(result))

    def test_instruction_operand_and_pc_wrap_use_each_mpr(self):
        new = mapped(7,9)
        result = analyze(snapshot([(0xFFFF,[0xA9,9,0x53,128,0x60],MPR)],
                                  entries=(0xFFFF,)),follow_mappings=True)
        first = next(row for row in result['instructions'] if row['pc']==0xFFFF)
        self.assertEqual(first['physical'],(0xFFFF,0))
        self.assertIn((3,new),keys(result))

    def test_conflicting_branch_values_remove_optimistic_remap_paths(self):
        # Taken path supplies A=9; fallthrough supplies A=8 at the same TAM.
        result = analyze(snapshot([(0xE000,[0xD0,6,0xA9,8,0x80,4],MPR),
                                   (0xE008,[0xA9,9,0x53,128],MPR),
                                   (0xE00C,[0x60],mapped(7,8)),
                                   (0xE00C,[0x60],mapped(7,9))]),follow_mappings=True)
        self.assertNotIn((0xE00C,mapped(7,8)),keys(result))
        self.assertNotIn((0xE00C,mapped(7,9)),keys(result))
        self.assertEqual(result['summary']['contexts'],1)
        self.assertTrue(any(row['pc']==0xE00A and row['reason']=='mapping_change'
                            for row in result['unresolved']))

    def test_matching_branch_values_keep_proven_transition(self):
        new = mapped(7,8)
        result = analyze(snapshot([(0xE000,[0xD0,6,0xA9,8,0x80,4],MPR),
                                   (0xE008,[0xA9,8,0x53,128],MPR),
                                   (0xE00C,[0x60],new)]),follow_mappings=True)
        self.assertIn((0xE00C,new),keys(result))

    def test_loop_converges_without_duplicate_nodes(self):
        result = analyze(snapshot([(0xE000,[0xA9,8,0xE8,0xD0,0xFD,0x53,128],MPR),
                                   (0xE007,[0x60],mapped(7,8))]),follow_mappings=True)
        self.assertIn((0xE007,mapped(7,8)),keys(result))
        self.assertEqual(len(keys(result)),len(result['instructions']))

    def test_calls_follow_target_but_do_not_invent_return_mapping(self):
        for opcode,data,target in [(0x20,[0x20,0x10,0xE0],0xE010),
                                    (0x44,[0x44,12],0xE010)]:
            with self.subTest(opcode=opcode):
                result = analyze(snapshot([(0xE000,[0xA9,8]+data+[0xEA],MPR),
                                           (target,[0x53,128],MPR),
                                           (target+2,[0x60],mapped(7,8))]),follow_mappings=True)
                self.assertIn((target,MPR),keys(result))
                self.assertIn((target+2,mapped(7,8)),keys(result))
                self.assertNotIn((0xE002+len(data),MPR),keys(result))
                self.assertTrue(any(row['reason']=='dynamic_return_site'
                                    for row in result['unresolved']))

    def test_indirect_jump_does_not_read_snapshot_pointer(self):
        result = analyze(snapshot([(0xE000,[0x6C,0,0x20],MPR),
                                   (0x2000,[0x10,0xE0],MPR),
                                   (0xE010,[0x60],MPR)]),follow_mappings=True)
        self.assertEqual(keys(result),{(0xE000,MPR)})
        self.assertEqual(result['unresolved'][0]['reason'],'indirect_jump')

    def test_same_pc_in_distinct_mappings_remains_distinct(self):
        new = mapped(7,8)
        result = analyze(snapshot([(0xE000,[0xA9,8,0x53,128],MPR),
                                   (0xE004,[0x4C,0,0xE0],new),
                                   (0xE000,[0x60],new)]),follow_mappings=True)
        self.assertIn((0xE000,MPR),keys(result))
        self.assertIn((0xE000,new),keys(result))
        ids = [row['node_id'] for row in result['instructions']]
        self.assertEqual(ids,list(range(len(ids))))

    def test_missing_bytes_and_unassigned_opcode_keep_explicit_reasons(self):
        result = analyze(snapshot([(0xE000,[0x0B],MPR)]),follow_mappings=True)
        self.assertFalse(result['instructions'][0]['native_supported'])
        self.assertEqual(result['unresolved'][0]['reason'],'unassigned_opcode')
        missing = analyze(snapshot([(0xE000,[0xEA],MPR)]),follow_mappings=True)
        self.assertEqual(missing['unresolved'][0]['reason'],'bytes_not_in_snapshot')
        self.assertEqual(missing['unresolved'][0]['pc'],0xE001)

    def test_context_and_instruction_limits_stop_with_target_identity(self):
        new = mapped(7,8)
        source = snapshot([(0xE000,[0xA9,8,0x53,128],MPR),(0xE004,[0x60],new)])
        result = analyze(source,follow_mappings=True,context_limit=1)
        row = next(row for row in result['unresolved'] if row['reason']=='context_limit')
        self.assertEqual(row['target'],dict(pc=0xE004,mpr=list(new)))
        self.assertEqual(result['summary']['contexts'],1)
        short = analyze(source,limit=1,follow_mappings=True)
        self.assertEqual(len(short['instructions']),1)
        self.assertEqual(short['unresolved'][0]['reason'],'instruction_limit')
        exact = analyze(source,limit=3,follow_mappings=True,context_limit=2)
        self.assertIn((0xE004,new),keys(exact))
        self.assertFalse(any(row['reason'].endswith('_limit') for row in exact['unresolved']))

    def test_initial_entries_are_unknown_even_when_other_entry_proves_a(self):
        result = analyze(snapshot([(0xE000,[0xA9,8,0x53,128],MPR)],
                                  entries=(0xE000,0xE002)),follow_mappings=True)
        self.assertTrue(any(row['reason']=='mapping_change' for row in result['unresolved']))

    def test_limits_count_explored_contexts_even_after_optimistic_path_is_pruned(self):
        # The first branch provisionally reaches bank9 before its A facts merge
        # to unknown. A separate, later entry must not reclaim that exploration
        # allowance and silently exceed the configured total-context bound.
        source = snapshot([(0xE000,[0xD0,6,0xA9,8,0x80,4],MPR),
                           (0xE008,[0xA9,9,0x53,128],MPR),
                           (0xE00C,[0x60],mapped(7,9)),
                           (0xE100,[0xEA]*8+[0xA9,10,0x53,128],MPR),
                           (0xE10C,[0x60],mapped(7,10))], entries=(0xE000,0xE100))
        result = analyze(source,follow_mappings=True,context_limit=2)
        self.assertEqual(result['summary']['explored_contexts'],2)
        self.assertEqual(result['summary']['contexts'],1)
        self.assertGreater(result['summary']['explored_states'],len(result['instructions']))
        self.assertTrue(any(row['reason']=='context_limit' and row['pc']==0xE10A
                            for row in result['unresolved']))
        self.assertNotIn((0xE00C,mapped(7,9)),keys(result))
        self.assertNotIn((0xE10C,mapped(7,10)),keys(result))

    def test_deterministic_output_and_full_context_edges(self):
        source = snapshot([(0xE000,[0xA9,8,0x53,128],MPR),
                           (0xE004,[0x60],mapped(7,8))])
        a = analyze(source,follow_mappings=True)
        b = analyze(source,follow_mappings=True)
        self.assertEqual(json.dumps(a),json.dumps(b))
        nodes = {row['node_id']:row for row in a['instructions']}
        for edge in a['edges']:
            for endpoint in ('from','to'):
                if endpoint+'_id' in edge:
                    node = nodes[edge[endpoint+'_id']]
                    self.assertEqual(edge[endpoint],dict(pc=node['pc'],mpr=node['mpr']))

    def test_invalid_options_and_context_snapshot(self):
        source = snapshot([(0xE000,[0x60],MPR)])
        for options in (dict(limit=True),dict(limit=0),dict(limit=100001),dict(limit=1.5),
                        dict(follow_mappings=1),dict(follow_mappings='yes'),
                        dict(context_limit=True),dict(context_limit=0),dict(context_limit=4097)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                analyze(source,**options)
        for broken in (Snapshot((0,)*7,{},(0xE000,),'bad'),
                       Snapshot((False,)+MPR[1:],{},(0xE000,),'bad'),
                       Snapshot(MPR,{},(True,),'bad'), Snapshot(MPR,{},(),'bad')):
            with self.assertRaises(ValueError):
                analyze(broken,follow_mappings=True)


if __name__ == '__main__':
    unittest.main()
