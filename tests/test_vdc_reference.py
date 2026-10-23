import unittest

from generate_vdc_fixture import make_fixture, MPR_VDC
from scripts.vdc_reference import plans, vdc_state


class VdcReferenceTests(unittest.TestCase):
    def test_bounded_authored_sequences_cover_selectors_and_vram_boundaries(self):
        snapshot, cases = make_fixture()
        sites = {pc: (op, value) for pc, op, value in cases}
        sequences = plans()
        self.assertEqual(snapshot.mpr, MPR_VDC)
        self.assertNotEqual(snapshot.mpr[0], 255)
        self.assertEqual(snapshot.mpr[5], 255)
        self.assertEqual(len(sequences), 48)
        self.assertEqual(len({p["id"] for p in sequences}), 48)
        self.assertEqual(sum(len(p["steps"]) for p in sequences), 856)
        self.assertEqual({p["id"] for p in sequences[:32]}, {f"selector-{i:02x}" for i in range(32)})
        self.assertEqual({p["id"] for p in sequences[32:]},
                         {f"vram-inc-{i}-address-{a:04x}" for i in range(4) for a in (0, 0x7FFF, 0x8000, 0xFFFF)})
        used = set()
        for plan in sequences:
            self.assertTrue(1 <= len(plan["steps"]) <= 128)
            for pc, value in plan["steps"]:
                self.assertEqual(pc >> 13, 1)
                self.assertTrue(-1 <= value <= 255)
                used.add(sites[pc])
        self.assertTrue({(0xAD, a) for a in (0xA001, 0xA002, 0xA003, 0xA3FD, 0xA3FE, 0xA3FF)} <= used)
        self.assertFalse({(0xAD, 0xA000), (0xAD, 0xA3FC)} & used)
        self.assertTrue({(0x8D, a) for a in (0xA002, 0xA003, 0xA3FC, 0xA3FD, 0xA3FE, 0xA3FF)} <= used)
        self.assertEqual([len(sequences[i::4]) for i in range(4)], [12] * 4)

    def test_live_scope_excludes_dma_and_display_or_irq_enabling(self):
        _, cases = make_fixture()
        sites = {pc: (op, value) for pc, op, value in cases}
        for plan in plans():
            selected = 0
            for pc, override in plan["steps"]:
                op, operand = sites[pc]
                if op == 3:
                    selected = operand & 31
                    continue
                if op == 0x8D and operand & 3 == 0:
                    selected = override & 31
                    continue
                port = 2 if op == 19 else 3 if op == 35 else operand & 3 if op == 0x8D else -1
                value = operand if op in (19, 35) else override
                if port == 3:
                    self.assertNotIn(selected, (18, 19))
                if selected == 5 and port == 2:
                    self.assertEqual(value & 0xCF, 0)
                if selected == 15 and port == 2:
                    self.assertEqual(value & 0x13, 0)

    def test_debugger_register_parser_is_strict_and_has_no_status_read(self):
        response = {"registers": [[i, f"{i * 257:04X}"] for i in range(20)] + [["AR", "001F"], ["SR", "0040"]]}
        self.assertEqual(vdc_state(response), {"selected": 31, "registers": [i * 257 for i in range(20)]})
        for rows in (response["registers"][:-1], list(reversed(response["registers"]))):
            with self.assertRaises(RuntimeError):
                vdc_state({"registers": rows})


if __name__ == "__main__":
    unittest.main()
