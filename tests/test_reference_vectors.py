"""Coverage checks for the authored independent-reference input matrix."""
import unittest

from pcerecomp.isa import BIT_OPCODES, STACK_OPCODES, DATA_OPCODES, RMW_OPCODES, INDIRECT_JUMP_OPCODES, TEST_OPCODES, BIT_BRANCH_OPCODES, _ROWS
from scripts.reference_geargrafx import vectors_for_opcode, patches_for_vector


class ReferenceVectorTests(unittest.TestCase):
    def test_bit_branch_both_outcomes_and_test_memory(self):
        for op in BIT_BRANCH_OPCODES:
            vectors=vectors_for_opcode(op)
            self.assertEqual(len(vectors),16)
            bit=1<<((op>>4)&7)
            self.assertEqual({bool(v["operand"]&bit) for v in vectors},{False,True})
            self.assertTrue(all(patches_for_vector(op,v)==[(255,v["operand"])] for v in vectors))
        for op in TEST_OPCODES:
            for v in vectors_for_opcode(op):
                self.assertEqual(len(patches_for_vector(op,v)),0 if op==0x89 else 1)
        self.assertEqual({v["sp"] for v in vectors_for_opcode(0x44)},{0,1,254,255})
    def test_rmw_edge_values_each_with_both_carries(self):
        for op in RMW_OPCODES:
            vectors = vectors_for_opcode(op)
            self.assertEqual(len(vectors), 16)
            self.assertEqual({(v["operand"], v["flags"]&1) for v in vectors},
                             {(value, carry) for value in (0, 1, 2, 0x7F, 0x80, 0x81, 0xFE, 0xFF) for carry in (0, 1)})
            self.assertEqual({bool(v["flags"]&0x20) for v in vectors}, {False, True})
            mode = _ROWS[op].split(".")[1]
            for v in vectors:
                patches = patches_for_vector(op, v)
                self.assertEqual(len(patches), 0 if mode in ("imp", "acc") else 1)
                self.assertTrue(all(0 <= offset < 0x400 for offset, _ in patches))

    def test_jump_pointer_bytes_are_consecutive(self):
        for op in INDIRECT_JUMP_OPCODES:
            vectors = vectors_for_opcode(op)
            self.assertEqual({v["x"] for v in vectors}, {0, 1, 0xE0, 0xFF})
            for v in vectors:
                patches = patches_for_vector(op, v)
                pointer = 0x2FF + (v["x"] if op==0x7C else 0)
                self.assertEqual(patches, [(pointer,v["target"]&255), (pointer+1,v["target"]>>8)])

    def test_data_carry_decimal_transfer_overflow_combinations(self):
        for op in DATA_OPCODES:
            vectors = vectors_for_opcode(op)
            self.assertEqual(len(vectors), 16)
            self.assertEqual({v["flags"] & 0x69 for v in vectors},
                             {c|d|t|o for c in (0, 1) for d in (0, 8) for t in (0, 32) for o in (0, 64)})
            self.assertTrue({0, 0x7F, 0x80, 0x99, 0xFF, 0xFA} <= {v["operand"] for v in vectors})

    def test_data_pointer_wrap_and_mapped_targets(self):
        for op in DATA_OPCODES:
            mode = _ROWS[op].split(".")[1]
            for vector in vectors_for_opcode(op):
                patches = dict(patches_for_vector(op, vector))
                self.assertTrue(all(0 <= offset < 0x1000 for offset in patches))
                if mode in ("idx", "idy", "zpi"):
                    pointer = (255+vector["x"])&255 if mode=="idx" else 255
                    self.assertEqual((patches[pointer], patches[(pointer+1)&255]), (255, 0x22))

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
