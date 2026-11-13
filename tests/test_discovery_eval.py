"""Opt-in source-rederived arithmetic, status joins and consumer closure."""
import json
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from pcerecomp import discovery
import test_discovery_vectors as helpers
from test_discovery import seed


class EvalDiscoveryTests(unittest.TestCase):
    setUp=helpers.VectorDiscoveryTests.setUp
    def inputs(self,patches,**options):
        first=patches[0][1][0]
        helpers.VectorDiscoveryTests.inputs(self,patches,roots=[seed(size=2 if first==0xA9 else 1)],**options)

    def graph(self,code,**options):
        return discovery.discover_roots(self.seeds,self.image,self.root/'graph',rom_ranges=[(0,len(bytes.fromhex(code)))],alu_facts=True,**options)

    def test_mask_and_shift_enable_a_bank_change_and_default_stays_unknown(self):
        code='A9 F1 29 0F 0A 4A 53 04 80 FE';self.inputs([(0,bytes.fromhex(code))])
        result=self.graph(code);self.assertEqual(result.report['analysis_policy'],discovery.EVAL_POLICY)
        self.assertEqual(result.report['unresolved'],[])
        target=next(n for n in result.report['nodes'] if n['pc']==0xE008)
        self.assertEqual(target['mpr'][2],1)
        old=discovery.discover_roots(self.seeds,self.image,self.root/'old',rom_ranges=[(0,10)])
        self.assertEqual({p['reason'] for p in old.report['unresolved']},{'mapping_change'})
        self.assertNotIn('flag_facts',old.report['nodes'][0])

    def test_carry_decimal_and_transfer_facts_are_explicit(self):
        code='A9 50 F8 38 E9 09 D8 53 04 80 FE';self.inputs([(0,bytes.fromhex(code))])
        result=self.graph(code)
        node=next(n for n in result.report['nodes'] if n['pc']==0xE004)
        self.assertEqual(node['flag_facts'],dict(c=1,d=1,t=0))
        self.assertEqual(node['register_evaluation']['registers']['a'],0x41)
        self.assertTrue(any(n['mpr'][2]==0x41 for n in result.report['nodes']))

    def test_set_logic_preserves_a_and_unknown_seed_t_is_not_guessed(self):
        code='A9 03 F4 29 00 53 04 80 FE';self.inputs([(0,bytes.fromhex(code))])
        result=self.graph(code);node=next(n for n in result.report['nodes'] if n['pc']==0xE003)
        self.assertEqual(node['register_evaluation']['registers']['a'],3)
        self.assertEqual(node['register_evaluation']['reason'],'transfer_destination_untracked')
        self.assertEqual(result.report['nodes'][0]['flag_facts'],dict(c=None,d=None,t=None))

    def test_missing_carry_or_decimal_and_invalid_digits_stop_tam(self):
        for number,code in enumerate(('A9 01 69 01 53 04','A9 01 18 69 01 53 04','A9 FA F8 18 69 01 53 04')):
            self.inputs([(0,bytes.fromhex(code))]);result=discovery.discover_roots(self.seeds,self.image,self.root/str(number),rom_ranges=[(0,len(bytes.fromhex(code)))],alu_facts=True)
            self.assertEqual({r['reason'] for r in result.report['unresolved']},{'mapping_change'})

    def test_rom_alu_permission_separate_from_code_and_read_is_rederived(self):
        code='A9 01 6D 00 E1 53 04';self.inputs([(0,bytes.fromhex('D8 18 '+code)),(0x100,b'\x02')])
        code='D8 18 '+code;result=self.graph(code,rom_data_ranges=[(0x100,1)])
        node=next(n for n in result.report['nodes'] if n['pc']==0xE004)
        self.assertEqual(node['rom_alu_operand']['value'],2)
        self.assertEqual(node['register_evaluation']['registers']['a'],3)
        self.assertEqual(result.report['summary']['resolved_rom_alu_operands'],1)
        copy=discovery.copy_discovery(result.report_path,self.image,self.root/'copy');self.assertEqual(copy.sha256,result.sha256)
        raw=result.report_path.read_bytes();value=json.loads(raw);next(n for n in value['nodes'] if 'rom_alu_operand' in n)['rom_alu_operand']['value']=3
        result.report_path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
        with self.assertRaises(ValueError):discovery.load_discovery(result.report_path,self.image)
        result.report_path.write_bytes(raw)

    def test_conflicting_carry_join_retracts_an_optimistic_bank(self):
        code='A9 01 D8 D0 03 18 80 01 38 69 00 53 04 80 FE'
        self.inputs([(0,bytes.fromhex(code))]);result=self.graph(code)
        node=next(n for n in result.report['nodes'] if n['pc']==0xE009)
        self.assertIsNone(node['flag_facts']['c']);self.assertIsNone(node['register_evaluation']['registers']['a'])
        self.assertEqual({tuple(n['mpr']) for n in result.report['nodes']},{(0,)*8})

    def test_policy_boolean_and_tampered_status_are_strict(self):
        code='18 80 FE';self.inputs([(0,bytes.fromhex(code))]);result=self.graph(code)
        raw=result.report_path.read_bytes()
        for key in ('option','input','output','summary'):
            value=json.loads(raw)
            if key=='option':value['options']['alu_facts']=1
            elif key=='input':value['nodes'][0]['flag_facts']['c']=0
            elif key=='output':value['nodes'][0]['register_evaluation']['flags']['c']=1
            else:value['summary']['register_evaluations']+=1
            result.report_path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(result.report_path,self.image)
        result.report_path.write_bytes(raw)
        for i,option in enumerate((1,None,'true',[])):
            with self.assertRaises(ValueError):discovery.discover_roots(self.seeds,self.image,self.root/str(i),rom_ranges=[(0,3)],alu_facts=option)
            self.assertFalse((self.root/str(i)).exists())

    def test_cli_admits_exact_new_policy(self):
        code='A9 01 09 02 53 04 80 FE';self.inputs([(0,bytes.fromhex(code))])
        done=subprocess.run([sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),'--rom-range','0:8','--alu-facts','--out',str(self.root/'cli')],capture_output=True,text=True,timeout=15)
        self.assertEqual(done.returncode,0,done.stderr)
        result=discovery.load_discovery(self.root/'cli',self.image);self.assertEqual(result.report['analysis_policy'],discovery.EVAL_POLICY)

    def test_all_48_alu_memory_modes_keep_independent_pointer_value_witnesses(self):
        spec=importlib.util.spec_from_file_location('load_fixture',Path(__file__).resolve().parents[1]/'examples/rom-data/fixture.py')
        f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
        original,cases=f.fixture();selected=cases[:32:4]
        for base in (0x00,0x20,0x40,0x60,0xC0,0xE0):
            raw=bytearray(original)
            for c in selected:raw[(c['pc']&8191)+4]=base|(c['opcode']&31)
            roots=[dict(pc=c['pc'],mpr=list(f.MM),selector=0,rom_offsets=[c['pc']&8191,(c['pc']&8191)+1]) for c in selected]
            helpers.VectorDiscoveryTests.inputs(self,[],roots=roots,size=32768)
            self.image.write_bytes(raw);value=json.loads(self.seeds.read_text());value['image']['sha256']=hashlib.sha256(raw).hexdigest();self.seeds.write_text(json.dumps(value))
            graph=discovery.discover_roots(self.seeds,self.image,self.root/str(base),rom_ranges=f.code_ranges(),rom_data_ranges=f.DATA_RANGES,alu_facts=True)
            self.assertEqual(graph.report['summary']['resolved_rom_alu_operands'],8)
            for c in selected:
                node=next(n for n in graph.report['nodes'] if n['pc']==c['pc']+4)
                self.assertEqual([(r['logical_address'],r['rom_offset'],r['value']) for r in node['rom_alu_operand']['reads']],c['reads'])
            graph.revalidate()

    def test_table_index_injection_preserves_status_and_composed_options(self):
        code='18 D8 7C 00 E1';self.inputs([(0,bytes.fromhex(code)),(0x100,bytes([0xE0])*257),(0xE0,b'\x60')])
        result=discovery.discover_roots(self.seeds,self.image,self.root/'tables',rom_ranges=[(0,5),(0xE0,1)],
            rom_vector_ranges=[(0x100,257)],rom_data_ranges=[(0x100,257)],call_depth_limit=8,rom_table_limit=1,alu_facts=True)
        self.assertEqual(result.report['summary']['resolved_vector_entries'],256)
        target=next(n for n in result.report['nodes'] if n['pc']==0xE0E0)
        self.assertEqual(target['flag_facts'],dict(c=0,d=0,t=0))
        discovery.load_discovery(result.report_path,self.image).revalidate()

    def test_plp_loses_status_even_when_registers_remain_known(self):
        code='A9 01 D8 18 28 EA 69 01 53 04 80 FE';self.inputs([(0,bytes.fromhex(code))]);result=self.graph(code)
        node=next(n for n in result.report['nodes'] if n['pc']==0xE006)
        self.assertEqual(node['flag_facts'],dict(c=None,d=None,t=0));self.assertIsNone(node['register_evaluation']['registers']['a'])
        self.assertEqual({r['reason'] for r in result.report['unresolved']},{'mapping_change'})

    def test_transfer_join_does_not_invent_an_accumulator_result(self):
        code='A9 03 D0 01 F4 29 00 53 04 80 FE';self.inputs([(0,bytes.fromhex(code))]);result=self.graph(code)
        node=next(n for n in result.report['nodes'] if n['pc']==0xE005)
        self.assertIsNone(node['flag_facts']['t']);self.assertIsNone(node['register_evaluation']['registers']['a'])
        self.assertEqual({tuple(n['mpr']) for n in result.report['nodes']},{(0,)*8})
