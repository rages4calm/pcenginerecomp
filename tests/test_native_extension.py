"""Authored native modules exercise real admission, not imported report JSON."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.emitter import emit_capture
from pcerecomp.native_catalog import load_native_catalog
from pcerecomp.native_extension import compare_native_extensions, report_native_extension


MPR = [255, 248, 128, 129, 130, 131, 132, 0]


def row(pc=0x4000, data=(0xEA,), mpr=None):
    mapping = list(MPR if mpr is None else mpr)
    return dict(pc=pc, mpr=mapping, data=list(data),
                physical=[mapping[((pc+i)&65535)>>13]*8192+((pc+i)&8191) for i in range(len(data))],
                native_hits=0, interpreted_hits=1)


class NativeExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def module(self, rows, **options):
        self.serial += 1
        capture = dict(schema=1, runtime_abi=29, capacity=65536,
                       complete=True, dropped_instructions=0, unreadable_instructions=0,
                       retired_instructions=len(rows), observations=rows)
        raw = json.dumps(capture, sort_keys=True, separators=(',', ':')).encode()
        input_path = self.root/f'input-{self.serial}.json'
        input_path.write_bytes(raw)
        output = self.root/f'module-{self.serial}'
        emit_capture(capture, output, hashlib.sha256(raw).hexdigest(), **options)
        return output/'module.json', input_path

    def compare(self, before, after):
        return compare_native_extensions(*before, *after)

    def test_strict_additive_keeps_every_identity_and_original_inputs(self):
        before = self.module([row()])
        after = self.module([row(), row(0x4001)])
        originals = {path: path.read_bytes() for pair in (before, after) for path in pair}
        report = self.compare(before, after)
        self.assertEqual(report['relation'], 'strict-additive')
        self.assertTrue(report['strict_additive'])
        self.assertTrue(report['source_is_subset'])
        self.assertTrue(report['policy_compatible'])
        self.assertEqual([report[key]['count'] for key in ('retained', 'added', 'removed')], [1, 1, 0])
        self.assertFalse(report['migration_authorized'])
        self.assertFalse(report['qualified'])
        self.assertFalse(report['execution_evidence'])
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        self.assertTrue(report['remaining_gates'])
        for side in ('source', 'destination'):
            self.assertFalse(report[side]['provenance']['linked_binary_verified'])
            self.assertFalse(report[side]['provenance']['execution_evidence'])
        public = json.dumps(report)
        self.assertNotIn(str(self.root), public)
        self.assertNotIn('raw_base64', public)
        self.assertNotIn('"data"', public)

    def test_unchanged_and_deterministic(self):
        pair = self.module([row()])
        first = self.compare(pair, pair)
        self.assertEqual(first, self.compare(pair, pair))
        self.assertEqual(first['relation'], 'unchanged')
        self.assertTrue(first['source_is_subset'])
        self.assertFalse(first['strict_additive'])

    def test_replacement_counts_source_byte_changes(self):
        before = self.module([row(data=(0xA9, 1))])
        after = self.module([row(data=(0xA9, 2))])
        report = self.compare(before, after)
        self.assertEqual(report['relation'], 'replacement')
        self.assertFalse(report['source_is_subset'])
        self.assertEqual(report['variant_changes']['replaced']['locations'], 1)
        self.assertEqual(report['removed']['count'], 1)
        self.assertEqual(report['added']['count'], 1)

    def test_added_byte_variant_preserves_original(self):
        before = self.module([row(data=(0xA9, 1))])
        after = self.module([row(data=(0xA9, 1)), row(data=(0xA9, 2))])
        report = self.compare(before, after)
        self.assertEqual(report['relation'], 'strict-additive')
        self.assertEqual(report['variant_changes']['extended']['locations'], 1)

    def test_removal(self):
        before = self.module([row(), row(0x4001)])
        after = self.module([row()])
        report = self.compare(before, after)
        self.assertEqual(report['relation'], 'removal')
        self.assertEqual(report['removed']['count'], 1)

    def test_all_mprs_remain_in_identity_even_unused_slot(self):
        other = MPR.copy()
        other[7] = 1
        report = self.compare(self.module([row()]), self.module([row(mpr=other)]))
        self.assertEqual(report['relation'], 'replacement')
        self.assertEqual(report['variant_changes']['replaced']['locations'], 0)

    def test_policies_are_explicit_and_never_equated_by_membership(self):
        cases = [({}, {'operand_sharing': True}, 'operand_sharing'),
                 ({'partition_layout': 'stable'}, {'partition_layout': 'stable', 'native_span': True}, 'native_span'),
                 ({}, {'partition_size': 64}, 'partition_size'),
                 ({}, {'exclude_ranges': [(0x100, 1)]}, 'excluded_physical_ranges')]
        for before_options, after_options, expected in cases:
            with self.subTest(policy=expected):
                report = self.compare(self.module([row()], **before_options),
                                      self.module([row()], **after_options))
                self.assertEqual(report['relation'], 'unchanged')
                self.assertFalse(report['policy_compatible'])
                self.assertIn(expected, report['manifest_policy_changes'])
                self.assertFalse(report['migration_authorized'])

    def test_abi_difference_remains_visible(self):
        before = self.module([row()])
        after = self.module([row()])
        manifest = json.loads(before[0].read_bytes())
        manifest['runtime_abi'] = 28
        capture = json.loads(before[1].read_bytes())
        capture['runtime_abi'] = 26
        before[1].write_text(json.dumps(capture), encoding='utf-8')
        manifest['capture_runtime_abi'] = 26
        manifest['code_capture_sha256'] = hashlib.sha256(before[1].read_bytes()).hexdigest()
        del manifest['bus_trace']
        before[0].write_text(json.dumps(manifest), encoding='utf-8')
        report = self.compare(before, after)
        self.assertEqual(report['source']['runtime_abi'], 28)
        self.assertEqual(report['destination']['runtime_abi'], 29)
        self.assertIn('runtime_abi', report['manifest_policy_changes'])
        self.assertIn('declared_emission_contract', report['policy_changes'])
        self.assertFalse(report['policy_compatible'])

    def test_actual_artifact_tamper_fails_admission(self):
        before = self.module([row()])
        after = self.module([row(), row(0x4001)])
        (after[0].parent/'module.cpp').write_text('// changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.compare(before, after)

    def test_manifest_bytes_must_match_admitted_catalogue(self):
        pair = self.module([row()])
        catalog = load_native_catalog(*pair)
        with self.assertRaisesRegex(ValueError, 'differs'):
            report_native_extension(catalog, catalog, source_manifest=pair[0].read_bytes()+b' ',
                                    destination_manifest=pair[0].read_bytes())
        with self.assertRaisesRegex(ValueError, 'admitted'):
            report_native_extension(copy.deepcopy(catalog.provenance), catalog,
                                    source_manifest=pair[0].read_bytes(), destination_manifest=pair[0].read_bytes())


if __name__ == '__main__':
    unittest.main()
