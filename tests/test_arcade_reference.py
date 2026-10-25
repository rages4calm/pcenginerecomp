"""Authored independent adapter/model boundary tests; no reference source data."""
import copy
import unittest
from scripts import arcade_reference as reference


class ArcadeReferenceTests(unittest.TestCase):
    def test_offset_negative_flag_is_not_int16_sign_extension(self):
        state=reference.LiteralState(0)
        state.ports[0]=[0,0x7FFF,0,10]
        self.assertEqual(state.effective(state.ports[0]),0x1F7FFF)
        state.ports[0][1]=0
        self.assertEqual(state.effective(state.ports[0]),0x1F0000)

    def test_read_uses_previous_address_and_advances_correct_destination(self):
        state=reference.LiteralState(0xA5)
        state.ports[2]=[0xFFFFFF,0,1,17]
        state.ram[0x1FFFFF]=0x6C
        self.assertEqual(state.data(2),0x6C)
        self.assertEqual(state.ports[2],[0,0,1,17])
        state.ports[2]=[0,0xFFFF,1,3]
        self.assertEqual(state.data(2),0xA5)
        self.assertEqual(state.ports[2],[0,0,1,3])

    def test_trigger_and_control_bit2_readback(self):
        state=reference.LiteralState(0)
        state.ports[1]=[1,0,0,0x2C]
        state.register(0x1A15,2)
        self.assertEqual(state.ports[1],[0xFF0003,2,0,0x2C])
        state.register(0x1A16,0x80)
        self.assertEqual(state.ports[1][0],0xFF0003)
        self.assertEqual(state.register(0x1A59),0x2C)
        self.assertEqual(state.register(0x1A1A),0)

    def test_rotate_and_hole_identity_literals(self):
        state=reference.LiteralState(0)
        state.value=0x80000001
        state.register(0x1AE5,0xFF)
        self.assertEqual((state.value,state.rotate),(0xC0000000,15))
        self.assertEqual([state.register(x)for x in range(0x1AFC,0x1B00)],[0,0,16,81])
        state.register(0x1AF0,0xAB)
        self.assertEqual(state.register(0x1AF0),255)
        self.assertEqual(state.value,0xC0000000)

    def test_typed_records_reject_bool_and_missing_observations(self):
        cases=[dict(operations=[('r',0),('q',255,0x1AFF)])]
        actual=[dict(kind='memory',values=[255,0x1AFF,81])]
        self.assertEqual(reference.expected_records(actual,cases,bytes(262144)),1)
        bad=copy.deepcopy(actual);bad[0]['values'][2]=True
        with self.assertRaisesRegex(ValueError,'type/shape'):reference.validate_records(bad,cases)
        with self.assertRaisesRegex(ValueError,'count'):reference.validate_records([],cases)

    def test_guest_is_bounded_and_uses_real_block_operations(self):
        image,count=reference.firmware()
        self.assertEqual(len(image),262144)
        self.assertEqual(image[8190:8192],bytes((0,0xE1)))
        self.assertGreater(count,100)
        self.assertIn(bytes.fromhex('73 08 20 00 40 04 00'),image[:8190])
        self.assertIn(bytes.fromhex('73 00 60 20 20 04 00'),image[:8190])


if __name__=='__main__':unittest.main()
