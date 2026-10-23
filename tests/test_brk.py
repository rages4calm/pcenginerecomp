"""BRK's hidden signature and direct lowering remain separate from reserved slots."""
import copy
import tempfile
from pathlib import Path
import unittest

from pcerecomp.analysis import Snapshot,analyze
from pcerecomp.emitter import body,emit_capture
from pcerecomp.isa import NATIVE,_ROWS,decode,physical
from generate_brk_fixture import make_fixture,generate
from scripts.brk_reference import compare,plans

class BrkTests(unittest.TestCase):
    def test_signature_has_dedicated_two_byte_metadata(self):
        ins=decode(lambda pc:(0,0xA5)[pc-0x4000],0x4000,(0xF8,)*8)
        self.assertEqual((ins.mnemonic,ins.mode,ins.data,ins.next_pc),('BRK','brk',(0,0xA5),0x4002))
        self.assertTrue(ins.native)

    def test_each_encoding_byte_uses_its_own_mpr_and_wrap(self):
        mpr=(0xF8,0xF8,0x80,0x81,0x82,0x83,0x84,0x85)
        for pc in (0x1FFF,0x5FFF,0xFFFF):
            memory={pc:0,(pc+1)&65535:0x55}
            ins=decode(memory.__getitem__,pc,mpr)
            self.assertEqual(ins.physical,(physical(pc,mpr),physical((pc+1)&65535,mpr)))
            self.assertEqual(ins.next_pc,(pc+2)&65535)

    def test_cfg_keeps_vector_unresolved_without_false_fallthrough(self):
        snapshot=Snapshot((0xF8,)*8,{0x1F0800:0,0x1F0801:0xA5,0x1F0802:0xEA},(0x2800,),'authored-brk')
        report=analyze(snapshot)
        self.assertEqual(report['edges'],[])
        self.assertEqual(report['unresolved'],[{'pc':0x2800,'reason':'interrupt_vector'}])
        self.assertEqual(report['summary']['native_supported'],1)

    def test_direct_body_never_polls_signature_and_orders_stack_before_vector(self):
        ins=decode(lambda pc:(0,0xA5)[pc-0x2800],0x2800,(0xF8,)*8)
        code,cycles=body(ins.report())
        self.assertEqual(cycles,'8')
        self.assertNotIn('interpret_step',code)
        self.assertNotIn('bus.read(s,10241)',code)
        self.assertIn('push(bus,s,40); push(bus,s,2);',code)
        self.assertLess(code.index('(s.p|B)&~T'),code.index('~(D|T)'))
        self.assertLess(code.index('push(bus,s'),code.index('bus.read(s,0xFFF6)'))

    def test_emitted_guards_bind_signature_before_guest_mutation(self):
        capture,_=make_fixture()
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'module';manifest=emit_capture(capture,out,single_unit=True)
            code=(out/'module.cpp').read_text()
        self.assertEqual(manifest['native_instructions_emitted'],15)
        self.assertIn('case 10240:',code)
        case=code[code.index('case 10240:'):]
        self.assertLess(case.index('bus.peek(2033665)'),case.index('bus.begin_instruction(s)'))
        self.assertIn('case 165ULL:',case)
        self.assertNotIn('interpret_step(',code)

    def test_fixture_regeneration_preserves_unrelated_output_and_exact_module(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'fixture';generate(out)
            first={p.name:p.read_bytes() for p in out.iterdir()}
            unrelated=out/'keep.txt';unrelated.write_text('authored unrelated marker')
            generate(out)
            self.assertEqual({name:(out/name).read_bytes() for name in first},first)
            self.assertEqual(unrelated.read_text(),'authored unrelated marker')

    def test_missing_signature_is_an_explicit_analysis_boundary(self):
        snapshot=Snapshot((0xF8,)*8,{0x1F0800:0},(0x2800,),'authored-truncated-brk')
        report=analyze(snapshot)
        self.assertEqual(report['instructions'],[])
        self.assertEqual(report['unresolved'],[{'pc':0x2800,'reason':'bytes_not_in_snapshot'}])

    def test_reference_plan_covers_flags_speeds_boundaries_and_pending_irq(self):
        rows=plans()
        self.assertEqual(len(rows),3040)
        self.assertEqual(sum(row[-1] for row in rows),5280)
        self.assertEqual({row[1] for row in rows},set(range(256)))
        self.assertEqual({row[3] for row in rows},{3,12})
        self.assertEqual({row[0] for row in rows},{0x2800,0x3FFF,0xFFFF,0x2100})
        self.assertTrue(any(row[4]==4 and row[5]==0 and row[1]==0 for row in rows))

    def test_reference_comparator_checks_shape_order_and_real_differences(self):
        rows=[(0x2800,0,255,3,0,0,2)]
        records=[dict(case=0,step=n,pc=0x2900 if n==1 else 0x2802,a=99,x=167,y=59,p=4 if n==1 else 0,
                      sp=252 if n==1 else 255,ticks=24 if n==1 else 45,mpr=[248]*8,stack='00'*256) for n in (1,2)]
        self.assertIsNone(compare(records,copy.deepcopy(records),rows))
        changed=copy.deepcopy(records);changed[0]['p']=8
        self.assertEqual(compare(changed,records,rows)['field'],'p')
        for field,value in [('step',2),('p',True),('sp',256),('mpr',[248]*7),('stack','z'*512)]:
            with self.subTest(field=field):
                broken=copy.deepcopy(records);broken[0][field]=value
                with self.assertRaises(ValueError):compare(broken,records,rows)
        with self.assertRaises(ValueError):compare(records[:-1],records,rows)

    def test_reserved_encodings_still_stop_explicitly(self):
        missing=[i for i in range(256) if i not in NATIVE]
        self.assertEqual(len(NATIVE),234)
        self.assertEqual(len(missing),22)
        self.assertTrue(all(_ROWS[i]=='ILL.non' for i in missing))
        self.assertEqual(missing,[0x0B,0x1B,0x2B,0x33,0x3B,0x4B,0x5B,0x5C,0x63,0x6B,0x7B,
            0x8B,0x9B,0xAB,0xBB,0xCB,0xDB,0xDC,0xE2,0xEB,0xFB,0xFC])

if __name__=='__main__':unittest.main()
