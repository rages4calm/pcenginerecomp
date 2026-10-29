"""Authored block/DMA/IRQ literals and strict grouped-call admission controls."""
import copy
from pathlib import Path
import tempfile
import unittest

from tests.block_dma_irq_fixture import cases,program,expected_ram,expected_wram,scratch,rom_pattern,LENGTH,OPCODES
from scripts.block_dma_irq_reference import validate_hits,validate_work,validate_original_group,validate_phase_journal,requested_tier,stack_literal
from scripts.block_dma_irq_qualify import full_hits,load,validate_stderr


def authored_group(case):
    """Literal 14 startup / 1023 x 6 byte / 3 epilogue, IRQ after completion."""
    markers=program(case)[1];calls=[];spans=[];ticks=1000
    for i in range(1,LENGTH+3):
        cycles=14 if i==1 else 3+8 if i==LENGTH+2 else 6
        duration=cycles*case['divisor'];spans.append([ticks,duration,ticks+duration]);ticks+=duration
        calls.append([i,duration,0,int(i==LENGTH+2),i-1,i-1,i,3 if i==512 else 0,int(i==LENGTH+2)])
    values=[0]*23;values[7]=ticks
    row=dict(bytes=[OPCODES[0],0,232,0,34,255,3],before=[2,case['loops'],0,255,1,0,0,0],
             ticks=ticks-1000,internal=0,clocks=spans,call_rows=calls,vector=0xfff6,cause=True,
             callbacks=[[512,spans[511][2],7,7,0,0,0,1,4],
                        [512,spans[511][2],7,8,0,0,0,1,12],
                        [LENGTH+2,ticks-33,1,0xfff6,markers['block']+7,1]],
             after=dict(values=values))
    return row,markers


class BlockDmaIrqTests(unittest.TestCase):
    def test_twenty_authored_recipes_and_safe_seven_byte_operands(self):
        matrix=cases();self.assertEqual(len(matrix),20);self.assertEqual(len({c['id']for c in matrix}),20)
        for case in matrix:
            rom,markers,plan=program(case);self.assertEqual(len(rom),262144)
            block=next(r for r in plan if r['pc']==markers['block']);self.assertEqual(len(block['data']),7)
            self.assertEqual(int.from_bytes(bytes(block['data'][5:]),'little'),1023)
            self.assertEqual(block['data'][0],OPCODES[['tii','tdd','tin','tia','tai'].index(case['family'])])
            self.assertTrue(all(bytes(rom[p]for p in r['physical'])==bytes(r['data'])for r in plan))
            self.assertLess(markers['pre_arm'],markers['block']);self.assertLess(markers['block'],markers['post_dma'])

    def test_independent_block_destination_patterns_and_stack_residue(self):
        for case in cases():
            data=rom_pattern();result=scratch(case);w=expected_wram(case)
            self.assertEqual(len(result),1023);self.assertEqual(len(w),8192)
            self.assertEqual(w[512:1535],result);self.assertEqual(w[508:512],[2 if case['kind']=='enabled'else 0,1,2,0])
            if case['family']in('tii','tdd'):self.assertEqual(result,data)
            elif case['family']=='tin':self.assertEqual(result,[data[1022]]+[0]*1022)
            elif case['family']=='tia':self.assertEqual(result,[data[1022],data[1021]]+[0]*1021)
            else:self.assertEqual(result[:5],[data[0],data[1],data[0],data[1],data[0]])
            self.assertEqual(expected_ram()[65534:],[0x53,0x64])

    def test_actual_empty_mode1_is_read_back_before_continuous_arm(self):
        for case in cases():
            rom,markers,_=program(case)
            sequence=bytes([0xa9,1,0x8d,11,24,0xad,11,24,0x8d,19,32])
            self.assertIn(sequence,rom[:markers['pre_arm']&8191])
            self.assertEqual(rom[markers['pre_arm']&8191:(markers['pre_arm']&8191)+3],bytes([0x8d,11,24]))

    def test_original_continuation_calls_are_not_retirements(self):
        case=cases()[0];row=dict(next(r for r in program(case)[2]if r['data'][0]in OPCODES),hits=1);hits=validate_hits([row],case)
        common=dict(instructions=1,blocks=1,block_bytes=1023,clock_ticks=6155*3,irqs=0,rtis=0,cause_blocks=0)
        validate_work(dict(common,calls=1025,clock_calls=1025),hits,6155*3,True)
        validate_work(dict(common,calls=1,clock_calls=0),hits,6155*3,False)
        for gear,calls,clock_calls in((True,1,1025),(False,1025,0)):
            with self.assertRaisesRegex(ValueError,'Continuation calls'):
                validate_work(dict(common,calls=calls,clock_calls=clock_calls),hits,6155*3,gear)
        with self.assertRaises(ValueError):validate_work(dict(common,calls=True,clock_calls=0),hits,6155*3,False)

    def test_original_group_requires_every_call_and_incomplete_cause(self):
        case=cases()[0];row,markers=authored_group(case);validate_original_group(row,case,markers)
        for mutate in('missing-call','early-complete','cause-in-epilogue','early-irq','wrong-byte-clock'):
            bad=copy.deepcopy(row)
            if mutate=='missing-call':bad['call_rows'].pop(10)
            elif mutate=='early-complete':bad['call_rows'][511][3]=1
            elif mutate=='cause-in-epilogue':bad['call_rows'][511][7]=0;bad['call_rows'][-1][7]=3
            elif mutate=='early-irq':bad['call_rows'][511][8]=1
            else:bad['call_rows'][510][1]+=3
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):validate_original_group(bad,case,markers)

    def test_cause_and_irq_callbacks_join_exact_continuation_call(self):
        case=cases()[0];row,markers=authored_group(case)
        for index,value in((0,513),(3,6),(7,False)):
            bad=copy.deepcopy(row);bad['callbacks'][0][index]=value
            with self.subTest(index=index),self.assertRaises(ValueError):validate_original_group(bad,case,markers)
        bad=copy.deepcopy(row);bad['callbacks'][-1][4]-=1
        with self.assertRaises(ValueError):validate_original_group(bad,case,markers)

    def test_unknown_callback_type_and_wrong_type_extent_are_refused(self):
        case=cases()[0];row,markers=authored_group(case)
        for event in([512,1000,99,0,0,0],[512,1000,5,0,0,0,0,0,0]):
            bad=copy.deepcopy(row);bad['callbacks'].append(event)
            with self.subTest(event=event),self.assertRaisesRegex(ValueError,'type/extent'):
                validate_original_group(bad,case,markers)

    def test_source_edge_and_irq_work_cannot_move_between_checkpoint_phases(self):
        cause=dict(cause=True,vector=0xfff6,bytes=[0x73,0,232,0,34,255,3])
        rti=dict(cause=False,vector=0,bytes=[0x40])
        prefix=dict(cause_blocks=1,irqs=1,rtis=0);window=dict(cause_blocks=0,irqs=0,rtis=1)
        validate_phase_journal(prefix,[cause]);validate_phase_journal(window,[rti])
        # Aggregate source-edge/IRQ/RTI totals remain unchanged, but these
        # claims would falsely turn imported prefix work into new suffix work.
        bad_prefix=dict(prefix,cause_blocks=0);bad_window=dict(window,cause_blocks=1)
        self.assertEqual(prefix['cause_blocks']+window['cause_blocks'],bad_prefix['cause_blocks']+bad_window['cause_blocks'])
        with self.assertRaisesRegex(ValueError,'different phase'):validate_phase_journal(bad_prefix,[cause])
        with self.assertRaisesRegex(ValueError,'different phase'):validate_phase_journal(bad_window,[rti])

    def test_independent_entry_frame_is_distinct_from_later_block_residue(self):
        case=cases()[0];ret=program(case)[1]['block']+7
        self.assertEqual(stack_literal(case,entry_x=21)[252:],[0,1,ret&255,ret>>8])
        self.assertEqual(stack_literal(case,entry_x=200,handler_saved=True)[252:],[2,129,ret&255,ret>>8])
        self.assertEqual(stack_literal(case,final=True)[252:],[2,1,2,0])

    def test_actual_full_source_ledger_requires_loop_extent_and_protocol_stores(self):
        for case in cases():
            _,markers,plan=program(case);rows=[]
            for source in plan:
                pc=source['pc']
                if pc==markers['done']or(pc>=0xf800 and case['kind']!='enabled'):continue
                rows.append(dict(source,hits=case['loops']if pc in(markers['block'],markers['block']+7,markers['block']+8)else 1))
            full_hits(rows,[],case)
            bad=copy.deepcopy(rows);next(r for r in bad if r['pc']==markers['block'])['hits']-=1
            with self.assertRaises(ValueError):full_hits(bad,[],case)

    def test_all_mpr_and_physical_source_bytes_are_required(self):
        case=cases()[0];row=dict(program(case)[2][0],hits=1)
        for key in('mpr','physical','data'):
            bad=copy.deepcopy(row);bad[key][0]^=1
            with self.assertRaises(ValueError):validate_hits([bad],case)
        bad=copy.deepcopy(row);bad['hits']=True
        with self.assertRaises(ValueError):validate_hits([bad],case)

    def test_requested_tier_and_guest_stderr_are_not_inferred_from_labels(self):
        requested_tier(dict(tier='native'),'native')
        with self.assertRaises(ValueError):requested_tier(dict(tier='interpreter'),'native')
        validate_stderr('tool-configure','CMake warning')
        with self.assertRaises(ValueError):validate_stderr('tii-enabled-div3-cut0-gear','unexpected')

    def test_duplicate_nonfinite_receipts_are_refused(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'receipt.json'
            for value in('{"x":1,"x":2}','{"x":Infinity}'):
                path.write_text(value)
                with self.assertRaises(ValueError):load(path)


if __name__=='__main__':unittest.main()
