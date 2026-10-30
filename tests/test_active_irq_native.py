"""Required authored active IRQ native/interpreter and fresh-restore smoke."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pcerecomp.capture import load_capture
from tests import active_irq_fixture as fixture

ROOT=Path(__file__).resolve().parent.parent
COMPILER=shutil.which('clang++')or shutil.which('g++')


@unittest.skipUnless(shutil.which('cmake')and shutil.which('ninja')and COMPILER,
                     'CMake/Ninja/C++ compiler required for actual active IRQ smoke')
class ActiveIrqNativeTests(unittest.TestCase):
    def test_actual_both_tiers_and_fresh_checkpoint_continuations(self):
        selected=('raster-high-retain-div3-vce4','raster-tai-mask-div12-vce3',
            'raster-high-mask-div12-vce2','collision-tai-retain-div12-vce4',
            'collision-high-mask-div3-vce3','collision-tai-retain-div3-vce2')
        with tempfile.TemporaryDirectory()as temporary:
            base=Path(temporary);module=fixture.fixtures(base/'inputs')
            wrapper=base/'wrapper';wrapper.mkdir()
            (wrapper/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.20)
project(ActiveIrqSmoke LANGUAGES CXX)
set(PCE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(PCE_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
add_subdirectory("{ROOT.as_posix()}" tool)
pce_add_native_module(native_objects MODULE "{(module/'module.cpp').as_posix()}" MANIFEST "{(module/'module.json').as_posix()}")
add_executable(active-irq "{(ROOT/'tests/active_irq_probe.cpp').as_posix()}")
target_include_directories(active-irq PRIVATE "{module.as_posix()}" "{(ROOT/'tests').as_posix()}")
target_link_libraries(active-irq PRIVATE pce-runtime ${{native_objects}})
''',encoding='utf-8')
            for command in (['cmake','-S',str(wrapper),'-B',str(base/'build'),'-G','Ninja',
                             '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+COMPILER],
                            ['cmake','--build',str(base/'build'),'--target','active-irq','--parallel','2']):
                result=subprocess.run(command,capture_output=True,text=True,timeout=180)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            binary=base/'build'/('active-irq.exe'if os.name=='nt'else'active-irq')
            for name in selected:
                for tier in ('native','interpreter'):
                    with self.subTest(case=name,tier=tier):
                        checkpoint=base/(name+'-'+tier+'.pcec')
                        reports=[]
                        for mode in ('write','resume'):
                            capture=base/(name+'-'+tier+'-'+mode+'.json')
                            command=[str(binary),name,str(module.parent/(name+'.pce')),
                                str(module.parent/'data.cue'),'2',mode,tier,str(checkpoint),str(capture)]
                            run=subprocess.run(command,capture_output=True,text=True,timeout=30)
                            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                            report=json.loads(run.stdout);reports.append(report)
                            observations,digest=load_capture(capture)
                            self.assertTrue(observations['complete'])
                            self.assertEqual(observations['retired_instructions'],report['window_work']['instructions'])
                            self.assertEqual(report['guard_misses'],0)
                            self.assertEqual(report['window_native'],report['window_work']['instructions']if tier=='native'else 0)
                            self.assertEqual(report['window_interpreted'],report['window_work']['instructions']if tier=='interpreter'else 0)
                            if mode=='resume':
                                self.assertEqual(observations['checkpoint_origin']['sha256'],report['checkpoint_sha256'])
                                self.assertEqual(observations['checkpoint_origin']['native_steps'],report['prefix_native'])
                                self.assertEqual(observations['checkpoint_origin']['interpreter_steps'],report['prefix_interpreted'])
                            else:self.assertNotIn('checkpoint_origin',observations)
                            self.assertEqual(report['final']['values'][8],2 if '-retain-'in name else 1)
                        self.assertEqual(reports[0]['checkpoint_sha256'],reports[1]['checkpoint_sha256'])
                        self.assertEqual(reports[0]['final_sha256'],reports[1]['final_sha256'])
                        for key in ('cut','final','journal','window_work','window_hits','ram','vram'):
                            self.assertEqual(reports[0][key],reports[1][key],key)


if __name__=='__main__':unittest.main()
