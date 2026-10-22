import unittest

from generate_fixture import MPR_DEFAULT, MPR_RESET, make_fixture, mpr_cases
from scripts.mpr_reference import plans


class MprReferenceTests(unittest.TestCase):
    def test_mask_coverage_and_resident_execution(self):
        sequences = plans()
        self.assertEqual(len(sequences), 524)
        self.assertEqual(sum(len(p["steps"]) for p in sequences), 1614)
        self.assertEqual(len({p["id"] for p in sequences}), len(sequences))
        instructions = {pc: (op,mask) for pc,op,mask in mpr_cases(True)}
        for op,name in ((0x43,"tma"),(0x53,"tam")):
            tested = [instructions[p["steps"][0][0]] for p in sequences if p["id"].startswith(name+"-")]
            self.assertEqual(tested, [(op,mask) for mask in range(256)])
        for plan in sequences:
            self.assertLessEqual(len(plan["steps"]),16)
            self.assertEqual(instructions[plan["steps"][-1][0]], (0x43,0))
            for pc,value in plan["steps"]:
                self.assertEqual(pc>>13,1)  # all instruction fetches remain in work RAM
                if pc in instructions:
                    op,mask = instructions[pc]
                    if op==0x53 and mask&2:
                        self.assertEqual(value,0xF8)

    def test_reference_reset_and_shards(self):
        snapshot,_ = make_fixture(oracle=True)
        self.assertEqual(bytes(snapshot.memory[0x1F0700+i] for i in range(32)), MPR_RESET)
        self.assertEqual(MPR_RESET[-4:], bytes((0xA9,0,0x53,0x80)))
        self.assertEqual(tuple(MPR_RESET[1::4]),MPR_DEFAULT)
        sequences = plans()
        shards = [sequences[i::4] for i in range(4)]
        self.assertEqual([len(s) for s in shards],[131]*4)
        self.assertEqual(len({p["id"] for shard in shards for p in shard}),524)


if __name__ == "__main__":
    unittest.main()
