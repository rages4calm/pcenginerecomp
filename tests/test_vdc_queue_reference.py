import unittest
from scripts.vdc_queue_reference import firmware,plans,serialize,slot_literal,validate_records,compare_gear

class VdcQueueReferenceTests(unittest.TestCase):
    def test_synthetic_slot_matrix_is_finite(self):
        cases=plans();self.assertEqual(len(cases),615)
        self.assertEqual(sum(c['id'].startswith('actual-cpu')for c in cases),6)
        self.assertIn('q 1',serialize(cases))
    def test_authored_rom_and_reset_vector(self):
        raw,ops=firmware();self.assertEqual(len(raw),262144);self.assertEqual(raw[8190:8192],b'\0\xe1');self.assertGreater(len(ops),40)
    def test_blank_and_hsync_literal_slots(self):
        self.assertEqual(slot_literal(('f',96,0,1,0,0,0,0,1365,0,0),0),1)
        self.assertEqual(slot_literal(('f',100,0,1,0,0,0,0,1365,0,0),0),0)
        self.assertEqual(slot_literal(('f',0,0,3,0,0,0,0,1365,0,0),0),0)
    def test_background_modes_and_sprite_window(self):
        self.assertEqual(slot_literal(('f',12,1,1,0,0,0,0,0,1365,0),0),1)
        self.assertEqual(slot_literal(('f',12,1,1,0,3,0,0,0,1365,0),0),0)
        self.assertEqual(slot_literal(('f',4,1,1,0,0,64,2,1365,0,0),0),0)
    def test_invalid_records_reject_boolean_numbers(self):
        with self.assertRaises(ValueError):validate_records([{'kind':'slot','values':[True]}],[{'operations':[('j',3)]}])
    def test_projection_is_restricted_to_named_bus_field_and_has_literal(self):
        case=[dict(id='active-background-0-3',operations=[('s',)])]
        a=dict(kind='device',values=[0]*37);a['values'][11]=44520
        b=dict(kind='device',values=list(a['values']));b['values'][11]=23374
        self.assertEqual(compare_gear([a],[b],case)[0]['field'],'vram_bus_latch')
        b['values'][5]=1
        with self.assertRaises(ValueError):compare_gear([a],[b],case)
        b['values'][5]=0;a['values'][11]=23374
        with self.assertRaises(ValueError):compare_gear([a],[b],case)
