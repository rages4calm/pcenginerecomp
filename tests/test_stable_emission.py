"""Authored stable source partitions; no object-reuse or execution claim."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.cli import main
from pcerecomp.emitter import emit_capture
from tests.test_capture import MPR, capture, observation


def files(root):
    return {path.name: path.read_bytes() for path in root.iterdir()}


def parts(root):
    return {name: data for name, data in files(root).items()
            if name.endswith('.cpp') and name != 'module.cpp'}


class StableEmissionTests(unittest.TestCase):
    def emit(self, root, items, **kwargs):
        return emit_capture(capture(items, capacity=max(64, len(items))), root,
                            partition_layout='stable', **kwargs)

    def test_fixed_ranges_and_complete_mapping_determine_names(self):
        other = MPR.copy(); other[7] = 1
        items = [observation(0x4000, (0xea,)), observation(0x40ff, (0xa9, 42)),
                 observation(0x4100, (0xea,)), observation(0x4000, (0xea,), mpr=other)]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'out'
            manifest = self.emit(out, items)
            mapping = sum(value << (8*i) for i, value in enumerate(MPR))
            other_mapping = mapping | (1 << 56)
            expected = {f'module_m{mapping:016x}_p4000.cpp',
                        f'module_m{mapping:016x}_p4100.cpp',
                        f'module_m{other_mapping:016x}_p4000.cpp'}
            self.assertEqual(set(parts(out)), expected)
            self.assertEqual(manifest['partition_layout'], 'stable')
            self.assertEqual(manifest['partition_identity'], 'full_mpr_logical_pc_range_v1')
            self.assertEqual(manifest['pc_bucket_size'], 256)
            self.assertTrue(manifest['partitioned'])
            self.assertEqual(manifest['largest_partition_instructions'], 2)
            self.assertEqual(manifest['native_contexts'], 2)
            entry = (out/'module.cpp').read_text()
            self.assertIn(f'case {mapping}ULL:', entry)
            self.assertIn(f'case {other_mapping}ULL:', entry)
            self.assertIn(f'return captured_m{mapping:016x}_p4000(bus,s);', entry)
            for item in manifest['translation_units'] + manifest['generated_headers']:
                self.assertEqual(hashlib.sha256((out/item['file']).read_bytes()).hexdigest(),
                                 item['sha256'])

    def test_earlier_site_and_context_do_not_renumber_existing_parts(self):
        # This deliberately crosses the legacy global partition threshold.
        # Changing an earlier MPR/PC must never renumber a later source unit.
        items = []
        for context in range(8):
            mpr = MPR.copy(); mpr[4] += context
            items += [observation(0x4100+i, (0xea,), mpr=mpr) for i in range(1024)]
        earlier = MPR.copy(); earlier[0] = 0
        with tempfile.TemporaryDirectory() as temp:
            first, second, third = [Path(temp)/name for name in ('first', 'second', 'third')]
            self.emit(first, items)
            self.emit(second, items + [observation(0x4000, (0xea,))])
            self.emit(third, items + [observation(0, (0xea,), mpr=earlier)])
            baseline = parts(first)
            self.assertEqual(len(baseline), 32)
            for changed in (second, third):
                self.assertEqual(len(parts(changed)), 33)
                self.assertTrue(all(parts(changed)[name] == data for name, data in baseline.items()))
                self.assertNotEqual((first/'module.cpp').read_bytes(), (changed/'module.cpp').read_bytes())
                self.assertNotEqual((first/'module_parts.hpp').read_bytes(),
                                    (changed/'module_parts.hpp').read_bytes())

    def test_variant_addition_changes_only_its_own_source_unit(self):
        items = [observation(0x4000, (0xa9, 1)), observation(0x4100, (0xea,))]
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp)/'first', Path(temp)/'second'
            self.emit(first, items)
            self.emit(second, items + [observation(0x4000, (0xa9, 2))])
            changed = {name for name, data in files(first).items() if files(second)[name] != data}
            self.assertEqual(len(changed), 2)
            self.assertIn('module.json', changed)
            changed.remove('module.json')
            self.assertTrue(next(iter(changed)).endswith('_p4000.cpp'))
            self.assertIn('s.a=1;', (second/next(iter(changed))).read_text())
            self.assertIn('s.a=2;', (second/next(iter(changed))).read_text())

    def test_changed_hits_and_input_order_leave_all_source_bytes_unchanged(self):
        items = [observation(0x4000, (0xa9, 3)), observation(0x4100, (0xea,))]
        changed = copy.deepcopy(items)
        changed.reverse()
        changed[0]['native_hits'] = 100
        with tempfile.TemporaryDirectory() as temp:
            first, second, third = [Path(temp)/name for name in ('first', 'second', 'third')]
            # Identical provenance, as in the existing balanced-layout test.
            # Capture file order is intentionally part of its source hash.
            one = self.emit(first, items, capture_sha256='a'*64)
            two = self.emit(second, list(reversed(items)), capture_sha256='a'*64)
            self.assertEqual(one, two)
            self.assertEqual(files(first), files(second))
            self.emit(third, changed)
            self.assertEqual(parts(first), parts(third))
            self.assertEqual((first/'module.cpp').read_bytes(), (third/'module.cpp').read_bytes())
            self.assertEqual((first/'module_parts.hpp').read_bytes(),
                             (third/'module_parts.hpp').read_bytes())
            self.assertNotEqual((first/'module.json').read_bytes(), (third/'module.json').read_bytes())

    def test_source_guards_wrap_mpr_boundaries_and_never_include_global_header(self):
        items = [observation(0xffff, (0xa9, 29)), observation(0x5fff, (0xad, 0x11, 0x22)),
                 observation(0x4000, (0xa9, 42)), observation(0x4000, (0xa9, 43))]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'out'
            self.emit(out, items)
            entry = (out/'module.cpp').read_text()
            self.assertLess(entry.index('s.ticks >= deadline'), entry.index('switch(mapping)'))
            text = '\n'.join(data.decode() for data in parts(out).values())
            self.assertNotIn('interpret_step(', text)
            self.assertNotIn('#include "module_parts.hpp"', text)
            self.assertNotIn('captured_part_', text)
            for address in (8191, 2088960, 0x101fff, 0x102000, 0x102001):
                self.assertIn(f'bus.peek({address})', text)
            self.assertIn('case 42ULL:', text)
            self.assertIn('case 43ULL:', text)
            self.assertIn('if(!operand_0) return Exit::miss;', text)

    def test_stable_does_not_switch_to_single_unit_for_tiny_or_empty_capture(self):
        for items in ([], [observation()], [observation(raw=(0x0b,))]):
            with self.subTest(items=items), tempfile.TemporaryDirectory() as temp:
                out = Path(temp)/'out'
                manifest = self.emit(out, items)
                self.assertTrue(manifest['partitioned'])
                self.assertEqual(len(parts(out)), int(bool(items) and items[0]['data'][0] != 0x0b))
                self.assertEqual([entry['file'] for entry in manifest['generated_headers']],
                                 ['module_parts.hpp'])
                self.assertIn('default: return Exit::miss;', (out/'module.cpp').read_text())

    def test_variants_may_exceed_range_span_without_splitting(self):
        items = [observation(0x4000, (0xa9, value)) for value in range(256)]
        items += [observation(0x4000, (0xa2, 7))]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'out'
            manifest = self.emit(out, items)
            self.assertEqual(manifest['largest_partition_instructions'], 257)
            self.assertEqual(len(parts(out)), 1)
            self.assertEqual(manifest['native_instructions_emitted'], 257)

    def test_balanced_remains_byte_identical_when_explicitly_selected(self):
        items = [observation(0x4000+i, (0xea,)) for i in range(257)]
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp)/'first', Path(temp)/'second'
            report = capture(items, capacity=512)
            old = emit_capture(report, first)
            explicit = emit_capture(report, second, partition_layout='balanced')
            self.assertEqual(old, explicit)
            self.assertEqual(files(first), files(second))
            self.assertNotIn('partition_layout', old)
            self.assertNotIn('pc_bucket_size', old)

    def test_invalid_options_fail_before_creating_directory(self):
        for options in ({'partition_layout': None}, {'partition_layout': True},
                        {'partition_layout': 'unknown'}, {'partition_layout': 'stable', 'single_unit': True},
                        {'partition_layout': 'stable', 'partition_size': 128}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp:
                out = Path(temp)/'out'
                with self.assertRaises(ValueError):
                    emit_capture(capture(), out, **options)
                self.assertFalse(out.exists())

    def test_cli_stable_is_explicit_and_incompatible_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'capture.json'
            source.write_text(json.dumps(capture()))
            self.assertEqual(main(['emit-capture', str(source), '--out', str(root/'stable'),
                                   '--partition-layout', 'stable']), 0)
            manifest = json.loads((root/'stable'/'module.json').read_bytes())
            self.assertEqual(manifest['partition_layout'], 'stable')
            for name, extra in (('single', ['--single-unit']), ('size', ['--partition-size', '128'])):
                self.assertEqual(main(['emit-capture', str(source), '--out', str(root/name),
                                       '--partition-layout', 'stable', *extra]), 2)
                self.assertFalse((root/name).exists())


if __name__ == '__main__':
    unittest.main()
