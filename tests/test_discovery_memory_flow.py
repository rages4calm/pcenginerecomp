"""Original ordered-copy, mutable-table and proven-mapper-address expectations."""
import hashlib
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from pcerecomp import discovery, memory_flow
from pcerecomp.isa import decode
from test_discovery import seed
import test_discovery_vectors as helpers

MPR=(0,248,251,0,0,0,0,0)


class MemoryFlowTests(unittest.TestCase):
    setUp=helpers.VectorDiscoveryTests.setUp

    def inputs(self,text,patches=(),mpr=MPR,profile='base'):
        code=bytes.fromhex(text);size=len(decode(lambda a:code[a-0xE000],0xE000,mpr).data)
        helpers.VectorDiscoveryTests.inputs(self,[(0,code),*patches],roots=[seed(size=size,mpr=mpr)],
            size=0x280000 if profile=='sf2' else 8192,profile=profile)
        self.ranges=[(0,len(code)),*((off,len(raw)) for off,raw in patches)]

    def graph(self,name='graph',**options):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,rom_ranges=self.ranges,
            alu_facts=True,branch_facts=True,stack_facts=True,wram_facts=True,call_depth_limit=8,
            memory_flow=True,block_transfer_limit=options.pop('block_transfer_limit',256),
            wram_data_ranges=options.pop('wram_data_ranges',[(0,64)]),**options)

    @staticmethod
    def node(g,offset):return next(n for n in g.report['nodes'] if n['pc']==0xE000+offset)

    def test_all_five_address_plans_include_wrap_and_alternation(self):
        expected={'TII':[(65535,65535),(0,0),(1,1)],'TDD':[(65535,65535),(65534,65534),(65533,65533)],
            'TIN':[(65535,65535),(0,65535),(1,65535)],'TIA':[(65535,65535),(0,0),(1,65535)],
            'TAI':[(65535,65535),(0,0),(65535,1)]}
        for name,rows in expected.items():self.assertEqual(list(memory_flow.block_addresses(name,65535,65535,3)),rows)

    def test_rom_copy_recovers_registers_data_and_later_mapping(self):
        self.inputs('A9 42 A2 03 A0 04 73 00 E1 00 20 02 00 A5 00 53 04 80 FE',[(0x100,b'\x02\x33')])
        g=self.graph(rom_data_ranges=[(0x100,2)]);self.assertEqual(g.report['unresolved'],[])
        end=self.node(g,17);self.assertEqual(end['register_facts'],dict(a=2,x=3,y=4))
        self.assertEqual(end['mpr'][2],2)
        effect=self.node(g,6)['block_effect'];self.assertTrue(effect['registers_preserved'])
        self.assertEqual([r['value'] for r in effect['transfers']],[2,51])
        self.assertEqual(g.report['summary']['known_block_reads'],2)

    def test_each_copy_mode_has_literal_destination_values(self):
        for index,(op,src,dst,expected) in enumerate((('73','00 E1','00 20',[1,2,3,4]),
            ('C3','03 E1','03 20',[1,2,3,4]),('E3','00 E1','00 20',[3,4,None,None]),
            ('F3','00 E1','00 20',[1,2,1,2]),('D3','00 E1','00 20',[4,None,None,None]))):
            self.inputs(f'{op} {src} {dst} 04 00 80 FE',[(0x100,bytes([1,2,3,4]))])
            g=self.graph(str(index),rom_data_ranges=[(0x100,4)])
            self.assertEqual([c['value'] for c in g.report['nodes'][-1]['wram_facts'][:4]],expected)

    def test_overlapping_reads_observe_earlier_writes_not_an_initial_snapshot(self):
        for index,(op,src,dst,expected) in enumerate((('73','00 20','01 20',[1,1,1,1]),
            ('C3','03 20','02 20',[4,4,4,4]),('E3','00 20','01 20',[1,1,1,4]),
            ('F3','00 20','01 20',[1,1,1,1]),('D3','00 20','01 20',[1,3,3,4]))):
            self.inputs(f'73 00 E1 00 20 04 00 {op} {src} {dst} 03 00 80 FE',[(0x100,bytes([1,2,3,4]))])
            g=self.graph(str(index),rom_data_ranges=[(0x100,4)])
            self.assertEqual([r['value'] for r in g.report['nodes'][-1]['wram_facts'][:4]],expected)

    def test_canonical_aliases_share_sequential_copy_values(self):
        self.inputs('73 00 E1 00 20 03 00 73 00 40 01 20 02 00 80 FE',[(0x100,bytes([7,8,9]))])
        g=self.graph(rom_data_ranges=[(0x100,3)])
        self.assertEqual([r['value'] for r in g.report['nodes'][-1]['wram_facts'][:3]],[7,7,7])

    def test_denied_and_unknown_sources_replace_old_values_with_unknown(self):
        self.inputs('A9 02 85 00 73 00 E1 00 20 02 00 A5 00 53 04',[(0x100,b'\x03\x04')])
        g=self.graph(rom_data_ranges=[(0x101,1)])
        effect=self.node(g,4)['block_effect'];self.assertEqual(effect['known_reads'],1)
        self.assertEqual(effect['unknown_reads'],1)
        self.assertEqual(effect['transfers'][0]['read_reason'],'allowed_data_boundary')
        self.assertIsNone(g.report['nodes'][-1]['wram_facts'][0]['value'])
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'mapping_change'})

    def test_block_can_cross_live_frame_only_when_all_writes_are_stack_disjoint(self):
        self.inputs('A9 42 48 20 20 E0 68 80 FE',[(0x20,bytes.fromhex('73 00 E1 00 20 01 00 60')),(0x100,b'\x03')])
        g=self.graph(rom_data_ranges=[(0x100,1)]);self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['nodes'][-1]['register_facts']['a'],0x42)
        self.assertEqual(g.report['summary']['maximum_temporary_stack_depth'],6)

    def test_any_stack_destination_alias_is_a_frontier_even_without_a_frame(self):
        for index,destination in enumerate(('00 21','00 41')):
            self.inputs(f'73 00 E1 {destination} 01 00 80 FE',[(0x100,b'\x01')])
            g=self.graph(str(index),rom_data_ranges=[(0x100,1)])
            self.assertEqual({p['reason'] for p in g.report['unresolved']},{'stack_write_barrier'})

    def test_temporary_stack_mapping_and_capacity_are_proved_before_copying(self):
        self.inputs('73 00 E1 00 20 01 00',[(0x100,b'\x01')],mpr=(0,0,0,0,0,0,0,0))
        self.assertEqual({p['reason'] for p in self.graph().report['unresolved']},{'unsupported_block_stack_mapping'})
        ins=decode(lambda a:bytes.fromhex('73 00 E1 00 20 01 00')[a-0xE000],0xE000,MPR)
        plan,pairs=memory_flow.plan_block(ins,MPR,254,'base',256)
        self.assertIsNone(pairs);self.assertEqual(plan['reason'],'stack_capacity')

    def test_zero_encoded_count_is_65536_not_an_empty_success(self):
        self.inputs('D3 00 E1 00 20 00 00')
        g=self.graph();event=g.report['nodes'][0]['block_effect']
        self.assertEqual(event['encoded_length'],0);self.assertEqual(event['length'],65536)
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'block_transfer_limit'})

    def test_transfer_state_bound_is_explicit_and_reprocessing_does_not_spend_twice(self):
        self.inputs('73 00 E1 00 20 02 00 73 00 E1 02 20 02 00 80 FE',[(0x100,b'\x01\x02')])
        with patch.object(memory_flow,'MAX_BLOCK_BYTES',3):
            g=self.graph(block_transfer_limit=2,rom_data_ranges=[(0x100,2)])
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'block_state_limit'})
        self.assertEqual(g.report['summary']['explored_block_bytes'],2)
        self.inputs('73 00 E1 00 20 02 00 80 F7',[(0x100,b'\x01\x02')])
        g=self.graph('loop',rom_data_ranges=[(0x100,2)])
        self.assertEqual(g.report['summary']['explored_block_states'],1)
        self.assertEqual(g.report['summary']['explored_block_bytes'],2)

    def test_safe_known_sf2_scalar_and_indirect_writes_no_longer_stop(self):
        for index,write in enumerate(('9D 10 20','91 02','9D E0 1F')):
            self.inputs('A9 00 85 02 A9 20 85 03 A2 00 A0 00 A9 02 85 00 '+write+' A5 00 53 04 80 FE',profile='sf2')
            g=self.graph(str(index));self.assertEqual(g.report['unresolved'],[])
            self.assertEqual(max(g.report['nodes'],key=lambda n:n['pc'])['mpr'][2],2)

    def test_sf2_latch_writes_and_unknown_addresses_still_stop(self):
        for index,text in enumerate(('A2 10 A9 42 9D E0 1F','A9 42 9D E0 1F',
            '73 00 E1 EF 1F 02 00')):
            self.inputs(text,profile='sf2');g=self.graph(str(index))
            self.assertEqual({p['reason'] for p in g.report['unresolved']},{'mapper_write_barrier'})

    def test_safe_block_sf2_span_is_checked_including_word_wrap(self):
        self.inputs('73 00 E1 FF 3F 02 00 80 FE',[(0x100,b'\x01\x02')],profile='sf2')
        g=self.graph(rom_data_ranges=[(0x100,2)])
        self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['nodes'][-1]['wram_facts'][0]['value'],2)

    def test_256_mutable_index_entries_include_rom_and_wram_pointer_bytes(self):
        self.inputs('F3 00 E1 00 20 00 01 7C FF 1F',[(0x100,b'\xE2\xE2'),(0x1FFF,b'\xE2'),(0x2E2,bytes.fromhex('80 FE'))])
        g=self.graph(wram_data_ranges=[(0,256)],rom_data_ranges=[(0x100,2)],rom_vector_ranges=[(0x1FFF,1)],wram_table_limit=1)
        self.assertEqual(g.report['unresolved'],[]);self.assertEqual(g.report['summary']['resolved_wram_table_entries'],256)
        table=next(n['wram_vector_table'] for n in g.report['nodes'] if 'wram_vector_table' in n)
        self.assertTrue(table['source_complete']);self.assertEqual({e['target'] for e in table['entries']},{0xE2E2})

    def test_mutable_table_permission_gaps_remain_per_index_frontiers(self):
        self.inputs('A9 20 85 00 A9 E0 85 01 7C 00 20',[(0x20,bytes.fromhex('80 FE'))])
        g=self.graph(wram_table_limit=1,wram_data_ranges=[(0,2)])
        table=next(n['wram_vector_table'] for n in g.report['nodes'] if 'wram_vector_table' in n)
        self.assertEqual(len(table['entries']),1);self.assertEqual(len(table['blocked']),255)
        self.assertFalse(table['source_complete']);self.assertEqual(table['entries'][0]['index'],0)

    def test_mutable_tables_recompute_per_caller_and_refine_x_per_edge(self):
        self.inputs('A9 20 85 00 A9 E0 85 01 20 40 E0 A9 30 85 00 20 40 E0 80 FE',
            [(0x20,b'\x60'),(0x30,b'\x60'),(0x40,bytes.fromhex('7C 00 20'))])
        g=self.graph(wram_table_limit=2,wram_data_ranges=[(0,2)])
        tables=[n['wram_vector_table'] for n in g.report['nodes'] if 'wram_vector_table' in n]
        # The first resolved edge refines X=0, retained through the return; the
        # second caller consequently uses the known-index pointer path.
        self.assertEqual(len(tables),1)
        self.assertEqual({n['wram_vector']['target'] for n in g.report['nodes'] if 'wram_vector' in n},{0xE030})
        self.assertEqual(self.node(g,0x20)['register_facts']['x'],0)

    def test_conflicting_pointer_join_retracts_stale_table_targets(self):
        self.inputs('A9 E0 85 01 B0 06 A9 20 85 00 80 04 A9 30 85 00 7C 00 20',
            [(0x20,bytes.fromhex('80 FE')),(0x30,bytes.fromhex('80 FE'))])
        g=self.graph(wram_table_limit=1,wram_data_ranges=[(0,2)])
        self.assertFalse({0xE020,0xE030}&{n['pc'] for n in g.report['nodes']})
        table=next(n['wram_vector_table'] for n in g.report['nodes'] if 'wram_vector_table' in n)
        self.assertEqual(table['entries'],[]);self.assertEqual(len(table['blocked']),256)

    def test_block_clears_t_and_preserves_other_status_without_inventing_registers(self):
        self.inputs('38 F8 B8 F4 73 00 E1 00 20 01 00 80 FE',[(0x100,b'\x02')])
        g=self.graph(rom_data_ranges=[(0x100,1)])
        end=self.node(g,11)
        self.assertEqual(end['register_facts'],dict(a=None,x=None,y=None))
        flags=end['flag_facts'];self.assertEqual((flags['c'],flags['d'],flags['t'],flags['v']),(1,1,0,0))
        self.assertIsNone(flags['n']);self.assertIsNone(flags['z'])

    def test_mutable_table_limit_applies_before_enumerating_another_state(self):
        self.inputs('7C 00 20',[(0x10,bytes.fromhex('7C 00 20'))])
        data=json.loads(self.seeds.read_text());data['roots'].append(seed(offset=0x10,size=3,mpr=MPR));self.seeds.write_text(json.dumps(data))
        g=self.graph(wram_table_limit=1)
        self.assertEqual(g.report['summary']['explored_wram_table_states'],1)
        self.assertIn('wram_table_limit',{p['reason'] for p in g.report['unresolved']})

    def test_omitting_table_opt_in_keeps_unknown_index_frontier(self):
        self.inputs('7C 00 20');g=self.graph()
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'wram_vector_index_unknown'})

    def test_block_records_table_entries_ranges_and_options_are_rederived(self):
        self.inputs('73 00 E1 00 20 02 00 7C 00 20',[(0x100,bytes.fromhex('20 E0')),(0x20,bytes.fromhex('80 FE'))])
        g=self.graph(rom_data_ranges=[(0x100,2)],wram_table_limit=1);raw=g.report_path.read_bytes()
        for field in ('transfer','temporary','entry','option','summary'):
            value=json.loads(raw)
            if field=='transfer':value['nodes'][0]['block_effect']['transfers'][0]['value']+=1
            elif field=='temporary':value['nodes'][0]['block_effect']['registers_preserved']=False
            elif field=='entry':next(n for n in value['nodes'] if 'wram_vector_table' in n)['wram_vector_table']['entries'][0]['target']+=1
            elif field=='option':value['options']['memory_flow']=1
            else:value['summary']['explored_block_bytes']+=1
            g.report_path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(g.report_path,self.image)
        g.report_path.write_bytes(raw)
        self.assertEqual(discovery.copy_discovery(g.report_path,self.image,self.root/'copy').sha256,g.sha256)

    def test_exact_limits_prerequisites_and_cli(self):
        self.inputs('EA 80 FD')
        for index,value in enumerate((None,0,True,65537)):
            with self.assertRaises(ValueError):self.graph(str(index),block_transfer_limit=value)
        args=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),'--rom-range','0:3','--memory-flow','--block-transfer-limit','256','--wram-table-limit','1']
        bad=subprocess.run([*args,'--out',str(self.root/'bad')],capture_output=True,text=True,timeout=15);self.assertEqual(bad.returncode,2)
        good=subprocess.run([*args,'--alu-facts','--branch-facts','--stack-facts','--call-depth','8','--wram-facts','--wram-data-range','0:1','--out',str(self.root/'good')],capture_output=True,text=True,timeout=15)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertEqual(discovery.load_discovery(self.root/'good',self.image).report['analysis_policy'],discovery.FLOW_POLICY)
