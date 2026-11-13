"""Authored table candidates and actual native all-byte execution are separate."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.discovery import discover_roots,load_discovery
from scripts.build_config import cmake_cache

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('rom_table_workflow',ROOT/'examples/rom-tables/workflow.py')
workflow=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(workflow)


class RomTableWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.out=Path(temp.name)/'fixture';workflow.create(self.out)

    def test_table_policy_derives_all_four_lanes_without_observations(self):
        graph=discover_roots(self.out/'seeds.json',self.out/'card.pce',self.out/'graph',
            rom_ranges=workflow.CODE_RANGES,rom_vector_ranges=workflow.VECTOR_RANGES,rom_table_limit=1)
        self.assertEqual(len(graph.declarations.roots),19)
        self.assertEqual(graph.report['summary']['resolved_vector_entries'],256)
        self.assertFalse(graph.report['execution_evidence'])
        self.assertEqual(graph.report['unresolved'],[])
        self.assertEqual({n['pc'] for n in graph.report['nodes'] if n['mnemonic']=='LDA'},
                         {0xE000,0xE040,0xE050,0x50E0,0x40E0})
        load_discovery(graph.report_path,self.out/'card.pce').revalidate()

    def test_omitted_option_stops_at_unknown_x_instead_of_fabricating_a_table(self):
        graph=discover_roots(self.out/'seeds.json',self.out/'card.pce',self.out/'legacy',
            rom_ranges=workflow.CODE_RANGES,rom_vector_ranges=workflow.VECTOR_RANGES)
        self.assertEqual(len(graph.declarations.roots),3)
        self.assertEqual({r['reason'] for r in graph.report['unresolved']},{'indirect_index_unknown'})

    def test_preparation_retains_exact_discovery_and_no_execution_claim(self):
        result=workflow.prepare(self.out)
        self.assertFalse(result['execution_evidence'])
        original=self.out/'discovery/discovery.json'
        copies=list((self.out/'consumer').rglob('discovery.json'))
        self.assertEqual(len(copies),1)
        self.assertEqual(copies[0].read_bytes(),original.read_bytes())
        manifest=json.loads((self.out/'consumer/module/module.json').read_text())
        self.assertEqual(manifest['declared_only'],19)
        self.assertEqual(manifest['observed_instructions'],0)

    def test_process_timeout_retains_partial_output_and_does_not_claim_completion(self):
        failure=subprocess.TimeoutExpired(['authored'],1,output=b'partial-out',stderr=b'partial-error')
        with patch.object(workflow.subprocess,'run',side_effect=failure),self.assertRaisesRegex(ValueError,'partial output retained'):
            workflow.process(self.out,'bounded',['authored'],timeout=1)
        self.assertEqual((self.out/'bounded.stdout').read_bytes(),b'partial-out')
        self.assertEqual((self.out/'bounded.stderr').read_bytes(),b'partial-error')
        record=json.loads((self.out/'bounded-process.json').read_text())
        self.assertIsNone(record['exit_code']);self.assertTrue(record['timed_out'])

    @unittest.skipUnless(shutil.which('cmake'),'CMake required for compiled matrix')
    def test_actual_official_cold_and_all_256_indices_native_reference_and_negatives(self):
        args=[];cache=cmake_cache(ROOT/'build',os.environ.get('PCE_TEST_CMAKE_CACHE'))
        if cache:
            for line in cache.read_text().splitlines():
                if line.startswith(('CMAKE_CXX_COMPILER:','CMAKE_MAKE_PROGRAM:')):
                    key,value=line.split('=',1);args.append('-D'+key.split(':',1)[0]+'='+value)
        workflow.prepare(self.out)
        result=workflow.qualify(self.out,'Ninja' if shutil.which('ninja') else None,args)
        self.assertTrue(result['passed'])
        self.assertEqual(result['official_cold_native'],7)
        for mode in ('native','reference'):
            actual=result['matrix'][mode]
            self.assertEqual(actual['state'],dict(passed=True,cases=256,native=1792 if mode=='native' else 0,
                interpreted=1792 if mode=='reference' else 0,guards=0))
            self.assertEqual(actual['capture']['identities'],19)
        for mode in ('source-change','vector-change'):
            self.assertEqual(result['matrix'][mode]['state'],dict(passed=True,cases=1,native=3,interpreted=0,guards=1))


if __name__=='__main__':unittest.main()
