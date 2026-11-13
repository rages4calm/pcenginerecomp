"""Source-rederived conditional decisions, joins and negative admission."""
import json
import subprocess
import sys
import unittest
from pcerecomp import discovery
from test_discovery import seed
import test_discovery_vectors as helpers


class ConditionalDiscoveryTests(unittest.TestCase):
    setUp=helpers.VectorDiscoveryTests.setUp

    def setup_code(self,text,patches=(),mpr=None):
        raw=bytes.fromhex(text)
        size=3 if raw[0]&15==15 else 2 if raw[0] in (0xA9,0xB0) else 1
        helpers.VectorDiscoveryTests.inputs(self,[(0,raw),*patches],roots=[seed(size=size,mpr=mpr)])
        self.length=len(raw)

    def graph(self,name='graph',**options):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,rom_ranges=[(0,self.length)],alu_facts=True,branch_facts=True,**options)

    def test_known_branch_preserves_a_mapping_and_omission_keeps_both_arms(self):
        self.setup_code('A9 01 38 90 04 A9 02 80 02 A9 03 53 04 80 FE')
        graph=self.graph();self.assertEqual(graph.report['unresolved'],[])
        condition=next(n['conditional'] for n in graph.report['nodes'] if 'conditional' in n)
        self.assertEqual(condition,dict(flag='c',expected=0,value=1,decision='fallthrough'))
        self.assertNotIn(0xE009,{n['pc'] for n in graph.report['nodes']})
        self.assertTrue(any(n['mpr'][2]==2 for n in graph.report['nodes']))
        old=discovery.discover_roots(self.seeds,self.image,self.root/'old',rom_ranges=[(0,self.length)],alu_facts=True)
        self.assertEqual({p['reason'] for p in old.report['unresolved']},{'mapping_change'})

    def test_unknown_branch_edges_refine_only_the_tested_status(self):
        self.setup_code('D8 A9 00 B0 07 69 01 53 04 80 FE EA 69 01 53 04 80 FE')
        graph=self.graph();self.assertEqual(graph.report['summary']['unknown_conditionals'],1)
        first=next(n for n in graph.report['nodes'] if n['pc']==0xE005)
        second=next(n for n in graph.report['nodes'] if n['pc']==0xE00C)
        self.assertEqual(first['flag_facts']['c'],0);self.assertEqual(second['flag_facts']['c'],1)
        self.assertEqual({n['mpr'][2] for n in graph.report['nodes'] if n['pc'] in (0xE009,0xE010)},{1,2})

    def test_conflicting_flag_join_broadens_a_previously_decided_branch(self):
        # Entry Z is deliberately unknown via PLP, so both carry predecessors live.
        self.setup_code('28 EA D0 03 18 80 01 38 B0 04 A9 02 80 02 A9 03 53 04 80 FE')
        graph=self.graph();node=next(n for n in graph.report['nodes'] if n['pc']==0xE008)
        self.assertEqual(node['conditional']['decision'],'both')
        self.assertEqual({tuple(n['mpr']) for n in graph.report['nodes']},{(0,)*8})

    def test_bit_branches_need_separate_rom_data_permission(self):
        self.setup_code('0F 80 04 A9 01 80 02 A9 02 53 04 80 FE',patches=[(0x80,b'\x00')])
        graph=self.graph(rom_data_ranges=[(0x80,1)]);node=graph.report['nodes'][0]
        self.assertEqual(node['conditional']['decision'],'taken');self.assertEqual(node['conditional']['reads'][0]['rom_offset'],0x80)
        unknown=self.graph('unknown');self.assertEqual(unknown.report['nodes'][0]['conditional']['reason'],'missing_data_permission')
        self.assertEqual(unknown.report['summary']['unknown_conditionals'],1)

    def test_mutable_bit_branch_reads_stay_unknown(self):
        self.setup_code('8F 80 04 A9 01 80 02 A9 02 53 04 80 FE',mpr=[0,248,0,0,0,0,0,0])
        graph=self.graph(rom_data_ranges=[(0,8192)])
        self.assertEqual(graph.report['nodes'][0]['conditional']['reason'],'non_rom_data')
        self.assertEqual({p['reason'] for p in graph.report['unresolved']},{'mapping_change'})

    def test_pruned_code_is_not_required_but_explicit_seeds_remain_roots(self):
        self.setup_code('38 90 02 80 FE 0B')
        graph=self.graph();self.assertNotIn(0xE005,{n['pc'] for n in graph.report['nodes']})
        value=json.loads(self.seeds.read_text());value['roots'].append(seed(offset=5,size=1));self.seeds.write_text(json.dumps(value))
        both=self.graph('seeds');self.assertIn(0xE005,{n['pc'] for n in both.report['nodes']})
        self.assertIn('unassigned_opcode',{p['reason'] for p in both.report['unresolved']})

    def test_zero_displacement_both_edges_join_back_to_unknown(self):
        self.setup_code('B0 00 69 00 53 04')
        graph=self.graph();node=next(n for n in graph.report['nodes'] if n['pc']==0xE002)
        self.assertIsNone(node['flag_facts']['c'])
        self.assertEqual(len([e for e in graph.report['edges'] if e['from_id']==0]),2)

    def test_restored_status_loses_a_previous_condition(self):
        self.setup_code('38 28 B0 04 A9 01 80 02 A9 02 53 04')
        graph=self.graph();node=next(n for n in graph.report['nodes'] if n['pc']==0xE002)
        self.assertEqual(node['conditional']['decision'],'both');self.assertIsNone(node['flag_facts']['c'])

    def test_tampered_flags_condition_summary_and_options_are_rederived(self):
        self.setup_code('38 90 02 80 FE 00');graph=self.graph();original=graph.report_path.read_bytes()
        for change in ('flag','decision','count','option'):
            data=json.loads(original)
            if change=='flag':data['nodes'][0]['register_evaluation']['flags']['n']=0
            elif change=='decision':data['nodes'][1]['conditional']['decision']='taken'
            elif change=='count':data['summary']['pruned_conditional_edges']+=1
            else:data['options']['branch_facts']=1
            graph.report_path.write_bytes(discovery._canonical(data,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(graph.report_path,self.image)
        graph.report_path.write_bytes(original)
        copied=discovery.copy_discovery(graph.report_path,self.image,self.root/'copy');self.assertEqual(copied.sha256,graph.sha256)

    def test_invalid_mode_types_and_missing_evaluator_refuse_new_output(self):
        self.setup_code('38 80 FE')
        for i,value in enumerate((1,None,[],True)):
            with self.assertRaises(ValueError):discovery.discover_roots(self.seeds,self.image,self.root/str(i),rom_ranges=[(0,3)],branch_facts=value)
            self.assertFalse((self.root/str(i)).exists())

    def test_cli_requires_explicit_evaluator_and_accepts_typed_mode(self):
        self.setup_code('38 90 02 80 FE 00')
        argv=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),'--rom-range','0:6','--branch-facts']
        failed=subprocess.run([*argv,'--out',str(self.root/'no')],capture_output=True,text=True,timeout=15)
        self.assertEqual(failed.returncode,2)
        passed=subprocess.run([*argv,'--alu-facts','--out',str(self.root/'yes')],capture_output=True,text=True,timeout=15)
        self.assertEqual(passed.returncode,0,passed.stderr)
        self.assertEqual(discovery.load_discovery(self.root/'yes',self.image).report['analysis_policy'],discovery.BRANCH_POLICY)

    def test_pruned_target_does_not_spend_code_permissions_or_instruction_slots(self):
        self.setup_code('38 90 02 80 FE 0B')
        graph=discovery.discover_roots(self.seeds,self.image,self.root/'bounded',rom_ranges=[(0,5)],instruction_limit=3,alu_facts=True,branch_facts=True)
        self.assertEqual(graph.report['unresolved'],[]);self.assertEqual(graph.report['summary']['candidate_roots'],3)
        self.assertFalse(graph.report['summary']['limit_reached'])

    def test_table_index_edges_keep_v_and_composed_call_options(self):
        helpers.VectorDiscoveryTests.inputs(self,[(0,bytes.fromhex('B8 7C 00 E1')),(0x100,bytes([0xE0])*257),(0xE0,bytes.fromhex('50 02 0B EA 80 FE'))],roots=[seed(size=1)])
        graph=discovery.discover_roots(self.seeds,self.image,self.root/'tables',rom_ranges=[(0,4),(0xE0,6)],rom_vector_ranges=[(0x100,257)],
            rom_data_ranges=[(0x100,257)],rom_table_limit=1,call_depth_limit=8,alu_facts=True,branch_facts=True)
        self.assertEqual(graph.report['summary']['resolved_vector_entries'],256)
        node=next(n for n in graph.report['nodes'] if n['pc']==0xE0E0)
        self.assertEqual(node['flag_facts']['v'],0);self.assertEqual(node['conditional']['decision'],'taken')
        self.assertNotIn(0xE0E2,{n['pc'] for n in graph.report['nodes']});self.assertFalse(graph.report['unresolved'])

    def test_relative_condition_wrap_keeps_logical_pc_and_source_mapping(self):
        helpers.VectorDiscoveryTests.inputs(self,[(0x1FFD,bytes.fromhex('18 90 02')),(2,bytes.fromhex('80 FE'))],roots=[seed(pc=0xFFFD,size=1,offsets=[0x1FFD])])
        graph=discovery.discover_roots(self.seeds,self.image,self.root/'wrap',rom_ranges=[(0x1FFD,3),(2,2)],alu_facts=True,branch_facts=True)
        self.assertEqual({n['pc'] for n in graph.report['nodes']},{0xFFFD,0xFFFE,2})
        self.assertEqual(next(n for n in graph.report['nodes'] if n['pc']==0xFFFE)['conditional']['decision'],'taken')
