"""Safety/clock expectations for the optional live raster oracle adapter."""
import unittest

from scripts.raster_reference import delay_program, plans


class RasterReferenceTests(unittest.TestCase):
    def test_delay_literal_cpu_cycle_counts(self):
        # Independently decode only this authored loop vocabulary. Branch
        # costs are HuC6280 two/taken-four, not MOS6502 page-cross timing.
        for ticks in (6, 12, 96, 1362, 4608, 4626, 357630, 715260):
            code = delay_program(ticks)
            pc = x = y = cycles = steps = 0
            while pc < len(code):
                op = code[pc]
                if op == 0xEA:
                    pc += 1; cycles += 2
                elif op in (0xA0, 0xA2):
                    if op == 0xA0: y = code[pc + 1]
                    else: x = code[pc + 1]
                    pc += 2; cycles += 2
                elif op in (0xCA, 0x88):
                    if op == 0xCA: x = (x - 1) & 255
                    else: y = (y - 1) & 255
                    pc += 1; cycles += 2
                elif op == 0xD0:
                    value = x if code[pc + 1] == 0xFD else y
                    delta = code[pc + 1] - 256
                    pc += 2
                    if value: pc += delta; cycles += 4
                    else: cycles += 2
                else:
                    self.fail(f"Unexpected authored opcode {op:02x}")
                steps += 1
                self.assertLess(steps, 200000)
            self.assertEqual(cycles * 3, ticks)
            self.assertLess(len(code), 800)

    def test_invalid_or_unbounded_delay_refused(self):
        for value in (-6, 1, 3, 2 * 1365 * 263 + 6):
            with self.assertRaises(ValueError): delay_program(value)
        with self.assertRaises(ValueError): delay_program(12, 4)

    def test_matrix_has_gating_and_programmed_timings(self):
        matrix = plans()
        self.assertEqual(len(matrix), 15)
        self.assertEqual(len({p["id"] for p in matrix}), 15)
        self.assertEqual({p["registers"][5] for p in matrix}, {0, 12, 140})
        self.assertIn(511, {p["registers"][13] for p in matrix})
        for plan in matrix:
            self.assertEqual(plan["times"], sorted(set(plan["times"])))
            self.assertTrue(all(t >= 24 and (t - 24) % 6 == 0 for t in plan["times"]))
            self.assertLess(max(plan["times"]), 2 * 1365 * 262 + 1365)


if __name__ == "__main__": unittest.main()
