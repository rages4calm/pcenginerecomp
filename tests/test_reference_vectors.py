"""Coverage checks for the authored independent-reference input matrix."""
import unittest

from pcerecomp.isa import BIT_OPCODES, STACK_OPCODES
from scripts.reference_geargrafx import vectors_for_opcode


class ReferenceVectorTests(unittest.TestCase):
    def test_each_bit_has_both_original_states(self):
        for opcode in BIT_OPCODES:
            with self.subTest(opcode=opcode):
                vectors = vectors_for_opcode(opcode)
                bit = (opcode >> 4) & 7
                self.assertEqual({(v["patch"][1] >> bit) & 1 for v in vectors}, {0, 1})
                self.assertEqual({v["patch"][0] for v in vectors}, {0x20})
                self.assertEqual({bool(v["flags"] & 0x20) for v in vectors}, {False, True})

    def test_stack_values_and_wrap_boundaries(self):
        for opcode in STACK_OPCODES:
            with self.subTest(opcode=opcode):
                vectors = vectors_for_opcode(opcode)
                self.assertEqual({v["sp"] for v in vectors}, {0, 1, 254, 255})
                if opcode in (0x48, 0x5A, 0xDA):
                    register = {0x48: "a", 0x5A: "y", 0xDA: "x"}[opcode]
                    self.assertTrue({0, 0x7F, 0x80, 0xFF} <= {v[register] for v in vectors})
                elif opcode in (0x28, 0x68, 0x7A, 0xFA):
                    self.assertTrue({0, 0x7F, 0x80, 0xFF} <= {v["patch"][1] for v in vectors})
                    for vector in vectors:
                        self.assertEqual(vector["patch"][0], 0x100 + ((vector["sp"]+1) & 255))

    def test_plp_checks_each_saved_break_transfer_combination(self):
        combinations = {(bool(v["patch"][1] & 0x10), bool(v["patch"][1] & 0x20))
                        for v in vectors_for_opcode(0x28)}
        self.assertEqual(combinations, {(False, False), (False, True), (True, False), (True, True)})


if __name__ == "__main__":
    unittest.main()
