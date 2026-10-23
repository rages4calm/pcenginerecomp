"""Boundaries of the authored, optional independent-reference adapter."""
import tempfile
from pathlib import Path
import unittest

from scripts.block_reference import initial_ram, measured_ticks, plans, write_plan
from generate_block_fixture import make_fixture


class BlockReferenceTests(unittest.TestCase):
    def test_matrix_covers_each_op_speed_flags_and_zero(self):
        matrix = plans()
        self.assertEqual(len({p['id'] for p in matrix}), len(matrix))
        self.assertEqual({p['op'] for p in matrix}, {0x73, 0xC3, 0xD3, 0xE3, 0xF3})
        for op in (0x73, 0xC3, 0xD3, 0xE3, 0xF3):
            selected = [p for p in matrix if p['op'] == op]
            self.assertEqual({p['divisor'] for p in selected}, {3, 12})
            self.assertEqual({p['p'] for p in selected}, {0, 255, 0x55, 0xAA})
            self.assertEqual(len([p for p in selected if p['length'] == 0]), 8)
            self.assertTrue(any(p['source'] == 0xFFFF for p in selected))
            self.assertTrue(any(p['destination'] == 0xFFFF for p in selected))
            self.assertTrue(any(p['id'].endswith('operand-stack-alias') for p in selected))

    def test_zero_tai_preserves_reference_opcode_cell(self):
        snapshot, _ = make_fixture()
        for plan in plans():
            if plan['op'] == 0xF3 and plan['length'] == 0:
                ram = initial_ram(snapshot, plan)
                self.assertEqual(ram[0x300:0x302], bytes((0xF3, 0xF3)))
                self.assertEqual(ram[plan['pc'] & 8191], 0xF3)
                self.assertTrue(plan['timing'])

    def test_probe_plan_has_finite_numeric_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.txt'
            for plan in plans():
                write_plan(path, plan)
                values = list(map(int, path.read_text().split()))
                self.assertEqual(values[:8], [plan[k] for k in ('index', 'seed', 'a', 'x', 'y', 'sp', 'p', 'divisor')])
                self.assertEqual(len(values), 9 + 2 * values[8])
                self.assertLessEqual(values[8], 32)

    def test_trace_requires_complete_monotonic_exact_pc_bank(self):
        trace = {'overrun': False, 'count': 2, 'lines': [
            '@100 CPU F8:2800 transfer', '@169 CPU F8:2700 nop']}
        self.assertEqual(measured_ticks(trace, 0x2800, 0x2700), 69)
        for bad in (trace | {'overrun': True}, trace | {'count': 3},
                    trace | {'lines': trace['lines'][:-1]},
                    trace | {'lines': [line.replace('F8:', 'F9:') for line in trace['lines']]},
                    trace | {'lines': [line.replace('@169', '@99') for line in trace['lines']]}):
            with self.assertRaises(RuntimeError):
                measured_ticks(bad, 0x2800, 0x2700)


if __name__ == '__main__':
    unittest.main()
