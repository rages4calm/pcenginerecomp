"""Actual native flag/bit branches and omitted-path refusals."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from pcerecomp.discovery import discover_roots
from scripts.build_config import cmake_cache
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('conditional_workflow',ROOT/'examples/branch-facts/workflow.py')
w=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(w)

class ConditionalWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.out=Path(temp.name)/'fixture';w.create(self.out)

    def test_old_both_path_join_blocks_main_and_overdeclares_matrix(self):
        old=discover_roots(self.out/'seeds.json',self.out/'card.pce',self.out/'old',rom_ranges=w.f.code_ranges(),rom_data_ranges=w.f.DATA_RANGES,call_depth_limit=8,alu_facts=True)
        self.assertEqual(len(old.declarations.roots),1193)
        self.assertEqual({r['reason'] for r in old.report['unresolved']},{'mapping_change'})
        self.assertEqual(len(w.f.plan()),1068);self.assertEqual(sum(c['steps'] for c in w.f.fixture()[1]),1040)

    def test_preparation_preserves_all_decisions_without_observed_hits(self):
        result=w.prepare(self.out);self.assertFalse(result['execution_evidence'])
        graph=json.loads((self.out/'discovery/discovery.json').read_text())
        self.assertEqual(graph['summary']['candidate_roots'],1068);self.assertEqual(graph['summary']['decided_conditionals'],99)
        self.assertEqual(graph['summary']['pruned_conditional_edges'],99);self.assertEqual(graph['summary']['unknown_conditionals'],0)
        self.assertEqual((self.out/'consumer/discovery/discovery.json').read_bytes(),(self.out/'discovery/discovery.json').read_bytes())
        manifest=json.loads((self.out/'consumer/module/module.json').read_text());self.assertEqual(manifest['declared_only'],1068)
        self.assertEqual(manifest['observed_instructions'],0)

    @unittest.skipUnless(shutil.which('cmake'),'CMake required for executed authored consumer')
    def test_real_native_conditions_both_senses_bit_forms_dynamic_data_and_guards(self):
        args=[];cache=cmake_cache(ROOT/'build',os.environ.get('PCE_TEST_CMAKE_CACHE'))
        if cache:
            for line in cache.read_text().splitlines():
                if line.startswith(('CMAKE_CXX_COMPILER:','CMAKE_MAKE_PROGRAM:')):
                    key,value=line.split('=',1);args.append('-D'+key.split(':',1)[0]+'='+value)
        w.prepare(self.out);result=w.qualify(self.out,'Ninja' if shutil.which('ninja') else None,args)
        self.assertTrue(result['passed']);self.assertEqual(result['declared'],1068)
        for mode,count in (('main',28),('matrix',1040),('value-change',28)):
            value=result['results'][mode]['state'];self.assertEqual((value['native'],value['interpreted'],value['guards']),(count,0,0))
        self.assertEqual(result['results']['matrix-reference']['state']['interpreted'],1040)
        for mode,count in (('bank-change',5),('overflow-change',14),('sign-change',22),('source-change',18)):
            value=result['results'][mode]['state'];self.assertEqual((value['native'],value['interpreted'],value['guards']),(count,0,1))
