"""Immutable data facts, independent address literals and conservative joins."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

from pcerecomp import discovery
import test_discovery_vectors as helpers
from test_discovery import seed

SPEC=importlib.util.spec_from_file_location('rom_data_fixture',Path(__file__).resolve().parents[1]/'examples/rom-data/fixture.py')
fixture=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(fixture)

class DataDiscoveryTests(unittest.TestCase):
    setUp=helpers.VectorDiscoveryTests.setUp
    inputs=helpers.VectorDiscoveryTests.inputs
    pcs=helpers.VectorDiscoveryTests.pcs
    reasons=helpers.VectorDiscoveryTests.reasons

    def graph(self,code,*,data=((0x100,1),),name='graph',**options):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,rom_ranges=code,
            rom_data_ranges=data,**options)

    def test_one_rom_byte_enables_a_previously_unknown_tam_mapping(self):
        self.inputs([(0,bytes.fromhex('AD 00 E1 53 04 80 FE')),(0x100,b'\x01')])
        result=self.graph([(0,7)])
        self.assertEqual(result.report['analysis_policy'],discovery.DATA_POLICY)
        self.assertIn((0,0,1,0,0,0,0,0),{tuple(r['mpr']) for r in result.declarations.roots})
        load=result.report['nodes'][0]['rom_data_load']
        self.assertEqual(load['reads'],[dict(role='value',logical_address=0xE100,physical=0x100,rom_offset=0x100,value=1)])
        self.assertEqual((load['status'],load['value']),('resolved',1))
        self.assertEqual(result.report['summary']['resolved_rom_data_loads'],1)

    def test_omission_is_legacy_and_code_permission_is_not_data_permission(self):
        self.inputs([(0,bytes.fromhex('AD 00 E1 53 04')),(0x100,b'\x01')])
        old=self.graph([(0,0x101)],data=None,name='old')
        self.assertEqual(self.reasons(old),{'mapping_change'})
        self.assertNotIn('rom_data_load',old.report['nodes'][0])
        result=self.graph([(0,5)],data=[(0x101,1)],name='denied')
        self.assertEqual(self.reasons(result),{'mapping_change'})
        self.assertEqual(result.report['nodes'][0]['rom_data_load']['reason'],'allowed_data_boundary')
        self.assertEqual(result.report['summary']['unknown_rom_data_loads'],1)

    def test_ram_load_remains_unknown_without_stopping_unrelated_control_flow(self):
        self.inputs([(0,bytes.fromhex('AD 00 20 E8 80 FE'))],roots=[seed(size=3,mpr=[0,248,0,0,0,0,0,0])])
        result=self.graph([(0,6)],data=[(0,8192)])
        self.assertEqual(self.pcs(result),{0xE000,0xE003,0xE004})
        self.assertEqual(result.report['unresolved'],[])
        self.assertEqual(result.report['nodes'][0]['rom_data_load']['reason'],'non_rom_data')
        self.assertIsNone(result.report['nodes'][1]['register_facts']['a'])

    def test_all_64_load_cases_match_separate_address_value_literals(self):
        rom,cases=fixture.fixture()
        roots=[dict(pc=c['pc'],mpr=list(fixture.MM),selector=0,rom_offsets=[c['pc']&8191,(c['pc']&8191)+1]) for c in cases]
        self.inputs([],roots=roots,size=len(rom));self.image.write_bytes(rom)
        config=json.loads(self.seeds.read_text());import hashlib
        config['image']['sha256']=hashlib.sha256(rom).hexdigest();self.seeds.write_text(json.dumps(config))
        result=self.graph([(c['pc']&8191,len(c['code'])) for c in cases],data=fixture.DATA_RANGES)
        self.assertEqual(len(result.declarations.roots),256)
        self.assertEqual(result.report['summary']['resolved_rom_data_loads'],64)
        for case in cases:
            node=next(n for n in result.report['nodes'] if n['pc']==case['pc']+4)
            load=node['rom_data_load']
            self.assertEqual(load['value'],case['value'])
            self.assertEqual([(r['logical_address'],r['rom_offset'],r['value']) for r in load['reads']],case['reads'])
            loop=next(n for n in result.report['nodes'] if n['pc']==case['end'])
            self.assertEqual(loop['register_facts'][case['name'][-1].lower()],case['value'])

    def test_pointer_permissions_are_independent_and_partial_reads_retained(self):
        self.inputs([(0,bytes.fromhex('B2 FF 53 04')),(0xFF,b'\x00'),(0,b'\xB2')],roots=[seed(size=2)])
        # Direct-page pointer is logical20FF/2000, both mirror ROM0 in this view.
        result=self.graph([(0,4)],data=[(0xFF,1)])
        load=result.report['nodes'][0]['rom_data_load']
        self.assertEqual(load['reason'],'allowed_data_boundary')
        self.assertEqual(len(load['reads']),1)
        self.assertEqual(load['reads'][0]['logical_address'],0x20FF)
        self.assertEqual(self.reasons(result),{'mapping_change'})

    def test_unknown_indices_do_not_read_a_guessed_address(self):
        for i,code in enumerate(('BD 00 E1','B9 00 E1','A1 FF','B1 FF')):
            self.inputs([(0,bytes.fromhex(code)),(0x100,b'\x01')],roots=[seed(size=len(bytes.fromhex(code)))])
            result=self.graph([(0,len(bytes.fromhex(code)))],data=[(0,8192)],name=str(i))
            load=result.report['nodes'][0]['rom_data_load']
            self.assertEqual(load['reason'],'data_index_unknown')
            self.assertNotIn('value',load)

    def test_16bit_index_wrap_and_distinct_mpr_data_sources(self):
        self.inputs([(0x20,bytes.fromhex('A2 02 BD FE FF 53 04 80 FE')),(0x2000,b'\x01')],
            roots=[seed(offset=0x20,size=2,mpr=[1,0,0,0,0,0,0,0])],size=16384)
        result=self.graph([(0x20,9)],data=[(0x2000,1)])
        node=next(n for n in result.report['nodes'] if n['pc']==0xE022)
        self.assertEqual(node['rom_data_load']['reads'][0]['logical_address'],0)
        self.assertEqual(node['rom_data_load']['reads'][0]['rom_offset'],0x2000)

    def test_calls_and_vector_data_are_explicit_separate_permissions(self):
        rom,_=fixture.fixture();import hashlib
        self.inputs([],roots=[seed(size=2)],size=len(rom));self.image.write_bytes(rom)
        config=json.loads(self.seeds.read_text());config['image']['sha256']=hashlib.sha256(rom).hexdigest();self.seeds.write_text(json.dumps(config))
        found=self.graph(fixture.code_ranges(),data=fixture.DATA_RANGES,rom_vector_ranges=fixture.VECTOR_RANGES,call_depth_limit=8)
        self.assertEqual(len(found.declarations.roots),17)
        self.assertEqual(found.report['summary']['resolved_rom_data_loads'],6)
        self.assertEqual(found.report['summary']['resolved_returns'],1)
        self.assertEqual(found.report['unresolved'],[])
        copied=discovery.copy_discovery(found.report_path,self.image,self.root/'copy')
        self.assertEqual(copied.sha256,found.sha256)

    def test_conflicting_index_join_retracts_a_previously_inferred_mapping(self):
        self.inputs([(0,bytes.fromhex('D0 04 A2 00 80 02 A2 02 BD 00 E1 53 04 80 FE')),
                     (0x100,b'\x01\x00\x02')],roots=[seed(size=2)])
        result=self.graph([(0,15)],data=[(0x100,3)])
        node=next(n for n in result.report['nodes'] if n['pc']==0xE008)
        self.assertEqual(node['rom_data_load']['status'],'unknown')
        self.assertNotIn('value',node['rom_data_load'])
        self.assertEqual({tuple(r['mpr']) for r in result.declarations.roots},{(0,)*8})
        self.assertEqual(self.reasons(result),{'mapping_change'})
        self.assertGreater(result.report['summary']['explored_states'],len(result.declarations.roots))

    def test_selector_views_do_not_borrow_rom_constants(self):
        mapping=[0,64,0,0,0,0,0,0]
        self.inputs([(0,bytes.fromhex('AD 00 20 53 04 80 FE')),(0x80000,b'\x01'),(0x100000,b'\x02')],
            roots=[seed(size=3,mpr=mapping,selector=s) for s in (0,1)],size=0x280000,profile='sf2')
        result=self.graph([(0,7)],data=[(0x80000,1),(0x100000,1)])
        loads={n['selector']:n['rom_data_load'] for n in result.report['nodes'] if 'rom_data_load' in n}
        self.assertEqual([loads[s]['value'] for s in (0,1)],[1,2])
        self.assertEqual([loads[s]['reads'][0]['rom_offset'] for s in (0,1)],[0x80000,0x100000])
        for selector,value in ((0,1),(1,2)):
            target=next(n for n in result.report['nodes'] if n['pc']==0xE005 and n['selector']==selector)
            self.assertEqual(target['mpr'][2],value)

    def test_data_policy_composes_with_unknown_x_table_enumeration(self):
        self.inputs([(0,bytes.fromhex('AD 00 E3 7C 00 E1')),(0x100,bytes([0xE0])*257),
                     (0x300,b'\x01'),(0xE0,b'\x60')])
        result=self.graph([(0,6),(0xE0,1)],data=[(0x300,1)],rom_vector_ranges=[(0x100,257)],rom_table_limit=1)
        self.assertEqual(result.report['analysis_policy'],discovery.DATA_POLICY)
        self.assertEqual(result.report['summary']['resolved_rom_data_loads'],1)
        self.assertEqual(result.report['summary']['resolved_vector_entries'],256)
        self.assertEqual(result.report['summary']['enumerated_vector_sites'],1)
        discovery.load_discovery(result.report_path,self.image).revalidate()

    def test_changed_data_evidence_is_rederived_even_when_canonical(self):
        self.inputs([(0,bytes.fromhex('AD 00 E1 53 04 80 FE')),(0x100,b'\x01')])
        result=self.graph([(0,7)]);path=result.report_path;raw=path.read_bytes()
        for change in ('value','offset','fact','count','permission'):
            value=json.loads(raw)
            if change=='value':value['nodes'][0]['rom_data_load']['value']=2
            elif change=='offset':value['nodes'][0]['rom_data_load']['reads'][0]['rom_offset']=257
            elif change=='fact':value['nodes'][1]['register_facts']['a']=2
            elif change=='count':value['summary']['resolved_rom_data_loads']=0
            else:value['options']['rom_data_ranges'][0]['start']=257
            path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(path,self.image)
        path.write_bytes(raw);result.revalidate()

    def test_wrong_types_and_empty_permissions_refuse_before_creating_output(self):
        self.inputs([(0,bytes.fromhex('AD 00 E1'))])
        for i,value in enumerate(([],True,{},[(True,1)],[(0,0)],[(0,1.0)])):
            with self.assertRaises(ValueError):self.graph([(0,3)],data=value,name=str(i))
            self.assertFalse((self.root/str(i)).exists())

    def test_cli_composes_options_without_relabelling_observations(self):
        self.inputs([(0,bytes.fromhex('AD 00 E1 53 04 80 FE')),(0x100,b'\x01')])
        command=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),
            '--rom-range','0:7','--rom-data-range','256:1','--out',str(self.root/'cli')]
        done=subprocess.run(command,capture_output=True,text=True,timeout=15)
        self.assertEqual(done.returncode,0,done.stderr)
        result=discovery.load_discovery(self.root/'cli',self.image)
        self.assertFalse(result.report['execution_evidence'])
        self.assertEqual(result.report['analysis_policy'],discovery.DATA_POLICY)

if __name__=='__main__':unittest.main()
