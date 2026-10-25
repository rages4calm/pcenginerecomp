"""Independent authored timer model and strict observation boundaries."""
import unittest
from scripts import timer_reference as r

class TimerReferenceTests(unittest.TestCase):
    def test_reset_phase_differs_from_disabled_after_transition(self):
        t=r.Timer();self.assertEqual(t.read(),127);t.write(0xC00,127);t.write(0xC01,2);t.advance(90000)
        self.assertEqual((t.read(),t.phase),(127,0));t.write(0xC00,0);t.write(0xC01,1);t.write(0xC01,0);t.advance(90000)
        self.assertEqual((t.read(),t.phase),(0,3072))
    def test_prediction_window_and_underflow(self):
        t=r.Timer();t.write(0xC01,1);t.advance(3056);self.assertEqual(t.read(),0)
        t.advance(1);self.assertEqual(t.read(),127);t.advance(15);self.assertEqual(t.state(),[1,0,0,1,0,3072])
    def test_same_control_and_reload_preserve_active_phase(self):
        t=r.Timer();t.write(0xC01,1);t.advance(3057);t.write(0xC01,255);t.write(0xC00,255)
        self.assertEqual(t.state(),[1,127,0,0,0,15]);t.advance(15);self.assertEqual(t.counter,127)
    def test_multiple_periods_and_ack(self):
        t=r.Timer();t.write(0xC00,1);t.write(0xC01,1);t.advance(3072*5)
        self.assertEqual(t.state(),[1,1,0,1,0,3072]);t.write(0x1402,255);t.write(0x1403,0)
        self.assertEqual(t.state(),[1,1,0,0,7,3072])
    def test_records_reject_boolean_or_missing(self):
        cases=[dict(operations=[('r',0),('q',0xC00)])]
        with self.assertRaisesRegex(ValueError,'count'):r.validate_records([],cases)
        with self.assertRaisesRegex(ValueError,'type/shape'):r.validate_records([dict(kind='read',values=[0xC00,True])],cases)
    def test_authored_rom_has_both_real_speed_operations(self):
        low,n=r.firmware(0);high,m=r.firmware(1)
        self.assertEqual((len(low),len(high)),(262144,262144));self.assertEqual((low[256],high[256]),(0x54,0xD4))
        self.assertEqual(m-n,384);self.assertIn(bytes.fromhex('AD 00 0C'),low);self.assertEqual(low[8190:8192],bytes((0,0xE1)))

if __name__=='__main__':unittest.main()
