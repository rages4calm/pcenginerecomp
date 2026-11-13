"""Real native bank transitions and immutable-data load witnesses stay distinct."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.discovery import discover_roots
from scripts.build_config import cmake_cache

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('rom_data_workflow',ROOT/'examples/rom-data/workflow.py')
w=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(w)

class RomDataWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.out=Path(temporary.name)/'fixture';w.create(self.out)

    def test_old_policy_stops_at_data_driven_tam_and_preserves_matrix_candidates(self):
        found=discover_roots(self.out/'seeds.json',self.out/'card.pce',self.out/'old',rom_ranges=w.f.code_ranges(),
            rom_vector_ranges=w.f.VECTOR_RANGES,call_depth_limit=8)
        self.assertEqual(len(found.declarations.roots),260)
        self.assertEqual({r['reason'] for r in found.report['unresolved']},{'mapping_change'})
        self.assertNotIn('resolved_rom_data_loads',found.report['summary'])

    def test_preparation_retains_original_graph_and_unobserved_membership(self):
        result=w.prepare(self.out)
        self.assertFalse(result['execution_evidence'])
        graph=json.loads((self.out/'discovery/discovery.json').read_text())
        self.assertEqual(graph['summary']['resolved_rom_data_loads'],70)
        self.assertEqual(graph['summary']['candidate_roots'],273)
        retained=list((self.out/'consumer').rglob('discovery.json'))
        self.assertEqual(len(retained),1)
        self.assertEqual(retained[0].read_bytes(),(self.out/'discovery/discovery.json').read_bytes())
        manifest=json.loads((self.out/'consumer/module/module.json').read_text())
        self.assertEqual(manifest['declared_only'],273)
        self.assertEqual(manifest['observed_instructions'],0)

    def test_helper_source_and_original_bytes_are_bound_separately(self):
        record=json.loads((self.out/'creation.json').read_text())
        record['sources']['examples/native_support.py']='0'*64
        (self.out/'creation.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'Fixture/SDK changed'):w.inputs(self.out)
        self.assertFalse((self.out/'discovery').exists())

    def test_shared_process_helper_preserves_failed_timeout_outputs(self):
        failure=subprocess.TimeoutExpired(['authored'],1,output=b'partial-out',stderr=b'partial-error')
        with patch.object(w.support.subprocess,'run',side_effect=failure),self.assertRaisesRegex(ValueError,'partial output retained'):
            w.process(self.out,'timed',['authored'],timeout=1)
        record=json.loads((self.out/'timed-process.json').read_text())
        self.assertIsNone(record['exit_code']);self.assertTrue(record['timed_out'])
        self.assertEqual((self.out/'timed.stdout').read_bytes(),b'partial-out')
        self.assertEqual((self.out/'timed.stderr').read_bytes(),b'partial-error')

    @unittest.skipUnless(shutil.which('cmake'),'CMake required for compiled authored workflow')
    def test_actual_native_banked_route_all_load_modes_data_variation_and_guards(self):
        args=[];cache=cmake_cache(ROOT/'build',os.environ.get('PCE_TEST_CMAKE_CACHE'))
        if cache:
            for line in cache.read_text().splitlines():
                if line.startswith(('CMAKE_CXX_COMPILER:','CMAKE_MAKE_PROGRAM:')):
                    key,value=line.split('=',1);args.append('-D'+key.split(':',1)[0]+'='+value)
        w.prepare(self.out);result=w.qualify(self.out,'Ninja' if shutil.which('ninja') else None,args)
        self.assertTrue(result['passed']);self.assertEqual(result['declared'],273)
        self.assertEqual(result['cold']['retired'],17)
        for mode,count in (('main',17),('matrix',256),('value-change',17)):
            self.assertEqual(result['results'][mode]['state']['native'],count)
            self.assertEqual(result['results'][mode]['state']['interpreted'],0)
            self.assertEqual(result['results'][mode]['state']['guards'],0)
        self.assertEqual(result['results']['reference']['state']['interpreted'],17)
        self.assertEqual(result['results']['matrix-reference']['state']['interpreted'],256)
        self.assertEqual(result['results']['bank-change']['state']['native'],4)
        self.assertEqual(result['results']['source-change']['state']['native'],10)
        for mode in ('bank-change','source-change'):self.assertEqual(result['results'][mode]['state']['guards'],1)

if __name__=='__main__':unittest.main()
