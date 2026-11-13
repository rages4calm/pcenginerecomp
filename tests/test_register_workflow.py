"""Prepared and executed original register-evaluation consumer."""
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
SPEC=importlib.util.spec_from_file_location('register_workflow',ROOT/'examples/register-eval/workflow.py')
w=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(w)

class RegisterWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.out=Path(temp.name)/'fixture';w.create(self.out)

    def test_old_policy_stops_and_full_plan_has_exact_independent_sources(self):
        old=discover_roots(self.out/'seeds.json',self.out/'card.pce',self.out/'old',rom_ranges=w.f.code_ranges(),rom_data_ranges=w.f.DATA_RANGES,call_depth_limit=8)
        self.assertEqual(len(old.declarations.roots),1999)
        self.assertEqual({r['reason'] for r in old.report['unresolved']},{'mapping_change'})
        self.assertEqual(len(w.f.plan()),2016);self.assertEqual(sum(c['steps'] for c in w.f.fixture()[1]),1992)

    def test_preparation_rederives_and_preserves_original_graph(self):
        result=w.prepare(self.out);self.assertFalse(result['execution_evidence'])
        graph=json.loads((self.out/'discovery/discovery.json').read_text())
        self.assertEqual(graph['summary']['candidate_roots'],2016)
        self.assertEqual(graph['summary']['resolved_rom_alu_operands'],109)
        self.assertEqual(graph['summary']['resolved_rom_data_loads'],2)
        self.assertEqual((self.out/'consumer/discovery/discovery.json').read_bytes(),(self.out/'discovery/discovery.json').read_bytes())
        manifest=json.loads((self.out/'consumer/module/module.json').read_text());self.assertEqual(manifest['declared_only'],2016)
        self.assertEqual(manifest['observed_instructions'],0)

    @unittest.skipUnless(shutil.which('cmake'),'CMake required for executed authored consumer')
    def test_native_matrix_dynamic_operand_and_mapping_source_guards(self):
        args=[];cache=cmake_cache(ROOT/'build',os.environ.get('PCE_TEST_CMAKE_CACHE'))
        if cache:
            for line in cache.read_text().splitlines():
                if line.startswith(('CMAKE_CXX_COMPILER:','CMAKE_MAKE_PROGRAM:')):
                    key,value=line.split('=',1);args.append('-D'+key.split(':',1)[0]+'='+value)
        w.prepare(self.out);result=w.qualify(self.out,'Ninja' if shutil.which('ninja') else None,args)
        self.assertTrue(result['passed']);self.assertEqual(result['declared'],2016)
        for mode,count in (('main',24),('matrix',1992),('value-change',24)):
            value=result['results'][mode]['state'];self.assertEqual((value['native'],value['interpreted'],value['guards']),(count,0,0))
        self.assertEqual(result['results']['matrix-reference']['state']['interpreted'],1992)
        for mode,count in (('bank-change',7),('source-change',14)):
            value=result['results'][mode]['state'];self.assertEqual((value['native'],value['interpreted'],value['guards']),(count,0,1))
