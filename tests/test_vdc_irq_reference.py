import unittest
from scripts.vdc_irq_reference import firmware,plans,validate_records


class VdcIrqReferenceTests(unittest.TestCase):
    def test_authored_image_and_vectors(self):
        image=firmware()
        self.assertEqual(len(image),262144)
        self.assertEqual(image[0x1FFA:0x1FFC],b'\x00\xe4')
        self.assertEqual(image[0x1FFE:0x2000],b'\x00\xe3')
        self.assertEqual(image[0x400],0x48)
        self.assertEqual(image[0x40D],0x40)

    def test_finite_cross_product(self):
        cases=plans()
        self.assertEqual(len(cases),54)
        self.assertEqual(len({c['id']for c in cases}),54)
        self.assertEqual({c['phase']for c in cases},{18,30,60})
        self.assertEqual(sum(c['operations'][2][1]for c in cases),1188)

    def test_underflow_is_after_both_fixed_read_preludes(self):
        for case in plans():
            self.assertGreater(case['phase'],3 if case['fast']else 12)

    def test_invalid_observation_is_rejected(self):
        with self.assertRaises(ValueError):validate_records([],plans())

