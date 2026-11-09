"""Authored consumer preparation, immutable inputs and truthful evidence scope."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp import prepare, project
from pcerecomp.abi import ABI
from pcerecomp.history import compose_history, load_history
from pcerecomp.observations import compose_observation_profile


class ConsumerPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root/'original.json'
        value = dict(schema=1, runtime_abi=ABI, capacity=16,
            dropped_instructions=0, unreadable_instructions=0, retired_instructions=1,
            complete=True, observations=[dict(pc=0x2800, mpr=[248]*8,
                physical=[0x1F0800], data=[0xEA], native_hits=0, interpreted_hits=1)])
        self.capture.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
        self.payload = self.root/'authored.bin'
        self.payload.write_bytes(b'\xEA')
        self.spec = dict(schema=1, format=prepare.FORMAT, name='authored-prepared',
            module=dict(kind='capture', path=self.capture.name),
            payload=dict(path=self.payload.name, physical_load=0x1F0800, pc=0x2800, mpr=[248]*8),
            runtime=dict(tier='native', video='snapshot', cd_unknown_status='fault',
                         joypad=2, region='usa', multitap='off', audio='off'),
            limits=dict(steps=1, ticks=1000, wall_seconds=5))

    def recipe(self, spec=None):
        path = self.root/'recipe.toml'
        path.write_text(prepare._toml(self.spec if spec is None else spec), encoding='utf-8', newline='\n')
        return path

    def test_prepare_pins_complete_history_without_claiming_execution(self):
        spec = self.recipe()
        original = {p: p.read_bytes() for p in (spec, self.payload, self.capture)}
        output = self.root/'prepared'
        receipt = prepare.prepare_project(spec, output)
        self.assertTrue(receipt['prepared'])
        for field in ('execution_evidence', 'compiled', 'executed'):
            self.assertIs(receipt[field], False)
        verified = project.verify(output/'project.toml')
        self.assertEqual(receipt['binding'], project._binding(verified))
        self.assertEqual(receipt['native_instructions_emitted'], 1)
        history = load_history(output/'observation-history')
        self.assertEqual(history.index_sha256, receipt['history_sha256'])
        blobs = list((output/'observation-history/captures').glob('*.json'))
        self.assertEqual(len(blobs), 1)
        self.assertEqual(blobs[0].read_bytes(), original[self.capture])
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        with self.assertRaisesRegex(ValueError, 'new directory'):
            prepare.prepare_project(spec, output)

    def test_profile_and_history_inputs_are_preserved_as_originals(self):
        profile = compose_observation_profile([self.capture], capacity=16)
        path = self.root/'profile.json'
        path.write_text(json.dumps(profile, indent=2)+'\n', encoding='utf-8')
        before = path.read_bytes()
        for kind, source in (('profile', path),):
            spec = copy.deepcopy(self.spec)
            spec['module'] = dict(kind=kind, path=source.name)
            result = prepare.prepare_project(self.recipe(spec), self.root/kind)
            self.assertTrue(result['prepared'])
            self.assertEqual(source.read_bytes(), before)
        compose_history([self.capture], self.root/'source-history')
        spec = copy.deepcopy(self.spec)
        spec['module'] = dict(kind='history', path='source-history')
        result = prepare.prepare_project(self.recipe(spec), self.root/'from-history')
        self.assertEqual(result['original_observations']['sha256'],
                         project.sha256(self.root/'source-history/history.json'))

    def test_invalid_or_implicit_recipes_refuse_before_destination_creation(self):
        variants = []
        for key, value in (('schema', True), ('format', 'unknown'), ('name', '../escape'), ('extra', 'guess')):
            changed = copy.deepcopy(self.spec); changed[key] = value; variants.append(changed)
        for key, value in (('kind', 'infer'), ('capacity', True), ('partition_size', 0),
                           ('partition_size', 4097), ('partition_size', 128),
                           ('exclude_ranges', [[0, 1]]*257),
                           ('exclude_ranges', [[0x1FFFFF, 2]]), ('native_span', 1)):
            changed = copy.deepcopy(self.spec); changed['module'][key] = value; variants.append(changed)
        changed = copy.deepcopy(self.spec)
        changed['limits']['steps'] = 20000000001
        variants.append(changed)
        changed = copy.deepcopy(self.spec); del changed['payload']; variants.append(changed)
        changed = copy.deepcopy(self.spec); changed['boot'] = dict(mode='infer'); variants.append(changed)
        for index, spec in enumerate(variants):
            destination = self.root/('invalid-'+str(index))
            with self.subTest(index=index), self.assertRaises(ValueError):
                prepare.prepare_project(self.recipe(spec), destination)
            self.assertFalse(destination.exists())

    def test_nested_output_cannot_change_original_history_membership(self):
        history_root = self.root/'closed-history'
        admitted = compose_history([self.capture], history_root)
        original = {p.relative_to(history_root): p.read_bytes()
                    for p in history_root.rglob('*') if p.is_file()}
        for selector in ('closed-history', 'closed-history/history.json'):
            with self.subTest(selector=selector):
                spec = copy.deepcopy(self.spec)
                spec['module'] = dict(kind='history', path=selector)
                output = history_root/'must-not-be-created'
                with self.assertRaisesRegex(ValueError, 'original history graph'):
                    prepare.prepare_project(self.recipe(spec), output)
                self.assertFalse(output.exists())
                admitted.revalidate()
                self.assertEqual({p.relative_to(history_root): p.read_bytes()
                                  for p in history_root.rglob('*') if p.is_file()}, original)

    def test_wrong_asset_hash_and_existing_file_are_never_replaced(self):
        spec = copy.deepcopy(self.spec)
        spec['payload']['sha256'] = '0'*64
        output = self.root/'wrong'
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            prepare.prepare_project(self.recipe(spec), output)
        self.assertFalse(output.exists())
        output.write_bytes(b'owner-data')
        with self.assertRaises(ValueError):
            prepare.prepare_project(self.recipe(), output)
        self.assertEqual(output.read_bytes(), b'owner-data')

    def test_non_git_sdk_label_requires_explicit_override(self):
        spec = copy.deepcopy(self.spec)
        spec['sdk'] = dict(revision='0'*40)
        output = self.root/'wrong-pin'
        with self.assertRaisesRegex(ValueError, 'revision mismatch'):
            prepare.prepare_project(self.recipe(spec), output)
        self.assertFalse(output.exists())

    def test_toml_roundtrip_retains_unicode_paths_and_typed_values(self):
        import tomllib
        value = dict(name='test', path='données/🎮.bin', mpr=[0, 255], enabled=False)
        self.assertEqual(tomllib.loads(prepare._toml(value)), value)
