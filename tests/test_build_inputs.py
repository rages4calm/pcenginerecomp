"""Input closure is content based, not compiler-name or timestamp based."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.build_inputs import prepare, tree_identity, verify_closure, configuration_identity


class TreeIdentityTests(unittest.TestCase):
    def test_content_and_inventory_changes_invalidate_even_with_preserved_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header = root/'header.hpp'
            header.write_bytes(b'old')
            before = tree_identity(root)
            stamp = header.stat()
            header.write_bytes(b'new')
            os.utime(header, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertNotEqual(before['sha256'], tree_identity(root)['sha256'])
            header.write_bytes(b'old')
            self.assertEqual(before['sha256'], tree_identity(root)['sha256'])
            (root/'shadow.hpp').write_bytes(b'new include candidate')
            self.assertNotEqual(before['sha256'], tree_identity(root)['sha256'])

    def test_empty_directories_participate_in_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = tree_identity(root)
            (root/'new-search-directory').mkdir()
            self.assertNotEqual(before['sha256'], tree_identity(root)['sha256'])

    def test_linked_external_input_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base/'inputs';root.mkdir()
            target = base/'outside.hpp';target.write_bytes(b'outside')
            try:
                (root/'linked.hpp').symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('Host does not permit symlink creation')
            with self.assertRaisesRegex(ValueError, 'links|reparse'):
                tree_identity(root)


@unittest.skipUnless(os.name == 'nt', 'Verified cache producer targets Windows LLVM-MinGW')
class ProducerInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bundle = self.base/'bundle'
        for folder in ('bin','include','lib','x86_64-w64-mingw32/include','x86_64-w64-mingw32/lib'):
            (self.bundle/folder).mkdir(parents=True, exist_ok=True)
        for name in ('clang++.exe','cmake.exe','ninja.exe'):
            (self.bundle/'bin'/name).write_bytes(b'MZ authored test tool identity')
        self.module = self.base/'module';self.module.mkdir()
        (self.module/'module.cpp').write_text('/* authored */')
        self.tool = self.base/'tool'
        for folder in ('runtime','cmake'):
            (self.tool/folder).mkdir(parents=True)
        (self.tool/'CMakeLists.txt').write_text('project(authored)')
        (self.tool/'runtime/helper.inc').write_text('an input outside canonical suffixes')
        self.project = dict(tool_root=self.tool, tool_identity=dict(source_sha256='a'*64),
            identities=dict(module_source='b'*64, module_manifest='c'*64, bios='d'*64),
            files=dict(module_source=self.module/'module.cpp'))
        self.args = ['-DCMAKE_CXX_COMPILER='+str(self.bundle/'bin/clang++.exe'),
                     '-DCMAKE_MAKE_PROGRAM='+str(self.bundle/'bin/ninja.exe')]
        self.patcher = patch('pcerecomp.build_inputs.shutil.which', return_value=str(self.bundle/'bin/cmake.exe'))
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def context(self, **changed):
        options = dict(generator='Ninja', desktop=False, cmake_args=self.args,
            toolchain_root=self.bundle, dependency_roots=[], build_dir=self.base/'build',
            cache_root=self.base/'cache')
        options.update(changed)
        return prepare(self.project, **options)

    def test_contract_rehashes_toolchain_and_noncanonical_compile_inputs(self):
        initial = self.context()['contract']
        header = self.bundle/'include/standard.hpp';header.write_text('changed SDK')
        self.assertNotEqual(initial, self.context()['contract'])
        header.unlink()
        self.assertEqual(initial, self.context()['contract'])
        (self.tool/'runtime/helper.inc').write_text('changed')
        self.assertNotEqual(initial, self.context()['contract'])

    def test_runtime_assets_are_fresh_receipt_bindings_not_compiled_key_inputs(self):
        before = self.context()['contract']
        self.project['identities']['bios'] = 'e'*64
        self.assertEqual(before, self.context()['contract'])
        self.project['identities']['module_source'] = 'f'*64
        self.assertNotEqual(before, self.context()['contract'])

    def test_cache_environment_excludes_external_build_search_and_flags(self):
        env = self.context()['environment']
        with patch.dict(os.environ, {'CXXFLAGS':'-include unknown.hpp', 'CMAKE_PREFIX_PATH':'external',
                                    'CPATH':'external', 'LIBRARY_PATH':'external'}):
            with self.assertRaisesRegex(ValueError,'ambient'):
                self.context()
        self.assertFalse({'CXXFLAGS','CMAKE_PREFIX_PATH','CPATH','LIBRARY_PATH'} & env.keys())
        self.assertEqual(Path(env['PATH'].split(os.pathsep)[0]), self.bundle/'bin')

    def test_explicit_roots_and_tools_are_required(self):
        for changed in (dict(generator=None), dict(toolchain_root=None),
                        dict(cmake_args=[]), dict(cmake_args=self.args+self.args[:1]),
                        dict(cmake_args=self.args+['-DCMAKE_TOOLCHAIN_FILE=opaque.cmake']),
                        dict(build_dir=self.module/'build'), dict(cache_root=self.bundle/'cache')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.context(**changed)

    def test_desktop_requires_hashed_sdk_and_invalidates_on_sdk_change(self):
        sdk = self.base/'sdl-sdk';config = sdk/'lib/cmake/SDL3'
        config.mkdir(parents=True)
        (config/'SDL3Config.cmake').write_text('authored package identity')
        args = self.args+['-DSDL3_DIR='+str(config)]
        with self.assertRaisesRegex(ValueError, 'hashed SDK'):
            self.context(desktop=True, cmake_args=args)
        before = self.context(desktop=True, cmake_args=args, dependency_roots=[sdk])['contract']
        (sdk/'new-runtime.dll').write_bytes(b'MZ new SDK input')
        self.assertNotEqual(before, self.context(desktop=True, cmake_args=args,
                                               dependency_roots=[sdk])['contract'])

    def closure(self, *, header=None, library=None, compiler=None, mutate=None,
                name='closure-build', configuration_only=False, desktop=False, sdl=None):
        build=self.base/name/'build';reply=build/'.cmake/api/v1/reply'
        reply.mkdir(parents=True,exist_ok=True)
        wrapper=build.parent/'source';wrapper.mkdir(exist_ok=True)
        (wrapper/'CMakeLists.txt').write_text('project(authored)')
        (build/'CMakeFiles').mkdir(exist_ok=True)
        (build/'CMakeFiles/generated.cmake').write_text('set(ROOT "'+str(build)+'")')
        context=self.context()
        context['contract']['desktop']=desktop
        documents={'index-test.json':dict(reply={
            'toolchains-v1':dict(jsonFile='toolchains.json'),
            'codemodel-v2':dict(jsonFile='model.json'),
            'cmakeFiles-v1':dict(jsonFile='files.json')}),
            'toolchains.json':dict(toolchains=[
            dict(language='CXX',compiler=dict(id='Clang',path=str(compiler or self.bundle/'bin/clang++.exe'),
                implicit=dict(includeDirectories=[str(self.bundle/'include')],linkDirectories=[str(self.bundle/'lib')]))),
            dict(language='RC',compiler=dict(path=str(self.bundle/'bin/windres.exe'),implicit={}))]),
            'files.json':dict(inputs=[dict(path='CMakeLists.txt'),dict(path=str(self.tool/'CMakeLists.txt')),
                dict(path=str(build/'CMakeFiles/generated.cmake'),isGenerated=True)]),
            'model.json':dict(configurations=[dict(name='Release',targets=[dict(jsonFile=name) for name in
                ('target.json','runtime.json','module.json')])])}
        for filename,name,kind,artifact in [('target.json','pce-consumer','EXECUTABLE','bin/pce-consumer.exe'),
                ('runtime.json','pce-runtime','STATIC_LIBRARY','tool/runtime.a'),
                ('module.json','pce-module-'+'a'*64,'OBJECT_LIBRARY','CMakeFiles/module.obj')]:
            documents[filename]=dict(name=name,type=kind,artifacts=[dict(path=artifact)],
                sources=[dict(path=str(self.module/'module.cpp'),compileGroupIndex=0)],
                compileGroups=[dict(language='CXX',includes=[dict(path=str(self.module))],
                    compileCommandFragments=[dict(fragment='-O3 -DNDEBUG -std=c++20')])])
        documents['target.json']['link']=dict(commandFragments=[dict(role='flags',fragment='-O3 -DNDEBUG'),
            dict(role='libraries',fragment='-lkernel32 -luser32'),
            dict(role='libraries',fragment='"'+str(library or build/'tool/runtime.a')+'"')])
        if desktop:
            documents['desktop.json']=dict(documents['runtime.json'],name='pce-desktop-host',
                artifacts=[dict(path='tool/desktop.a')])
            documents['model.json']['configurations'][0]['targets'].append(dict(jsonFile='desktop.json'))
            dll=sdl or self.bundle/'bin/SDL3.dll'
            if sdl is None:dll.write_bytes(b'MZ authored SDL identity')
            (build/'cache-sdl-runtime.txt').write_text(str(dll))
        graphs={'build.ninja':'build all: phony\nworkdir = '+str(build)+'\n',
                'CMakeFiles/rules.ninja':'rule CXX_COMPILER\n  command = clang++ $in\n'}
        if mutate:mutate(documents,graphs,build)
        for filename,data in documents.items():
            (reply/filename).write_text(json.dumps(data))
        for filename,data in graphs.items():
            (build/filename).write_text(data)
        def run(command,**options):
            from types import SimpleNamespace
            return SimpleNamespace(stdout=('x86_64-w64-windows-gnu\n' if '-dumpmachine' in command
                else 'object.o: #deps\n    '+str(header or self.bundle/'include/standard.hpp')+'\n'))
        with patch('pcerecomp.build_inputs.subprocess.run',side_effect=run):
            return (configuration_identity if configuration_only else verify_closure)(context,build)

    def test_actual_cmake_closure_supports_resource_compiler_and_library_lists(self):
        report=self.closure()
        self.assertEqual(report['header_count'],1)
        self.assertTrue(report['cmake_file_api'] and report['ninja_dependencies'])

    def test_actual_header_and_library_inputs_outside_hashed_roots_are_refused(self):
        for options in (dict(header=self.base/'untracked.hpp'),
                        dict(header=self.tool/'untracked.hpp'),
                        dict(library=self.base/'external library.a'),
                        dict(compiler=self.base/'other-compiler.exe')):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.closure(**options)

    def test_configuration_key_changes_for_actual_flags_defines_and_ninja_commands(self):
        before=self.closure(configuration_only=True)
        for field in ('flags','defines','command'):
            def mutate(d,g,b):
                if field=='flags':d['target.json']['compileGroups'][0]['compileCommandFragments'][0]['fragment']='-O2 -DNDEBUG'
                elif field=='defines':d['target.json']['compileGroups'][0]['defines']=[dict(define='EXTERNAL_READ_VALUE=2')]
                else:g['CMakeFiles/rules.ninja']+='  description = changed actual graph\n'
            self.assertNotEqual(before,self.closure(mutate=mutate,configuration_only=True))

    def test_independent_build_paths_normalize_but_generated_configuration_bytes_still_bind(self):
        before=self.closure(name='cold',configuration_only=True)
        self.assertEqual(before,self.closure(name='warm',configuration_only=True))
        def mutate(d,g,b):(b/'CMakeFiles/generated.cmake').write_text('set(CHANGED 1)')
        self.assertNotEqual(before,self.closure(name='changed',mutate=mutate,configuration_only=True))

    def test_external_cmake_input_and_generated_compile_source_or_header_are_rejected(self):
        def outside(d,g,b):d['files.json']['inputs'].append(dict(path=str(self.base/'external.cmake')))
        def generated(d,g,b):d['target.json']['sources'][0].update(path=str(b/'generated.cpp'),isGenerated=True)
        def header(d,g,b):d['target.json']['compileGroups'][0]['includes'].append(dict(path=str(b/'generated-headers')))
        for mutate in (outside,generated,header):
            with self.subTest(mutate=mutate.__name__),self.assertRaises(ValueError):self.closure(mutate=mutate)
        with self.assertRaises(ValueError):self.closure(header=self.base/'closure-build/build/generated.hpp')

    def test_external_flags_response_files_and_nonstandard_target_graph_are_rejected(self):
        for flag in ('@external.rsp','--config=outside.cfg','-fplugin=evil.dll','-Wl,--script=outside.ld','-Wl=--script=outside'):
            def mutate(d,g,b):d['target.json']['link']['commandFragments'][0]['fragment']=flag
            with self.subTest(flag=flag),self.assertRaisesRegex(ValueError,'flag'):self.closure(mutate=mutate)
        def target(d,g,b):d['runtime.json']['name']='third-party-generator'
        def custom(d,g,b):g['build.ninja']+='build generated.hpp: CUSTOM_COMMAND\n  COMMAND = external.exe\n'
        def imported(d,g,b):d['target.json']['link']['commandFragments'][-1]['fragment']=str(b/'copied-external.a')
        for mutate in (target,custom,imported):
            with self.subTest(mutate=mutate.__name__),self.assertRaises(ValueError):self.closure(mutate=mutate)

    def test_desktop_selected_runtime_dll_is_bound_and_external_selection_rejected(self):
        report=self.closure(desktop=True,configuration_only=True)
        self.assertEqual(report['sdl_runtime']['path'],str(self.bundle/'bin/SDL3.dll'))
        self.assertEqual(len(report['sdl_runtime']['sha256']),64)
        with self.assertRaisesRegex(ValueError,'outside hashed'):
            self.closure(desktop=True,sdl=self.base/'outside.dll',configuration_only=True)

    def test_only_actual_object_artifacts_can_be_generated_synthetic_sources(self):
        def actual(d,g,b):d['target.json']['sources'].append(dict(path=str(b/'CMakeFiles/module.obj'),isGenerated=True))
        self.closure(mutate=actual)
        def fake(d,g,b):d['target.json']['sources'].append(dict(path=str(b/'CMakeFiles/external.obj'),isGenerated=True))
        with self.assertRaisesRegex(ValueError,'Generated compile'):
            self.closure(mutate=fake)

    def test_desktop_gnu_standard_and_native_ninja_include_supported_but_launchers_refused(self):
        def supported(d,g,b):
            d['target.json']['compileGroups'][0]['compileCommandFragments'][0]['fragment']='-O3 -DNDEBUG -std=gnu++20'
            g['build.ninja']+='include CMakeFiles/rules.ninja\n'
        self.closure(mutate=supported)
        for line in ('  LAUNCHER = outside.exe','  CODE_CHECK = outside.exe',
                     'include external.ninja','subninja CMakeFiles/extra.ninja'):
            def mutate(d,g,b):g['build.ninja']+=line+'\n'
            with self.subTest(line=line),self.assertRaises(ValueError):self.closure(mutate=mutate)
