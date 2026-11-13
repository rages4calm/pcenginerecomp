"""Original synchronous BRK/RTI facts; no asynchronous IRQ assumptions."""
import json
import subprocess
import sys
import unittest
from pcerecomp import discovery
from test_discovery import seed
import test_discovery_vectors as helpers

MPR=(0,248,251,0,0,0,0,0)

class SoftwareInterruptTests(unittest.TestCase):
    setUp=helpers.VectorDiscoveryTests.setUp

    def inputs(self,text,handler='40',patches=(),mpr=MPR,profile='base'):
        self.code=bytes.fromhex(text);handlers=bytes.fromhex(handler)
        helpers.VectorDiscoveryTests.inputs(self,[(0,self.code),(0x100,handlers),(0x1FF6,b'\x00\xE1'),*patches],
            roots=[seed(size=2 if self.code[0]==0 else 1,mpr=mpr)],size=0x280000 if profile=='sf2' else 32768,profile=profile)
        from pcerecomp.isa import decode
        value=json.loads(self.seeds.read_text(encoding='utf-8'));value['roots']=[seed(size=len(decode(lambda a:self.code[a-0xE000],0xE000,mpr).data),mpr=mpr)]
        self.seeds.write_text(json.dumps(value),encoding='utf-8')
        self.ranges=[(0,len(self.code)),(0x100,len(handlers)),*((off,len(raw)) for off,raw in patches)]

    def graph(self,name='g',**options):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,rom_ranges=self.ranges,
            alu_facts=True,branch_facts=True,stack_facts=True,wram_facts=True,
            wram_data_ranges=options.pop('wram_data_ranges',[(0,8)]),call_depth_limit=options.pop('call_depth_limit',8),
            memory_flow=True,block_transfer_limit=256,software_interrupts=options.pop('software_interrupts',True),
            rom_vector_ranges=options.pop('rom_vector_ranges',[(0x1FF6,2)]),**options)

    def test_brk_saves_two_byte_resume_and_partial_status_rti_restores_it(self):
        self.inputs('00 EA 80 FE')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        handler=next(n for n in g.report['nodes'] if n['pc']==0xE100)
        self.assertEqual(handler['stack_bytes'],3)
        self.assertEqual(handler['stack_facts'],[dict(known_mask=255,value=0xE0),dict(known_mask=255,value=2),dict(known_mask=0x30,value=0x10)])
        self.assertEqual(handler['flag_facts']['i'],1);self.assertEqual(handler['flag_facts']['d'],0)
        end=next(n for n in g.report['nodes'] if n['pc']==0xE002)
        self.assertEqual(end['stack_bytes'],0);self.assertIsNone(end['flag_facts']['i']);self.assertEqual(end['flag_facts']['t'],0)

    def test_known_saved_flags_drive_return_branch_and_handler_mutations_do_not_leak(self):
        self.inputs('A9 CD 48 28 F4 00 EA B0 02 EA 00 80 FE','18 D8 B8 78 40')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        branch=next(n for n in g.report['nodes'] if n['pc']==0xE007)
        self.assertEqual(branch['conditional']['decision'],'taken')
        self.assertEqual(branch['flag_facts'],dict(c=1,d=1,t=0,n=1,z=0,v=1,i=1))
        self.assertFalse(any(n['pc']==0xE009 for n in g.report['nodes']))

    def test_nested_calls_and_interrupt_frames_keep_return_kinds_separate(self):
        self.inputs('20 20 E0 80 FE','20 30 E1 40',[(0x20,bytes.fromhex('00 EA 60')),(0x130,b'\x60')])
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(g.report['summary']['resolved_returns'],2)
        self.assertEqual(g.report['summary']['software_interrupt_returns'],1)
        self.assertEqual(next(n for n in g.report['nodes'] if n['pc']==0xE003)['stack_bytes'],0)

    def test_rts_cannot_consume_an_interrupt_frame_and_rti_cannot_consume_a_call(self):
        self.inputs('00 EA 80 FE','60')
        self.assertIn('wrong_return_frame_kind',{p['reason'] for p in self.graph().report['unresolved']})
        self.inputs('20 00 E1 80 FE','40')
        self.assertIn('unmatched_interrupt_return',{p['reason'] for p in self.graph('call').report['unresolved']})

    def test_unframed_rti_and_unbalanced_interrupt_return_remain_frontiers(self):
        self.inputs('40')
        self.assertEqual({p['reason'] for p in self.graph().report['unresolved']},{'unmatched_interrupt_return'})
        self.inputs('00 EA 80 FE','48 40')
        self.assertIn('unbalanced_interrupt_return',{p['reason'] for p in self.graph('unbalanced').report['unresolved']})

    def test_handler_cannot_pop_or_overwrite_protected_status_or_return_words(self):
        for i,handler in enumerate(('68 40','28 40','8D 00 21 40')):
            self.inputs('00 EA 80 FE',handler)
            reasons={p['reason'] for p in self.graph(str(i)).report['unresolved']}
            self.assertIn('stack_write_barrier' if i==2 else 'stack_frame_pop',reasons)

    def test_alias_stack_mapping_and_current_return_mpr_are_preserved(self):
        self.inputs('00 EA 80 FE','A9 FB 53 02 A9 02 53 04 40')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        end=next(n for n in g.report['nodes'] if n['pc']==0xE002)
        self.assertEqual(end['mpr'][1:3],[251,2]);self.assertEqual(end['register_facts']['a'],2)

    def test_known_wram_vector_and_missing_permission_do_not_use_zero_fills(self):
        mpr=(*MPR[:7],248)
        # Code at C000 uses MPR6=0 while MPR7 resolves the vector through WRAM.
        self.inputs('A9 00 8D F6 3F A9 C1 8D F7 3F 00 EA 80 FE',mpr=mpr)
        value=json.loads(self.seeds.read_text(encoding='utf-8'));value['roots']=[seed(size=2,pc=0xC000,mpr=mpr)];self.seeds.write_text(json.dumps(value),encoding='utf-8')
        g=self.graph(wram_data_ranges=[(0x1FF6,2)],rom_vector_ranges=None)
        self.assertEqual(g.report['unresolved'],[])
        entry=next(n['software_interrupt'] for n in g.report['nodes'] if 'software_interrupt' in n)
        self.assertEqual([r['storage'] for r in entry['reads']],['wram','wram'])
        denied=self.graph('denied',wram_data_ranges=[(0x1FF6,1)],rom_vector_ranges=None)
        self.assertIn('allowed_wram_data_boundary',{p['reason'] for p in denied.report['unresolved']})

    def test_missing_rom_vector_permission_stops_and_old_policy_remains_unchanged(self):
        self.inputs('00 EA 80 FE')
        self.assertEqual({p['reason'] for p in self.graph(rom_vector_ranges=None).report['unresolved']},{'missing_vector_permission'})
        old=self.graph('old',software_interrupts=False)
        self.assertEqual({p['reason'] for p in old.report['unresolved']},{'interrupt_vector'})

    def test_nested_software_interrupt_limit_and_noncanonical_stack_refuse(self):
        self.inputs('00 EA 80 FE','00 EA 40')
        g=self.graph(call_depth_limit=2);self.assertIn('call_depth_limit',{p['reason'] for p in g.report['unresolved']})
        self.inputs('00 EA 80 FE',mpr=(0,0,0,0,0,0,0,0))
        self.assertEqual({p['reason'] for p in self.graph('mapping').report['unresolved']},{'unsupported_stack_mapping'})

    def test_full_word_resume_wrap_is_zero_and_not_rts_plus_one(self):
        self.inputs('EA 80 FE',patches=[(0x1FFE,b'\x00\xEA')])
        value=json.loads(self.seeds.read_text(encoding='utf-8'))
        value['roots']=[seed(size=2,pc=0xFFFE,mpr=MPR,offsets=[0x1FFE,0x1FFF])]
        self.seeds.write_text(json.dumps(value),encoding='utf-8')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        ret=next(n['interrupt_return'] for n in g.report['nodes'] if 'interrupt_return' in n)
        self.assertEqual(ret['resume_pc'],0)
        self.assertTrue(any(n['pc']==0 for n in g.report['nodes']))

    def test_temporary_interrupt_frame_capacity_is_checked_before_vector_reads(self):
        for count in (253,254):
            self.inputs('48 '*count+'00 EA 80 FE')
            import hashlib
            image=bytearray(self.image.read_bytes());image[:len(self.code)]=self.code;image[0x200]=0x40;image[0x1FF6:0x1FF8]=b'\x00\xE2'
            self.image.write_bytes(image);value=json.loads(self.seeds.read_text(encoding='utf-8'));value['image']['sha256']=hashlib.sha256(image).hexdigest();self.seeds.write_text(json.dumps(value),encoding='utf-8')
            self.ranges=[(0,len(self.code)),(0x200,1)]
            g=self.graph(str(count))
            if count==253:
                self.assertEqual(g.report['unresolved'],[])
                self.assertEqual(g.report['summary']['peak_stack_bytes'],256)
            else:
                self.assertIn('stack_capacity',{p['reason'] for p in g.report['unresolved']})

    def test_conflicting_vector_join_retracts_optimistic_handler_edges(self):
        mpr=(*MPR[:7],248)
        self.inputs('A9 C1 8D F7 3F B0 07 A9 00 8D F6 3F 80 05 A9 20 8D F6 3F 00 EA',mpr=mpr)
        value=json.loads(self.seeds.read_text(encoding='utf-8'));value['roots']=[seed(size=2,pc=0xC000,mpr=mpr)];self.seeds.write_text(json.dumps(value),encoding='utf-8')
        g=self.graph(wram_data_ranges=[(0x1FF6,2)],rom_vector_ranges=None)
        self.assertIn('wram_value_unknown',{p['reason'] for p in g.report['unresolved']})
        self.assertFalse(any(n['pc'] in (0xC100,0xC120) for n in g.report['nodes']))

    def test_saved_status_join_restores_unknown_bits_without_a_false_branch(self):
        self.inputs('B0 03 18 80 01 38 00 EA B0 02 80 FE 80 FE')
        g=self.graph();self.assertEqual(g.report['unresolved'],[])
        branch=next(n for n in g.report['nodes'] if n['pc']==0xE008)
        self.assertIsNone(branch['flag_facts']['c'])
        self.assertIsNone(branch['flag_facts']['d'])
        self.assertEqual(branch['conditional']['decision'],'both')
        self.assertTrue({0xE00A,0xE00C}.issubset({n['pc'] for n in g.report['nodes']}))

    def test_mapper_policy_composes_and_return_keeps_live_selector(self):
        self.inputs('00 EA 80 FE','8D F1 1F 40',profile='sf2')
        g=self.graph(mapper_facts=True);self.assertEqual(g.report['unresolved'],[])
        self.assertEqual(next(n for n in g.report['nodes'] if n['pc']==0xE002)['selector'],1)

    def test_options_frames_vectors_and_return_witnesses_are_rederived(self):
        self.inputs('00 EA 80 FE');g=self.graph();raw=g.report_path.read_bytes()
        for field in ('option','frame','vector','return','summary'):
            value=json.loads(raw)
            if field=='option':value['options']['software_interrupts']=1
            elif field=='frame':next(n for n in value['nodes'] if n['call_stack'])['call_stack'][-1]['stored_return_word']+=1
            elif field=='vector':value['nodes'][0]['software_interrupt']['target']+=1
            elif field=='return':next(n for n in value['nodes'] if 'interrupt_return' in n)['interrupt_return']['resume_pc']+=1
            else:value['summary']['software_interrupt_returns']+=1
            g.report_path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(g.report_path,self.image)
        g.report_path.write_bytes(raw);self.assertEqual(discovery.copy_discovery(g.report_path,self.image,self.root/'copy').sha256,g.sha256)

    def test_cli_requires_memory_flow_and_literal_boolean_options(self):
        self.inputs('00 EA 80 FE')
        for i,v in enumerate((None,1,'true',[])):
            with self.assertRaises(ValueError):self.graph(str(i),software_interrupts=v)
        args=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),'--rom-range','0:4','--rom-range','256:1','--rom-vector-range','8182:2','--software-interrupts']
        bad=subprocess.run([*args,'--out',str(self.root/'bad')],capture_output=True,text=True,timeout=15);self.assertEqual(bad.returncode,2)
        good=subprocess.run([*args,'--memory-flow','--block-transfer-limit','256','--alu-facts','--branch-facts','--stack-facts','--call-depth','8','--wram-facts','--wram-data-range','0:4','--out',str(self.root/'good')],capture_output=True,text=True,timeout=15)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertEqual(discovery.load_discovery(self.root/'good',self.image).report['analysis_policy'],discovery.SOFTWARE_POLICY)
