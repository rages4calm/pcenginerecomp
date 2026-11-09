"""Authored declarations remain separate from actual native retirement evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from scripts.build_config import cmake_cache

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('declared_workflow_example',ROOT/'examples/declared-roots/workflow.py')
EXAMPLE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(EXAMPLE)
HEADLESS=Path(os.environ.get('PCE_TEST_HEADLESS',ROOT/'build'/('pce-headless.exe' if os.name=='nt' else 'pce-headless')))

class DeclaredWorkflowPlanTests(unittest.TestCase):
    def test_process_timeout_preserves_exact_partial_outputs_and_failed_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            failure=subprocess.TimeoutExpired(['authored'],1,output=b'partial-out',stderr=b'partial-error')
            with patch.object(EXAMPLE.subprocess,'run',side_effect=failure),self.assertRaisesRegex(ValueError,'partial output retained'):
                EXAMPLE.process(out,'bounded',['authored'],timeout=1)
            self.assertEqual((out/'bounded.stdout').read_bytes(),b'partial-out')
            self.assertEqual((out/'bounded.stderr').read_bytes(),b'partial-error')
            receipt=json.loads((out/'bounded-process.json').read_text())
            self.assertIsNone(receipt['exit_code']);self.assertIs(receipt['timed_out'],True)
    def test_cli_validation_does_not_claim_emission_and_cli_emission_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'authored.pce';image.write_bytes(EXAMPLE.card_bytes())
            path=root/'roots.json';path.write_text(json.dumps(EXAMPLE.roots(image)),encoding='utf-8')
            result=subprocess.run([sys.executable,'-m','pcerecomp','declared-roots',str(path),'--image',str(image)],
                cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            admitted=json.loads(result.stdout)
            for key in ('execution_evidence','emitted','compiled','executed'):self.assertIs(admitted[key],False)
            self.assertEqual(admitted['membership']['observed_instructions'],0)
            self.assertEqual(admitted['membership']['declared_only'],6)
            self.assertNotIn('emitted_instructions',admitted['membership'])
            output=root/'module'
            result=subprocess.run([sys.executable,'-m','pcerecomp','emit-roots',str(path),'--image',str(image),
                '--out',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            manifest=json.loads((output/'module.json').read_text())
            self.assertEqual(manifest['observed_instructions'],0)
            self.assertEqual(manifest['declared_instructions'],6)
            self.assertEqual(manifest['native_instructions_emitted'],6)
            self.assertNotIn('historical_totals',manifest)

    def test_authored_image_vector_loop_and_never_run_routine_are_explicit(self):
        image=EXAMPLE.card_bytes()
        self.assertEqual(len(image),8192)
        self.assertEqual(image[:18],bytes.fromhex('A9 F8 53 02 D4 A2 FF 9A AD 00 20 F0 FB 20 40 E0 80 F6'))
        self.assertEqual(image[64:73],bytes.fromhex('A9 2A 8D 01 20 9C 00 20 60'))
        self.assertEqual(image[-2:],bytes.fromhex('00 E0'))
        self.assertEqual([p for p,n in EXAMPLE.ENTRIES],[13,16,64,66,69,72])
        # Five setup ops/14 cycles;48 LDA*5 +47 takenBEQ*4 =442 cycles.
        self.assertEqual(14+48*5+47*4,442)
        # Nine slow cycles, plus433 fastcycles:108+1299=1407 ticks.
        self.assertEqual(9*12+433*3,1407)

    def test_numeric_declarations_have_source_offsets_and_no_retirement_claims(self):
        from pcerecomp.declarations import load_declarations
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'authored.pce';image.write_bytes(EXAMPLE.card_bytes())
            value=EXAMPLE.roots(image);path=Path(directory)/'roots.json';path.write_text(json.dumps(value),encoding='utf-8')
            admitted=load_declarations(path,image)
            self.assertEqual(len(admitted.instructions),6)
            self.assertEqual(value['execution_evidence'],False)
            for row in admitted.instructions:
                self.assertNotIn('native_hits',row);self.assertNotIn('interpreted_hits',row)
            bad=copy.deepcopy(value);bad['roots'][0]['native_hits']=1;path.write_text(json.dumps(bad),encoding='utf-8')
            with self.assertRaises(ValueError):load_declarations(path,image)

@unittest.skipUnless(HEADLESS.is_file(),'Build headless runner or set PCE_TEST_HEADLESS')
class DeclaredWorkflowActualTests(unittest.TestCase):
    def test_valid_counter_edit_cannot_relabel_original_process_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'declared';EXAMPLE.capture(out,HEADLESS)
            value=json.loads((out/'observed.json').read_bytes())
            value['observations'][0]['interpreted_hits']+=1;value['retired_instructions']+=1
            (out/'observed.json').write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'discovery artifacts'):
                EXAMPLE.prepare(out)
            self.assertFalse((out/'history').exists());self.assertFalse((out/'consumer').exists())

    def test_real_prefix_mixed_compile_later_declared_execution_ram_and_guard(self):
        if not shutil.which('cmake'):self.skipTest('CMake required for compiled native probe')
        args=[];cache=cmake_cache(ROOT/'build',os.environ.get('PCE_TEST_CMAKE_CACHE'))
        if cache:
            for line in cache.read_text(encoding='utf-8').splitlines():
                if line.startswith(('CMAKE_CXX_COMPILER:','CMAKE_MAKE_PROGRAM:')):
                    key,val=line.split('=',1);key=key.split(':',1)[0]
                    if Path(val).is_file():args.append('-D'+key+'='+val)
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'declared'
            captured=EXAMPLE.capture(out,HEADLESS)
            self.assertEqual(captured['declared_roots_executed'],0)
            originals={name:(out/name).read_bytes() for name in ('observed.json','roots.json','authored-card.pce')}
            prepared=EXAMPLE.prepare(out)
            self.assertFalse(prepared['execution_evidence'])
            manifest=json.loads((out/'consumer/module/module.json').read_text())
            self.assertEqual(manifest['observed_instructions'],7)
            self.assertEqual(manifest['declared_instructions'],6)
            self.assertEqual(manifest['source_identity_count'],13)
            self.assertEqual(manifest['historical_totals']['retired_instructions'],100)
            qualified=EXAMPLE.qualify(out,'Ninja' if shutil.which('ninja') else None,args)
            self.assertEqual(qualified['actual_work'],dict(native=100,interpreted=0,total=100,native_fraction=1.0))
            self.assertEqual(qualified['declared_roots_executed'],0)
            probed=EXAMPLE.probe(out)
            self.assertEqual(probed['results']['normal'],dict(passed=True,mode='normal',native=110,interpreted=0,guards=0,cycles=488,ticks=1545))
            self.assertEqual(probed['results']['guard'],dict(passed=True,mode='guard',native=104,interpreted=0,guards=1,cycles=460,ticks=1461))
            self.assertEqual({name:(out/name).read_bytes() for name in originals},originals)
            self.assertEqual(json.loads((out/'consumer/module/module.json').read_text())['historical_totals']['retired_instructions'],100)
