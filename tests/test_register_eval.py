"""Mathematical expected values independent of runtime/emitter implementations."""
from types import SimpleNamespace
import unittest
from pcerecomp.register_eval import evaluate


def instruction(name, value=0, mode='imm'):
    return SimpleNamespace(mnemonic=name, mode=mode, data=bytes([0,value]))


class RegisterEvalTests(unittest.TestCase):
    def run_op(self,name,a,b,c=0,d=0,t=0,mode='imm'):
        return evaluate(instruction(name,b or 0,'abs' if b is None else mode),(a,7,9,c,d,t),(0,)*8,b)

    def test_all_binary_add_subtract_inputs_and_carries(self):
        for name in ('ADC','SBC'):
            for a in range(256):
                for b in range(256):
                    for c in (0,1):
                        value=a+b+c if name=='ADC' else a-b-(1-c)
                        actual,reason=self.run_op(name,a,b,c)
                        expected_c=int(value>255) if name=='ADC' else int(value>=0)
                        self.assertEqual(actual,(value%256,7,9,expected_c,0,0))
                        self.assertIsNone(reason)

    def test_all_valid_decimal_pairs_and_carries(self):
        for name in ('ADC','SBC'):
            for left in range(100):
                for right in range(100):
                    for carry in (0,1):
                        a,b=int(str(left),16),int(str(right),16)
                        value=left+right+carry if name=='ADC' else left-right-1+carry
                        actual,reason=self.run_op(name,a,b,carry,1)
                        expected=int(str(value%100),16)
                        expected_c=int(value>=100) if name=='ADC' else int(value>=0)
                        self.assertEqual(actual,(expected,7,9,expected_c,1,0));self.assertIsNone(reason)

    def test_all_bitwise_byte_pairs(self):
        for name in ('AND','ORA','EOR'):
            for a in range(256):
                for b in range(256):
                    expected=a&b if name=='AND' else a|b if name=='ORA' else a^b
                    self.assertEqual(self.run_op(name,a,b,1,1)[0],(expected,7,9,1,1,0))

    def test_all_accumulator_shifts_rotates(self):
        for name in ('ASL','LSR','ROL','ROR'):
            for a in range(256):
                for carry in (0,1):
                    expected={'ASL':a*2,'LSR':a//2,'ROL':a*2+carry,'ROR':a//2+128*carry}[name]%256
                    expected_c=int(a>=128) if name in ('ASL','ROL') else a%2
                    self.assertEqual(self.run_op(name,a,0,carry,1,1,'acc')[0],(expected,7,9,expected_c,1,0))

    def test_set_destination_is_not_the_accumulator(self):
        for name in ('ADC','AND','ORA','EOR'):
            result,reason=self.run_op(name,0x55,0xAA,1,1,1)
            self.assertEqual(result[0],0x55);self.assertEqual(result[3],None if name=='ADC' else 1)
            self.assertEqual(result[5],0);self.assertEqual(reason,'transfer_destination_untracked')

    def test_sbc_ignores_t_under_the_reference_contract(self):
        for transfer in (0,1,None):
            result,reason=self.run_op('SBC',0x50,9,1,1,transfer)
            self.assertEqual(result,(0x41,7,9,1,1,0));self.assertIsNone(reason)

    def test_unknown_inputs_and_invalid_bcd_do_not_create_facts(self):
        for a,b,c,d,t in ((None,1,0,0,0),(1,None,0,0,0),(1,1,None,0,0),(1,1,0,None,0),(1,1,0,0,None),(0xFA,1,0,1,0),(1,0xAF,1,1,0)):
            result,reason=self.run_op('ADC',a,b,c,d,t)
            self.assertIsNone(result[0]);self.assertIsNone(result[3]);self.assertIsNotNone(reason)
        result,_=self.run_op('ROL',0x80,0,None,0,0,'acc')
        self.assertIsNone(result[0]);self.assertEqual(result[3],1)

    def test_memory_shifts_clobber_carry_but_not_accumulator(self):
        for name in ('ASL','LSR','ROL','ROR'):
            result,reason=self.run_op(name,3,1,1,0,0,'abs')
            self.assertEqual(result,(3,7,9,None,0,0));self.assertEqual(reason,'memory_shift_carry_unknown')

    def test_status_controls_restores_and_ordinary_t_clear(self):
        for name,expected in (('CLC',(0,1,0)),('SEC',(1,1,0)),('CLD',(1,0,0)),('SED',(1,1,0)),('SET',(1,1,1)),('PLP',(None,None,None)),('RTI',(None,None,None)),('NOP',(1,1,0))):
            result,_=self.run_op(name,3,0,1,1,1,'imp');self.assertEqual(result[3:],expected)

    def test_comparisons_are_binary_and_preserve_registers(self):
        for name,left in (('CMP',3),('CPX',7),('CPY',9)):
            for right in range(256):
                result,_=self.run_op(name,3,right,1,1,1)
                self.assertEqual(result,(3,7,9,int(left>=right),1,0))
