"""Authored retained-profile consumer admission, provenance and receipt guards."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pcerecomp import project
from pcerecomp.emitter import emit_observation_profile
from pcerecomp import observations
from pcerecomp.observations import compose_observation_profile
from tests.test_observation_emitter import inputs
from tests import test_project as project_tests


class ProjectObservationTests(unittest.TestCase):
    def setUp(self):
        project_tests.ConsumerProjectTests.setUp(self)
        self.profile = compose_observation_profile(inputs(self.root))
        self.profile_path = self.root/'retained-profile.json'
        self.profile_path.write_text(json.dumps(self.profile, indent=2)+'\n', encoding='utf-8')
        self.generated = self.root/'generated'
        self.manifest = emit_observation_profile(self.profile, self.generated,
            project.sha256(self.profile_path), partition_layout='stable')
        self.descriptor_text = self.text.replace('path = "module.cpp"', 'path = "generated/module.cpp"')
        self.descriptor_text = self.descriptor_text.replace(
            project.sha256(self.root/'module.cpp'), project.sha256(self.generated/'module.cpp'))
        self.descriptor_text = self.descriptor_text.replace('path = "module.json"', 'path = "generated/module.json"')
        self.original_manifest_sha = project.sha256(self.root/'module.json')
        self.write_descriptor()

    def write_descriptor(self, *, bound=True, entry=None):
        text = self.descriptor_text.replace(self.original_manifest_sha,
                                            project.sha256(self.generated/'module.json'))
        if bound:
            if entry is None:
                entry = {'path': 'retained-profile.json', 'sha256': project.sha256(self.profile_path)}
            text += '\n[module.observation_profile]\n'
            for key, value in entry.items():
                text += key+' = '+json.dumps(value)+'\n'
        self.descriptor.write_text(text, encoding='utf-8')

    def write_manifest(self, value):
        (self.generated/'module.json').write_text(json.dumps(value), encoding='utf-8')
        self.write_descriptor()

    def verify(self):
        return project.verify(self.descriptor, allow_revision_override=True)

    def test_opt_in_binding_reconstructs_original_abi_origin_and_history(self):
        with patch('pcerecomp.emitter.emit_observation_profile', side_effect=AssertionError('verification must not emit')):
            checked = self.verify()
        self.assertEqual(checked['files']['module_observation_profile'], self.profile_path)
        self.assertEqual(checked['identities']['module_observation_profile'], project.sha256(self.profile_path))
        self.assertEqual(project._binding(checked)['files']['module_observation_profile'],
                         project.sha256(self.profile_path))
        self.assertEqual({item['runtime_abi'] for item in self.manifest['observation_inputs']}, {18, 26})
        self.assertEqual(self.manifest['historical_totals']['retired_instructions'], 15)
        self.assertFalse(self.manifest['execution_evidence'])
        self.assertNotIn('capture_runtime_abi', self.manifest)

    def test_details_loader_preserves_old_api_and_reconstructs_once(self):
        original = self.profile_path.read_bytes()
        with patch.object(observations, '_derive', wraps=observations._derive) as derive:
            loaded, digest, instructions, provenance = observations.load_observation_profile_details(self.profile_path)
        self.assertEqual(derive.call_count, 1)
        self.assertEqual((loaded, digest), observations.load_observation_profile(self.profile_path))
        self.assertEqual(instructions, observations.validate_observation_profile(self.profile))
        self.assertEqual(provenance, observations.observation_profile_provenance(self.profile))
        self.assertEqual(self.profile_path.read_bytes(), original)
        with patch.object(observations, '_derive', wraps=observations._derive) as derive:
            self.verify()
        self.assertEqual(derive.call_count, 1)

    def test_omitting_binding_preserves_legacy_context_and_command(self):
        bound = self.verify()
        self.write_descriptor(bound=False)
        unbound = self.verify()
        self.assertNotIn('module_observation_profile', unbound['identities'])
        self.assertNotEqual(project.checkpoint_context(bound), project.checkpoint_context(unbound))
        self.assertEqual(project.command_for(bound, Path('host')), project.command_for(unbound, Path('host')))
        self.assertNotIn(str(self.profile_path), project.command_for(bound, Path('host')))
        self.profile_path.unlink()
        self.assertNotIn('module_observation_profile', self.verify()['files'])

    def test_limits_do_not_change_bound_checkpoint_context(self):
        checked = self.verify()
        changed = copy.deepcopy(checked)
        changed['config']['limits'] = dict(steps=9, ticks=10, wall_seconds=4)
        changed['descriptor_sha256'] = 'a'*64
        self.assertEqual(project.checkpoint_context(checked), project.checkpoint_context(changed))
        changed['identities']['module_observation_profile'] = 'a'*64
        self.assertNotEqual(project.checkpoint_context(checked), project.checkpoint_context(changed))

    def test_missing_or_changed_profile_refuses_before_build(self):
        self.profile_path.write_bytes(self.profile_path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.verify()
        build = self.root/'unwritten-build'
        with patch.object(project.subprocess, 'run', wraps=project.subprocess.run) as called:
            with self.assertRaises(ValueError):
                project.build(self.descriptor, build, allow_revision_override=True)
        self.assertFalse(build.exists())
        self.assertFalse(any(call.args and call.args[0][0] == 'cmake' for call in called.call_args_list))
        self.profile_path.unlink()
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.verify()

    def test_bad_profile_descriptor_table_refuses(self):
        for entry in ({}, {'path': 'retained-profile.json'}, {'path': True, 'sha256': 'a'*64},
                      {'path': 'retained-profile.json', 'sha256': True},
                      {'path': 'retained-profile.json', 'sha256': 'A'*64},
                      {'path': 'retained-profile.json', 'sha256': project.sha256(self.profile_path), 'extra': 1}):
            self.write_descriptor(entry=entry)
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.verify()

    def test_oversized_profile_refuses_before_hashing_or_loading(self):
        oversized = self.root/'oversized-profile.json'
        with oversized.open('wb') as stream:
            stream.truncate(observations.MAX_PROFILE_BYTES+1)
        self.write_descriptor(entry={'path': oversized.name, 'sha256': 'a'*64})
        original_sha = project.sha256
        def bounded_sha(path):
            self.assertNotEqual(Path(path), oversized, 'oversized profile must not be fully hashed')
            return original_sha(path)
        with patch.object(project, 'sha256', side_effect=bounded_sha), \
                patch.object(observations, 'load_observation_profile_details',
                             side_effect=AssertionError('oversized profile must not be loaded')):
            with self.assertRaisesRegex(ValueError, 'profile exceeds 128 MiB'):
                self.verify()

    def test_valid_profile_does_not_allow_forged_manifest_provenance(self):
        changes = [
            ('observation_profile_sha256', 'a'*64),
            ('observation_profile_format', 'capture'),
            ('observation_profile_schema', True),
            ('observation_profile_schema', 1.0),
            ('observation_inputs', []),
            ('historical_totals', dict(native_hits=6, interpreted_hits=9, retired_instructions=True)),
            ('historical_count_policy', 'new execution'),
            ('execution_evidence', True),
            ('execution_evidence', 0),
        ]
        for key, value in changes:
            manifest = copy.deepcopy(self.manifest);manifest[key] = value
            self.write_manifest(manifest)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.verify()
        for key in ('observation_profile_sha256', 'observation_inputs', 'historical_totals'):
            manifest = copy.deepcopy(self.manifest);manifest.pop(key)
            self.write_manifest(manifest)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.verify()

    def test_nested_input_numeric_types_and_checkpoint_prefix_are_strict(self):
        for key, value in (('runtime_abi', 18.0), ('schema', True), ('capacity', True),
                           ('retired_instructions', 8), ('complete', 1), ('native_hits', True)):
            manifest = copy.deepcopy(self.manifest)
            source = next(i for i in manifest['observation_inputs'] if i['runtime_abi'] == 18)
            source[key] = value
            self.write_manifest(manifest)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
        manifest = copy.deepcopy(self.manifest)
        source = next(i for i in manifest['observation_inputs'] if 'checkpoint_origin' in i)
        source['checkpoint_origin']['native_steps'] += 1
        self.write_manifest(manifest)
        with self.assertRaises(ValueError):
            self.verify()

    def test_bound_profile_refuses_synthetic_capture_or_origin_fields(self):
        for key, value in (('capture_runtime_abi', 26), ('capture_checkpoint_origin', {}),
                           ('captured_native_hits', 6), ('code_capture_sha256', 'a'*64),
                           ('checkpoint_origin', {}), ('execution_window', 'fresh')):
            self.write_manifest(self.manifest | {key: value})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'capture execution evidence'):
                self.verify()

    def test_union_emission_and_exclusion_count_types_are_checked(self):
        for key in ('native_instructions_emitted', 'native_contexts', 'observed_instructions',
                    'excluded_observations', 'excluded_retired_hits', 'unsupported_observations'):
            for value in (True, float(self.manifest[key]), self.manifest[key]+1):
                self.write_manifest(self.manifest | {key: value})
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.verify()

    def test_exclusions_reconstruct_touching_operand_and_historical_hits(self):
        output = self.root/'excluded'
        expected = emit_observation_profile(self.profile, output, project.sha256(self.profile_path),
            partition_layout='stable', exclude_ranges=[(0x100001, 1)])
        self.descriptor_text = self.descriptor_text.replace('generated/', 'excluded/').replace(
            project.sha256(self.generated/'module.cpp'), project.sha256(output/'module.cpp'))
        self.generated, self.manifest = output, expected
        self.write_descriptor()
        self.assertIn('module_observation_profile', self.verify()['files'])
        self.assertEqual(self.manifest['excluded_observations'], 3)
        self.assertEqual(self.manifest['excluded_retired_hits'], 12)
        for spans in ([{'start': True, 'length': 1}], [{'start': 0x100001, 'length': True}],
                      [{'start': 0x1fffff, 'length': 2}], [{'start': 0, 'length': 0}],
                      [{'start': 0, 'length': 1}, {'start': 0, 'length': 1}],
                      [{'start': 1, 'length': 1}, {'start': 0, 'length': 1}],
                      [{'start': 0, 'length': 1, 'extra': 0}], None):
            self.write_manifest(self.manifest | {'excluded_physical_ranges': spans})
            with self.subTest(spans=spans), self.assertRaises(ValueError):
                self.verify()

    def test_rehashed_profile_tampering_still_refuses(self):
        changed = copy.deepcopy(self.profile)
        changed['observations'][0]['contributions'][0]['native_hits'] += 1
        self.profile_path.write_text(json.dumps(changed), encoding='utf-8')
        self.manifest['observation_profile_sha256'] = project.sha256(self.profile_path)
        self.write_manifest(self.manifest)
        with self.assertRaisesRegex(ValueError, 'contributions disagree'):
            self.verify()

    def test_duplicate_and_nonfinite_manifest_json_refuses(self):
        original = json.dumps(self.manifest)
        for raw in ('{"schema":1,'+original[1:],
                    original.replace('"observation_inputs": [', '"observation_inputs": [', 1)
                        .replace('"size_bytes": ', '"size_bytes": NaN, "shadow_size": ', 1),
                    original[:-1]+',"unused":1e999}',
                    original[:-1]+',"unused":Infinity}'):
            (self.generated/'module.json').write_text(raw, encoding='utf-8')
            self.write_descriptor()
            with self.subTest(raw=raw[:25]), self.assertRaises(ValueError):
                self.verify()


if __name__ == '__main__':
    unittest.main()
