"""Discovery provenance through consumer boundaries; authored data, no game media."""
import copy
import json
import os
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import discovery, incremental as inc, prepare, project
from pcerecomp.history import load_history
from tests import test_build_inputs, test_declared_consumers


class DiscoveryConsumerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_declared_consumers.DeclaredConsumerTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root,self.image=self.fixture.root,self.fixture.image
        self.seeds=self.root/'seeds.json'
        self.fixture.write_roots(self.seeds,test_declared_consumers.numeric_roots(self.image,(0xE100,)))
        self.graph=self.derive('graph')
        self.descriptor=self.descriptor_for(self.graph,'consumer')
        self.workspace=self.root/'managed'

    def derive(self,name):
        return discovery.discover_roots(self.seeds,self.image,self.root/name,rom_ranges=[(0x100,4)])

    def descriptor_for(self,graph,name,*,history=None):
        descriptor=self.fixture.descriptor_for(graph.roots_path,name,history=history)
        config=tomllib.loads(descriptor.read_text(encoding='utf-8'))
        config['module']['discovery']=dict(path=str(graph.report_path),sha256=graph.sha256)
        descriptor.write_text(inc._toml(config),encoding='utf-8')
        return descriptor

    def checked(self,path=None):
        return project.verify(path or self.descriptor,allow_revision_override=True)

    def recipe(self,*,path=None,kind='discovery',history=None):
        config=tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        module=dict(kind=kind,path=str(path or self.graph.report_path))
        if history is not None:module.update(history_path=str(history.index_path),history_version=2,capacity=131072)
        spec=dict(schema=1,format=prepare.FORMAT,name='authored-discovery',
            sdk=dict(revision='0'*40,allow_revision_override=True),module=module,
            boot=config['boot'],cartridge=config['cartridge'],runtime=config['runtime'],limits=config['limits'])
        path=self.root/'prepare.toml';path.write_text(prepare._toml(spec),encoding='utf-8')
        return path

    def prepare(self,name='prepared',**options):
        recipe=self.recipe(**options)
        with patch.object(prepare,'TOOL_ROOT',self.fixture.fixture.tool):
            return prepare.prepare_project(recipe,self.root/name)

    def retained(self):
        checked=self.checked();files=inc._module(checked)
        owned=self.workspace/'module';owned.mkdir(parents=True);inc._sync(files,owned)
        config=inc._config(checked,self.workspace,files)
        descriptor=self.workspace/'project.toml';descriptor.write_text(inc._toml(config),encoding='utf-8')
        output=self.workspace/'output';output.mkdir();(output/'authored.obj').write_bytes(b'Authored state sentinel, NOT a compiled object.')
        archive=self.workspace/'history/000000';archive.mkdir(parents=True)
        for name,path in files.items():
            if name.startswith('discovery/'):
                target=archive/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(path.read_bytes())
        state=dict(schema=1,generation=0,build_tree=inc._snapshot(output),module_tree=inc._snapshot(owned),
            descriptor_sha256=project.sha256(descriptor),fixed_config=inc._fixed_config(config),
            declared_roots=dict(file='discovery/roots.json',sha256=self.graph.declarations.sha256),
            discovery=inc._discovery_state(checked))
        self.state(state)
        return owned,archive,state

    def state(self,state):
        file=self.workspace/'history/000000/state.json'
        file.write_text(json.dumps(state),encoding='utf-8')
        (self.workspace/'current.json').write_text(json.dumps(dict(generation=0,sha256=project.sha256(file))),encoding='utf-8')

    def test_copy_retains_exact_original_three_file_closure_and_no_media(self):
        original={p:p.read_bytes() for p in (self.seeds,self.image,*self.graph.report_path.parent.iterdir())}
        result=discovery.copy_discovery(self.graph.report_path,self.image,self.root/'copy')
        self.assertEqual(result.sha256,self.graph.sha256)
        self.assertEqual({p.name for p in result.report_path.parent.iterdir()},
                         {'seed-roots.json','roots.json','discovery.json'})
        for name in ('seed-roots.json','roots.json','discovery.json'):
            self.assertEqual((result.report_path.parent/name).read_bytes(),(self.graph.report_path.parent/name).read_bytes())
        self.assertEqual({p:p.read_bytes() for p in original},original)

    def test_copy_rejects_existing_or_nested_output_without_modifying_source(self):
        for output in (self.graph.report_path.parent,self.graph.report_path.parent/'nested',self.image):
            before={p.name:p.read_bytes() for p in self.graph.report_path.parent.iterdir()}
            with self.subTest(output=output.name),self.assertRaises(ValueError):
                discovery.copy_discovery(self.graph.report_path,self.image,output)
            self.assertEqual({p.name:p.read_bytes() for p in self.graph.report_path.parent.iterdir()},before)

    def test_interrupted_copy_does_not_publish_report_or_admit_partial_graph(self):
        output=self.root/'interrupted';original=discovery._write_new
        def fail(path,data):
            if path.name==discovery.REPORT_NAME:raise OSError('authored interruption')
            original(path,data)
        with patch.object(discovery,'_write_new',side_effect=fail),self.assertRaises(OSError):
            discovery.copy_discovery(self.graph.report_path,self.image,output)
        self.assertFalse((output/'discovery.json').exists())
        with self.assertRaises(ValueError):discovery.load_discovery(output,self.image)
        self.graph.revalidate()

    def test_copy_detects_original_change_during_copy(self):
        output=self.root/'changed';original=discovery._write_new
        def change(path,data):
            original(path,data)
            if path.name==discovery.SEEDS_NAME:
                self.graph.report_path.write_bytes(self.graph.report_path.read_bytes()+b' ')
        with patch.object(discovery,'_write_new',side_effect=change),self.assertRaises(ValueError):
            discovery.copy_discovery(self.graph.report_path,self.image,output)
        self.assertFalse((output/'discovery.json').exists())

    def test_verifier_binds_each_artifact_and_keeps_image_fixed(self):
        checked=self.checked()
        keys={'module_discovery','module_discovery:roots.json','module_discovery:seed-roots.json'}
        self.assertTrue(keys<=checked['files'].keys())
        self.assertEqual(checked['identities']['module_discovery'],self.graph.sha256)
        self.assertEqual(checked['files']['module_declared_roots'],checked['files']['module_discovery:roots.json'])
        self.assertFalse(any(k.startswith('module_') and p==self.image for k,p in checked['files'].items()))
        self.assertNotIn('module_observation_history',checked['files'])

    def test_preparation_owns_closed_graph_without_duplicate_roots_or_observed_hits(self):
        original={p:p.read_bytes() for p in (self.seeds,self.image,*self.graph.report_path.parent.iterdir())}
        receipt=self.prepare();output=self.root/'prepared';checked=self.checked(output/'project.toml')
        self.assertEqual(receipt['original_discovery']['sha256'],self.graph.sha256)
        self.assertEqual(receipt['original_discovery']['analysis_policy'],discovery.POLICY)
        self.assertFalse(receipt['execution_evidence']);self.assertFalse(receipt['compiled']);self.assertFalse(receipt['executed'])
        self.assertNotIn('original_observations',receipt)
        self.assertFalse((output/'declarations').exists());self.assertFalse((output/'observation-history').exists())
        self.assertEqual(checked['config']['module']['declared_roots']['path'],'discovery/roots.json')
        self.assertEqual(checked['files']['module_discovery'].parent,output/'discovery')
        manifest=json.loads(checked['files']['module_manifest'].read_bytes())
        self.assertEqual((manifest['observed_instructions'],manifest['declared_instructions']),(0,3))
        self.assertNotIn('historical_totals',manifest)
        self.assertEqual({p:p.read_bytes() for p in original},original)

    def test_report_or_directory_recipe_inputs_preserve_identical_graph_bytes(self):
        first=self.prepare('file-input')
        second=self.prepare('dir-input',path=self.graph.report_path.parent)
        self.assertEqual(first['original_discovery'],second['original_discovery'])
        for name in ('seed-roots.json','roots.json','discovery.json'):
            self.assertEqual((self.root/'file-input/discovery'/name).read_bytes(),
                             (self.root/'dir-input/discovery'/name).read_bytes())

    def test_prepared_consumer_does_not_depend_on_original_graph_location(self):
        self.prepare()
        self.graph.report_path.parent.rename(self.root/'retired-original-graph')
        checked=self.checked(self.root/'prepared/project.toml')
        self.assertEqual(checked['identities']['module_discovery'],self.graph.sha256)
        self.assertEqual(checked['files']['module_discovery'].parent,self.root/'prepared/discovery')

    def test_vector_policy_copy_and_preparation_retain_their_explicit_data_ranges(self):
        raw=bytearray(self.image.read_bytes())
        raw[0x100:0x105]=bytes.fromhex('A2 02 7C FE E1')
        raw[0x110]=0x60;raw[0x200:0x202]=bytes.fromhex('10 E1')
        self.image.write_bytes(raw)
        self.fixture.write_roots(self.seeds,test_declared_consumers.numeric_roots(self.image,(0xE100,)))
        self.graph=discovery.discover_roots(self.seeds,self.image,self.root/'vector-graph',
            rom_ranges=[(0x100,5),(0x110,1)],rom_vector_ranges=[(0x200,2)])
        self.descriptor=self.descriptor_for(self.graph,'vector-consumer')
        result=self.prepare()
        self.assertEqual(result['original_discovery']['analysis_policy'],discovery.VECTOR_POLICY)
        copied=discovery.load_discovery(self.root/'prepared/discovery',self.image)
        self.assertEqual(copied.report['options']['rom_vector_ranges'],[dict(start=0x200,length=2)])
        self.assertEqual(copied.report['summary']['resolved_vectors'],1)

    def test_mixed_preparation_keeps_observation_provenance_separate(self):
        history=self.fixture.history();original=history.index_path.read_bytes()
        receipt=self.prepare(history=history)
        copied=load_history(self.root/'prepared/observation-history')
        self.assertEqual(copied.accounting,history.accounting)
        self.assertEqual(copied.index['selection_stages'],history.index['selection_stages'])
        self.assertEqual(copied.index['schema'],2)
        self.assertEqual(receipt['original_observations']['sha256'],history.index_sha256)
        self.assertIn('original_discovery',receipt)
        self.assertEqual(history.index_path.read_bytes(),original)

    def test_declared_preparation_still_does_not_infer_discovery_provenance(self):
        receipt=self.prepare(kind='declared',path=self.graph.roots_path)
        checked=self.checked(self.root/'prepared/project.toml')
        self.assertNotIn('original_discovery',receipt)
        self.assertNotIn('discovery',checked['config']['module'])
        self.assertFalse((self.root/'prepared/discovery').exists())

    def test_preparation_refuses_invalid_graph_or_output_inside_original_before_allocation(self):
        recipe=self.recipe();nested=self.graph.report_path.parent/'prepared'
        with self.assertRaisesRegex(ValueError,'original discovery graph'):
            prepare.prepare_project(recipe,nested)
        self.assertFalse(nested.exists())
        self.graph.report_path.write_bytes(self.graph.report_path.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse((self.root/'prepared').exists())

    def test_discovery_binding_requires_declarations_exact_digest_and_shape(self):
        config=tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        variants=[]
        bad=copy.deepcopy(config);bad['module'].pop('declared_roots');variants.append(bad)
        bad=copy.deepcopy(config);bad['module']['discovery']['sha256']='a'*64;variants.append(bad)
        bad=copy.deepcopy(config);bad['module']['discovery']['execution_evidence']=True;variants.append(bad)
        bad=copy.deepcopy(config);bad['module']['discovery']['path']=False;variants.append(bad)
        for index,value in enumerate(variants):
            path=self.root/f'invalid-{index}.toml';path.write_text(inc._toml(value),encoding='utf-8')
            with self.subTest(index=index),self.assertRaises(ValueError):self.checked(path)

    def test_valid_but_different_discovery_roots_cannot_bind_compiled_declarations(self):
        self.fixture.write_roots(self.seeds,test_declared_consumers.numeric_roots(self.image,(0xE103,)))
        other=self.derive('different')
        config=tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        config['module']['discovery']=dict(path=str(other.report_path),sha256=other.sha256)
        self.descriptor.write_text(inc._toml(config),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'expanded roots differ'):self.checked()

    def test_rehashed_report_edits_cannot_replace_rederived_graph(self):
        report=self.graph.report;report['summary']['seed_roots']+=1
        self.graph.report_path.write_bytes(discovery._canonical(report,discovery.MAX_REPORT_BYTES))
        config=tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        config['module']['discovery']['sha256']=project.sha256(self.graph.report_path)
        self.descriptor.write_text(inc._toml(config),encoding='utf-8')
        with self.assertRaises(ValueError):self.checked()

    def test_module_copies_only_three_graph_files_and_reuses_the_single_roots_file(self):
        checked=self.checked();files=inc._module(checked)
        self.assertNotIn('declared-roots.json',files)
        self.assertEqual({n for n in files if n.startswith('discovery/')},
                         {'discovery/discovery.json','discovery/roots.json','discovery/seed-roots.json'})
        self.assertNotIn(self.image,files.values())
        config=inc._config(checked,self.workspace,files)
        self.assertEqual(config['module']['declared_roots']['path'],str(self.workspace/'module/discovery/roots.json'))
        self.assertEqual(config['module']['discovery']['path'],str(self.workspace/'module/discovery/discovery.json'))

    def test_owned_and_archived_graph_tampering_is_refused(self):
        owned,archive,_=self.retained();inc._state(self.workspace)
        for parent in (owned,archive):
            for name in ('seed-roots.json','roots.json','discovery.json'):
                path=parent/'discovery'/name;raw=path.read_bytes();stamp=path.stat().st_mtime_ns
                path.write_bytes(raw+b' ')
                with self.subTest(parent=parent.name,name=name),self.assertRaises(ValueError):inc._state(self.workspace)
                path.write_bytes(raw);os.utime(path,ns=(stamp,stamp))
        inc._state(self.workspace)

    def test_archive_rehash_or_missing_declared_binding_does_not_admit_false_provenance(self):
        _,_,state=self.retained()
        for value in (dict(state['discovery'],file='../discovery.json'),
                      dict(state['discovery'],artifacts=[])):
            changed=dict(state,discovery=value);self.state(changed)
            with self.assertRaises(ValueError):inc._state(self.workspace)
        changed=dict(state);changed.pop('declared_roots');self.state(changed)
        with self.assertRaises(ValueError):inc._state(self.workspace)

    def test_valid_alternate_archive_cannot_be_rebound_away_from_owned_descriptor(self):
        _,archive,state=self.retained()
        self.fixture.write_roots(self.seeds,test_declared_consumers.numeric_roots(self.image,(0xE100,0xE103)))
        other=self.derive('valid-alternate')
        checked=self.checked(self.descriptor_for(other,'valid-alternate-consumer'))
        self.assertEqual(other.declarations.sha256,state['declared_roots']['sha256'])
        self.assertNotEqual(other.sha256,state['discovery']['sha256'])
        for name,path in inc._discovery_files(checked).items():
            (archive/'discovery'/name).write_bytes(path.read_bytes())
        state['discovery']=inc._discovery_state(checked)
        self.state(state) # Even new self-consistent archive/state hashes must match the live descriptor.
        with self.assertRaisesRegex(ValueError,'archive disagrees with owned descriptor'):
            inc._state(self.workspace)

    def test_rehashed_owned_descriptor_cannot_move_discovery_outside_its_namespace(self):
        _,_,state=self.retained()
        descriptor=self.workspace/'project.toml'
        config=tomllib.loads(descriptor.read_text(encoding='utf-8'))
        config['module']['discovery']=dict(path=str(self.graph.report_path),sha256=self.graph.sha256)
        descriptor.write_text(inc._toml(config),encoding='utf-8')
        state['descriptor_sha256']=project.sha256(descriptor)
        self.state(state)
        with self.assertRaisesRegex(ValueError,'outside its owned module namespace'):
            inc._state(self.workspace)

    def test_owned_seed_change_refuses_even_with_rehashed_module_tree_and_state(self):
        owned,_,state=self.retained()
        seed=owned/'discovery/seed-roots.json'
        seed.write_bytes(seed.read_bytes()+b' ')
        state['module_tree']=inc._snapshot(owned)
        self.state(state)
        with self.assertRaisesRegex(ValueError,'input disagrees with archived binding'):
            inc._state(self.workspace)

    @unittest.skipUnless(os.name=='nt','Windows extended-path namespace')
    def test_copy_refuses_physical_parent_alias_before_modifying_original_graph(self):
        source=self.graph.report_path.parent
        output=Path('\\\\?\\'+str(source/'alias-copy'))
        self.assertTrue(output.parent.samefile(source))
        with self.assertRaisesRegex(ValueError,'original closed graph'):
            discovery.copy_discovery(self.graph.report_path,self.image,output)
        self.assertFalse(output.exists())
        self.graph.revalidate()

    @unittest.skipUnless(os.name=='nt','Windows extended-path namespace')
    def test_preparation_refuses_physical_parent_alias_before_allocation(self):
        recipe=self.recipe()
        output=Path('\\\\?\\'+str(self.graph.report_path.parent/'alias-consumer'))
        self.assertTrue(output.parent.samefile(self.graph.report_path.parent))
        with patch.object(prepare,'TOOL_ROOT',self.fixture.fixture.tool),self.assertRaisesRegex(ValueError,'original discovery graph'):
            prepare.prepare_project(recipe,output)
        self.assertFalse(output.exists())
        self.graph.revalidate()

    def test_managed_graph_binding_cannot_be_dropped_before_compile(self):
        self.retained()
        config=tomllib.loads(self.descriptor.read_text(encoding='utf-8'));config['module'].pop('discovery')
        candidate=self.root/'drop.toml';candidate.write_text(inc._toml(config),encoding='utf-8')
        self.checked(candidate) # A separately declared-only consumer is valid, but cannot downgrade this workspace.
        before=inc._snapshot(self.workspace)
        with patch.object(inc,'prepare') as compiler,self.assertRaisesRegex(ValueError,'discovery binding cannot be removed'):
            inc.rebuild(candidate,self.workspace,allow_revision_override=True)
        compiler.assert_not_called();self.assertEqual(before,inc._snapshot(self.workspace))

    def test_archive_rebinds_original_cartridge_as_fixed_source(self):
        self.retained();raw=self.image.read_bytes();data=bytearray(raw);data[0x100]^=1;self.image.write_bytes(data)
        with self.assertRaises(ValueError):inc._state(self.workspace)

    @unittest.skipUnless(os.name=='nt','Audited compiler contract targets Windows LLVM-MinGW')
    def test_graph_only_change_updates_cache_contract_without_new_compiler_roots(self):
        fixture=test_build_inputs.ProducerInputTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        checked=self.checked();fixture.project['files'].update(checked['files'])
        fixture.project['files']['module_source']=fixture.module/'module.cpp'
        fixture.project['identities'].update(checked['identities'])
        before=fixture.context();inputs=before['contract']['module_inputs']
        self.assertEqual(inputs['module_discovery'],self.graph.sha256)
        self.assertNotIn('cartridge',inputs)
        self.assertNotIn(self.graph.report_path.parent,before['roots'])
        self.fixture.write_roots(self.seeds,test_declared_consumers.numeric_roots(self.image,(0xE100,0xE103)))
        other=self.derive('second');self.assertEqual(other.declarations.sha256,self.graph.declarations.sha256)
        updated=self.checked(self.descriptor_for(other,'second-consumer'))
        fixture.project['files'].update(updated['files']);fixture.project['identities'].update(updated['identities'])
        fixture.project['files']['module_source']=fixture.module/'module.cpp'
        after=fixture.context()
        self.assertNotEqual(before['contract']['module_inputs'],after['contract']['module_inputs'])
        self.assertEqual(inc._fixed_contract(before),inc._fixed_contract(after))
