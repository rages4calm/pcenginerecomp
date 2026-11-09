"""Authored complete-history bindings through consumer and managed interfaces."""
import copy
import json
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pcerecomp import incremental as inc, native_catalog, native_gaps, project
from pcerecomp.history import compose_history, load_history
from pcerecomp.emitter import emit_history, emit_observation_profile
from pcerecomp.observations import (compose_additive_observation_profile,
    compose_observation_profile, serialize_observation_profile)
from tests import test_capture, test_project


class HistoryConsumerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_project.ConsumerProjectTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.original = self.capture('original', 18, [test_capture.observation(0x4000, (0xea,))])
        self.history = compose_history([self.original], self.root/'history')
        self.descriptor = self.descriptor_for(self.history.index_path, 'native')
        self.workspace = self.root/'managed'

    def capture(self, name, abi, observations):
        value = test_capture.capture(observations)
        value['runtime_abi'] = abi
        path = self.root/(name+'.json')
        path.write_text(json.dumps(value), encoding='utf-8', newline='\n')
        return path

    def descriptor_for(self, history, name):
        module = self.root/name
        emit_history(history, module, partition_layout='stable')
        config = __import__('tomllib').loads(self.fixture.text)
        config['module'] = dict(source=dict(path=f'{name}/module.cpp', sha256=project.sha256(module/'module.cpp')),
            manifest=dict(path=f'{name}/module.json', sha256=project.sha256(module/'module.json')),
            observation_history=dict(path=str(history), sha256=project.sha256(history)))
        path = self.root/(name+'.toml')
        path.write_text(inc._toml(config), encoding='utf-8', newline='\n')
        return path

    def checked(self, path=None):
        return project.verify(path or self.descriptor, allow_revision_override=True)

    def test_verification_binds_every_blob_and_source_identity(self):
        checked = self.checked()
        self.assertEqual(checked['files']['module_observation_history'], self.history.index_path)
        expected = {'module_history:'+relative: value['sha256']
                    for relative, value in self.history.artifact_bindings.items() if relative != 'history.json'}
        self.assertEqual({key:value for key,value in checked['identities'].items()
                          if key.startswith('module_history:')}, expected)
        self.assertEqual(checked['identities']['module_observation_history'], self.history.index_sha256)
        self.assertEqual(len(expected), 2)  # One exact original and one derived shard.
        for artifact in self.history.artifact_bindings.values():
            path = artifact['path']; raw = path.read_bytes()
            path.write_bytes(raw+b' ')
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                self.checked()
            path.write_bytes(raw)
        self.checked()

    def test_history_binding_is_required_and_cannot_be_replaced_by_profile(self):
        config = __import__('tomllib').loads(self.descriptor.read_text(encoding='utf-8'))
        del config['module']['observation_history']
        path = self.root/'unbound.toml'; path.write_text(inc._toml(config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'complete observation_history binding'):
            self.checked(path)
        config['module']['observation_history'] = dict(path=str(self.history.index_path), sha256=self.history.index_sha256)
        config['module']['observation_profile'] = dict(path=str(self.original), sha256=project.sha256(self.original))
        path.write_text(inc._toml(config), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'mutually exclusive'):
            self.checked(path)

    def test_managed_copy_uses_complete_reserved_graph_and_preserves_mtimes(self):
        checked = self.checked(); files = inc._module(checked)
        graph = {'observation-history/'+name for name in self.history.artifact_bindings}
        self.assertEqual({name for name in files if name.startswith('observation-history/')}, graph)
        owned = self.workspace/'module'; owned.mkdir(parents=True)
        changed = inc._sync(files, owned)
        self.assertTrue(graph <= set(changed['changed']))
        before = {name:(owned/name).stat().st_mtime_ns for name in graph}
        unchanged = inc._sync(files, owned, old={name:0 for name in files})
        self.assertTrue(graph <= set(unchanged['unchanged']))
        self.assertEqual(before, {name:(owned/name).stat().st_mtime_ns for name in graph})
        copied = load_history(owned/'observation-history/history.json')
        self.assertEqual(copied.index_sha256, self.history.index_sha256)
        config = inc._config(checked, self.workspace, files)
        self.assertEqual(config['module']['observation_history'],
            dict(path=str(owned/'observation-history/history.json'), sha256=self.history.index_sha256))
        for name in graph:
            self.assertEqual((owned/name).read_bytes(), files[name].read_bytes())

    def retained(self, descriptor=None):
        checked = self.checked(descriptor); owned = self.workspace/'module'; owned.mkdir(parents=True)
        inc._sync(inc._module(checked), owned)
        output = self.workspace/'output'; output.mkdir()
        (output/'authored.obj').write_bytes(b'Authored state fixture; not a compiled object')
        descriptor = self.workspace/'project.toml'; descriptor.write_text('schema=1\n')
        archive = self.workspace/'history/000000'; archive.mkdir(parents=True)
        binding = inc._history_state(checked)
        state = dict(schema=1, generation=0, build_tree=inc._snapshot(output),
            module_tree=inc._snapshot(owned), descriptor_sha256=project.sha256(descriptor))
        if binding is not None:
            state['observation_history'] = binding
            for artifact in binding['artifacts']:
                target = archive/artifact['file']; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((owned/artifact['file']).read_bytes())
        if 'module_observation_profile' in checked['files']:
            profile = checked['files']['module_observation_profile']
            (archive/'observation-profile.json').write_bytes(profile.read_bytes())
            state['observation_profile'] = dict(file='observation-profile.json', sha256=project.sha256(profile))
        project._write_new(archive/'state.json', state)
        project._write_new(self.workspace/'current.json', dict(generation=0,sha256=project.sha256(archive/'state.json')))
        return owned, archive

    def test_live_and_archived_graph_tampering_invalidates_managed_state(self):
        owned, archive = self.retained(); inc._state(self.workspace)
        for root in (owned, archive):
            for name in self.history.artifact_bindings:
                path = root/'observation-history'/name; raw = path.read_bytes(); stamp = path.stat().st_mtime_ns
                path.write_bytes(raw+b' '); os.utime(path, ns=(stamp,stamp))
                with self.subTest(root=root,name=name), self.assertRaises(ValueError):
                    inc._state(self.workspace)
                path.write_bytes(raw); os.utime(path, ns=(stamp,stamp))
        inc._state(self.workspace)

    def test_managed_history_downgrade_refuses_before_compiler(self):
        self.retained(); checked = self.checked()
        config = copy.deepcopy(checked['config']); del config['module']['observation_history']
        # The new-format module itself requires its graph; stripping both fields
        # is not an implicit permission to drop retained history.
        manifest = self.root/'native/module.json'
        value = json.loads(manifest.read_text(encoding='utf-8'))
        for key in list(value):
            if key.startswith('observation_history_'):
                del value[key]
        manifest.write_text(json.dumps(value), encoding='utf-8')
        config['module']['manifest']['sha256'] = project.sha256(manifest)
        candidate = self.root/'downgrade.toml'; candidate.write_text(inc._toml(config), encoding='utf-8')
        before = inc._snapshot(self.workspace)
        with patch.object(inc, 'prepare') as compiler, self.assertRaisesRegex(ValueError, 'binding cannot be removed'):
            inc.rebuild(candidate, self.workspace, allow_revision_override=True)
        compiler.assert_not_called(); self.assertEqual(before, inc._snapshot(self.workspace))
        # A fully valid legacy inline profile is still a downgrade, even when
        # its current instruction union happens to match this history exactly.
        profile = compose_observation_profile([self.original])
        profile_path = self.root/'downgrade-profile.json'
        profile_path.write_bytes(serialize_observation_profile(profile))
        module = self.root/'downgrade-profile-module'
        emit_observation_profile(profile, module, project.sha256(profile_path), partition_layout='stable')
        config['module'] = dict(source=dict(path=str(module/'module.cpp'), sha256=project.sha256(module/'module.cpp')),
            manifest=dict(path=str(module/'module.json'), sha256=project.sha256(module/'module.json')),
            observation_profile=dict(path=str(profile_path), sha256=project.sha256(profile_path)))
        candidate = self.root/'profile-downgrade.toml'; candidate.write_text(inc._toml(config), encoding='utf-8')
        self.checked(candidate)
        with patch.object(inc, 'prepare') as compiler, self.assertRaisesRegex(ValueError, 'binding cannot be removed'):
            inc.rebuild(candidate, self.workspace, allow_revision_override=True)
        compiler.assert_not_called(); self.assertEqual(before, inc._snapshot(self.workspace))

    def test_history_extension_preserves_stages_policy_capacity_and_zero_novel_inputs(self):
        extra = self.capture('extra', 29, [test_capture.observation(0x4001, (0xe8,))])
        zero = self.capture('zero-novel', 29, [test_capture.observation(0x4000, (0xea,), interpreted=7)])
        newer = compose_history([extra, zero], self.root/'history-new', baseline_history=self.history.index_path)
        inc._history_extension(self.history.index, newer)
        # These are relation checks over independently admitted graphs; mutating
        # a dictionary is not a way to construct or authenticate a history.
        for field,value in (('inputs', []), ('selection_stages', []), ('capacity', 1),
                            ('selection_policy', 'invented')):
            altered = newer.index; altered[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'retain prior'):
                inc._history_extension(self.history.index, SimpleNamespace(index=altered))
        current = {entry['sha256'] for entry in newer.index['inputs']}
        self.assertIn(project.sha256(zero), current)
        # Same identities and old union are insufficient: this removes an
        # original whose exact raw window selected no new observation key.
        omitted = compose_history([self.original, extra], self.root/'omitted-zero')
        self.assertEqual({(tuple(row['mpr']),row['pc'],tuple(row['data'])) for row in omitted.instructions},
                         {(tuple(row['mpr']),row['pc'],tuple(row['data'])) for row in newer.instructions})
        with self.assertRaisesRegex(ValueError, 'retain prior'):
            inc._history_extension(newer.index, omitted)

    def test_inline_migration_refuses_altered_selection_or_omitted_zero_novel_raw_atomically(self):
        zero = self.capture('zero-novel-migration', 29,
                            [test_capture.observation(0x4000, (0xea,), interpreted=7)])
        profile = compose_additive_observation_profile([zero], baseline_inputs=[self.original])
        profile_path = self.root/'old-profile.json'
        profile_path.write_bytes(serialize_observation_profile(profile))
        module = self.root/'inline-module'
        emit_observation_profile(profile, module, project.sha256(profile_path), partition_layout='stable')
        config = __import__('tomllib').loads(self.fixture.text)
        config['module'] = dict(source=dict(path=str(module/'module.cpp'), sha256=project.sha256(module/'module.cpp')),
            manifest=dict(path=str(module/'module.json'), sha256=project.sha256(module/'module.json')),
            observation_profile=dict(path=str(profile_path), sha256=project.sha256(profile_path)))
        inline = self.root/'inline.toml'; inline.write_text(inc._toml(config), encoding='utf-8', newline='\n')
        self.retained(inline)
        before = inc._snapshot(self.workspace)
        # Both are fully authenticated, valid graphs. Their relation to the
        # retained stage decisions is invalid before any compiler is consulted.
        for name,paths in (('changed-stages', [self.original,zero]), ('dropped-zero', [self.original])):
            candidate_history = compose_history(paths, self.root/name)
            descriptor = self.descriptor_for(candidate_history.index_path, name+'-module')
            with self.subTest(name=name), patch.object(inc, 'prepare') as compiler:
                with self.assertRaisesRegex(ValueError, 'retain prior'):
                    inc.rebuild(descriptor, self.workspace, allow_revision_override=True)
                compiler.assert_not_called()
            self.assertEqual(before, inc._snapshot(self.workspace))

    def test_catalogue_and_gap_report_preserve_full_history_provenance(self):
        catalog = native_catalog.load_native_catalog(self.root/'native/module.json', self.history.index_path)
        self.assertEqual(catalog.provenance['observations']['kind'], 'history')
        self.assertEqual(catalog.provenance['original_inputs'][0]['runtime_abi'], 18)
        self.assertEqual(len(catalog.provenance['history_artifacts']), len(self.history.artifact_bindings))
        self.assertNotIn(str(self.root), json.dumps(catalog.provenance))
        gaps = native_gaps.report_native_gaps(catalog, [self.original])
        self.assertEqual(gaps['summary']['uncompiled_observed'], 0)
        manifest = self.root/'native/module.json'; value = json.loads(manifest.read_text(encoding='utf-8'))
        value['runtime_abi'] = 28; value.pop('bus_trace', None)
        manifest.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'producer ABI29'):
            native_catalog.load_native_catalog(manifest, self.history.index_path)

    def test_history_v2_binds_exact_extended_original_and_archived_graph(self):
        capture = test_capture.capture([test_capture.observation(0x4000,(0xea,))],capacity=65537)
        capture['runtime_abi'] = 29
        raw = test_project.ConsumerProjectTests.extended_capture_bytes(capture)
        source = self.root/'authored-extended.jsonl'; source.write_bytes(raw)
        history = compose_history([source],self.root/'history-v2',history_version=2,capacity=131072)
        descriptor = self.descriptor_for(history.index_path,'native-v2')
        checked = self.checked(descriptor)
        self.assertEqual(checked['identities']['module_observation_history'],history.index_sha256)
        for relative,artifact in history.artifact_bindings.items():
            key = 'module_observation_history' if relative == 'history.json' else 'module_history:'+relative
            self.assertEqual(checked['identities'][key],artifact['sha256'])
        catalog = native_catalog.load_native_catalog(self.root/'native-v2/module.json',history.index_path)
        self.assertEqual(catalog.provenance['original_inputs'][0]['schema'],2)
        self.assertEqual(catalog.provenance['original_inputs'][0]['format'],'pce-code-capture-2')
        self.assertEqual(catalog.provenance['original_inputs'][0]['sha256'],project.sha256(source))
        self.retained(descriptor)
        inc._state(self.workspace)
        archived = self.workspace/'history/000000/observation-history/captures'/(project.sha256(source)+'.json')
        self.assertEqual(archived.read_bytes(),raw)
        archived.write_bytes(raw+b' ')
        with self.assertRaises(ValueError):
            inc._state(self.workspace)

    def test_managed_v2_promotion_preserves_prior_inputs_stages_and_nondecreasing_capacity(self):
        promoted = compose_history([],self.root/'promoted-v2',baseline_history=self.history.index_path,
                                   history_version=2,capacity=131072)
        inc._history_extension(self.history.index,promoted)
        self.assertEqual(promoted.instructions,self.history.instructions)
        self.assertEqual(promoted.index['inputs'],self.history.index['inputs'])
        grown = compose_history([],self.root/'grown-v2',baseline_history=promoted.index_path,capacity=262144)
        inc._history_extension(promoted.index,grown)
        shrunk = compose_history([],self.root/'shrunk-v2',baseline_history=promoted.index_path,capacity=65536)
        for candidate in (shrunk,self.history):
            with self.subTest(schema=candidate.index['schema']), self.assertRaisesRegex(ValueError,'retain prior'):
                inc._history_extension(promoted.index,candidate)
        changed = grown.index; changed['selection_stages'] = []
        with self.assertRaisesRegex(ValueError,'retain prior'):
            inc._history_extension(promoted.index,SimpleNamespace(index=changed))
        promoted_descriptor = self.descriptor_for(promoted.index_path,'promoted-v2-module')
        self.retained(promoted_descriptor)
        before = inc._snapshot(self.workspace)
        with patch.object(inc,'prepare') as compiler, self.assertRaisesRegex(ValueError,'retain prior'):
            inc.rebuild(self.descriptor,self.workspace,allow_revision_override=True)
        compiler.assert_not_called()
        self.assertEqual(inc._snapshot(self.workspace),before)

    def test_extended_capture_catalogue_requires_explicit_original_format_metadata(self):
        from pcerecomp.capture import load_capture
        from pcerecomp.emitter import emit_capture
        value = test_capture.capture([test_capture.observation(0x4000,(0xea,))],capacity=65537)
        value['runtime_abi'] = 29
        source = self.root/'source-extended.jsonl'
        source.write_bytes(test_project.ConsumerProjectTests.extended_capture_bytes(value))
        original,digest = load_capture(source)
        module = self.root/'extended-module'; manifest = emit_capture(original,module,digest)
        self.assertEqual(len(native_catalog.load_native_catalog(module/'module.json',source).emitted),1)
        for key in ('capture_schema','capture_format'):
            altered = copy.deepcopy(manifest); del altered[key]
            (module/'module.json').write_text(json.dumps(altered),encoding='utf-8')
            with self.subTest(key=key), self.assertRaises(ValueError):
                native_catalog.load_native_catalog(module/'module.json',source)


if __name__ == '__main__':
    unittest.main()
