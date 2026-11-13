"""Independent saved-byte/status, calling-frame and unsafe-frontier expectations."""
import json
import subprocess
import sys
import unittest

from pcerecomp import discovery
from pcerecomp.isa import decode
from pcerecomp import stack_facts
from test_discovery import seed
import test_discovery_vectors as helpers

MPR = (0, 248, 0, 0, 0, 0, 0, 0)


class StackValueDiscoveryTests(unittest.TestCase):
    setUp = helpers.VectorDiscoveryTests.setUp

    def inputs(self, text, patches=(), mpr=MPR):
        code = bytes.fromhex(text)
        helpers.VectorDiscoveryTests.inputs(self, [(0, code), *patches], roots=[seed(size=len(decode(lambda a: code[(a-0xE000)&65535], 0xE000, mpr).data), mpr=mpr)])
        self.ranges = [(0, len(code)), *((offset, len(data)) for offset, data in patches)]

    def graph(self, name='graph', **options):
        return discovery.discover_roots(self.seeds, self.image, self.root/name,
            rom_ranges=self.ranges, call_depth_limit=8, alu_facts=True,
            branch_facts=True, stack_facts=True, **options)

    def node(self, graph, offset):
        return next(n for n in graph.report['nodes'] if n['pc'] == 0xE000+offset)

    def test_saved_registers_restore_bank_and_indirect_index(self):
        self.inputs('A9 02 48 A9 03 68 53 04 A2 00 DA A2 07 FA 7C 00 E1',
                    [(0x100, bytes.fromhex('20 E1')), (0x120, bytes.fromhex('80 FE'))])
        graph = self.graph(rom_vector_ranges=[(0x100, 2)])
        self.assertEqual(graph.report['unresolved'], [])
        end = self.node(graph, 0x120)
        self.assertEqual(end['register_facts'], dict(a=2, x=0, y=None))
        self.assertEqual(end['mpr'][2], 2)
        self.assertEqual(end['stack_facts'], [])
        old = discovery.discover_roots(self.seeds, self.image, self.root/'old',
            rom_ranges=self.ranges, call_depth_limit=8, alu_facts=True, branch_facts=True)
        self.assertIn('mapping_change', {p['reason'] for p in old.report['unresolved']})

    def test_all_register_push_pop_pairs_and_lifo(self):
        self.inputs('A9 80 48 A2 00 DA A0 FF 5A A9 01 A2 02 A0 03 7A FA 68 80 FE')
        graph = self.graph(); end = graph.report['nodes'][-1]
        self.assertEqual(end['register_facts'], dict(a=128, x=0, y=255))
        self.assertEqual({k: end['flag_facts'][k] for k in ('n', 'z')}, dict(n=1, z=0))
        self.assertEqual(graph.report['summary']['stack_pops'], 3)
        self.assertEqual(graph.report['summary']['peak_stack_bytes'], 3)

    def test_php_forces_saved_b_and_clears_saved_t_even_after_set(self):
        self.inputs('A9 FF 48 28 F4 08 68 80 FE')
        graph = self.graph(); end = graph.report['nodes'][-1]
        self.assertEqual(end['register_facts']['a'], 0xDF)
        self.assertEqual(end['flag_facts'], dict(c=1, d=1, t=0, n=1, z=0, v=1, i=1))
        php = self.node(graph, 5)['stack_event']['pushed']
        self.assertEqual(php, [dict(known_mask=255, value=0xDF)])

    def test_plp_restores_t_and_i_but_pops_clear_t_and_update_nz(self):
        self.inputs('A9 24 48 28 A9 02 69 01 80 FE')
        graph = self.graph(); restored = self.node(graph, 4)
        self.assertEqual(restored['flag_facts']['t'], 1)
        self.assertEqual(restored['flag_facts']['i'], 1)
        # LDA clears T before ADC; restoring T is not allowed to leak past it.
        self.assertEqual(graph.report['nodes'][-1]['register_facts']['a'], 3)

    def test_partial_php_can_prove_nz_without_inventing_other_bits(self):
        self.inputs('08 68 80 FE')
        end = self.graph().report['nodes'][-1]
        self.assertIsNone(end['register_facts']['a'])
        self.assertIsNone(end['flag_facts']['n'])
        self.assertEqual(end['flag_facts']['z'], 0)  # Stored B guarantees nonzero.
        self.assertEqual(self.node(self.graph('again'), 1)['stack_facts'],
                         [dict(known_mask=0x30, value=0x10)])

    def test_restored_t_routes_adc_to_unknown_direct_page_without_changing_a(self):
        self.inputs('A2 00 A9 24 48 28 69 01 80 FE')
        end = self.graph().report['nodes'][-1]
        self.assertEqual(end['register_facts']['a'], 0x24)
        self.assertIsNone(end['flag_facts']['c'])
        self.assertIsNone(end['flag_facts']['n'])
        self.assertIsNone(end['flag_facts']['z'])
        self.assertEqual(end['flag_facts']['t'], 0)

    def test_unknown_saved_register_is_not_initial_memory_and_alias_writes_stop(self):
        self.inputs('48 68 80 FE')
        end = self.graph().report['nodes'][-1]
        self.assertIsNone(end['register_facts']['a'])
        self.assertIsNone(end['flag_facts']['n'])
        self.assertIsNone(end['flag_facts']['z'])
        self.inputs('48 8D 00 41', mpr=(0,248,251,0,0,0,0,0))
        graph = self.graph('alias')
        self.assertEqual({p['reason'] for p in graph.report['unresolved']}, {'stack_write_barrier'})

    def test_empty_stack_does_not_guess_sp_and_status_controls_preserve_saved_i(self):
        self.inputs('78 08 58 28 BA 80 FE')
        graph = self.graph(); end = graph.report['nodes'][-1]
        self.assertEqual(end['flag_facts']['i'], 1)
        self.assertIsNone(end['register_facts']['x'])  # Relative depth never supplies an absolute SP.

    def test_return_and_interrupt_frontiers_are_not_invented(self):
        for index, (code, reason) in enumerate((('60','dynamic_return'),('40','interrupt_return'),('00 00','interrupt_vector'))):
            self.inputs(code)
            graph = self.graph(str(index))
            self.assertEqual({p['reason'] for p in graph.report['unresolved']}, {reason})

    def test_stack_saved_rom_index_composes_with_explicit_operand_permissions(self):
        self.inputs('A2 02 DA A2 09 FA BD 00 E1 53 04 80 FE', [(0x102,b'\x03')])
        graph = self.graph(rom_data_ranges=[(0x102,1)])
        self.assertEqual(graph.report['unresolved'], [])
        self.assertEqual(graph.report['nodes'][-1]['mpr'][2], 3)
        denied = self.graph('denied')
        self.assertEqual({p['reason'] for p in denied.report['unresolved']}, {'mapping_change'})

    def test_status_roundtrips_every_byte_with_independent_expected_bits(self):
        plp = decode(lambda a: 0x28, 0xE000, MPR)
        php = decode(lambda a: 0x08, 0xE000, MPR)
        for byte in range(256):
            incoming = (None,)*9 + (None, ((255, byte),))
            restored, _ = stack_facts.transfer(plp, incoming, (None,)*9)
            self.assertEqual(restored[3:10], tuple((byte >> b) & 1 for b in (0,3,5,7,1,6,2)))
            saved, event = stack_facts.transfer(php, restored, restored[:9])
            self.assertEqual(saved[10], ((255, (byte | 16) & ~32),))
            self.assertEqual(event['pushed'][0]['value'], (byte | 16) & ~32)

    def test_conflicting_saved_bytes_join_bitwise_and_retract_mapping(self):
        # Unknown entry carry picks 0x80 or 0x81; only one saved bit differs.
        self.inputs('B0 05 A9 80 48 80 03 A9 81 48 68 53 04 80 FE')
        graph = self.graph(); pop = self.node(graph, 10)
        self.assertEqual(pop['stack_facts'], [dict(known_mask=254, value=128)])
        self.assertEqual(pop['register_evaluation']['flags']['n'], 1)
        self.assertEqual(pop['register_evaluation']['flags']['z'], 0)
        self.assertIsNone(pop['register_evaluation']['registers']['a'])
        self.assertEqual({p['reason'] for p in graph.report['unresolved']}, {'mapping_change'})
        self.assertEqual({n['mpr'][2] for n in graph.report['nodes']}, {0})

    def test_partial_status_join_restores_only_common_bits(self):
        self.inputs('B0 05 A9 05 48 80 03 A9 04 48 28 80 FE')
        end = self.graph().report['nodes'][-1]
        self.assertIsNone(end['flag_facts']['c'])
        self.assertEqual(end['flag_facts']['i'], 1)
        self.assertEqual(end['flag_facts']['d'], 0)
        self.assertEqual(end['flag_facts']['t'], 0)

    def test_nested_jsr_bsr_return_bytes_and_wram_aliases(self):
        self.inputs('A9 02 48 20 20 E0 68 53 04 80 FE',
            [(0x20, bytes.fromhex('A9 F9 53 02 A2 07 DA 44 07 FA 60')),
             (0x30, bytes.fromhex('A0 80 5A A0 00 7A 60'))])
        graph = self.graph()
        self.assertEqual(graph.report['unresolved'], [])
        end = self.node(graph, 9)
        self.assertEqual(end['register_facts'], dict(a=2, x=7, y=128))
        self.assertEqual(end['mpr'][1:3], [249, 2])
        self.assertEqual(graph.report['summary']['resolved_returns'], 2)
        self.assertEqual(self.node(graph, 3)['stack_event']['pushed'],
            [dict(known_mask=255, value=0xE0), dict(known_mask=255, value=5)])
        self.assertEqual(self.node(graph, 0x36)['stack_event']['popped'],
            [dict(known_mask=255, value=0x28), dict(known_mask=255, value=0xE0)])

    def test_unsafe_stack_frontiers_are_explicit(self):
        cases = [('68', 'stack_underflow'), ('48 9A', 'stack_pointer_change'),
            ('48 8D 00 21', 'stack_write_barrier'), ('48 9D 00 20', 'stack_write_barrier'),
            ('48 81 00', 'stack_write_barrier'), ('48 73 00 20 00 21 01 00', 'stack_write_barrier'),
            ('48 A9 00 53 02', 'stack_mapping_change'),
            ('20 10 E0', 'stack_frame_pop')]
        for index, (code, reason) in enumerate(cases):
            self.inputs(code, [(0x10, bytes.fromhex('68 60'))] if reason == 'stack_frame_pop' else ())
            graph = self.graph(str(index))
            self.assertEqual({p['reason'] for p in graph.report['unresolved']},
                {reason, 'unresolved_call_return'} if reason == 'stack_frame_pop' else {reason}, code)

    def test_non_wram_stack_refuses_and_all_canonical_aliases_work(self):
        for bank in (0, 247, 248, 249, 250, 251, 252, 255):
            self.inputs('A9 42 48 68 80 FE', mpr=(0,bank,0,0,0,0,0,0))
            graph = self.graph(str(bank))
            self.assertEqual({p['reason'] for p in graph.report['unresolved']},
                set() if 248 <= bank <= 251 else {'unsupported_stack_mapping'})

    def test_empty_stack_rebase_safe_writes_and_capacity(self):
        self.inputs('A2 FF 9A A9 42 48 A2 01 9D 00 22 85 00 68 80 FE')
        self.assertEqual(self.graph().report['unresolved'], [])
        self.inputs('48 80 FD')
        graph = self.graph('capacity', instruction_limit=1024)
        self.assertEqual({p['reason'] for p in graph.report['unresolved']}, {'stack_capacity'})
        self.assertEqual(graph.report['summary']['peak_stack_bytes'], 256)

    def test_tampering_saved_bits_events_policy_and_i_is_rederived(self):
        self.inputs('78 08 28 80 FE'); graph = self.graph(); raw = graph.report_path.read_bytes()
        for field in ('saved', 'event', 'i', 'option', 'policy', 'count'):
            data = json.loads(raw)
            if field == 'saved': self.node_data(data, 2)['stack_facts'][0]['value'] ^= 4
            elif field == 'event': self.node_data(data, 1)['stack_event']['pushed'][0]['known_mask'] = 255
            elif field == 'i': self.node_data(data, 3)['flag_facts']['i'] = 0
            elif field == 'option': data['options']['stack_facts'] = 1
            elif field == 'policy': data['analysis_policy'] = discovery.BRANCH_POLICY
            else: data['summary']['stack_transfers'] += 1
            graph.report_path.write_bytes(discovery._canonical(data, discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError): discovery.load_discovery(graph.report_path, self.image)
        graph.report_path.write_bytes(raw)
        self.assertEqual(discovery.copy_discovery(graph.report_path,self.image,self.root/'copy').sha256,graph.sha256)

    @staticmethod
    def node_data(data, offset):
        return next(n for n in data['nodes'] if n['pc'] == 0xE000+offset)

    def test_requires_exact_options_and_cli_composition(self):
        self.inputs('48 68 80 FE')
        for index, value in enumerate((1, None, [], True)):
            with self.assertRaises(ValueError):
                discovery.discover_roots(self.seeds,self.image,self.root/str(index),
                    rom_ranges=self.ranges,stack_facts=value)
            self.assertFalse((self.root/str(index)).exists())
        argv=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),
              '--rom-range','0:4','--stack-facts','--alu-facts','--branch-facts','--call-depth','8']
        result=subprocess.run([*argv,'--out',str(self.root/'cli')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(discovery.load_discovery(self.root/'cli',self.image).report['analysis_policy'], discovery.STACK_POLICY)
