"""Authored opt-in larger catalogues; immutable legacy contracts and provenance."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import capture as capture_module, history, observations
from test_history import capture, row


def extended(entries=None, **changes):
    value = capture([row()] if entries is None else entries, abi=29)
    value.pop('schema')
    entries = value.pop('observations')
    value['capacity'] = 1048576
    value.update(changes)
    line = lambda item: json.dumps(item, separators=(',', ':')).encode('utf-8') + b'\n'
    return (capture_module.EXTENDED_MAGIC + line(value) + b''.join(line(item) for item in entries)
            + line(dict(record='end', observations=len(entries))))


class HistoryV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def write(self, raw=None):
        self.serial += 1
        path = self.root / ('raw-' + str(self.serial) + '.json')
        path.write_bytes(extended() if raw is None else raw)
        return path

    def make(self, paths=None, name='history', **options):
        return history.compose_history([self.write()] if paths is None else paths,
                                       self.root / name, **options)

    def test_opt_in_defaults_strict_versions_and_legacy_limits(self):
        raw = self.write()
        for options in ({}, dict(history_version=1), dict(history_version=True),
                        dict(history_version=0), dict(history_version=3)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.make([raw], **options)
            self.assertFalse((self.root / 'history').exists())
        admitted = self.make([raw], history_version=2)
        self.assertEqual(admitted.index['schema'], 2)
        self.assertEqual(admitted.index['format'], history.FORMAT_V2)
        self.assertEqual(admitted.index['capacity'], 1048576)
        self.assertEqual(history.FORMAT, 'pce-observation-history-1')
        self.assertEqual(history.MAX_RAW_BYTES, 256 * 64 * 1024 * 1024)
        self.assertEqual(capture_module.MAX_OBSERVATIONS, 65536)
        self.assertEqual(observations.MAX_CONTRIBUTIONS, 262144)
        self.assertEqual(history.history_limits(2)['max_total_bytes'], 256 * 512 * 1024 * 1024)
        self.assertEqual(admitted.input_metadata[0]['format'], capture_module.EXTENDED_FORMAT)
        self.assertEqual(admitted.input_metadata[0]['schema'], 2)
        self.assertEqual(admitted.input_metadata[0]['runtime_abi'], 29)
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        self.assertEqual((admitted.index_path.parent / 'captures' / (digest + '.json')).read_bytes(), raw.read_bytes())

    def test_legacy_history_default_bytes_unchanged_and_mixed_metadata(self):
        legacy = self.write(json.dumps(capture()).encode())
        one = self.make([legacy], name='one')
        explicit = self.make([legacy], name='explicit', history_version=1)
        self.assertEqual(one.index_sha256, explicit.index_sha256)
        promoted = self.make([self.write()], name='mixed', history_version=2, baseline_history=one.index_path)
        self.assertEqual(promoted.index['capacity'], 65536)
        self.assertEqual(promoted.index['selection_stages'][0], one.index['selection_stages'][0])
        old = next(item for item in promoted.input_metadata if item['schema'] == 1)
        self.assertNotIn('format', old)
        self.assertEqual(old, one.input_metadata[0])
        self.assertEqual(promoted.index['selection_counts'], dict(original_contributions=2,
                         selected_contributions=1, omitted_contributions=1))
        self.assertEqual(promoted.index['historical_totals']['retired_instructions'], 2)
        self.assertEqual(len(promoted.index['inputs']), 2)

    def test_inheritance_explicit_growth_and_downgrade_refusal(self):
        base = self.make(history_version=2, capacity=1)
        inherited = self.make([], name='inherited', baseline_history=base.index_path)
        self.assertEqual(inherited.index_sha256, base.index_sha256)
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            self.make([], name='downgrade', history_version=1, baseline_history=base.index_path)
        self.assertFalse((self.root / 'downgrade').exists())
        novel = self.write(extended([row(data=(0xA9, 43))]))
        with self.assertRaisesRegex(ValueError, 'union capacity'):
            self.make([novel], name='no-growth', baseline_history=base.index_path)
        self.assertFalse((self.root / 'no-growth').exists())
        grown = self.make([novel], name='grown', baseline_history=base.index_path, capacity=65537)
        self.assertEqual(grown.index['capacity'], 65537)
        self.assertEqual(len(grown.instructions), 2)

    def test_profile_promotion_preserves_originals_and_stages(self):
        a = self.write(json.dumps(capture()).encode())
        b = self.write(json.dumps(capture([row(data=(0xA9, 43))])).encode())
        first = observations.compose_observation_profile([a])
        base = self.root / 'base-profile.json'; base.write_text(json.dumps(first), encoding='utf-8')
        staged = observations.compose_additive_observation_profile([b], baseline_profile=base)
        profile = self.root / 'staged-profile.json'; profile.write_text(json.dumps(staged), encoding='utf-8')
        for index, (source, value) in enumerate(((base, first), (profile, staged))):
            before = source.read_bytes()
            upgraded = self.make([], name='upgraded-' + str(index), history_version=2, baseline_profile=source)
            self.assertEqual(upgraded.index['selection_stages'], value.get('selection_stages',
                             [[item['sha256'] for item in value['inputs']]]))
            self.assertEqual(upgraded.input_metadata, observations.observation_profile_provenance(value))
            self.assertEqual(upgraded.instructions, observations.validate_observation_profile(value))
            self.assertEqual(upgraded.index['capacity'], value['capacity'])
            self.assertEqual(source.read_bytes(), before)

    def test_duplicate_zero_novel_inputs_and_policy_keep_exact_provenance(self):
        policy = dict(schema=1, reference_enabled=True, selected=True, configured_tier='native',
                      effective_policy='interpreter', effective_native_span=0)
        origin = dict(sha256='a'*64, ticks=20, frame=3, native_steps=4, interpreter_steps=5)
        first = self.write(extended(execution_policy=policy, checkpoint_origin=origin))
        base = self.make([first], history_version=2)
        exact = self.make([first], name='duplicate', baseline_history=base.index_path)
        self.assertEqual(exact.index_sha256, base.index_sha256)
        second = self.write(extended(retired_instructions=4,
                                    entries=[row(interpreted=4)]))
        added = self.make([second], name='added', baseline_history=base.index_path)
        self.assertEqual(added.index['selection_counts']['selected_contributions'], 1)
        self.assertEqual(added.index['historical_totals']['retired_instructions'], 5)
        original = next(item for item in added.input_metadata if item['sha256'] == hashlib.sha256(first.read_bytes()).hexdigest())
        self.assertEqual(original['execution_policy'], policy)
        self.assertEqual(original['checkpoint_origin'], origin)

    def test_shared_derivation_explicit_bounds_and_legacy_defaults(self):
        raws = [json.dumps(capture([row()])).encode(), json.dumps(capture([row(data=(0xA9, 43))])).encode()]
        mapping = {hashlib.sha256(raw).hexdigest(): raw for raw in raws}
        inputs = [dict(sha256=sha, size_bytes=len(mapping[sha])) for sha in sorted(mapping)]
        def derive(**options):
            return observations._derive_raw_observations(inputs, 2, [sorted(mapping)], mapping.__getitem__,
                                                        max_total_bytes=100000, **options)
        with self.assertRaisesRegex(ValueError, 'profile capacity'):
            derive(union_limit=1)
        with self.assertRaisesRegex(ValueError, 'contribution capacity'):
            derive(contribution_limit=1)
        with self.assertRaisesRegex(ValueError, 'input byte size'):
            derive(max_capture_bytes=1)
        self.assertEqual(len(derive()[0]), 2)
        with patch.object(history, 'MAX_CONTRIBUTIONS_V2', 1):
            with self.assertRaisesRegex(ValueError, 'contribution capacity'):
                self.make([self.write(raws[0]), self.write(raws[1])], history_version=2)
        self.assertFalse((self.root / 'history').exists())

    def test_version_pair_capacity_and_cached_fact_tampering_refuse(self):
        base = self.make(history_version=2)
        original = base.index_path.read_bytes()
        for change in (dict(schema=True), dict(schema=1), dict(format=history.FORMAT),
                       dict(capacity=1048577), dict(capacity=True),
                       dict(selection_counts=dict(original_contributions=1, selected_contributions=0, omitted_contributions=1))):
            value = base.index; value.update(change)
            base.index_path.write_bytes(observations._canonical(value) + b'\n')
            with self.subTest(change=change), self.assertRaises(ValueError):
                history.load_history(base.index_path)
            base.index_path.write_bytes(original)
        shard = next(item for name, item in base.artifact_bindings.items() if name.startswith('catalogue/'))
        shard['path'].write_bytes(shard['path'].read_bytes().replace(b'42', b'43'))
        with self.assertRaises(ValueError):
            history.load_history(base.index_path)

    def test_extended_raw_size_transport_and_union_bounds_before_allocation(self):
        raw = self.write()
        with patch.object(history, 'MAX_CAPTURE_BYTES_V2', 1):
            with self.assertRaises(ValueError):
                self.make([raw], history_version=2)
        with patch.object(history, 'MAX_RAW_BYTES_V2', 1):
            with self.assertRaises(ValueError):
                self.make([raw], history_version=2)
        with patch.object(history, 'MAX_OBSERVATIONS_V2', 1):
            with self.assertRaisesRegex(ValueError, 'history capacity'):
                self.make([raw], history_version=2, capacity=2)
        self.assertFalse((self.root / 'history').exists())

    def test_history_v2_does_not_widen_legacy_capture_or_inline_contracts(self):
        too_large = capture()
        too_large['capacity'] = 65537
        source = self.write(json.dumps(too_large).encode())
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.make([source], history_version=2)
        self.assertFalse((self.root / 'history').exists())
        # A JSON object carrying schema2 is not the framed extended transport.
        unframed = capture(abi=29)
        unframed.update(schema=2, format=capture_module.EXTENDED_FORMAT)
        source = self.write(json.dumps(unframed).encode())
        for compose in (observations.compose_observation_profile,
                        lambda paths: history.compose_history(paths, self.root / 'bare', history_version=2)):
            with self.assertRaises(ValueError):
                compose([source])
        with self.assertRaises(ValueError):
            observations.compose_observation_profile([self.write()])
        with self.assertRaisesRegex(ValueError, 'profile capacity'):
            observations.compose_observation_profile([self.write(json.dumps(capture()).encode())], capacity=65537)

    def test_authored_capture_above_legacy_identity_bound(self):
        # Full logical address space plus a different MPR context at the same PC.
        entries = [row(pc, (0xEA,)) for pc in range(65536)]
        mapping = [*entries[0]['mpr']]; mapping[7] = 1
        entries.append(row(0, (0xEA,), mpr=mapping))
        path = self.write(extended(entries))
        admitted = self.make([path], history_version=2)
        self.assertEqual(len(admitted.instructions), 65537)
        self.assertEqual(sum(item['identity_count'] for item in admitted.index['catalogue']), 65537)
        self.assertEqual(len(admitted.index['catalogue']), 17)
        self.assertEqual(admitted.index['historical_totals']['retired_instructions'], 65537)
        self.assertEqual(admitted.index['selection_counts']['selected_contributions'], 65537)
        admitted.revalidate()


if __name__ == '__main__':
    unittest.main()
