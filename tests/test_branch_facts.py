"""Independent arithmetic/status expectations for conditional candidate facts."""
from types import SimpleNamespace
import unittest
from pcerecomp.branch_facts import extend_status,flag_decision,refine,FLAGS
from pcerecomp.register_eval import evaluate


def result(name,a=0,b=0,c=0,d=0,t=0,n=1,z=1,v=1,mode='imm'):
    ins=SimpleNamespace(mnemonic=name,mode=mode,data=bytes([0,b]))
    incoming=(a,7,9,c,d,t,n,z,v)
    outgoing,_=evaluate(ins,incoming[:6],(0,)*8,b)
    return extend_status(ins,incoming,outgoing,b)


class BranchStatusTests(unittest.TestCase):
    def test_all_binary_arithmetic_status_inputs(self):
        for name in ('ADC','SBC'):
            for a in range(256):
                for b in range(256):
                    for c in (0,1):
                        value=(a+b+c if name=='ADC' else a-b-1+c)%256
                        overflow=bool((a^value)&(~(a^b) if name=='ADC' else (a^b))&128)
                        self.assertEqual(result(name,a,b,c)[6:],(int(value>=128),int(value==0),int(overflow)))

    def test_valid_decimal_results_preserve_both_overflow_values(self):
        for name in ('ADC','SBC'):
            for a in range(100):
                for b in range(100):
                    for c in (0,1):
                        total=a+b+c if name=='ADC' else a-b-1+c;byte=int(f'{total%100:02}',16)
                        for v in (0,1):self.assertEqual(result(name,int(f'{a:02}',16),int(f'{b:02}',16),c,1,v=v)[6:],(int(byte>=128),int(byte==0),v))

    def test_bitwise_and_shifts_use_result_status(self):
        for name in ('AND','ORA','EOR'):
            for a in range(256):
                for b in range(256):
                    value=a&b if name=='AND' else a|b if name=='ORA' else a^b
                    self.assertEqual(result(name,a,b)[6:],(int(value>=128),int(value==0),1))
        for name in ('ASL','LSR','ROL','ROR'):
            for a in range(256):
                for c in (0,1):
                    value={'ASL':a*2,'LSR':a//2,'ROL':a*2+c,'ROR':a//2+128*c}[name]%256
                    self.assertEqual(result(name,a,c=c,mode='acc')[6:],(int(value>=128),int(value==0),1))

    def test_comparison_flags_use_subtraction_without_changing_registers(self):
        for name,left in (('CMP',3),('CPX',7),('CPY',9)):
            for b in range(256):
                value=(left-b)%256;out=result(name,3,b,d=1)
                self.assertEqual(out[:3],(3,7,9));self.assertEqual(out[6:],(int(value>=128),int(value==0),1))

    def test_clear_swap_and_tma_do_not_set_nz(self):
        for name in ('CLA','CLX','CLY','SAX','SAY','SXY','TMA','TXS','NOP'):
            self.assertEqual(result(name,0,b=1,mode='imp')[6:],(1,1,1))
        self.assertEqual(result('CLV',mode='imp')[6:],(1,1,0))

    def test_load_transfer_increment_and_stack_unknowns(self):
        for name in ('LDA','LDX','LDY'):
            for value in range(256):self.assertEqual(result(name,b=value)[6:],(int(value>=128),int(value==0),1))
        self.assertEqual(result('TAX',a=128,mode='imp')[6:],(1,0,1))
        self.assertEqual(result('INA',a=255,mode='imp')[6:],(0,1,1))
        for name in ('PLA','PLX','PLY','TSX'):
            self.assertEqual(result(name,mode='imp')[6:],(None,None,1))

    def test_transfer_destinations_do_not_infer_nz_from_preserved_a(self):
        for name in ('ADC','AND','ORA','EOR'):
            self.assertEqual(result(name,0,b=255,t=1)[6:8],(None,None))
        self.assertIsNone(result('ADC',0,b=1,t=1)[8])
        self.assertEqual(result('ADC',0,b=1,d=1,t=1)[8],1)
        self.assertEqual(result('SBC',0,b=1,c=1,t=1)[6:],(1,0,0))

    def test_tests_and_restored_status_are_not_guessed(self):
        for name in ('PLP','RTI','ILL','BIT','TST','TSB','TRB'):
            self.assertEqual(result(name,mode='imp')[6:],(None,None,None))
        for name in ('INC','DEC','ASL','ROL','LSR','ROR'):
            self.assertEqual(result(name,mode='abs')[6:8],(None,None))

    def test_all_conditions_decide_known_and_refine_unknown_bits(self):
        specs={'BCC':('c',0),'BCS':('c',1),'BNE':('z',0),'BEQ':('z',1),'BPL':('n',0),'BMI':('n',1),'BVC':('v',0),'BVS':('v',1)}
        for name,(flag,expected) in specs.items():
            for value in (0,1,None):
                facts=[None]*9;facts[3+FLAGS.index(flag)]=value;record=flag_decision(name,facts)
                self.assertEqual(record['decision'],'both' if value is None else 'taken' if value==expected else 'fallthrough')
                for kind,bit in (('taken',expected),('fallthrough',1-expected)):
                    outgoing=refine(tuple(facts),record,kind)
                    self.assertEqual(outgoing[3+FLAGS.index(flag)],bit)
                    self.assertEqual(sum(v is not None for v in outgoing),1)

    def test_unknown_decimal_and_carry_do_not_invent_status(self):
        self.assertEqual(result('ADC',1,1,c=None)[6:],(None,None,None))
        self.assertEqual(result('SBC',1,1,d=None)[6:],(None,None,None))
        self.assertEqual(result('ADC',0xFA,1,d=1)[6:],(None,None,1))
