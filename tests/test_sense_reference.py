"""Authored fixed NEC payload/lifecycle and strict reference-model boundaries."""
import copy
import unittest
from scripts import sense_reference as r

class SenseReferenceTests(unittest.TestCase):
    def test_fixed_nec_response_has_only_declared_fields(self):
        self.assertEqual(r.sense_bytes([3,0x11,5,0]),[0x70,0,3,0,0,0,0,10,0,0,0,0,0x11,5,0,0,0,0])
    def test_all_allocation_values_remain_eighteen_bytes(self):
        case=r.plans()[-1];actual=r.expected([case],'beetle')
        self.assertEqual(len(actual),256)
        self.assertEqual({len(row['data'])for row in actual},{18})
        self.assertEqual([row['cdb'][4]for row in actual],list(range(256)))
    def test_lifetime_preserves_success_and_reset_consumes_on_sense(self):
        case=[dict(operations=[('r',2),r.command(8,1),('z',),r.command(0),('p',),('b',),('p',)])]
        result=r.expected(case,'beetle')
        self.assertEqual(result[2],dict(kind='pending',values=[3,0x1D,0,0]))
        self.assertEqual(result[3],dict(kind='pending',values=[0,0,0,0]))
    def test_read_failure_categories_and_prefix_are_distinct(self):
        cases=[dict(operations=[('r',1),r.command(8,2,19),r.command(3),('r',3),r.command(8,1),r.command(3),('r',4),r.command(8,1),r.command(3)])]
        rows=r.expected(cases,'beetle');self.assertEqual(len(rows[0]['data']),2048)
        self.assertEqual(rows[0]['data'][:3],[19,20,21])
        self.assertEqual([rows[n]['data'][12:14]for n in (1,3,5)],[[0x25,0],[0,0],[0x11,5]])
    def test_known_gear_disagreement_is_not_parity_or_type_coercion(self):
        gear=r.expected(r.stub_plan(),'gear');nec=r.expected(r.stub_plan(),'tool')
        self.assertEqual([len(row['data'])for row in gear],[0]*4);self.assertEqual([len(row['data'])for row in nec],[18]*4)
        bad=copy.deepcopy(nec);bad[0]['data'][0]=True
        with self.assertRaisesRegex(ValueError,'literal/type'):r.validate_rows(bad,nec)
        with self.assertRaisesRegex(ValueError,'count'):r.validate_rows([],nec)
    def test_guest_is_authored_bounded_and_drives_real_ports(self):
        image,end=r.firmware();self.assertEqual(len(image),262144);self.assertTrue(0xE100<end<0xFF00)
        self.assertEqual(image[end&8191:(end&8191)+2],bytes((0x80,0xFE)))
        self.assertIn(bytes.fromhex('AD 00 18 29 40 C9 40'),image)
        self.assertIn(bytes.fromhex('8D 01 18'),image);self.assertEqual(image[8190:8192],bytes((0,0xE1)))

if __name__=='__main__':unittest.main()
