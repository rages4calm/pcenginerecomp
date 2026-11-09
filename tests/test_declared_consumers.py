"""Authored declarations through source-pinned consumer and managed interfaces."""
import copy
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import incremental as inc, prepare, project
from pcerecomp.declarations import FORMAT, load_compilation
from pcerecomp.emitter import emit_declarations, emit_history
from pcerecomp.history import compose_history, load_history
from tests import test_build_inputs, test_capture, test_incremental_native, test_project


def authored_image():
    image = bytearray([0xEA]*8192)
    image[256:260] = bytes([0xA2,7,0xE8,0xEA])
    image[8190:8192] = bytes([0,0xE1])
    return bytes(image)


def numeric_roots(image, addresses=(0xE100,0xE102,0xE103), **conversion):
    source = dict(sha256=project.sha256(image),profile='base',header='none',encoding='linear')
    source.update(conversion)
    return dict(format=FORMAT,schema=1,execution_evidence=False,kind='declared',
        image=source,
        roots=[dict(pc=pc,mpr=[0]*8,selector=0,
                    rom_offsets=list(range(pc&8191,(pc&8191)+(2 if pc==0xE100 else 1)))) for pc in addresses])


class DeclaredConsumerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_project.ConsumerProjectTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.image = self.root/'authored.pce'; self.image.write_bytes(authored_image())
        self.roots = self.root/'roots.json'; self.write_roots(self.roots,numeric_roots(self.image))
        self.descriptor = self.descriptor_for(self.roots,'declared')
        self.workspace = self.root/'managed'

    def write_roots(self,path,value):
        path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')

    def descriptor_for(self,roots,name,*,history=None,image=None,boot=None,exclude_ranges=()):
        image = image or self.image; module = self.root/name
        emit_declarations(roots,image,module,observation_history=history,partition_layout='stable',exclude_ranges=exclude_ranges)
        config = tomllib.loads(self.fixture.text); del config['payload']
        config['boot'] = boot or dict(mode='hucard-reset',profile='base',header='none',encoding='linear')
        config['cartridge'] = dict(path=str(image),sha256=project.sha256(image))
        config['module'] = dict(source=dict(path=str(module/'module.cpp'),sha256=project.sha256(module/'module.cpp')),
            manifest=dict(path=str(module/'module.json'),sha256=project.sha256(module/'module.json')),
            declared_roots=dict(path=str(roots),sha256=project.sha256(roots)))
        if history is not None:
            config['module']['observation_history'] = dict(path=str(history),sha256=project.sha256(history))
        path = self.root/(name+'.toml'); path.write_text(inc._toml(config),encoding='utf-8',newline='\n')
        return path

    def checked(self,path=None):
        return project.verify(path or self.descriptor,allow_revision_override=True)

    def history(self):
        capture = test_capture.capture([test_capture.observation(0xE100,(0xA2,7),mpr=[0]*8,interpreted=5)])
        capture['runtime_abi'] = 18
        path = self.root/'observed.json'; path.write_text(json.dumps(capture),encoding='utf-8')
        return compose_history([path],self.root/'observed-history')

    def test_pure_declared_binding_has_no_fabricated_history_or_mutable_image_input(self):
        checked = self.checked()
        self.assertEqual(checked['identities']['module_declared_roots'],project.sha256(self.roots))
        self.assertEqual(checked['files']['cartridge'],self.image)
        self.assertNotIn('module_observation_history',checked['files'])
        self.assertFalse(any(key.startswith('module_') and value==self.image for key,value in checked['files'].items()))
        manifest = json.loads(checked['files']['module_manifest'].read_text(encoding='utf-8'))
        self.assertEqual((manifest['observed_instructions'],manifest['declared_instructions'],
                          manifest['declared_only'],manifest['emitted_instructions']),(0,3,3,3))
        self.assertNotIn('historical_totals',manifest)
        self.assertNotIn('observation_inputs',manifest)

    def test_mixed_binding_retains_original_history_and_separate_membership_counts(self):
        history = self.history(); descriptor = self.descriptor_for(self.roots,'mixed',history=history.index_path)
        checked = self.checked(descriptor)
        manifest = json.loads(checked['files']['module_manifest'].read_text(encoding='utf-8'))
        self.assertEqual((manifest['observed_instructions'],manifest['declared_instructions'],
                          manifest['declared_observed_overlap'],manifest['declared_only']),(1,3,1,2))
        self.assertEqual(manifest['historical_totals'],dict(native_hits=0,interpreted_hits=5,retired_instructions=5))
        self.assertEqual(manifest['observation_inputs'][0]['runtime_abi'],18)
        self.assertEqual(checked['identities']['module_observation_history'],history.index_sha256)
        self.assertEqual(len([key for key in checked['files'] if key.startswith('module_history:')]),2)
        source = next(item['path'] for relative,item in history.artifact_bindings.items() if relative.startswith('captures/'))
        source.write_bytes(source.read_bytes()+b' ')
        with self.assertRaises(ValueError): self.checked(descriptor)

    def test_excluded_operand_counts_only_authentic_observed_hits(self):
        for name,history,expected_observed,expected_hits in (
                ('excluded-pure',None,0,0),('excluded-mixed',self.history().index_path,1,5)):
            descriptor = self.descriptor_for(self.roots,name,history=history,exclude_ranges=((257,1),))
            checked = self.checked(descriptor)
            manifest = json.loads(checked['files']['module_manifest'].read_text(encoding='utf-8'))
            self.assertEqual((manifest['excluded_observations'],manifest['excluded_declarations'],
                              manifest['excluded_retired_hits'],manifest['native_instructions_emitted']),
                             (expected_observed,1,expected_hits,2))

    def test_declared_binding_and_exact_source_recipe_are_required(self):
        config = tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        variants = []
        absent = copy.deepcopy(config); del absent['module']['declared_roots']; variants.append(absent)
        wrong = copy.deepcopy(config); wrong['boot']['encoding'] = 'bit-reversed'; variants.append(wrong)
        wrong = copy.deepcopy(config); wrong['module']['declared_roots']['sha256'] = 'a'*64; variants.append(wrong)
        wrong = copy.deepcopy(config); wrong['module']['declared_roots']['native_hits'] = 1; variants.append(wrong)
        wrong = copy.deepcopy(config); wrong['module']['observation_profile'] = dict(path=str(self.roots),sha256=project.sha256(self.roots)); variants.append(wrong)
        wrong = copy.deepcopy(config); del wrong['boot']; wrong['payload'] = tomllib.loads(self.fixture.text)['payload']; variants.append(wrong)
        for index,value in enumerate(variants):
            path = self.root/f'invalid-{index}.toml'; path.write_text(inc._toml(value),encoding='utf-8')
            with self.subTest(index=index),self.assertRaises(ValueError):self.checked(path)
        self.image.write_bytes(self.image.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.checked()

    def test_explicit_header_and_encoding_use_raw_image_binding_and_decoded_offsets(self):
        reverse = bytes(int(f'{value:08b}'[::-1],2) for value in range(256))
        for name,data,header,encoding in (
                ('copier',bytes(512)+authored_image(),'copier512','linear'),
                ('reversed',authored_image().translate(reverse),'none','bit-reversed')):
            image = self.root/(name+'.pce'); image.write_bytes(data)
            roots = self.root/(name+'-roots.json')
            self.write_roots(roots,numeric_roots(image,header=header,encoding=encoding))
            boot = dict(mode='hucard-reset',profile='base',header=header,encoding=encoding)
            descriptor = self.descriptor_for(roots,name,image=image,boot=boot)
            checked = self.checked(descriptor)
            manifest = json.loads(checked['files']['module_manifest'].read_text(encoding='utf-8'))
            source = manifest['declared_roots_source']
            self.assertEqual(source['image_sha256'],project.sha256(image))
            self.assertNotEqual(source['image_sha256'],source['decoded_rom_sha256'])
            self.assertEqual(source['rom_bytes'],8192)

    def test_forged_counts_source_and_capture_evidence_are_rejected(self):
        config = tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        manifest = self.root/'declared/module.json'; original = json.loads(manifest.read_text(encoding='utf-8'))
        variants = [dict(observed_instructions=3),dict(declared_only=0),dict(native_instructions_emitted=99),
                    dict(historical_totals=dict(native_hits=0,interpreted_hits=0,retired_instructions=0)),
                    dict(captured_native_hits=3),dict(execution_evidence=True),
                    dict(declared_roots_source=original['declared_roots_source'] | dict(image_sha256='a'*64))]
        for index,changed in enumerate(variants):
            manifest.write_text(json.dumps(original | changed),encoding='utf-8')
            config['module']['manifest']['sha256'] = project.sha256(manifest)
            descriptor = self.root/f'forged-{index}.toml'; descriptor.write_text(inc._toml(config),encoding='utf-8')
            with self.subTest(index=index),self.assertRaises(ValueError):self.checked(descriptor)

    def test_preparation_copies_numeric_roots_but_does_not_invent_an_observation(self):
        config = tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        spec = dict(schema=1,format=prepare.FORMAT,name='authored-declared-preparation',
            sdk=dict(revision='0'*40,allow_revision_override=True),
            module=dict(kind='declared',path=self.roots.name),
            boot=config['boot'],cartridge=config['cartridge'],runtime=config['runtime'],limits=config['limits'])
        recipe = self.root/'recipe.toml'; recipe.write_text(prepare._toml(spec),encoding='utf-8')
        output = self.root/'prepared'
        originals = {path:path.read_bytes() for path in (self.roots,self.image)}
        with patch.object(prepare,'TOOL_ROOT',self.fixture.tool):
            receipt = prepare.prepare_project(recipe,output)
        self.assertFalse(receipt['compiled']); self.assertFalse(receipt['executed'])
        self.assertNotIn('history_sha256',receipt); self.assertNotIn('original_observations',receipt)
        self.assertFalse((output/'observation-history').exists())
        self.assertEqual((output/'declarations/roots.json').read_bytes(),originals[self.roots])
        self.assertEqual({path:path.read_bytes() for path in originals},originals)
        self.checked(output/'project.toml')
        history = self.history(); spec['module'].update(history_path=str(history.index_path),history_version=2,capacity=131072)
        recipe.write_text(prepare._toml(spec),encoding='utf-8')
        with patch.object(prepare,'TOOL_ROOT',self.fixture.tool):
            mixed = prepare.prepare_project(recipe,self.root/'prepared-mixed')
        self.assertIn('original_observations',mixed)
        copied = load_history(self.root/'prepared-mixed/observation-history')
        self.assertEqual(copied.index['schema'],2)
        self.assertEqual(copied.index['selection_stages'],history.index['selection_stages'])
        self.assertEqual(copied.accounting,history.accounting)

    def test_preparation_refuses_wrong_kind_image_or_meaningless_history_options(self):
        config = tomllib.loads(self.descriptor.read_text(encoding='utf-8'))
        base = dict(schema=1,format=prepare.FORMAT,name='invalid-declared',module=dict(kind='declared',path=str(self.roots)),
                    boot=config['boot'],cartridge=config['cartridge'],runtime=config['runtime'],limits=config['limits'])
        variants = []
        for key,value in (('history_version',2),('capacity',16)):
            spec = copy.deepcopy(base); spec['module'][key] = value; variants.append(spec)
        wrong = copy.deepcopy(base); wrong['boot']['mode'] = 'system-card-reset'; variants.append(wrong)
        wrong = copy.deepcopy(base); wrong['boot']['encoding'] = 'bit-reversed'; variants.append(wrong)
        wrong = copy.deepcopy(base); del wrong['cartridge']; variants.append(wrong)
        for index,value in enumerate(variants):
            recipe = self.root/f'invalid-recipe-{index}.toml'; recipe.write_text(prepare._toml(value),encoding='utf-8')
            output = self.root/f'invalid-prepared-{index}'
            with self.subTest(index=index),self.assertRaises(ValueError):prepare.prepare_project(recipe,output)
            self.assertFalse(output.exists())

    def retained(self):
        checked = self.checked(); owned = self.workspace/'module'; owned.mkdir(parents=True)
        inc._sync(inc._module(checked),owned)
        output = self.workspace/'output'; output.mkdir(); (output/'authored.obj').write_bytes(b'Authored state sentinel, not compiled.')
        descriptor = self.workspace/'project.toml'; descriptor.write_text('schema=1\n',encoding='utf-8')
        archive = self.workspace/'history/000000'; archive.mkdir(parents=True)
        (archive/'declared-roots.json').write_bytes(self.roots.read_bytes())
        state = dict(schema=1,generation=0,build_tree=inc._snapshot(output),module_tree=inc._snapshot(owned),
                     descriptor_sha256=project.sha256(descriptor),
                     declared_roots=dict(file='declared-roots.json',sha256=project.sha256(self.roots)))
        project._write_new(archive/'state.json',state)
        project._write_new(self.workspace/'current.json',dict(generation=0,sha256=project.sha256(archive/'state.json')))
        return owned,archive

    def test_managed_numeric_copy_archive_tamper_and_binding_removal(self):
        checked = self.checked(); files = inc._module(checked)
        self.assertEqual(files['declared-roots.json'],self.roots)
        self.assertNotIn(self.image,files.values())
        config = inc._config(checked,self.workspace,files)
        self.assertEqual(config['module']['declared_roots']['path'],str(self.workspace/'module/declared-roots.json'))
        owned,archive = self.retained(); inc._state(self.workspace)
        for path in (owned/'declared-roots.json',archive/'declared-roots.json'):
            raw = path.read_bytes(); stamp = path.stat().st_mtime_ns
            path.write_bytes(raw+b' ')
            with self.assertRaises(ValueError):inc._state(self.workspace)
            path.write_bytes(raw); os.utime(path,ns=(stamp,stamp))
        history = self.history(); module = self.root/'observed-only'
        emit_history(history.index_path,module,partition_layout='stable')
        config = tomllib.loads(self.descriptor.read_text(encoding='utf-8')); del config['module']['declared_roots']
        for role,name in (('source','module.cpp'),('manifest','module.json')):
            config['module'][role] = dict(path=str(module/name),sha256=project.sha256(module/name))
        config['module']['observation_history'] = dict(path=str(history.index_path),sha256=history.index_sha256)
        candidate = self.root/'remove-declarations.toml'; candidate.write_text(inc._toml(config),encoding='utf-8')
        before = inc._snapshot(self.workspace)
        with patch.object(inc,'prepare') as compiler,self.assertRaisesRegex(ValueError,'binding cannot be removed'):
            inc.rebuild(candidate,self.workspace,allow_revision_override=True)
        compiler.assert_not_called(); self.assertEqual(before,inc._snapshot(self.workspace))

    @unittest.skipUnless(os.name=='nt','Audited compiler input contract targets Windows LLVM-MinGW')
    def test_only_annotations_are_mutable_module_cache_inputs_and_image_stays_fixed_asset(self):
        fixture = test_build_inputs.ProducerInputTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        checked = self.checked(); fixture.project['files'].update(checked['files'])
        # Keep the authored fake compiler's own source root; this is admission,
        # not a claim that the fake toolchain executed a compiler.
        fixture.project['files']['module_source'] = fixture.module/'module.cpp'
        fixture.project['identities'].update(checked['identities'])
        context = fixture.context(); inputs = context['contract']['module_inputs']
        self.assertEqual(inputs['module_declared_roots'],project.sha256(self.roots))
        self.assertNotIn('cartridge',inputs)
        self.assertNotIn(self.image.parent,context['roots'])
        before = copy.deepcopy(context['contract'])
        fixture.project['identities']['module_declared_roots'] = 'a'*64
        after = fixture.context()['contract']
        self.assertNotEqual(before,after)
        self.assertEqual(inc._fixed_contract(dict(contract=before)),inc._fixed_contract(dict(contract=after)))
        config = inc._config(checked,self.workspace,inc._module(checked)); changed = copy.deepcopy(config)
        changed['cartridge']['sha256'] = 'b'*64
        self.assertNotEqual(inc._fixed_config(config),inc._fixed_config(changed))


class NativeDeclaredManagedTests(unittest.TestCase):
    def test_actual_declared_promotion_keeps_history_objects_and_immutable_cartridge(self):
        compiler,bundle = test_incremental_native.NativeManagedRebuildTests.compiler_bundle(self)
        sdk = Path(__file__).resolve().parent.parent; identity = project.source_identity(sdk)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); image = root/'authored.pce'; image.write_bytes(authored_image())
            image_sha = project.sha256(image)
            original = root/'original-roots.json'; original.write_text(json.dumps(numeric_roots(image)),encoding='utf-8')
            common = dict(schema=1,name='authored-declared-native',
                tool=dict(path=str(sdk),revision=identity['revision'],source_sha256=identity['source_sha256'],runtime_abi=project.ABI),
                boot=dict(mode='hucard-reset',profile='base',header='none',encoding='linear'),
                cartridge=dict(path=str(image),sha256=image_sha),
                runtime=dict(tier='hybrid',video='snapshot',audio='off',cd_unknown_status='fault',
                             joypad=2,region='usa',multitap='off'),limits=dict(steps=4,ticks=10000,wall_seconds=5))
            def descriptor(roots,name,history=None,source_image=image):
                module = root/(name+'-module')
                manifest = emit_declarations(roots,source_image,module,observation_history=history,partition_layout='stable')
                config = copy.deepcopy(common); config['cartridge'] = dict(path=str(source_image),sha256=project.sha256(source_image))
                config['module'] = dict(source=dict(path=str(module/'module.cpp'),sha256=project.sha256(module/'module.cpp')),
                    manifest=dict(path=str(module/'module.json'),sha256=project.sha256(module/'module.json')),
                    declared_roots=dict(path=str(roots),sha256=project.sha256(roots)))
                if history is not None:
                    config['module']['observation_history'] = dict(path=str(history),sha256=project.sha256(history))
                target = root/(name+'.toml'); target.write_text(inc._toml(config),encoding='utf-8',newline='\n')
                return target,manifest
            initial,manifest = descriptor(original,'initial')
            self.assertEqual(manifest['observed_instructions'],0)
            self.assertNotIn('historical_totals',manifest)
            workspace = root/'managed'
            args = ('-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(bundle/'bin/ninja.exe'))
            inc.rebuild(initial,workspace,create=True,toolchain_root=bundle,cmake_args=args)
            def execute(name):
                capture = root/(name+'-capture.json')
                result = project.run(workspace/'project.toml',workspace/'output',root/(name+'-receipt.json'),
                                     code_capture=capture,capture_limit=16)
                self.assertTrue(result['qualified'],result)
                self.assertEqual({key:result['result'][key] for key in ('pc','x','a','y','p','cycles','ticks')},
                                 dict(pc=0xE105,x=8,a=0,y=0,p=4,cycles=8,ticks=96))
                return result,capture
            before,observed = execute('before')
            self.assertEqual((before['work']['native'],before['work']['interpreted']),(3,1))
            previous_objects = test_incremental_native.retained_files(workspace/'output',{'.obj','.o'})
            history = compose_history([observed],root/'actual-history')
            added = root/'added-roots.json'
            added.write_text(json.dumps(numeric_roots(image,(0xE100,0xE102,0xE103,0xE104,0xE120))),encoding='utf-8')
            promoted,manifest = descriptor(added,'promoted',history.index_path)
            self.assertEqual((manifest['observed_instructions'],manifest['declared_instructions'],
                              manifest['declared_only'],manifest['declared_observed_overlap']),(4,5,1,4))
            self.assertEqual(manifest['historical_totals'],dict(native_hits=3,interpreted_hits=1,retired_instructions=4))
            updated = inc.rebuild(promoted,workspace)
            self.assertEqual(updated['incremental']['generation'],1)
            self.assertEqual(len(updated['incremental']['object_timestamps']['rebuilt']),1)
            after_objects = test_incremental_native.retained_files(workspace/'output',{'.obj','.o'})
            self.assertEqual(len([name for name in previous_objects if previous_objects[name]!=after_objects[name]]),1)
            after,new_capture = execute('after')
            self.assertEqual((after['work']['native'],after['work']['interpreted']),(4,0))
            self.assertEqual(after['result']['guard_misses'],0)
            extended = compose_history([new_capture],root/'extended-actual-history',baseline_history=history.index_path)
            self.assertEqual(extended.index['catalogue_sha256'],history.index['catalogue_sha256'])
            changed = root/'same-roots-new-bytes.json'; changed.write_bytes(added.read_bytes()+b'\n')
            selected,_ = descriptor(changed,'same-operations',extended.index_path)
            noop = inc.rebuild(selected,workspace)
            self.assertEqual(noop['incremental']['generation'],2)
            self.assertEqual(noop['incremental']['object_timestamps']['rebuilt'],[])
            self.assertEqual(test_incremental_native.retained_files(workspace/'output',{'.obj','.o'}),after_objects)
            for generation,source in ((0,original),(1,added),(2,changed)):
                self.assertEqual((workspace/'history'/f'{generation:06d}'/'declared-roots.json').read_bytes(),source.read_bytes())
            self.assertEqual(project.sha256(image),image_sha)
            original_state = inc._snapshot(workspace)
            no_history,_ = descriptor(changed,'drop-history')
            with patch.object(inc,'prepare') as producer,self.assertRaisesRegex(ValueError,'history binding cannot be removed'):
                inc.rebuild(no_history,workspace)
            producer.assert_not_called(); self.assertEqual(original_state,inc._snapshot(workspace))
            different_image = root/'other-image.pce'; raw = bytearray(image.read_bytes()); raw[500] ^= 1
            different_image.write_bytes(raw)
            wrong_roots = root/'other-image-roots.json'
            wrong_roots.write_text(json.dumps(numeric_roots(different_image,(0xE100,0xE102,0xE103,0xE104,0xE120))),encoding='utf-8')
            wrong,_ = descriptor(wrong_roots,'replace-image',extended.index_path,source_image=different_image)
            with patch.object(inc,'prepare') as producer,self.assertRaisesRegex(ValueError,'Only module may change'):
                inc.rebuild(wrong,workspace)
            producer.assert_not_called(); self.assertEqual(original_state,inc._snapshot(workspace))
            inc._state(workspace)


if __name__=='__main__':unittest.main()
