"""Optional native span emission and actual authored boundary/fault execution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pcerecomp.cli import main
from pcerecomp.emitter import emit_capture
from tests.test_capture import capture, observation
from tests.generate_native_span_fixture import generate

ROOT = Path(__file__).resolve().parent.parent
COMPILER = shutil.which('clang++') or shutil.which('g++')


class SpanEmissionTests(unittest.TestCase):
    def test_optional_feature_is_explicit_and_legacy_source_remains_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); report=capture([observation(0x4000,(0xea,))])
            omitted=emit_capture(report,root/'omitted',partition_layout='stable')
            disabled=emit_capture(report,root/'disabled',partition_layout='stable',native_span=False)
            self.assertEqual(omitted,disabled)
            for path in (root/'omitted').iterdir():
                self.assertEqual(path.read_bytes(),(root/'disabled'/path.name).read_bytes())
            self.assertNotIn('native_span',omitted)
            selected=emit_capture(report,root/'selected',partition_layout='stable',native_span=True)
            self.assertEqual(selected['native_span'],dict(schema=1,protocol='per_instruction_v1'))
            self.assertEqual(selected['translated_body_count'],omitted['translated_body_count'])
            self.assertEqual(selected['native_span_translated_body_count'],selected['translated_body_count'])
            source='\n'.join(p.read_text() for p in (root/'selected').glob('*.cpp'))
            self.assertIn('Exit generated_step(',source)
            self.assertIn('Exit generated_span(',source)
            self.assertIn('s.mpr!=expected_mpr',source)
            self.assertIn('span.commit(bus,s,deadline)',source)
            self.assertNotIn('interpret_step(',source)

    def test_invalid_feature_values_or_layout_fail_before_writing(self):
        for options in (dict(native_span=1),dict(native_span='true'),dict(native_span=None),
                        dict(native_span=True),dict(native_span=True,partition_layout='balanced')):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                out=Path(directory)/'output'
                with self.assertRaises(ValueError):emit_capture(capture(),out,**options)
                self.assertFalse(out.exists())

    def test_cli_flag_emits_versioned_optional_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'capture.json';path.write_text(json.dumps(capture()))
            self.assertEqual(main(['emit-capture',str(path),'--out',str(root/'module'),
                '--partition-layout','stable','--native-span']),0)
            self.assertEqual(json.loads((root/'module/module.json').read_text())['native_span'],
                             dict(schema=1,protocol='per_instruction_v1'))

    @unittest.skipUnless(shutil.which('cmake') and shutil.which('ninja') and COMPILER,
                         'CMake/Ninja/C++ compiler required for actual native span test')
    def test_actual_native_boundaries_fallback_self_modification_irq_block_and_faults(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); generate(root/'module'); (root/'captures').mkdir()
            (root/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.20)
project(SpanBoundaryTests LANGUAGES CXX)
set(PCE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(PCE_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
add_subdirectory("{ROOT.as_posix()}" tool)
pce_add_native_module(native_objects MODULE module/module.cpp MANIFEST module/module.json)
add_executable(span-boundaries "{(ROOT/'tests/native_span_tests.cpp').as_posix()}")
target_link_libraries(span-boundaries PRIVATE pce-runtime ${{native_objects}})
''',encoding='utf-8')
            configured=subprocess.run(['cmake','-S',str(root),'-B',str(root/'build'),'-G','Ninja',
                '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+COMPILER],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(configured.returncode,0,configured.stdout+configured.stderr)
            compiled=subprocess.run(['cmake','--build',str(root/'build'),'--parallel','2','--target','span-boundaries'],
                capture_output=True,text=True,timeout=90)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            executable=root/'build'/('span-boundaries.exe' if os.name=='nt' else 'span-boundaries')
            result=subprocess.run([str(executable),str(root/'captures')],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=json.loads(result.stdout)
            self.assertTrue(report['passed'])
            self.assertGreater(report['checks'],350)
            self.assertGreater(report['cases'],100)
            self.assertEqual(report['basic_native'],18)
            self.assertEqual(report['basic_ticks'],162)
            for path in (root/'captures').glob('*.json'):
                captured=json.loads(path.read_text())
                self.assertTrue(captured['complete'])
                self.assertEqual(captured['dropped_instructions'],0)
                self.assertEqual(captured['unreadable_instructions'],0)


if __name__=='__main__':unittest.main()
