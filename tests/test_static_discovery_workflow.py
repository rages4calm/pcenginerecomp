"""Authored static discovery, explicit frontiers and a real native/reference call."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from pcerecomp.declarations import load_compilation
from pcerecomp.discovery import discover_roots,load_discovery
from pcerecomp.history import compose_history
from scripts.build_config import cmake_cache

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('authored_static_workflow',ROOT/'examples/static-discovery/workflow.py')
workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)
HEADLESS=Path(os.environ.get('PCE_TEST_HEADLESS',ROOT/'build'/('pce-headless.exe' if os.name=='nt' else 'pce-headless')))


class StaticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.out=Path(self.temporary.name)/'fixture';workflow.create(self.out)
        self.image=self.out/'authored-card.pce'

    def seeds(self,name,entries):
        path=self.out/(name+'.json');workflow.write(path,workflow.roots_document(self.image,entries));return path

    def test_two_seeds_expand_known_mappings_without_invented_observations(self):
        result=workflow.discover(self.out)
        self.assertFalse(result['execution_evidence']);self.assertFalse(result['compiled']);self.assertFalse(result['executed'])
        discovery=load_discovery(self.out/'discovery',self.image)
        self.assertEqual({workflow.root_key(row) for row in discovery.declarations.roots},
                         {workflow.root_key(row) for row in workflow.expected_roots()})
        self.assertEqual(len(discovery.declarations.instructions),15)
        self.assertEqual(len({tuple(row['mpr']) for row in discovery.declarations.roots}),3)
        self.assertEqual((self.out/'discovery/seed-roots.json').read_bytes(),(self.out/'seed-roots.json').read_bytes())
        compilation=load_compilation(discovery.roots_path,self.image)
        self.assertEqual(len(compilation.declared_keys),15);self.assertEqual(compilation.observed_keys,frozenset())
        self.assertEqual(compilation.accounting,{})
        self.assertTrue(all('native_hits' not in row and 'interpreted_hits' not in row for row in compilation.instructions))
        report=discovery.report
        self.assertFalse(report['routine_closure']);self.assertEqual(report['static_reachability'],'candidates_only')
        self.assertEqual(report['summary']['seed_roots'],2)

    def test_unknown_flow_and_reserved_opcode_are_frontiers_not_guessed_successors(self):
        cases=(('indirect',0xE170,0x2170,3,((0x2170,3),),{0xE170},'indirect_jump'),
               ('unknown-tam',0xE180,0x2180,3,((0x2180,6),),{0xE180,0xE183},'mapping_change'),
               ('reserved',0xE190,0x2190,1,((0x2190,2),),{0xE190},'unassigned_opcode'),
               ('unknown-call',0xE198,0x2198,3,((0x2198,4),),{0xE198},'allowed_rom_boundary'))
        for name,pc,offset,length,ranges,expected,reason in cases:
            seeds=self.seeds(name,[workflow.root_entry(pc,workflow.M2,offset,length)])
            admitted=discover_roots(seeds,self.image,self.out/(name+'-out'),rom_ranges=ranges)
            with self.subTest(name=name):
                self.assertEqual({row['pc'] for row in admitted.declarations.roots},expected)
                self.assertIn(reason,{row['reason'] for row in admitted.report['unresolved']})
                self.assertFalse(admitted.report['routine_closure'])
        explicit=self.seeds('explicit-return',[workflow.root_entry(0xE198,workflow.M2,0x2198,3),
                                               workflow.root_entry(0xE19B,workflow.M2,0x219B,1)])
        result=discover_roots(explicit,self.image,self.out/'explicit-return-out',rom_ranges=((0x2198,4),))
        self.assertEqual({row['pc'] for row in result.declarations.roots},{0xE198,0xE19B})

    def test_limits_and_closed_output_tamper_are_explicit(self):
        limited=discover_roots(self.out/'seed-roots.json',self.image,self.out/'limited',
            rom_ranges=workflow.ROM_RANGES,instruction_limit=3,context_limit=16)
        self.assertTrue(limited.report['summary']['limit_reached'])
        self.assertIn('instruction_limit',{row['reason'] for row in limited.report['unresolved']})
        admitted=discover_roots(self.out/'seed-roots.json',self.image,self.out/'sealed',rom_ranges=workflow.ROM_RANGES)
        for name in ('seed-roots.json','roots.json','discovery.json'):
            path=self.out/'sealed'/name;original=path.read_bytes();path.write_bytes(original+b' ')
            with self.subTest(name=name),self.assertRaises(ValueError):load_discovery(self.out/'sealed',self.image)
            path.write_bytes(original)
        (self.out/'sealed/extra.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):admitted.revalidate()

    def test_discovery_does_not_rewrite_a_separate_original_history(self):
        # Authored unit fixture, explicitly not claimed as executed discovery.
        capture=dict(schema=1,runtime_abi=29,capacity=4,dropped_instructions=0,unreadable_instructions=0,
            complete=True,retired_instructions=1,observations=[dict(pc=0xE100,mpr=list(workflow.M0),
                physical=[0x100,0x101],data=[0xA9,0xF8],native_hits=0,interpreted_hits=1)])
        raw=self.out/'authored-unexecuted-capture-fixture.json';workflow.write(raw,capture)
        history=compose_history([raw],self.out/'original-history')
        before={relative:item['path'].read_bytes() for relative,item in history.artifact_bindings.items()}
        discover_roots(self.out/'seed-roots.json',self.image,self.out/'static-only',rom_ranges=workflow.ROM_RANGES)
        self.assertEqual({relative:item['path'].read_bytes() for relative,item in history.artifact_bindings.items()},before)
        history.revalidate()


@unittest.skipUnless(HEADLESS.is_file() and shutil.which('cmake'),'Build a headless host and install CMake')
class StaticWorkflowActualTests(unittest.TestCase):
    def test_real_known_bank_switch_native_reference_call_ram_and_guard(self):
        cache=cmake_cache(ROOT/'build',os.environ.get('PCE_TEST_CMAKE_CACHE'))
        if cache is None:self.skipTest('Built compiler configuration required')
        options={}
        for line in cache.read_text(encoding='utf-8').splitlines():
            if '=' in line and ':' in line.split('=',1)[0]:
                key,value=line.split('=',1);options[key.split(':',1)[0]]=value
        arguments=[]
        for key in ('CMAKE_CXX_COMPILER','CMAKE_MAKE_PROGRAM'):
            if key in options:
                value=Path(shutil.which(options[key]) or options[key]).resolve()
                arguments.append('-D'+key+'='+str(value))
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'authored';workflow.create(out)
            original=workflow.capture(out,HEADLESS)
            self.assertEqual(original['actual_work'],dict(native=0,interpreted=100))
            discovered=workflow.discover(out)
            self.assertEqual(discovered['expanded_identities'],15)
            prepared=workflow.prepare(out,with_history=True)
            self.assertFalse(prepared['compiled']);self.assertFalse(prepared['executed'])
            prefix=workflow.qualify(out,options.get('CMAKE_GENERATOR'),arguments)
            self.assertEqual(prefix['actual_work']['native'],100)
            result=workflow.probe(out)
            self.assertEqual(result['results']['native']['capture']['native'],110)
            self.assertEqual(result['results']['reference']['capture']['interpreted'],110)
            self.assertEqual(result['results']['guard']['capture']['native'],104)
            self.assertEqual(result['results']['native']['ram_sha256'],result['results']['reference']['ram_sha256'])
            self.assertEqual(result['results']['native']['ram_bytes'],8192)


if __name__=='__main__':unittest.main()
