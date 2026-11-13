"""Authored mutable-data/pointer facts, joins, invalidation and strict admission."""
import json
import subprocess
import sys
import unittest

from pcerecomp import discovery
from pcerecomp.isa import decode
from test_discovery import seed
import test_discovery_vectors as helpers

MPR = (0,248,0,0,0,0,0,0)


class WramDiscoveryTests(unittest.TestCase):
    setUp = helpers.VectorDiscoveryTests.setUp

    def inputs(self, text, patches=(), mpr=MPR):
        code=bytes.fromhex(text)
        size=len(decode(lambda a:code[a-0xE000],0xE000,mpr).data)
        helpers.VectorDiscoveryTests.inputs(self,[(0,code),*patches],roots=[seed(size=size,mpr=mpr)])
        self.ranges=[(0,len(code)),*((off,len(data)) for off,data in patches)]

    def graph(self,name='graph',**options):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,
            rom_ranges=self.ranges,alu_facts=True,branch_facts=True,stack_facts=True,
            wram_facts=True,call_depth_limit=8,wram_data_ranges=options.pop('wram_data_ranges',[(0,64)]),**options)

    @staticmethod
    def node(graph,offset):
        return next(n for n in graph.report['nodes'] if n['pc']==0xE000+offset)

    def test_written_variable_recovers_mapping_without_assuming_initial_zero(self):
        self.inputs('A9 03 85 00 A9 FF A5 00 53 04 80 FE')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['nodes'][-1]['mpr'][2],3)
        self.assertIsNone(g.report['nodes'][0]['wram_facts'][0]['value'])
        load=self.node(g,6)['data_load'];self.assertEqual(load['value'],3)
        self.assertEqual(load['reads'][0]['storage'],'wram')
        old=discovery.discover_roots(self.seeds,self.image,self.root/'old',rom_ranges=self.ranges,
            alu_facts=True,branch_facts=True,stack_facts=True,call_depth_limit=8)
        self.assertEqual({p['reason'] for p in old.report['unresolved']},{'mapping_change'})

    def test_uninitialized_unpermitted_or_io_reads_do_not_invent_values(self):
        for index,(code,reason) in enumerate((('AD 00 20 53 04','wram_value_unknown'),
            ('AD 80 20 53 04','allowed_wram_data_boundary'),('AD 00 00 53 04','non_rom_data'))):
            self.inputs(code,mpr=(255,248,0,0,0,0,0,0));g=self.graph(str(index))
            self.assertEqual(g.report['nodes'][0]['data_load']['reason'],reason)
            self.assertEqual({p['reason'] for p in g.report['unresolved']},{'mapping_change'})

    def test_all_store_registers_zero_and_load_destinations(self):
        self.inputs('A9 12 A2 34 A0 56 85 00 86 01 84 02 64 03 A5 00 A6 01 A4 02 80 FE')
        end=self.graph().report['nodes'][-1]
        self.assertEqual(end['register_facts'],dict(a=0x12,x=0x34,y=0x56))
        self.assertEqual([r['value'] for r in end['wram_facts'][:4]],[0x12,0x34,0x56,0])

    def test_aliases_and_wrapped_absolute_index_share_canonical_bytes(self):
        self.inputs('A2 01 A9 42 9D FF FF AD 00 20 80 FE',mpr=(249,248,0,0,0,0,0,0))
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['nodes'][-1]['register_facts']['a'],0x42)
        effect=self.node(g,4)['wram_effect'];self.assertEqual(effect['logical_address'],0)
        self.assertEqual(effect['writes'][0]['offset'],0)

    def test_direct_page_index_wrap_and_indirect_pointer_wrap(self):
        self.inputs('A9 30 85 FF A9 20 85 00 A9 42 85 30 B2 FF 80 FE')
        g=self.graph(wram_data_ranges=[(0,64),(255,1)])
        self.assertEqual(g.report['nodes'][-1]['register_facts']['a'],0x42)
        self.assertEqual([r['wram_offset'] for r in self.node(g,12)['data_load']['reads']],[255,0,48])
        self.inputs('A2 01 A9 03 95 FF B5 FF 53 04 80 FE')
        self.assertEqual(self.graph('indexed').report['nodes'][-1]['mpr'][2],3)

    def test_indexed_indirect_and_indirect_indexed_load_and_store(self):
        self.inputs('A9 30 85 02 A9 20 85 03 A2 02 A0 01 A9 42 81 00 A9 43 91 02 A1 00 B1 02 80 FE')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        end=g.report['nodes'][-1];self.assertEqual(end['register_facts']['a'],0x43)
        self.assertEqual([r['value'] for r in end['wram_facts'][48:50]],[0x42,0x43])

    def test_known_rmw_results_and_status(self):
        cases=[('06',128,0,0,1,0,1),('46',1,0,0,1,0,1),
               ('26',128,1,1,1,0,0),('66',1,1,128,1,1,0),
               ('E6',255,0,0,0,0,1),('C6',0,0,255,0,1,0)]
        for i,(op,byte,carry,result,c,n,z) in enumerate(cases):
            self.inputs(f'A9 {byte:02X} 85 00 '+('38' if carry else '18')+f' {op} 00 80 FE')
            end=self.graph(str(i)).report['nodes'][-1]
            self.assertEqual(end['wram_facts'][0]['value'],result)
            self.assertEqual({k:end['flag_facts'][k] for k in ('c','n','z')},dict(c=c,n=n,z=z))

    def test_rotate_with_unknown_carry_preserves_only_known_outgoing_carry(self):
        self.inputs('A9 80 85 00 26 00 80 FE')
        end=self.graph().report['nodes'][-1]
        self.assertIsNone(end['wram_facts'][0]['value'])
        self.assertEqual(end['flag_facts']['c'],1)
        self.assertIsNone(end['flag_facts']['n']);self.assertIsNone(end['flag_facts']['z'])

    def test_bit_set_reset_preserve_flags_and_resolve_wram_bit_branches(self):
        for index,change in enumerate(('07 00','87 00')):
            self.inputs('A9 01 85 00 '+change+' 0F 00 04 A9 02 80 02 A9 03 53 04 80 FE')
            g=self.graph(str(index));self.assertEqual(g.report['unresolved'],[])
            end=g.report['nodes'][-1]
            self.assertEqual(end['mpr'][2],3 if index==0 else 2)
            cond=next(n['conditional'] for n in g.report['nodes'] if 'conditional' in n)
            self.assertEqual(cond['reads'][0]['storage'],'wram')

    def test_tsb_trb_huc6280_nvz_and_memory_result(self):
        for index,(op,initial,a,result,pflags) in enumerate((('04',0x80,0x40,0xC0,(1,0,0)),
            ('14',0xC0,0xC0,0,(1,1,1)),('04',0,0,0,(0,0,1)))):
            self.inputs(f'A9 {initial:02X} 85 00 A9 {a:02X} {op} 00 80 FE')
            end=self.graph(str(index)).report['nodes'][-1]
            self.assertEqual(end['wram_facts'][0]['value'],result)
            self.assertEqual(tuple(end['flag_facts'][k] for k in ('n','v','z')),pflags)

    def test_bit_and_tst_modes_use_known_operand_bits(self):
        for index,op in enumerate(('24 00','34 00','2C 00 20','3C 00 20','83 40 00','A3 40 00','93 40 00 20','B3 40 00 20')):
            self.inputs('A9 C0 85 00 A9 40 A2 00 '+op+' 80 FE')
            end=self.graph(str(index)).report['nodes'][-1]
            self.assertEqual(tuple(end['flag_facts'][k] for k in ('n','v','z')),(1,1,0))

    def test_transfer_alu_writes_memory_and_preserves_accumulator(self):
        cases=[('09',0x80,1,0x81,0,1,0,0),('29',0x80,0,0,0,0,1,0),
            ('49',0xFF,0xFF,0,0,0,1,0),('69',0x7F,1,0x80,0,1,0,1)]
        for index,(op,left,right,result,c,n,z,v) in enumerate(cases):
            self.inputs(f'A9 {left:02X} 85 00 A9 55 A2 00 D8 18 B8 F4 {op} {right:02X} 80 FE')
            end=self.graph(str(index)).report['nodes'][-1]
            self.assertEqual(end['register_facts']['a'],0x55)
            self.assertEqual(end['wram_facts'][0]['value'],result)
            self.assertEqual(tuple(end['flag_facts'][k] for k in ('c','n','z','v','t')),(c,n,z,v,0))

    def test_transfer_decimal_and_sbc_destination(self):
        self.inputs('A9 99 85 00 A9 55 A2 00 F8 18 B8 F4 69 01 80 FE')
        end=self.graph().report['nodes'][-1]
        self.assertEqual(end['wram_facts'][0]['value'],0)
        self.assertEqual(end['register_facts']['a'],0x55)
        self.assertEqual(tuple(end['flag_facts'][k] for k in ('c','n','z','v')),(1,0,1,0))
        self.inputs('A9 42 85 00 A9 05 D8 38 F4 E9 02 80 FE')
        end=self.graph('sbc').report['nodes'][-1]
        self.assertEqual(end['register_facts']['a'],3);self.assertEqual(end['wram_facts'][0]['value'],0x42)

    def test_transfer_unknown_index_or_status_invalidates_possible_destinations(self):
        for index,text in enumerate(('A9 02 85 00 F4 09 00 A5 00 53 04',
            'A2 00 A9 02 85 00 AD 00 22 48 28 69 00 A5 00 53 04')):
            self.inputs(text);g=self.graph(str(index))
            self.assertEqual({p['reason'] for p in g.report['unresolved']},{'mapping_change'})
            self.assertIsNone(g.report['nodes'][-1]['wram_facts'][0]['value'])

    def test_invalid_decimal_and_unknown_operand_do_not_predict_written_bytes(self):
        for index,text in enumerate(('A9 FA 85 00 A2 00 F8 18 F4 69 01 80 FE',
            'A9 01 85 00 A2 00 D8 18 F4 6D 80 20 80 FE')):
            self.inputs(text);end=self.graph(str(index)).report['nodes'][-1]
            self.assertIsNone(end['wram_facts'][0]['value']);self.assertIsNone(end['flag_facts']['z'])

    def test_unknown_store_and_block_writes_invalidate_existing_facts(self):
        for index,text in enumerate(('A9 02 85 00 81 10 A5 00 53 04',
            'A9 02 85 00 73 00 E0 00 20 01 00 A5 00 53 04')):
            self.inputs(text);g=self.graph(str(index))
            self.assertEqual(g.report['summary']['wram_invalidations'],1)
            self.assertIsNone(g.report['nodes'][-1]['wram_facts'][0]['value'])

    def test_known_untracked_write_does_not_destroy_unrelated_bytes(self):
        self.inputs('A9 03 85 00 8D 00 24 A5 00 53 04 80 FE')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['nodes'][-1]['mpr'][2],3)

    def test_unknown_stored_value_replaces_an_old_known_byte(self):
        self.inputs('A9 03 85 00 AD 00 22 85 00 A5 00 53 04')
        g=self.graph()
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'mapping_change'})
        self.assertIsNone(g.report['nodes'][-1]['wram_facts'][0]['value'])

    def test_same_pointer_instruction_is_recomputed_per_calling_state(self):
        self.inputs('A9 20 85 00 A9 E0 85 01 20 40 E0 A9 30 85 00 20 40 E0 80 FE',
            [(0x20,b'\x60'),(0x30,b'\x60'),(0x40,bytes.fromhex('6C 00 20'))])
        g=self.graph()
        self.assertEqual(g.report['unresolved'],[])
        self.assertEqual({n['wram_vector']['target'] for n in g.report['nodes'] if 'wram_vector' in n},{0xE020,0xE030})
        self.assertEqual(g.report['summary']['resolved_returns'],2)

    def test_conflicting_pointer_join_retracts_optimistic_targets(self):
        self.inputs('A9 E0 85 01 B0 06 A9 20 85 00 80 04 A9 30 85 00 6C 00 20',
            [(0x20,bytes.fromhex('80 FE')),(0x30,bytes.fromhex('80 FE'))])
        g=self.graph()
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'wram_value_unknown'})
        self.assertFalse({0xE020,0xE030}&{n['pc'] for n in g.report['nodes']})

    def test_unknown_index_does_not_enumerate_or_cache_mutable_tables(self):
        self.inputs('7C 00 20')
        g=self.graph(rom_table_limit=1,rom_vector_ranges=[(0x1000,257)])
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'wram_vector_index_unknown'})
        self.assertEqual(g.report['summary']['explored_vector_tables'],0)

    def test_join_equal_bytes_survive_conflicts_retract_stale_mapping(self):
        for index,right in enumerate((1,2)):
            self.inputs(f'B0 06 A9 01 85 00 80 04 A9 {right:02X} 85 00 A5 00 53 04 80 FE')
            g=self.graph(str(index))
            if right==1:
                self.assertEqual(g.report['unresolved'],[]);self.assertEqual(g.report['nodes'][-1]['mpr'][2],1)
            else:
                self.assertEqual({p['reason'] for p in g.report['unresolved']},{'mapping_change'})
                self.assertEqual({n['mpr'][2] for n in g.report['nodes']},{0})

    def test_written_indirect_vector_requires_both_authorized_proven_bytes(self):
        self.inputs('A9 20 85 00 A9 E0 85 01 6C 00 20',[(0x20,bytes.fromhex('80 FE'))])
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['summary']['resolved_wram_vectors'],1)
        self.assertEqual(self.node(g,8)['wram_vector']['target'],0xE020)
        denied=self.graph('denied',wram_data_ranges=[(0,1)])
        self.assertEqual({p['reason'] for p in denied.report['unresolved']},{'allowed_wram_data_boundary'})

    def test_known_index_vector_unknown_index_frontier_and_no_ram_code_admission(self):
        self.inputs('A9 20 85 02 A9 E0 85 03 A2 02 7C 00 20',[(0x20,bytes.fromhex('80 FE'))])
        self.assertEqual(self.graph().report['unresolved'],[])
        self.inputs('7C 00 20')
        self.assertEqual({p['reason'] for p in self.graph('unknown').report['unresolved']},{'wram_vector_index_unknown'})
        self.inputs('A9 20 85 00 A9 20 85 01 6C 00 20')
        g=self.graph('ram');self.assertEqual({p['reason'] for p in g.report['unresolved']},{'non_rom_fetch'})

    def test_mixed_rom_and_wram_pointer_bytes_keep_permissions_separate(self):
        self.inputs('A9 E0 85 00 6C FF 1F',[(0x1FFF,b'\x20'),(0x20,bytes.fromhex('80 FE'))])
        g=self.graph(rom_vector_ranges=[(0x1FFF,1)])
        self.assertEqual(g.report['unresolved'],[])
        self.assertEqual([r['storage'] for r in self.node(g,4)['wram_vector']['reads']],['rom','wram'])
        denied=self.graph('denied');self.assertEqual({p['reason'] for p in denied.report['unresolved']},{'missing_vector_permission'})

    def test_safe_indirect_write_can_cross_call_frame_but_stack_alias_cannot(self):
        for index,high in enumerate((0x20,0x21)):
            self.inputs(f'A9 00 85 00 A9 {high:02X} 85 01 20 20 E0 80 FE',
                [(0x20,bytes.fromhex('A9 42 92 00 60'))])
            g=self.graph(str(index))
            self.assertEqual({p['reason'] for p in g.report['unresolved']},
                set() if high==0x20 else {'stack_write_barrier','unresolved_call_return'})

    def test_exact_options_range_bounds_and_stack_exclusion(self):
        self.inputs('EA 80 FD')
        for index,ranges in enumerate((None,[],[(0,257)],[(256,1)],[(255,2)],[(8192,1)],[(0,True)])):
            with self.assertRaises(ValueError):self.graph(str(index),wram_data_ranges=ranges)
            self.assertFalse((self.root/str(index)).exists())
        for index,value in enumerate((None,1,[],True)):
            with self.assertRaises(ValueError):discovery.discover_roots(self.seeds,self.image,self.root/f'option{index}',rom_ranges=self.ranges,wram_facts=value,wram_data_ranges=[(0,1)])

    def test_saved_cells_effects_vectors_and_options_are_rederived(self):
        self.inputs('A9 20 85 00 A9 E0 85 01 6C 00 20',[(0x20,bytes.fromhex('80 FE'))]);g=self.graph();raw=g.report_path.read_bytes()
        for field in ('cell','write','vector','option','range','summary'):
            value=json.loads(raw)
            if field=='cell':value['nodes'][1]['wram_facts'][0]['value']=4
            elif field=='write':value['nodes'][1]['wram_effect']['writes'][0]['value']=4
            elif field=='vector':next(n for n in value['nodes'] if 'wram_vector' in n)['wram_vector']['target']+=1
            elif field=='option':value['options']['wram_facts']=1
            elif field=='range':value['options']['wram_data_ranges'][0]['start']=1
            else:value['summary']['resolved_wram_vectors']+=1
            g.report_path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(g.report_path,self.image)
        g.report_path.write_bytes(raw)
        copied=discovery.copy_discovery(g.report_path,self.image,self.root/'copy');self.assertEqual(copied.sha256,g.sha256)

    def test_cli_requires_prerequisites_and_admits_exact_mode(self):
        self.inputs('A9 02 85 00 A5 00 80 FE')
        args=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),
              '--rom-range','0:8','--wram-facts','--wram-data-range','0:1']
        bad=subprocess.run([*args,'--out',str(self.root/'bad')],capture_output=True,text=True,timeout=15)
        self.assertEqual(bad.returncode,2)
        good=subprocess.run([*args,'--alu-facts','--branch-facts','--stack-facts','--call-depth','8',
            '--out',str(self.root/'good')],capture_output=True,text=True,timeout=15)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertEqual(discovery.load_discovery(self.root/'good',self.image).report['analysis_policy'],discovery.WRAM_POLICY)
