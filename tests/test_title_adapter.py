"""Authored manifest/settings/source-closure tests; metadata mocks never execute."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import project, prepare, title_adapter as adapter, build_inputs, build_cache


def manifest():
    return dict(format=adapter.FORMAT,schema=1,id='authored-qol',state_bytes=32,
        settings=[dict(name='protection',min=0,max=1,default=0),
                  dict(name='exp',min=1,max=8,default=1),dict(name='gold',min=1,max=8,default=1)],
        events=[dict(name='earned-exp',pc=0x4000,mpr=[255,248,128,129,130,131,132,0],selector=0,data='ea')])


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'manifest.json'
        self.write(manifest())

    def write(self,value):
        self.path.write_text(json.dumps(value),encoding='utf-8',newline='\n')

    def test_literal_settings_defaults_and_independent_multipliers(self):
        value=manifest()
        self.assertEqual(adapter.settings(value),({'exp':1,'gold':1,'protection':0},'exp=1,gold=1,protection=0'))
        self.assertEqual(adapter.settings(value,{'gold':8,'exp':2,'protection':1},mode='enhanced'),
                         ({'exp':2,'gold':8,'protection':1},'exp=2,gold=8,protection=1'))
        self.assertEqual(adapter.settings(value,{'gold':1},mode='pristine')[1],'exp=1,gold=1,protection=0')

    def test_unknown_types_ranges_and_nondefault_pristine_refuse(self):
        for values in ({'unknown':1},{'exp':0},{'gold':9},{'exp':True},{'exp':1.0},{'protection':2},[],{'exp':'2'}):
            with self.subTest(values=values),self.assertRaises(ValueError):adapter.settings(manifest(),values,mode='enhanced')
        with self.assertRaisesRegex(ValueError,'Pristine'):adapter.settings(manifest(),{'exp':2})
        for mode in (None,True,1,'unknown'):
            with self.subTest(mode=mode),self.assertRaises(ValueError):adapter.settings(manifest(),mode=mode)

    def test_strict_initial_argv_rejects_duplicate_and_noncanonical_values(self):
        self.assertEqual(adapter.parse_settings(['gold=8','exp=2']),{'gold':8,'exp':2})
        for items in (['exp=2','exp=3'],['exp=+2'],['exp=02'],['exp=-0'],['exp= 2'],['Exp=2'],['exp=true'],['exp=9223372036854775808']):
            with self.subTest(items=items),self.assertRaises(ValueError):adapter.parse_settings(items)

    def test_manifest_closed_schema_legal_instruction_and_complete_mapping(self):
        changes=[('schema',True),('schema',1.0),('format','unknown'),('state_bytes',4097),('id','escape"'),('settings',[dict(name='x',min=2,max=1,default=1)])]
        for key,value in changes:
            item=manifest();item[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):adapter.validate(item)
        bad_events=[dict(pc=True),dict(mpr=[248]*7),dict(selector=16),dict(data='a90500'),dict(data='a9'),dict(data='EA'),dict(data='0b')]
        for changed in bad_events:
            value=manifest();value['events'][0].update(changed)
            with self.subTest(changed=changed),self.assertRaises(ValueError):adapter.validate(value)
        for data in ('a905','73002000400100','00ff'):
            value=manifest();value['events'][0]['data']=data
            self.assertEqual(adapter.validate(value),value)

    def test_duplicate_keys_events_and_settings_refuse(self):
        self.path.write_bytes(b'{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError,'Duplicate'):adapter.load(self.path)
        for key in ('settings','events'):
            value=manifest();value[key].append(copy.deepcopy(value[key][0]))
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Duplicate'):adapter.validate(value)
        value=manifest();value['events'].append({**value['events'][0],'name':'other'})
        with self.assertRaisesRegex(ValueError,'Duplicate'):adapter.validate(value)

    def test_empty_settings_and_signed_limits_generate_without_cpp_overflow(self):
        value=manifest();value['settings']=[]
        self.assertEqual(adapter.settings(value),({},''))
        value['settings']=[dict(name='signed',min=adapter.MIN_INT,max=adapter.MAX_INT,default=adapter.MIN_INT)]
        data=adapter.binding_bytes(value,'a'*64)
        self.assertIn(b'(-INT64_C(9223372036854775807)-1)',data)
        self.assertIn(b'&consumer::title_adapter_after',data)

    def test_generation_pins_original_bytes_and_refuses_unowned_output(self):
        snapshot,store=adapter.load(self.path)
        out=self.root/'binding.cpp';adapter.generate(self.path,out)
        self.assertEqual(out.read_bytes(),adapter.binding_bytes(snapshot.value,snapshot.sha256))
        adapter.generate(self.path,out)
        out.write_bytes(b'owner source')
        with self.assertRaisesRegex(ValueError,'non-generated'):adapter.generate(self.path,out)
        self.assertEqual(out.read_bytes(),b'owner source')
        self.write({**manifest(),'state_bytes':64})
        with self.assertRaises(ValueError):store.revalidate()

    def test_invalid_manifest_does_not_allocate_generated_output(self):
        value=manifest();value['unexpected']=True;self.write(value)
        out=self.root/'uncreated.cpp'
        with self.assertRaises(ValueError):adapter.generate(self.path,out)
        self.assertFalse(out.exists())

    def test_source_growth_is_bounded_even_after_stat_admission(self):
        path=self.root/'source.cpp';path.write_bytes(b'tiny')
        original=os.fstat;calls=0
        def grow(descriptor):
            nonlocal calls
            info=original(descriptor);calls+=1
            if calls==1:path.write_bytes(b'x'*10000)
            return info
        with patch.object(adapter,'MAX_BYTES',32),patch.object(adapter.os,'fstat',side_effect=grow):
            with self.assertRaisesRegex(ValueError,'changed'):adapter._read(path)


class SourceGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        (self.source/'logic.cpp').write_bytes(b'#include "detail.hpp"\n// authored callback\n')
        (self.source/'detail.hpp').write_bytes(b'// authored header\n')
        (self.root/'contract.json').write_text(json.dumps(manifest()),encoding='utf-8')
        self.recipe=dict(source='source/logic.cpp',manifest='contract.json',headers=['source/detail.hpp'])

    def test_copy_closes_only_explicit_headers_and_revalidates_content(self):
        (self.source/'unrelated-owner.bin').write_bytes(b'do not copy or infer')
        graph=adapter.recipe_graph(self.root,self.recipe)
        output=self.root/'owned';copied=adapter.copy_graph(graph,output)
        self.assertEqual(set(path.name for path in output.iterdir()),{'logic.cpp','detail.hpp','manifest.json'})
        self.assertNotIn('unrelated-owner.bin',str(copied))
        before=(self.source/'detail.hpp').stat();(self.source/'detail.hpp').write_bytes(b'// altered header!\n')
        os.utime(self.source/'detail.hpp',ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'changed'):graph.revalidate()

    def test_header_duplicates_case_collisions_escape_and_wrong_types_refuse(self):
        (self.root/'outside.hpp').write_bytes(b'outside')
        for headers in (['source/detail.hpp','source/detail.hpp'],['source/detail.hpp','source/DETAIL.hpp'],['outside.hpp'],['source/../source/detail.hpp'],['source/logic.cpp'],[1]):
            with self.subTest(headers=headers),self.assertRaises(ValueError):adapter.recipe_graph(self.root,{**self.recipe,'headers':headers})

    def test_copied_descriptor_rejects_extra_namespace_and_changed_header(self):
        copied=adapter.copy_graph(adapter.recipe_graph(self.root,self.recipe),self.root/'owned')
        entry={name:{key:dict(path=str(item['path']),sha256=item['sha256']) for key,item in value.items()}
               if name=='headers' else dict(path=str(value['path']),sha256=value['sha256']) for name,value in copied.items()}
        files={};adapter.verify_descriptor(self.root,entry,files)
        self.assertIn('title_adapter_header:h000',files)
        extra=self.root/'owned/unbound.hpp';extra.write_bytes(b'unbound include')
        with self.assertRaisesRegex(ValueError,'exactly'):adapter.verify_descriptor(self.root,entry,{})
        extra.unlink();(self.root/'owned/detail.hpp').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SHA256'):adapter.verify_descriptor(self.root,entry,{})


class ConsumerTitleContractTests(unittest.TestCase):
    def setUp(self):
        from tests.test_project import ConsumerProjectTests
        self.fixture=ConsumerProjectTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        folder=self.root/'adapter';folder.mkdir()
        (folder/'logic.cpp').write_bytes(b'// authored source; metadata fixture only\n')
        (folder/'detail.hpp').write_bytes(b'// explicit header\n')
        (folder/'manifest.json').write_text(json.dumps(manifest()),encoding='utf-8')
        config=tomllib.loads(self.fixture.text)
        def bound(path):return dict(path=str(path.relative_to(self.root)),sha256=project.sha256(path))
        config['title_adapter']=dict(source=bound(folder/'logic.cpp'),manifest=bound(folder/'manifest.json'),
                                    headers={'h000':bound(folder/'detail.hpp')})
        self.fixture.descriptor.write_text(prepare._toml(config),encoding='utf-8',newline='\n')
        self.checked=self.fixture.verify()

    def cache_origin(self,*,hit=False,generated_override=None):
        """A metadata-only fixture; its placeholder binary is never launched."""
        directory,binary=self.fixture.build_fixture()
        receipt_path=directory/'build-receipt.json';built=json.loads(receipt_path.read_text(encoding='utf-8'))
        snapshot,_=adapter.load(self.checked['files']['title_adapter_manifest'])
        contract=dict(schema=1,producer='windows-x64-llvm-mingw-ninja-v1',
            tool=dict(source_sha256=self.checked['tool_identity']['source_sha256']),
            title_adapter=dict(inputs={key:value for key,value in self.checked['identities'].items() if key.startswith('title_adapter_')},
                binding_sha256=generated_override or hashlib.sha256(adapter.binding_bytes(snapshot.value,snapshot.sha256)).hexdigest(),
                generator='pce-title-adapter-binding-1'))
        identity=build_cache.contract_identity(contract)
        key=hashlib.sha256(build_cache._canonical(identity)).hexdigest()
        origin=self.root/'origin.json';origin.write_text(json.dumps(dict(schema=1,kind='pce-build-package',key=key,contract=identity,
            files=[dict(name=binary.name,bytes=binary.stat().st_size,sha256=project.sha256(binary),executable=True)])),encoding='utf-8')
        built['cache']=dict(schema=1,hit=hit,key=key,producer=contract['producer'],input_contract=contract,key_contract=identity,
            manifest=dict(path=str(origin),sha256=project.sha256(origin),bytes=origin.stat().st_size),manifest_sha256=project.sha256(origin),
            input_audit=None if hit else dict(cmake_file_api=True,ninja_dependencies=True,header_count=1))
        receipt_path.write_text(json.dumps(built),encoding='utf-8')
        return directory,binary,built

    def test_manifest_headers_and_source_are_explicit_descriptor_bindings(self):
        self.assertEqual({key for key in self.checked['files'] if key.startswith('title_adapter_')},
                         {'title_adapter_source','title_adapter_manifest','title_adapter_header:h000'})
        (self.root/'adapter/detail.hpp').write_bytes(b'changed header')
        with self.assertRaisesRegex(ValueError,'SHA256'):self.fixture.verify()

    def test_settings_are_initial_structured_argv_and_checkpoint_context(self):
        base=project.command_for(self.checked,Path('runner'))
        self.assertEqual(base[base.index('--title-settings')+1],'exp=1,gold=1,protection=0')
        changed=project.command_for(self.checked,Path('runner'),title_mode='enhanced',title_settings={'exp':2,'gold':8})
        self.assertEqual(changed[changed.index('--title-mode')+1],'enhanced')
        self.assertEqual(changed[changed.index('--title-settings')+1],'exp=2,gold=8,protection=0')
        self.assertNotEqual(project.checkpoint_context(self.checked),project.checkpoint_context(self.checked,title_mode='enhanced',title_settings={'exp':2,'gold':8}))
        self.assertEqual(project.checkpoint_context(self.checked),project.checkpoint_context(self.checked,title_settings={'gold':1}))

    def test_enhanced_original_observation_paths_refuse_and_pristine_remains_usable(self):
        for changed in (dict(code_capture=self.root/'capture.json'),dict(bus_trace=self.root/'trace.jsonl'),dict(disc_origin=True)):
            with self.subTest(changed=changed),self.assertRaisesRegex(ValueError,'Enhanced'):
                project.command_for(self.checked,Path('runner'),title_mode='enhanced',**changed)
        self.assertIn('--code-capture',project.command_for(self.checked,Path('runner'),code_capture=self.root/'capture.json'))

    def test_unclosed_managed_build_and_legacy_run_enhancements_refuse(self):
        with self.assertRaisesRegex(ValueError,'audited'):
            project.build(self.fixture.descriptor,self.root/'uncreated',allow_revision_override=True)
        self.assertFalse((self.root/'uncreated').exists())
        with self.assertRaisesRegex(ValueError,'launch-plan'):
            project.run(self.fixture.descriptor,self.root/'unused',self.root/'uncreated.json',title_mode='enhanced')
        self.assertFalse((self.root/'uncreated.json').exists())

    def test_cli_preserves_distinct_settings_and_rejects_duplicates(self):
        args=['launch-plan',str(self.fixture.descriptor),'--build-dir',str(self.root/'build'),
              '--title-mode','enhanced','--title-setting','exp=2','--title-setting','gold=8']
        with patch.object(project,'prepare_launch',return_value={}) as invoked,patch('builtins.print'):
            self.assertEqual(project.main(args),0)
        self.assertEqual(invoked.call_args.kwargs['title_settings'],{'exp':2,'gold':8})
        with patch.object(project,'prepare_launch') as invoked,patch('builtins.print'):
            self.assertEqual(project.main(args+['--title-setting','exp=3']),2)
        invoked.assert_not_called()

    def test_only_exact_regenerated_binding_is_allowed_outside_hashed_inputs(self):
        build=self.root/'build';path,data=adapter.expected_binding(self.checked,build)
        path.parent.mkdir(parents=True);path.write_bytes(data)
        context=dict(roots=[self.checked['tool_root']],tool_root=self.checked['tool_root'],
                     title_binding=dict(path=str(path),sha256=hashlib.sha256(data).hexdigest()))
        allowed=build_inputs._audit_paths(context,build)
        self.assertEqual(allowed(path),path)
        other=path.with_name('other.cpp');other.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'outside'):allowed(other)
        path.write_bytes(data+b'// altered')
        with self.assertRaisesRegex(ValueError,'independently'):allowed(path)

    def test_adapters_cannot_be_smuggled_into_unrelated_continuation_recipe(self):
        with patch('pcerecomp.checkpoint_continuation.prepare_continuation_launch') as launch:
            with self.assertRaisesRegex(ValueError,'unsupported'):
                project.prepare_launch(self.fixture.descriptor,self.root/'unused',checkpoint_continuation=self.root/'none',title_mode='enhanced')
        launch.assert_not_called()

    def test_cache_origin_is_readmitted_and_launch_settings_are_separately_bound(self):
        directory,binary,built=self.cache_origin(hit=True)
        output=self.root/'audit.jsonl'
        plan=project.prepare_launch(self.fixture.descriptor,directory,allow_revision_override=True,
            title_mode='enhanced',title_settings={'exp':8,'protection':1},title_audit=output,
            dev_port=0,start_paused=True,checkpoint_dir=self.root)
        self.assertIs(plan['executed'],False)
        self.assertEqual(plan['title_adapter']['settings'],{'exp':8,'gold':1,'protection':1})
        self.assertIn('--title-audit',plan['command']);self.assertFalse(output.exists())
        actual=plan['command'][plan['command'].index('--checkpoint-context')+1]
        self.assertEqual(actual,project.checkpoint_context(self.checked,title_mode='enhanced',title_settings={'exp':8,'protection':1}))
        origin=Path(built['cache']['manifest']['path']);origin.write_bytes(origin.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'SHA256|digest'):
            project.prepare_launch(self.fixture.descriptor,directory,allow_revision_override=True)

    def test_metadata_marker_and_wrong_generated_contract_cannot_authorize_launch(self):
        directory,binary,built=self.cache_origin(generated_override='f'*64)
        with self.assertRaisesRegex(ValueError,'generated binding'):
            project.prepare_launch(self.fixture.descriptor,directory,allow_revision_override=True)
        built['cache']={};(directory/'build-receipt.json').write_text(json.dumps(built),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'producer receipt'):
            project.prepare_launch(self.fixture.descriptor,directory,allow_revision_override=True)

    def test_ordinary_receipt_cannot_bypass_required_adapter_producer(self):
        directory,_=self.fixture.build_fixture()
        with self.assertRaisesRegex(ValueError,'audited'):
            project.prepare_launch(self.fixture.descriptor,directory,allow_revision_override=True)


class PreparedAdapterTests(unittest.TestCase):
    def test_common_source_parent_layout_copies_closed_graph_and_preserves_inputs(self):
        from tests.test_prepare import ConsumerPreparationTests
        fixture=ConsumerPreparationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        source=fixture.root/'adapter.cpp';source.write_bytes(b'// authored single-file implementation\n')
        contract=fixture.root/'qol.json';contract.write_text(json.dumps(manifest()),encoding='utf-8')
        fixture.spec['title_adapter']=dict(source=source.name,manifest=contract.name)
        original={path:path.read_bytes() for path in (source,contract)}
        output=fixture.root/'prepared'
        result=prepare.prepare_project(fixture.recipe(),output)
        checked=project.verify(output/'project.toml')
        self.assertEqual(checked['files']['title_adapter_source'].read_bytes(),original[source])
        self.assertEqual(checked['files']['title_adapter_manifest'].read_bytes(),original[contract])
        self.assertEqual({path:path.read_bytes() for path in original},original)
        self.assertIs(result['title_adapter']['execution_evidence'],False)
        self.assertEqual(set((output/'title-adapter').iterdir()),{output/'title-adapter/adapter.cpp',output/'title-adapter/manifest.json'})


if __name__=='__main__':unittest.main()
