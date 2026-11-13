"""Authored address-selected mapper facts; no emulator/runtime expected values."""
import json
import subprocess
import sys
import unittest
from pcerecomp import discovery
from test_discovery import seed
import test_discovery_vectors as helpers

MPR=(0,248,251,0,0,64,0,0)

class MapperFlowTests(unittest.TestCase):
    setUp=helpers.VectorDiscoveryTests.setUp

    def inputs(self,text,patches=(),mpr=MPR,profile='sf2'):
        self.code=bytes.fromhex(text)
        helpers.VectorDiscoveryTests.inputs(self,[(0,self.code),*patches],roots=[seed(size=min(len(self.code),2),mpr=mpr)],
            size=0x280000 if profile=='sf2' else 8192,profile=profile)
        # First instruction may be three/seven bytes; the seed must bind it all.
        from pcerecomp.isa import decode
        size=len(decode(lambda a:self.code[a-0xE000],0xE000,mpr).data)
        value=json.loads(self.seeds.read_text(encoding='utf-8'));value['roots']=[seed(size=size,mpr=mpr)]
        self.seeds.write_text(json.dumps(value),encoding='utf-8')
        self.ranges=[(0,len(self.code)),*((off,len(raw)) for off,raw in patches)]

    def graph(self,name='g',**options):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,rom_ranges=self.ranges,
            alu_facts=True,branch_facts=True,stack_facts=True,wram_facts=True,call_depth_limit=8,
            wram_data_ranges=[(0,32)],memory_flow=True,block_transfer_limit=256,
            mapper_facts=options.pop('mapper_facts',True),**options)

    def test_all_sixteen_addresses_select_independently_of_unknown_data(self):
        for latch in range(16):
            self.inputs(f'8D {0xF0+latch:02X} 1F 80 FE')
            g=self.graph(str(latch));nodes=g.report['nodes']
            self.assertEqual(g.report['unresolved'],[])
            effect=next(n['mapper_effect'] for n in nodes if 'mapper_effect' in n)
            self.assertEqual((effect['selector_before'],effect['selector_after']),(0,latch))
            self.assertEqual(effect['selection_source'],'write_address')
            self.assertEqual(next(n for n in nodes if n['pc']==0xE003)['selector'],latch)

    def test_known_index_and_indirect_forms_and_rmw_do_not_need_known_write_values(self):
        for i,writer in enumerate(('9D F0 1F','99 F0 1F','81 02','91 00','92 03','0E F1 1F','CE F1 1F','9C F1 1F')):
            # Pointer[0:2]=$1FF0, pointer[3:5]=$1FF1, X=Y=1.
            self.inputs('A9 F0 85 00 A9 1F 85 01 A9 F1 85 03 A9 1F 85 04 A2 01 A0 01 '+writer+' 80 FE')
            g=self.graph(str(i));self.assertEqual(g.report['unresolved'],[])
            effect=next(n['mapper_effect'] for n in g.report['nodes'] if 'mapper_effect' in n)
            self.assertEqual(effect['selector_after'],1)

    def test_unknown_destination_still_stops_and_old_policy_is_unchanged(self):
        self.inputs('9D F0 1F 80 FE')
        self.assertEqual({p['reason'] for p in self.graph().report['unresolved']},{'mapper_write_barrier'})
        self.inputs('8D F1 1F 80 FE')
        self.assertEqual({p['reason'] for p in self.graph('old',mapper_facts=False).report['unresolved']},{'mapper_write_barrier'})

    def test_conflicting_index_join_retracts_speculative_mapper_continuations(self):
        self.inputs('B0 04 A2 01 80 02 A2 02 9D F0 1F 80 FE')
        g=self.graph()
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'mapper_write_barrier'})
        self.assertFalse(any(n['pc']==0xE00B for n in g.report['nodes']))
        self.assertEqual({n['selector'] for n in g.report['nodes']},{0})

    def test_safe_mapper_write_crosses_call_frame_and_returns_with_current_selector(self):
        self.inputs('20 20 E0 80 FE',[(0x20,bytes.fromhex('8D F1 1F 60'))])
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['summary']['resolved_returns'],1)
        end=next(n for n in g.report['nodes'] if n['pc']==0xE003)
        self.assertEqual((end['selector'],end['stack_bytes']),(1,0))

    def test_new_selector_drives_data_loads_and_subsequent_mpr_facts(self):
        self.inputs('8D F1 1F AD 00 A0 53 04 80 FE',[(0x100000,b'\x02')])
        g=self.graph(rom_data_ranges=[(0x100000,1)])
        end=next(n for n in g.report['nodes'] if n['pc']==0xE008)
        self.assertEqual((end['selector'],end['mpr'][2],end['register_facts']['a']),(1,2,2))
        load=next(n['data_load'] for n in g.report['nodes'] if 'data_load' in n)
        self.assertEqual(load['reads'][0]['rom_offset'],0x100000)

    def test_next_instruction_is_redecoded_under_new_window_and_permissions(self):
        mpr=(*MPR[:7],64)
        self.inputs('8D F1 1F',mpr=MPR)
        # Root fetch is in the window, not fixed ROM. A mapper write replaces
        # the following bytes; no stale initial-selector instruction is reused.
        value=json.loads(self.seeds.read_text(encoding='utf-8'));value['roots']=[dict(pc=0xE000,mpr=list(mpr),selector=0,rom_offsets=[0x80000,0x80001,0x80002])]
        self.seeds.write_text(json.dumps(value),encoding='utf-8')
        image=bytearray(self.image.read_bytes());image[0x80000:0x80003]=self.code;image[0x100003:0x100007]=bytes.fromhex('A9 42 80 FE');self.image.write_bytes(image)
        import hashlib
        value['image']['sha256']=hashlib.sha256(image).hexdigest();self.seeds.write_text(json.dumps(value),encoding='utf-8')
        self.ranges=[(0x80000,3),(0x100003,4)]
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        end=next(n for n in g.report['nodes'] if n['pc']==0xE005)
        self.assertEqual((end['selector'],end['rom_offsets'],end['register_facts']['a']),(1,[0x100005,0x100006],66))
        self.ranges=[(0x80000,3)]
        self.assertEqual({p['reason'] for p in self.graph('denied').report['unresolved']},{'allowed_rom_boundary'})

    def test_each_block_mode_changes_window_before_later_source_reads(self):
        # Sources A000 onward differ by selector; data is deliberately unrelated
        # to the selected address. The write address alone changes the window.
        expected={'73':([0,0,1,2],[10,11,22,33],3),
            'C3':([0,3,2,1],[13,42,31,20],0),
            'E3':([0,0,1,0],[10,11,22,13],1),
            'F3':([0,0,1,2],[10,11,20,31],3),
            'D3':([0,1,1,1],[10,21,22,23],1)}
        patches=[(0x80000+bank*0x80000,bytes(range(10+10*bank,14+10*bank))) for bank in range(4)]
        for op,(selectors,values,last) in expected.items():
            self.inputs(f'{op} '+('03 A0 F3 1F' if op=='C3' else '00 A0 F1 1F' if op=='D3' else '00 A0 F0 1F')+' 04 00 80 FE',patches)
            g=self.graph(op,rom_data_ranges=[(off,len(raw)) for off,raw in patches]);self.assertEqual(g.report['unresolved'],[])
            event=next(n['block_effect'] for n in g.report['nodes'] if 'block_effect' in n)
            self.assertEqual([r['selector_before'] for r in event['transfers']],selectors)
            self.assertEqual([r['value'] for r in event['transfers']],values)
            self.assertEqual(event['selector_after'],last)

    def test_unknown_block_data_does_not_prevent_address_selected_transition(self):
        self.inputs('73 00 A0 F1 1F 01 00 80 FE')
        g=self.graph();event=g.report['nodes'][0]['block_effect']
        self.assertEqual(event['unknown_reads'],1);self.assertEqual(event['selector_after'],1)
        self.assertEqual(g.report['unresolved'],[])

    def test_whole_span_stack_hazard_prevents_inference_even_if_latch_would_change(self):
        self.inputs('73 00 A0 F0 1F 12 01 80 FE')
        # Ends in $2101, so even the earlier valid latch writes cannot license
        # preserved stack/register assumptions for this operation.
        g=discovery.discover_roots(self.seeds,self.image,self.root/'wide',rom_ranges=self.ranges,
            alu_facts=True,branch_facts=True,stack_facts=True,wram_facts=True,call_depth_limit=8,
            wram_data_ranges=[(0,32)],memory_flow=True,block_transfer_limit=512,mapper_facts=True)
        self.assertEqual({p['reason'] for p in g.report['unresolved']},{'stack_write_barrier'})

    def test_boundary_change_and_each_internal_transition_are_counted_separately(self):
        self.inputs('8D F4 1F E3 00 A0 F0 1F 03 00 80 FE')
        g=self.graph();summary=g.report['summary']
        # Scalar 0->4 aliases window0, copy 4->0->1->0 ends where it started
        # in effective-window terms but still has two internal window changes.
        self.assertEqual(summary['mapper_writes'],4)
        self.assertEqual(summary['mapper_transitions'],4)
        self.assertEqual(summary['mapper_window_changes'],2)
        raw=g.report_path.read_bytes();value=json.loads(raw)
        block=next(n['block_effect'] for n in value['nodes'] if 'block_effect' in n)
        block['transfers'][1]['selector_before']=15
        g.report_path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
        with self.assertRaises(ValueError):discovery.load_discovery(g.report_path,self.image)

    def test_non_boolean_or_missing_dependencies_cannot_enable_mapper_facts(self):
        self.inputs('8D F1 1F 80 FE')
        for i,value in enumerate((None,1,'true',[])):
            with self.assertRaises(ValueError):self.graph(str(i),mapper_facts=value)
        with self.assertRaises(ValueError):discovery.discover_roots(self.seeds,self.image,self.root/'prereq',rom_ranges=self.ranges,mapper_facts=True)

    def test_options_witnesses_and_new_policy_are_rederived(self):
        self.inputs('8D F1 1F 80 FE');g=self.graph();raw=g.report_path.read_bytes()
        for field in ('option','selector','write','summary'):
            value=json.loads(raw)
            if field=='option':value['options']['mapper_facts']=1
            elif field=='summary':value['summary']['mapper_writes']+=1
            else:
                effect=next(n['mapper_effect'] for n in value['nodes'] if 'mapper_effect' in n)
                effect['selector_after' if field=='selector' else 'writes']+=1
            g.report_path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(g.report_path,self.image)
        g.report_path.write_bytes(raw);self.assertEqual(discovery.copy_discovery(g.report_path,self.image,self.root/'copy').sha256,g.sha256)
        self.inputs('EA',profile='base')
        with self.assertRaises(ValueError):self.graph('bad-base')

    def test_cli_requires_explicit_dependencies(self):
        self.inputs('8D F1 1F 80 FE')
        args=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),'--rom-range','0:5','--mapper-facts']
        bad=subprocess.run([*args,'--out',str(self.root/'bad')],capture_output=True,text=True,timeout=15);self.assertEqual(bad.returncode,2)
        good=subprocess.run([*args,'--memory-flow','--block-transfer-limit','256','--alu-facts','--branch-facts','--stack-facts','--call-depth','8','--wram-facts','--wram-data-range','0:4','--out',str(self.root/'good')],capture_output=True,text=True,timeout=15)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertEqual(discovery.load_discovery(self.root/'good',self.image).report['analysis_policy'],discovery.MAPPER_POLICY)
