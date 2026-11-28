"""Authored vectors: authenticated byte witnesses and conservative write barriers."""
import json
import unittest

from pcerecomp import ram_cd_analysis as analysis
from pcerecomp.isa import decode, physical


MPR = (255, 248, 128, 129, 130, 131, 132, 0)


def canonical(pa):
    return 0x1F0000 + (pa & 8191) if 0x1F0000 <= pa < 0x1F8000 else pa


class VectorSource:
    def __init__(self, code, vectors=(), *, protected=()):
        self.raw = {}
        self.allowed_code = set()
        self.protected = {canonical(pa) for pa in protected}
        self.reads = []
        for address, text in code:
            for offset, byte in enumerate(bytes.fromhex(text)):
                pa = canonical(address + offset)
                self.raw[pa] = byte
                self.allowed_code.add(pa)
        for address, text in vectors:
            for offset, byte in enumerate(bytes.fromhex(text)):
                pa = canonical(address + offset)
                self.raw[pa] = byte
                self.protected.add(pa)
        self.allowed_code.difference_update(self.protected)

    def code(self, pa):
        return canonical(pa) in self.allowed_code

    def ram(self, pa):
        pa = canonical(pa)
        return 0x100000 <= pa < 0x110000 or 0x1F0000 <= pa < 0x1F2000

    def fetch(self, pc, mpr):
        def read(logical):
            pa = canonical(physical(logical, mpr))
            if pa not in self.allowed_code:
                raise ValueError('outside_allowed_code')
            return self.raw[pa]
        ins = decode(read, pc, mpr)
        return ins, [dict(source='authored-code', physical=canonical(pa)) for pa in ins.physical]

    def read_vector(self, logical, mpr):
        pa = canonical(physical(logical, mpr))
        self.reads.append((logical, tuple(mpr)))
        if pa not in self.protected or pa not in self.raw:
            raise ValueError('vector_byte_outside_authenticated_range')
        return self.raw[pa], dict(source='authored-vector', offset=pa)

    def run(self, *, entries=None, mapping=MPR, limit=100, vectors=True, **kwargs):
        options = dict(fetch=self.fetch, is_code=self.code, is_ram=self.ram,
            canonical=canonical, instruction_limit=limit, context_limit=16,
            call_depth_limit=8)
        if vectors:
            options.update(vector_jumps=True, read_vector_byte=self.read_vector,
                           is_vector=lambda pa: pa in self.protected)
        options.update(kwargs)
        return analysis.derive([0x4000] if entries is None else entries, mapping, **options)


class RamCdVectorTests(unittest.TestCase):
    def pcs(self, result):
        return {row['pc'] for row in result[1]}

    def reasons(self, result):
        return {row['reason'] for row in result[0]['unresolved']}

    def word(self, result):
        return next(row['vector_word'] for row in result[0]['edges'] if row['kind'] == 'vector_jump')

    def test_indirect_word_has_exact_mapping_and_authenticated_byte_witnesses(self):
        source = VectorSource([(0x100000, '6C 00 42'), (0x100010, 'A9 42 80 FE')],
                              [(0x100200, '10 40')])
        result = source.run()
        self.assertEqual(self.pcs(result), {0x4000, 0x4010, 0x4012})
        self.assertEqual(self.reasons(result), set())
        word = self.word(result)
        self.assertEqual((word['pc'], word['mpr'], word['mode'], word['base'],
                          word['index'], word['pointer'], word['target']),
                         (0x4000, list(MPR), 'ind', 0x4200, None, 0x4200, 0x4010))
        for side, logical, value in (('low', 0x4200, 0x10), ('high', 0x4201, 0x40)):
            self.assertEqual(word[side], dict(logical=logical, physical=0x100000+(logical&8191),
                canonical_physical=0x100000+(logical&8191), value=value,
                provenance=dict(source='authored-vector', offset=0x100000+(logical&8191))))
        self.assertEqual(source.reads, [(0x4200, MPR), (0x4201, MPR)])
        jump = next(row for row in result[1] if row['pc'] == 0x4000)
        self.assertIsNone(jump['target'])  # Analysis must not replace the runtime JMP.
        self.assertEqual(result, source.run())

    def test_known_x_selects_one_vector_without_enumerating_unknown_entries(self):
        source = VectorSource([(0x100000, 'A2 02 7C FE 41'), (0x100010, '80 FE')],
                              [(0x100200, '10 40')])
        result = source.run()
        self.assertEqual(self.pcs(result), {0x4000, 0x4002, 0x4010})
        self.assertEqual((self.word(result)['index'], self.word(result)['pointer']), (2, 0x4200))
        self.assertEqual([pc for pc, _ in source.reads], [0x4200, 0x4201])
        unknown = VectorSource([(0x100000, '7C 00 42')], [(0x100200, '10 40')])
        self.assertEqual(self.reasons(unknown.run()), {'unknown_vector_index'})
        self.assertEqual(unknown.reads, [])

    def test_stack_recovered_x_and_call_frame_survive_vector_transfer(self):
        source = VectorSource([(0x100000, '20 10 40 A9 77 80 FE'),
                               (0x100010, 'A2 02 DA A2 00 FA 7C FE 41'),
                               (0x100030, '60')], [(0x100200, '30 40')])
        result = source.run()
        self.assertEqual(self.pcs(result), {0x4000, 0x4010, 0x4012, 0x4013,
                         0x4015, 0x4016, 0x4030, 0x4003, 0x4005})
        self.assertEqual(self.word(result)['index'], 2)
        edge = next(row for row in result[0]['edges'] if row['kind'] == 'return')
        self.assertEqual(edge['target']['pc'], 0x4003)
        self.assertTrue(edge['return_word']['matched_call'])
        self.assertEqual(self.reasons(result), set())

    def test_high_byte_uses_full_increment_not_6502_page_wrap(self):
        source = VectorSource([(0x100000, '6C FF 42'), (0x100010, '80 FE')],
                              [(0x1002FF, '10 40'), (0x100200, 'FF')])
        result = source.run()
        self.assertEqual(self.word(result)['target'], 0x4010)
        self.assertEqual([pc for pc, _ in source.reads], [0x42FF, 0x4300])

    def test_pointer_and_high_byte_wrap_16bit_with_independent_mpr_mapping(self):
        mapping = (128, 248, 130, 131, 132, 133, 134, 129)
        for code, pointer, addresses in (('6C FF FF', 0xFFFF, (0x103FFF, 0x100000)),
                                         ('A2 01 7C FF FF', 0, (0x100000, 0x100001))):
            with self.subTest(code=code):
                source = VectorSource([(0x104000, code), (0x105010, '80 FE')],
                                      [(addresses[0], '10'), (addresses[1], '50')])
                result = source.run(mapping=mapping)
                self.assertIn(0x5010, self.pcs(result))
                word = self.word(result)
                self.assertEqual((word['pointer'], word['low']['physical'], word['high']['physical']),
                                 (pointer, *addresses))
                self.assertEqual([pc for pc, _ in source.reads], [pointer, (pointer+1)&65535])
        mapping = tuple(133 if i == 3 else bank for i, bank in enumerate(MPR))
        source = VectorSource([(0x100000, '6C FF 5F'), (0x10B000, '80 FE')],
                              [(0x101FFF, '00'), (0x10A000, '70')])
        word = self.word(source.run(mapping=mapping))
        self.assertEqual((word['low']['physical'], word['high']['physical'], word['target']),
                         (0x101FFF, 0x10A000, 0x7000))

    def test_tam_changes_mapping_before_vector_read_and_target_fetch(self):
        source = VectorSource([(0x100000, 'A9 81 53 08 6C 00 60'), (0x100010, '80 FE')],
                              [(0x102000, '10 40')])
        mapping = tuple(133 if i == 3 else bank for i, bank in enumerate(MPR))
        result = source.run(mapping=mapping)
        self.assertIn(0x4010, self.pcs(result))
        self.assertTrue(all(mpr[3] == 129 for _, mpr in source.reads))
        self.assertEqual(self.word(result)['mpr'][3], 129)

    def test_missing_or_unpermitted_byte_never_creates_a_target_edge(self):
        for protected in ((), (0x100201,)):
            with self.subTest(protected=protected):
                source = VectorSource([(0x100000, '6C 00 42')], [(0x100200, '10')],
                                      protected=protected)
                result = source.run()
                self.assertEqual(self.reasons(result), {'vector_read_unproven'})
                self.assertEqual(result[0]['edges'], [])
                frontier = result[0]['unresolved'][0]
                self.assertEqual(frontier['detail'], 'vector_byte_outside_authenticated_range')
                self.assertEqual(len(frontier['reads']), 1)
        source = VectorSource([(0x100000, '6C 00 42')], [(0x100200, '10 40')])
        for value, provenance in ((True, {'source': 'authored'}), (256, {'source': 'authored'}), (1, {})):
            with self.subTest(value=value, provenance=provenance):
                result = source.run(read_vector_byte=lambda *_: (value, provenance))
                self.assertEqual(self.reasons(result), {'vector_read_unproven'})
                self.assertEqual(result[0]['edges'], [])

    def test_resolved_destination_still_requires_normal_allowed_source_fetch(self):
        source = VectorSource([(0x100000, '6C 00 42')], [(0x100200, '00 45')])
        result = source.run()
        self.assertEqual(self.pcs(result), {0x4000})
        self.assertEqual(self.word(result)['target'], 0x4500)
        self.assertEqual(self.reasons(result), {'outside_allowed_code'})

    def test_vector_writes_stop_even_before_the_first_read_and_when_marked_data(self):
        for writer in ('8D 00 42', 'EE 00 42', '0C 00 42', '9D 00 42'):
            with self.subTest(writer=writer):
                source = VectorSource([(0x100000, writer+' 6C 00 42')], [(0x100200, '10 40')])
                result = source.run()
                self.assertEqual(self.reasons(result), {'possible_vector_write'})
                self.assertEqual(self.pcs(result), {0x4000})
                self.assertEqual(source.reads, [])
        source = VectorSource([(0x100000, '8D 00 43 6C 00 42'), (0x100010, '80 FE')],
                              [(0x100200, '10 40')])
        self.assertIn(0x4010, self.pcs(source.run()))  # Ordinary non-vector data remains writable.

    def test_alias_zero_page_t_mode_and_implicit_stack_writes_are_protected(self):
        cases = [('8D 02 60', 0x1F0002, 3), ('07 02', 0x1F0002, None),
                 ('F4 29 01', 0x1F0002, None), ('A2 02 F4 29 01', 0x1F0002, None),
                 ('69 01', 0x1F0002, None), ('48', 0x1F0102, None),
                 ('20 10 40', 0x1F01F0, None)]
        for code, address, alias in cases:
            with self.subTest(code=code):
                mapping = tuple(249 if i == alias else bank for i, bank in enumerate(MPR))
                source = VectorSource([(0x100000, code+' 00 00')], [(address, '10 40')])
                self.assertEqual(self.reasons(source.run(mapping=mapping)), {'possible_vector_write'})
                self.assertEqual(source.reads, [])
        source = VectorSource([(0x100000, 'EA 69 01 6C 02 20'), (0x100010, '80 FE')],
                              [(0x1F0002, '10 40')])
        self.assertIn(0x4010, self.pcs(source.run()))  # Known clear T does not invent a write.

    def test_indexed_write_wrap_cannot_bypass_vector_protection(self):
        mapping = (128, 248, 130, 131, 132, 133, 134, 129)
        source = VectorSource([(0x104000, 'A2 20 9D F0 FF')], [(0x100010, '10 50')])
        result = source.run(mapping=mapping)
        self.assertEqual(self.pcs(result), {0x4000, 0x4002})
        self.assertEqual(self.reasons(result), {'possible_vector_write'})
        self.assertEqual(source.reads, [])

    def test_unknown_writes_blocks_and_devices_keep_existing_frontiers(self):
        cases = [('91 02', 'unknown_write_target'),
                 ('73 00 20 00 42 01 00', 'block_transfer_changes_memory'),
                 ('03 00', 'opaque_device_write')]
        for code, reason in cases:
            with self.subTest(code=code):
                source = VectorSource([(0x100000, code)], [(0x100200, '10 40')])
                self.assertEqual(self.reasons(source.run()), {reason})
                self.assertEqual(source.reads, [])

    def test_legacy_stack_and_plain_graphs_have_no_new_fields_or_edges(self):
        source = VectorSource([(0x100000, '6C 00 42')], [(0x100200, '10 40')])
        for far in (False, True):
            with self.subTest(far=far):
                before = source.run(vectors=False, far_calls=far)
                explicit = source.run(vectors=False, far_calls=far, vector_jumps=False)
                self.assertEqual(before, explicit)
                self.assertEqual(self.reasons(before), {'indirect_jump'})
                self.assertNotIn('vector_word', json.dumps(before))
                self.assertEqual(source.reads, [])

    def test_policy_callbacks_and_limits_are_strict(self):
        source = VectorSource([(0x100000, '6C 00 42')], [(0x100200, '00 40')])
        for kwargs in (dict(vector_jumps=1), dict(vector_jumps=None),
                       dict(read_vector_byte=None), dict(is_vector=False), dict(call_depth_limit=None)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                source.run(**kwargs)
        with self.assertRaisesRegex(ValueError, 'explicit vector analysis'):
            source.run(vectors=False, read_vector_byte=source.read_vector)
        loop = source.run()
        self.assertEqual(len(loop[0]['nodes']), 2)  # Unknown initial T becomes clear.
        self.assertEqual(len(loop[0]['edges']), 2)
        limited = VectorSource([(0x100000, '6C 00 42'), (0x100010, '80 FE')],
                               [(0x100200, '10 40')]).run(limit=1)
        self.assertEqual(self.reasons(limited), {'state_limit'})
        self.assertEqual(self.pcs(limited), {0x4000})


if __name__ == '__main__':
    unittest.main()
