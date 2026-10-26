"""Actual cold/warm native packages, without retail input or owner saves."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import project
from pcerecomp.capture import load_capture
from scripts.build_config import cmake_cache
from test_queued_persistence import prepare, isolated_environment

ROOT=Path(__file__).resolve().parent.parent


class NativePackageCacheTests(unittest.TestCase):
    def test_verified_package_hit_freshly_configures_then_launches_without_consumer_build(self):
        if os.name!='nt' or not shutil.which('cmake') or not shutil.which('ninja'):
            self.skipTest('Verified cache producer requires Windows LLVM-MinGW and Ninja')
        cache_file=cmake_cache(ROOT/'build',os.environ.get('PCE_TEST_CMAKE_CACHE'))
        compiler=None
        if cache_file:
            for line in cache_file.read_text(encoding='utf-8').splitlines():
                if line.startswith('CMAKE_CXX_COMPILER:'):
                    compiler=Path(line.split('=',1)[1]).resolve();break
        if compiler is None or compiler.name.lower()!='clang++.exe':
            self.skipTest('Verified LLVM-MinGW bundle not selected')
        bundle=compiler.parent.parent
        if not (bundle/'x86_64-w64-mingw32/include').is_dir():
            self.skipTest('Compiler is not the supported self-contained LLVM-MinGW bundle')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache=root/'cache';cache.mkdir()
            descriptor,emission=prepare(root/'authored')
            args=('-DCMAKE_CXX_COMPILER='+str(compiler),
                  '-DCMAKE_MAKE_PROGRAM='+str(bundle/'bin/ninja.exe'))
            options=dict(generator='Ninja',cmake_args=args,cache_root=cache,cache_toolchain_root=bundle)
            cold=project.build(descriptor,root/'cold',**options)
            with patch('pcerecomp.project.subprocess.run',wraps=subprocess.run) as calls:
                warm=project.build(descriptor,root/'warm',**options)
            invoked=[call.args[0] for call in calls.call_args_list]
            self.assertTrue(any('-S' in command for command in invoked))
            self.assertFalse(any('--build' in command for command in invoked))
            self.assertFalse(cold['cache']['hit']);self.assertTrue(warm['cache']['hit'])
            self.assertEqual(len(warm['commands']),1)
            self.assertIn('-S',warm['commands'][0])
            self.assertEqual(cold['cache']['key'],warm['cache']['key'])
            self.assertEqual(cold['output_files'],warm['output_files'])
            self.assertFalse(cold['execution_evidence'] or warm['execution_evidence'])
            self.assertFalse(emission['execution_evidence'])
            runs=[]
            for name in ('cold','warm'):
                capture=root/(name+'-capture.json')
                with patch.dict(os.environ,isolated_environment(),clear=True):
                    receipt=project.run(descriptor,root/name,root/(name+'-run.json'),
                                        code_capture=capture,capture_limit=512)
                self.assertTrue(receipt['qualified'],receipt)
                result=receipt['result']
                self.assertEqual((result['native_steps'],result['interpreter_steps'],result['guard_misses']),
                                 (200,0,0))
                self.assertEqual((result['a'],result['x'],result['y'],result['vdc']['dma_words']),
                                 (255,1,0xCA,128))
                self.assertGreater(result['vdc_access']['wait_ticks'],0)
                observed,_=load_capture(capture)
                self.assertEqual(observed['retired_instructions'],200)
                self.assertTrue(observed['complete'])
                self.assertTrue(all(row['interpreted_hits']==0 for row in observed['observations']))
                self.assertNotIn('bram_session',receipt)
                runs.append(result)
            self.assertEqual(*runs)


if __name__=='__main__':unittest.main()
