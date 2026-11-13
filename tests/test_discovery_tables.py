"""Authored complete byte-index domains, source boundaries and closure negatives."""
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from pcerecomp import discovery
from test_discovery import seed
import test_discovery_vectors as helpers


class TableDiscoveryTests(unittest.TestCase):
    setUp=helpers.VectorDiscoveryTests.setUp
    inputs=helpers.VectorDiscoveryTests.inputs
    pcs=helpers.VectorDiscoveryTests.pcs
    reasons=helpers.VectorDiscoveryTests.reasons

    def graph(self, *, name='graph', code=None, vectors=None, limit=1, **options):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,
            rom_ranges=code or [(0,3),(0x40,1)],
            rom_vector_ranges=vectors if vectors is not None else [(0x100,257)],
            rom_table_limit=limit,**options)

    def test_all_256_indices_record_both_source_bytes_and_conditional_edge_facts(self):
        self.inputs([(0,bytes.fromhex('7C 00 E1')),(0x100,bytes([0xE0])*257),
                     (0xE0,bytes.fromhex('80 FE'))])
        result=self.graph(code=[(0,3),(0xE0,2)])
        self.assertEqual(self.pcs(result),{0xE000,0xE0E0})
        self.assertEqual(result.report['analysis_policy'],discovery.TABLE_POLICY)
        table=result.report['nodes'][0]['rom_vector_table']
        self.assertEqual((table['index_domain'],table['source_complete']),([0,255],True))
        self.assertEqual(table['entries'],[dict(index=x,logical_addresses=[0xE100+x,0xE101+x],
            rom_offsets=[0x100+x,0x101+x],target=0xE0E0) for x in range(256)])
        self.assertEqual({e['vector_index'] for e in result.report['edges'] if e['kind']=='rom_vector'},set(range(256)))
        self.assertIsNone(result.report['nodes'][1]['register_facts']['x'])
        self.assertEqual(result.report['summary']['resolved_vector_entries'],256)
        self.assertFalse(result.report['execution_evidence'])
        discovery.load_discovery(result.report_path,self.image).revalidate()

    def test_partial_permission_keeps_only_proven_entries_and_explicit_frontiers(self):
        self.inputs([(0,bytes.fromhex('7C 00 E1')),(0x102,bytes.fromhex('40 E0')),(0x40,b'\x60')])
        result=self.graph(vectors=[(0x102,2)])
        table=result.report['nodes'][0]['rom_vector_table']
        self.assertFalse(table['source_complete'])
        self.assertEqual([r['index'] for r in table['entries']],[2])
        target=next(n for n in result.report['nodes'] if n['pc']==0xE040)
        self.assertEqual(target['register_facts']['x'],2)
        self.assertEqual({e['vector_index'] for e in result.report['unresolved'] if 'vector_index' in e},set(range(256))-{2})
        self.assertEqual(self.reasons(result),{'allowed_vector_boundary','dynamic_return'})

    def test_each_pointer_byte_has_its_own_mapping_and_16bit_wrap(self):
        mapping=[1,0,0,0,0,0,0,0]
        self.inputs([(0x20,bytes.fromhex('7C FE FF')),(0x1FFF,b'\x40'),(0x2000,b'\xE0'),(0x40,b'\x60')],
            [seed(pc=0xE020,mpr=mapping,offsets=[0x20,0x21,0x22])],size=16384)
        result=self.graph(code=[(0x20,3),(0x40,1)],vectors=[(0x1FFF,2)])
        self.assertEqual(result.report['nodes'][0]['rom_vector_table']['entries'],[
            dict(index=1,logical_addresses=[65535,0],rom_offsets=[8191,8192],target=0xE040)])

    def test_known_x_still_reads_one_vector_without_spending_table_sites(self):
        self.inputs([(0,bytes.fromhex('A2 02 7C 00 E1')),(0x102,bytes.fromhex('40 E0')),(0x40,b'\x60')],[seed(size=2)])
        result=self.graph(code=[(0,5),(0x40,1)],vectors=[(0x102,2)])
        self.assertEqual(result.report['summary']['explored_vector_tables'],0)
        self.assertEqual(result.report['summary']['resolved_vector_entries'],1)
        self.assertEqual(self.reasons(result),{'dynamic_return'})
        self.assertNotIn('rom_vector_table',result.report['nodes'][1])

    def test_two_selectors_do_not_borrow_pointer_data_or_site_budget(self):
        mapping=[0,64,0,0,0,0,0,0]
        self.inputs([(0,bytes.fromhex('7C 00 20')),(0x80000,bytes.fromhex('40 E0')),
                     (0x100000,bytes.fromhex('50 E0')),(0x40,b'\x60'),(0x50,b'\x60')],
                    roots=[seed(size=3,mpr=mapping,selector=s) for s in (0,1)],size=0x280000,profile='sf2')
        result=self.graph(code=[(0,3),(0x40,1),(0x50,1)],vectors=[(0x80000,2),(0x100000,2)],limit=2)
        tables={n['selector']:n['rom_vector_table'] for n in result.report['nodes'] if 'rom_vector_table' in n}
        self.assertEqual(tables[0]['entries'][0]['rom_offsets'],[0x80000,0x80001])
        self.assertEqual(tables[1]['entries'][0]['rom_offsets'],[0x100000,0x100001])
        self.assertEqual([tables[s]['entries'][0]['target'] for s in (0,1)],[0xE040,0xE050])
        self.assertEqual(result.report['summary']['explored_vector_tables'],2)

    def test_conflicting_x_join_replaces_single_vector_with_full_table(self):
        self.inputs([(0,bytes.fromhex('D0 04 A2 00 80 02 A2 02 7C 00 E1')),
                     (0x100,bytes([0xE0])*257),(0xE0,b'\x60')],roots=[seed(size=2)])
        result=self.graph(code=[(0,11),(0xE0,1)])
        node=next(n for n in result.report['nodes'] if n['pc']==0xE008)
        self.assertIsNone(node['register_facts']['x'])
        self.assertNotIn('rom_vector',node)
        self.assertEqual(len(node['rom_vector_table']['entries']),256)
        self.assertEqual(result.report['summary']['explored_vector_tables'],1)

    def test_two_call_frames_reuse_one_immutable_source_table(self):
        self.inputs([(0,bytes.fromhex('20 10 E0 20 10 E0 80 FE')),(0x10,bytes.fromhex('7C 00 E1')),
                     (0x100,bytes([0xE0])*257),(0xE0,b'\x60')],roots=[seed(size=3,mpr=[0,248,0,0,0,0,0,0])])
        result=self.graph(code=[(0,8),(0x10,3),(0xE0,1)],call_depth_limit=8)
        self.assertEqual(result.report['summary']['explored_vector_tables'],1)
        self.assertEqual(result.report['summary']['enumerated_vector_sites'],2)
        self.assertEqual(result.report['summary']['resolved_returns'],2)
        self.assertEqual(self.reasons(result),set())

    def test_call_frame_expansion_has_a_separate_whole_table_witness_bound(self):
        self.inputs([(0,bytes.fromhex('20 10 E0 20 10 E0 80 FE')),(0x10,bytes.fromhex('7C 00 E1')),
                     (0x100,bytes([0xE0])*257),(0xE0,b'\x60')],roots=[seed(size=3,mpr=[0,248,0,0,0,0,0,0])])
        with patch.object(discovery,'MAX_ROM_TABLE_STATES',1):
            result=self.graph(code=[(0,8),(0x10,3),(0xE0,1)],call_depth_limit=8)
        self.assertEqual(result.report['summary']['explored_vector_tables'],1)
        self.assertEqual(result.report['summary']['explored_vector_table_states'],1)
        self.assertIn('rom_table_state_limit',self.reasons(result))
        self.assertTrue(result.report['summary']['limit_reached'])

    def test_site_bound_stops_whole_next_table_without_a_numeric_prefix(self):
        self.inputs([(0,bytes.fromhex('7C 00 E1')),(0x40,bytes.fromhex('FA 7C 00 E2')),
                     (0x100,bytes([0xE0])*257)],roots=[seed(size=3),seed(0x40,size=1)])
        result=self.graph(code=[(0,3),(0x40,4)],limit=1)
        self.assertEqual(result.report['summary']['explored_vector_tables'],1)
        self.assertEqual(result.report['summary']['enumerated_vector_sites'],1)
        self.assertIn('rom_table_limit',self.reasons(result))
        self.assertTrue(result.report['summary']['limit_reached'])
        self.assertNotIn('rom_vector_table',next(n for n in result.report['nodes'] if n['pc']==0xE041))

    def test_instruction_limit_preserves_pointer_proofs_but_not_unadmitted_targets(self):
        self.inputs([(0,bytes.fromhex('7C 00 E1')),(0x100,bytes([0xE0])*257),(0xE0,b'\x60')])
        result=self.graph(code=[(0,3),(0xE0,1)],instruction_limit=1)
        self.assertEqual(self.pcs(result),{0xE000})
        self.assertEqual(result.report['summary']['resolved_vector_entries'],256)
        self.assertEqual(len(result.report['unresolved']),256)
        self.assertEqual(self.reasons(result),{'instruction_limit'})

    def test_call_policy_composes_and_return_candidate_does_not_become_execution(self):
        mapping=[0,248,0,0,0,0,0,0]
        self.inputs([(0,bytes.fromhex('20 10 E0 80 FE')),(0x10,bytes.fromhex('7C 00 E1')),
                     (0x100,bytes([0xE0])*257),(0xE0,b'\x60')],roots=[seed(size=3,mpr=mapping)])
        result=self.graph(code=[(0,5),(0x10,3),(0xE0,1)],call_depth_limit=8)
        self.assertEqual(result.report['analysis_policy'],discovery.TABLE_CALL_POLICY)
        self.assertEqual(result.report['summary']['resolved_returns'],1)
        self.assertEqual(result.report['summary']['calls_with_candidate_returns'],1)
        self.assertEqual(self.reasons(result),set())
        self.assertFalse(result.report['routine_closure'])
        copied=discovery.copy_discovery(result.report_path,self.image,self.root/'copied')
        self.assertEqual(copied.sha256,result.sha256)

    def test_denied_ram_io_and_mapper_sources_are_not_table_data(self):
        for index,bank in enumerate((248,255,128)):
            self.inputs([(0,bytes.fromhex('7C 00 20'))],roots=[seed(size=3,mpr=[0,bank,0,0,0,0,0,0])])
            result=self.graph(name=str(index),vectors=[(0,8192)])
            self.assertEqual(self.pcs(result),{0xE000})
            self.assertEqual(self.reasons(result),{'non_rom_vector'})
            self.assertEqual(result.report['summary']['resolved_vector_entries'],0)

    def test_mutated_canonical_pointer_edges_options_or_policy_are_rederived(self):
        self.inputs([(0,bytes.fromhex('7C 00 E1')),(0x102,bytes.fromhex('40 E0')),(0x40,b'\x60')])
        graph=self.graph(vectors=[(0x102,2)]);path=graph.report_path;original=path.read_bytes()
        def entries(v):v['nodes'][0]['rom_vector_table']['entries'][0]['target']^=1
        def edges(v):v['edges'][0]['vector_index']=3
        def count(v):v['summary']['resolved_vector_entries']=256
        def policy(v):v['analysis_policy']=discovery.VECTOR_POLICY
        for mutate in (entries,edges,count,policy):
            value=json.loads(original);mutate(value)
            path.write_bytes(discovery._canonical(value,discovery.MAX_REPORT_BYTES))
            with self.assertRaises(ValueError):discovery.load_discovery(path,self.image)
        path.write_bytes(original);graph.revalidate()

    def test_wrong_typed_or_missing_permissions_refuse_before_output(self):
        self.inputs([(0,bytes.fromhex('7C 00 E1'))])
        for i,value in enumerate((True,False,0,-1,257,1.0,'1')):
            with self.assertRaises(ValueError):self.graph(name=str(i),limit=value)
            self.assertFalse((self.root/str(i)).exists())
        with self.assertRaises(ValueError):discovery.discover_roots(self.seeds,self.image,self.root/'missing',
            rom_ranges=[(0,3)],rom_table_limit=1)
        self.assertFalse((self.root/'missing').exists())

    def test_cli_opt_in_and_default_unknown_index_behavior_remain_separate(self):
        self.inputs([(0,bytes.fromhex('7C 00 E1')),(0x100,bytes([0xE0])*257),(0xE0,b'\x60')])
        command=[sys.executable,'-m','pcerecomp','discover-roots',str(self.seeds),'--image',str(self.image),
            '--rom-range','0:3','--rom-range','224:1','--rom-vector-range','256:257']
        done=subprocess.run(command+['--rom-table-limit','1','--out',str(self.root/'cli')],capture_output=True,text=True,timeout=15)
        self.assertEqual(done.returncode,0,done.stderr)
        result=discovery.load_discovery(self.root/'cli',self.image)
        self.assertIn(0xE0E0,self.pcs(result))
        legacy=self.graph(name='legacy',code=[(0,3),(0xE0,1)],limit=None)
        self.assertEqual(self.reasons(legacy),{'indirect_index_unknown'})
        self.assertNotIn('rom_table_limit',legacy.report['options'])


if __name__=='__main__':unittest.main()
