"""Literal RAM geometry and per-derivation admission, without cached authority."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pcerecomp import overlay_snapshot as snapshots, overlays


MPR = [255, 248, 128, 129, 130, 131, 132, 0]


def machine(mode='standard'):
    if mode == 'payload':
        boot = dict(mode='payload', physical_load=0x100000, pc=0x4000, mpr=MPR.copy())
        assets = dict(payload='a' * 64)
    elif mode == 'hucard':
        boot = dict(mode='hucard-reset', profile='base', header='none', encoding='linear')
        assets = dict(cartridge='b' * 64)
    else:
        boot = dict(mode='system-card-reset', profile=mode)
        assets = dict(bios='c' * 64)
    return dict(format='pce-overlay-machine-1', schema=1, runtime_abi=29, boot=boot, assets=assets)


def snapshot(code, value=None, mapping=None):
    return SimpleNamespace(document={'machine': machine() if value is None else value},
        before={'host': {'cpu': {'mpr': MPR.copy() if mapping is None else mapping}}},
        regions=((0x100000, bytes(code)),))


class OverlayGeometryTests(unittest.TestCase):
    def test_literal_machine_banks_and_last_byte_boundaries(self):
        banks = {'hucard': {248}, 'payload': set(range(128, 136)) | {248},
                 'standard': set(range(128, 136)) | {248}, 'super': set(range(104, 136)) | {248}}
        for mode, allowed in banks.items():
            geometry = snapshots._ram_geometry(machine(mode))
            for bank in range(256):
                for address in (bank * 8192, bank * 8192 + 8191):
                    with self.subTest(mode=mode, address=address):
                        self.assertEqual(geometry.contains_byte(address), bank in allowed)
                        if bank in allowed:
                            self.assertEqual(geometry.ranges([(address, 1)]), [(address, 1)])
                        else:
                            with self.assertRaises(ValueError): geometry.ranges([(address, 1)])

    def test_cross_bank_edges_aliases_and_aggregate_constraints_stay_strict(self):
        standard, super_card = machine(), machine('super')
        self.assertEqual(snapshots.ram_ranges(standard, [(0x100000, 65536)]), [(0x100000, 65536)])
        self.assertEqual(snapshots.ram_ranges(super_card, [(0xFF000, 8192)]), [(0xFF000, 8192)])
        complete = [(0xD0000 + index * 65536, 65536) for index in range(4)] + [(0x1F0000, 8192)]
        self.assertEqual(snapshots.ram_ranges(super_card, complete), complete)
        for ranges in ([], [(0x10FFFF, 2)], [(0x1F1FFF, 2)], [(0x100000, 65537)],
                       [(0x1F2000, 1)], [(0x1F0000, 1), (0x100000, 1)],
                       [(0x100000, 2), (0x100001, 2)], [(True, 1)], [(0x100000, True)]):
            with self.subTest(ranges=ranges), self.assertRaises(ValueError): snapshots.ram_ranges(standard, ranges)
        geometry = snapshots._ram_geometry(standard)
        for bad in (-1, 0x200000, True, False, 0x1F0000 + .0, '2031616', None):
            self.assertFalse(geometry.contains_byte(bad))
        self.assertEqual(snapshots.canonical(0x1F7FFF), 0x1F1FFF)
        self.assertFalse(geometry.contains_byte(0x1F7FFF))
        self.assertTrue(geometry.contains_byte(snapshots.canonical(0x1F7FFF)))

    def test_bad_machine_never_acquires_geometry(self):
        for key, replacement in (('runtime_abi', True), ('runtime_abi', 30), ('schema', 1.0),
                                 ('format', 'wrong'), ('assets', {'bios': 'wrong'})):
            value = machine(); value[key] = replacement
            with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError): snapshots._ram_geometry(value)
        for boot in ({'mode': 'unknown'}, {'mode': 'system-card-reset', 'profile': 'arcade'},
                     {'mode': 'system-card-reset', 'profile': 'standard', 'arcade_card': 'duo'}):
            value = machine(); value['boot'] = boot
            with self.assertRaises(ValueError): snapshots._ram_geometry(value)

    def test_frozen_geometry_cannot_expand_with_mutating_dictionary(self):
        value = machine(); geometry = snapshots._ram_geometry(value)
        value['boot']['profile'] = 'super'
        self.assertFalse(geometry.contains_byte(0xD0000))
        with self.assertRaisesRegex(ValueError, 'machine changed'): geometry.revalidate(value)
        # A fresh public call must validate the new machine instead of reusing
        # object identity, old timestamps or a process-global cached bank set.
        self.assertEqual(snapshots.ram_ranges(value, [(0xD0000, 1)]), [(0xD0000, 1)])
        value['boot']['profile'] = 'invalid'
        with self.assertRaises(ValueError): snapshots.ram_ranges(value, [(0xD0000, 1)])
        with self.assertRaises(FrozenInstanceError): geometry._banks = frozenset({0x68})
        with self.assertRaises(AttributeError): geometry._banks.add(0x68)

    def test_non_geometry_machine_changes_and_type_changes_are_not_ignored(self):
        for mutate in (lambda value: value['assets'].__setitem__('bios', 'd' * 64),
                       lambda value: value.__setitem__('schema', True),
                       lambda value: value.__setitem__('schema', 1.0),
                       lambda value: value.__setitem__(1, 'unexpected')):
            value = machine(); geometry = snapshots._ram_geometry(value); mutate(value)
            with self.assertRaisesRegex(ValueError, 'machine changed'): geometry.revalidate(value)

    def test_write_barrier_reuses_one_validation_and_preserves_literal_frontier(self):
        # Unknown X enumerates all 256 legal zero-page RAM target bytes for
        # every indexed store. Code itself is in the distinct CD RAM region.
        code = bytes.fromhex('9D 00 20') * 12 + bytes.fromhex('4C 00 40')
        with patch.object(snapshots, 'validate_machine', wraps=snapshots.validate_machine) as validate:
            graph, instructions, roots = overlays._derive(snapshot(code), [0x4000], [(0x100000, len(code))], 1000, 10)
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(graph['summary'], {'states': 14, 'identities': 13, 'contexts': 1, 'unresolved': 0})
        self.assertEqual(len(instructions), 13); self.assertEqual(len(roots), 13)
        self.assertFalse(graph['unresolved']); self.assertEqual(len(graph['edges']), 14)
        # Repeated writing of source RAM still stops at the original barrier.
        code = bytes.fromhex('8D 00 40 EA')
        graph, instructions, _ = overlays._derive(snapshot(code), [0x4000], [(0x100000, len(code))], 100, 10)
        self.assertEqual(len(instructions), 1)
        self.assertEqual(graph['unresolved'][0]['reason'], 'possible_code_write')

    def test_machine_mutation_during_derivation_refuses_before_returning_graph(self):
        for mutate in (lambda value: value['boot'].__setitem__('profile', 'super'),
                       lambda value: value['assets'].__setitem__('bios', 'e' * 64),
                       lambda value: value.__setitem__('schema', 1.0)):
            value = machine(); original_decode = overlays.decode
            def changed_decode(*args):
                mutate(value)
                return original_decode(*args)
            with patch.object(overlays, 'decode', side_effect=changed_decode), self.assertRaisesRegex(ValueError, 'machine changed'):
                overlays._derive(snapshot(bytes.fromhex('80 FE'), value), [0x4000], [(0x100000, 2)], 100, 10)


if __name__ == '__main__': unittest.main()
