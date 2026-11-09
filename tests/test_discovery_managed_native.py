"""Actual native managed generations retain and rederive original discovery graphs."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import discovery, incremental as inc, project
from pcerecomp.emitter import emit_declarations
from tests import test_incremental_native
from test_queued_persistence import isolated_environment

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('managed_vector_workflow',ROOT/'examples/rom-vectors/workflow.py')
workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)


class NativeDiscoveryManagedTests(unittest.TestCase):
    def test_graph_only_update_reuses_actual_objects_and_archives_both_derivations(self):
        compiler,bundle=test_incremental_native.NativeManagedRebuildTests.compiler_bundle(self)
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'fixture';workflow.create(out);workflow.prepare(out,retain_discovery=True)
            image=out/'card.pce';descriptor=out/'consumer/project.toml';workspace=out/'managed'
            args=('-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(bundle/'bin/ninja.exe'))
            initial=inc.rebuild(descriptor,workspace,create=True,toolchain_root=bundle,cmake_args=args)
            self.assertFalse(initial['execution_evidence'])
            self.assertIn('module_discovery',initial['binding']['files'])
            self.assertFalse((workspace/'module/declared-roots.json').exists())

            def run(name):
                capture=out/(name+'-capture.json')
                with patch.dict(os.environ,isolated_environment(),clear=True):
                    result=project.run(workspace/'project.toml',workspace/'output',out/(name+'-run.json'),
                                       code_capture=capture,capture_limit=32)
                self.assertTrue(result['qualified'])
                state=result['result']
                self.assertEqual((state['pc'],state['a'],state['x'],state['y'],state['sp'],state['p']),
                                 (0xE143,42,2,0,0,4))
                self.assertEqual((state['cycles'],state['ticks'],state['native_steps'],
                                  state['interpreter_steps'],state['guard_misses']),(39,468,9,0,0))
                workflow.check_capture(capture,'native')
                self.assertEqual(result['binding']['files']['module_discovery'],
                                 project.sha256(workspace/'module/discovery/discovery.json'))
                return result

            run('before')
            old_archive=workspace/'history/000000/discovery'
            old_bytes={p.name:p.read_bytes() for p in old_archive.iterdir()}
            objects={p.relative_to(workspace).as_posix():(project.sha256(p),p.stat().st_mtime_ns)
                     for p in (workspace/'output').rglob('*') if p.suffix in ('.obj','.o')}
            self.assertTrue(objects)
            code={p.name:(project.sha256(p),p.stat().st_mtime_ns)
                  for p in (workspace/'module').iterdir() if p.suffix in ('.cpp','.hpp')}
            seeds=json.loads((out/'seeds.json').read_bytes())
            seeds['roots'].append(workflow.entry(*workflow.PLAN[-1]))
            second_seeds=out/'second-seeds.json';workflow.write(second_seeds,seeds)
            graph=discovery.discover_roots(second_seeds,image,out/'second-discovery',
                rom_ranges=workflow.CODE_RANGES,rom_vector_ranges=workflow.VECTOR_RANGES,
                instruction_limit=32,context_limit=4)
            self.assertEqual((out/'discovery/roots.json').read_bytes(),graph.roots_path.read_bytes())
            self.assertNotEqual(project.sha256(out/'discovery/discovery.json'),graph.sha256)
            module=out/'second-module';emit_declarations(graph.roots_path,image,module,partition_layout='stable')
            config=tomllib.loads(descriptor.read_text(encoding='utf-8'))
            config['tool']['path']=str(ROOT);config['cartridge']['path']=str(image)
            config['module']['declared_roots']=dict(path=str(graph.roots_path),sha256=graph.declarations.sha256)
            config['module']['discovery']=dict(path=str(graph.report_path),sha256=graph.sha256)
            for role,name in (('source','module.cpp'),('manifest','module.json')):
                config['module'][role]=dict(path=str(module/name),sha256=project.sha256(module/name))
            candidate=out/'candidate.toml';candidate.write_text(inc._toml(config),encoding='utf-8')
            updated=inc.rebuild(candidate,workspace)
            work=updated['incremental']['object_timestamps']
            self.assertEqual(work['rebuilt'],[]);self.assertEqual(work['added'],[]);self.assertEqual(work['obsolete'],[])
            self.assertEqual(len(work['retained']),len(objects))
            self.assertEqual({p.relative_to(workspace).as_posix():(project.sha256(p),p.stat().st_mtime_ns)
                              for p in (workspace/'output').rglob('*') if p.suffix in ('.obj','.o')},objects)
            self.assertEqual({p.name:(project.sha256(p),p.stat().st_mtime_ns)
                              for p in (workspace/'module').iterdir() if p.suffix in ('.cpp','.hpp')},code)
            self.assertEqual(set(updated['incremental']['module_changes']['changed']),
                             {'discovery/discovery.json','discovery/seed-roots.json'})
            run('after')
            self.assertEqual({p.name:p.read_bytes() for p in old_archive.iterdir()},old_bytes)
            first=discovery.load_discovery(old_archive,image)
            second=discovery.load_discovery(workspace/'history/000001/discovery',image)
            self.assertEqual(first.report['summary']['seed_roots'],1)
            self.assertEqual(second.report['summary']['seed_roots'],2)
            self.assertEqual(first.declarations.sha256,second.declarations.sha256)
            self.assertNotEqual(first.sha256,second.sha256)
            state=inc._state(workspace)
            self.assertEqual(state['discovery']['sha256'],graph.sha256)
            self.assertEqual(state['declared_roots']['file'],'discovery/roots.json')
            self.assertEqual({p.name for p in second.report_path.parent.iterdir()},
                             {'seed-roots.json','roots.json','discovery.json'})
            config['module'].pop('discovery');dropped=out/'drop.toml';dropped.write_text(inc._toml(config),encoding='utf-8')
            before=inc._snapshot(workspace)
            with patch.object(inc,'prepare') as compile_inputs,self.assertRaisesRegex(ValueError,'discovery binding cannot be removed'):
                inc.rebuild(dropped,workspace)
            compile_inputs.assert_not_called();self.assertEqual(inc._snapshot(workspace),before)
