"""Authored mutable-source fixtures with literal independent reachability."""
import unittest

from pcerecomp.isa import decode, physical
from pcerecomp.ram_cd_analysis import derive


MPR = (255, 248, 128, 129, 130, 131, 132, 0)


def canonical(pa):
    return 0x1F0000 + (pa & 8191) if 0x1F0000 <= pa < 0x1F8000 else pa


class Source:
    def __init__(self, chunks, *, code_extra=()):
        self.raw = {}
        for address, data in chunks:
            for offset, value in enumerate(bytes.fromhex(data)):
                self.raw[canonical(address + offset)] = value
        self.code_extra = set(code_extra)

    def code(self, pa):
        return canonical(pa) in self.raw or canonical(pa) in self.code_extra

    def ram(self, pa):
        pa = canonical(pa)
        return 0x100000 <= pa < 0x110000 or 0x1F0000 <= pa < 0x1F2000

    def fetch(self, pc, mpr):
        locations = []

        def read(logical):
            address = canonical(physical(logical, mpr))
            if address not in self.raw:
                raise ValueError('outside_allowed_code')
            return self.raw[address]

        ins = decode(read, pc, mpr)
        for pa in ins.physical:
            locations.append(dict(authored_offset=canonical(pa)))
        return ins, locations

    def run(self, *, entries=None, mapping=MPR, depth=8, limit=100, contexts=16):
        return derive([0x4000] if entries is None else entries, mapping,
                      fetch=self.fetch, is_code=self.code, is_ram=self.ram,
                      canonical=canonical, instruction_limit=limit,
                      context_limit=contexts, call_depth_limit=depth)


class RamCdAnalysisTests(unittest.TestCase):
    def pcs(self, result):
        return {r['pc'] for r in result[1]}

    def reasons(self, result):
        return {r['reason'] for r in result[0]['unresolved']}

    def test_nested_jsr_bsr_and_balanced_pushes(self):
        source = Source([(0x100000, '20 10 40 00 00'),
                         (0x100010, '48 DA 5A 08 28 7A FA 68 44 06 A9 42 60'),
                         (0x100020, 'A2 03 60')])
        result = source.run()
        self.assertEqual(self.pcs(result), {0x4000, 0x4003, 0x4010, 0x4011,
                         0x4012, 0x4013, 0x4014, 0x4015, 0x4016, 0x4017,
                         0x4018, 0x401A, 0x401C, 0x4020, 0x4022})
        continuation = next(n for n in result[0]['nodes'] if n['pc'] == 0x4003)
        self.assertEqual(continuation['registers'], [0x42, 3, None])
        self.assertEqual((continuation['frames'], continuation['stack_depth']), ([], 0))
        self.assertEqual(self.reasons(result), {'interrupt_vector'})
        self.assertEqual(result, source.run())

    def test_callee_mapping_is_used_for_return(self):
        source = Source([(0x100000, '20 10 40 0B'),
                         (0x100010, 'A9 81 53 04'),
                         (0x102014, 'A9 55 60'),
                         (0x102003, '00 00')])
        result = source.run()
        self.assertEqual(self.pcs(result), {0x4000, 0x4010, 0x4012, 0x4014, 0x4016, 0x4003})
        node = next(n for n in result[0]['nodes'] if n['pc'] == 0x4003)
        self.assertEqual(node['mpr'][2], 129)
        self.assertEqual(node['registers'][0], 0x55)
        self.assertEqual(self.reasons(result), {'interrupt_vector'})

    def test_unproven_calls_do_not_fabricate_continuation(self):
        source = Source([(0x100000, '20 10 40 A9 FF'), (0x100010, '60')])
        result = source.run(depth=None)
        self.assertEqual(self.pcs(result), {0x4000, 0x4010})
        self.assertEqual(self.reasons(result), {'return_continuation_unproven', 'dynamic_return'})
        result = source.run(entries=[0x4010])
        self.assertEqual(self.reasons(result), {'dynamic_return'})

    def test_stack_corruption_unbalanced_pop_and_txs_stop(self):
        cases = [('8D 00 21', 'stack_write_barrier'),
                 ('8D 00 61', 'stack_write_barrier'),
                 ('68', 'stack_return_word_pop'), ('48 60', 'unbalanced_return_stack'),
                 ('9A', 'stack_pointer_write_barrier'),
                 ('A9 80 53 02', 'unsupported_stack_mapping')]
        for code, reason in cases:
            with self.subTest(code=code):
                # MPR3 mirrors the stack physically; direct aliases must stop.
                mapping = list(MPR); mapping[3] = 249
                source = Source([(0x100000, '20 10 40 A9 FF'), (0x100010, code)])
                result = source.run(mapping=mapping)
                self.assertIn(reason, self.reasons(result))
                self.assertNotIn(0x4003, self.pcs(result))

    def test_stack_mirror_remap_is_safe(self):
        result = Source([(0x100000, '20 10 40 00 00'),
                         (0x100010, 'A9 FB 53 02 60')]).run()
        self.assertIn(0x4003, self.pcs(result))
        node = next(n for n in result[0]['nodes'] if n['pc'] == 0x4003)
        self.assertEqual(node['mpr'][1], 251)

    def test_recursive_depth_is_explicit_and_bounded(self):
        result = Source([(0x100000, '20 00 40')]).run(depth=3)
        self.assertEqual(len(result[0]['nodes']), 4)
        self.assertEqual(self.reasons(result), {'call_depth_limit'})

    def test_stack_capacity_unknown_pop_and_mapping_context_budget(self):
        # 254 pushes plus a return word exactly fill the circular stack page;
        # the next push would overwrite a potentially live byte.
        code = '48 ' * 254 + '20 10 42'
        source = Source([(0x100000, code), (0x100210, '48')])
        result = source.run(limit=300)
        self.assertEqual(self.reasons(result), {'stack_depth_limit'})
        self.assertEqual(len(result[0]['nodes']), 256)
        self.assertEqual(self.reasons(Source([(0x100000, '68')]).run()), {'unproven_stack_pop'})
        source = Source([(0x100000, 'A9 81 53 04'), (0x102004, '00 00')])
        result = source.run(contexts=1)
        self.assertEqual(self.pcs(result), {0x4000, 0x4002})
        self.assertEqual(self.reasons(result), {'context_limit'})
        target = result[0]['unresolved'][0]['target']
        self.assertEqual((target['pc'], target['mpr'][2]), (0x4004, 129))

    def test_mutable_data_store_continues_but_code_store_stops(self):
        source = Source([(0x100000, 'A9 42 8D 00 20 AD 00 20 53 04')])
        result = source.run()
        self.assertEqual(self.pcs(result), {0x4000, 0x4002, 0x4005, 0x4008})
        self.assertEqual(self.reasons(result), {'unknown_mapping_value'})
        self.assertIsNone(result[0]['nodes'][-1]['registers'][0])
        source = Source([(0x100000, '8D 03 40 EA')])
        self.assertEqual(self.reasons(source.run()), {'possible_code_write'})
        source = Source([(0x100000, '48 60')], code_extra=[0x1F0100])
        self.assertEqual(self.reasons(source.run()), {'possible_code_write'})

    def test_unknown_index_and_t_mode_are_conservative(self):
        cases = [('91 00', 'unknown_write_target'),
                 ('9D 00 40', 'possible_code_write'),
                 ('8D 00 18', 'write_not_proven_ram'),
                 ('03 00', 'opaque_device_write'),
                 ('73 00 20 00 30 01 00', 'block_transfer_changes_memory'),
                 ('6C 00 20', 'indirect_jump'), ('40', 'interrupt_return')]
        for code, reason in cases:
            with self.subTest(code=code):
                self.assertEqual(self.reasons(Source([(0x100000, code)]).run()), {reason})
        # Unknown initial T or explicit SET may write zero page through X.
        for code in ('69 01', 'F4 69 01', 'A2 03 F4 29 01'):
            result = Source([(0x100000, code)], code_extra=[0x1F0003]).run()
            self.assertIn('possible_code_write', self.reasons(result))
        result = Source([(0x100000, 'EA 69 01 00 00')], code_extra=[0x1F0003]).run()
        self.assertEqual(self.reasons(result), {'interrupt_vector'})

    def test_fetch_boundaries_budgets_and_invalid_parameters(self):
        with self.assertRaises(ValueError):
            Source([(0x100000, 'A9')]).run()
        result = Source([(0x100000, 'EA A9')]).run()
        self.assertEqual(self.pcs(result), {0x4000})
        self.assertEqual(self.reasons(result), {'outside_allowed_code'})
        result = Source([(0x100000, 'EA EA EA')]).run(limit=1)
        self.assertEqual(self.reasons(result), {'state_limit'})
        source = Source([(0x100000, 'EA')])
        for options in (dict(depth=True), dict(depth=65), dict(limit=True),
                        dict(contexts=True), dict(entries=[True]), dict(entries=[0x4000, 0x4000])):
            with self.subTest(options=options), self.assertRaises(ValueError):
                source.run(**options)


if __name__ == '__main__':
    unittest.main()
