import unittest

from scripts.speed_reference import plans, timing, trace_deltas


class SpeedReferenceTests(unittest.TestCase):
    def test_transition_and_sequence_coverage(self):
        sequences=plans()
        self.assertEqual(len(sequences),24)
        self.assertEqual(sum(len(p["steps"]) for p in sequences),120)
        self.assertEqual(len({p["id"] for p in sequences}),24)
        singles=[p for p in sequences if len(p["steps"])==3]
        self.assertEqual({(p["divisor"],p["steps"][0][1],p["p"]) for p in singles},
                         {(d,op,p) for d in (3,12) for op in (0x54,0xD4) for p in (0,255,0x55,0xAA)})
        mismatches=0
        for plan in sequences:
            old=plan["divisor"]
            self.assertLessEqual(len(plan["steps"]),16)
            self.assertEqual(plan["steps"][-1][1],0x43)
            for pc,op in plan["steps"]:
                self.assertEqual(pc>>13,1)
                new,cycles,split,oracle=timing(op,old)
                self.assertGreater(cycles,0)
                if split!=oracle:
                    self.assertIn(op,(0x54,0xD4)); self.assertNotEqual(old,new)
                    mismatches+=1
                old=new
        self.assertEqual(mismatches,28)

    def test_trace_rejects_missing_stale_or_invalid_entries(self):
        trace={"count":3,"overrun":False,"lines":[
            "@000000000192          F8:2800 A:80 ??? 54",
            "@000000000228 +36      F8:2801 A:80 NOP EA",
            "@000000000252 +24      F8:2802 A:80 CSH D4"]}
        self.assertEqual(trace_deltas(trace,[0x2800,0x2801,0x2802]),[36,24])
        for patch in ({"count":2},{"overrun":True},{"lines":[]},
                      {"lines":[trace["lines"][0]]*3},
                      {"lines":[trace["lines"][0].replace("F8:","00:")]+trace["lines"][1:]}):
            with self.assertRaises(RuntimeError):
                trace_deltas(trace|patch,[0x2800,0x2801,0x2802])
        with self.assertRaises(RuntimeError):
            trace_deltas(trace,[0x2801,0x2800,0x2802])


if __name__=="__main__":
    unittest.main()
