"""Finite authored IRQ matrix and trace boundaries, without the emulator."""
import tempfile
from pathlib import Path
import unittest
from scripts.irq_reference import initial_ram, measured_ticks, plans, write_plan


class IrqReferenceTests(unittest.TestCase):
    def test_matrix_covers_every_rti_status_and_source_mask(self):
        matrix=plans()
        self.assertEqual(len(matrix),832)
        self.assertEqual(len({p['id'] for p in matrix}),len(matrix))
        for speed in (3,12):
            selected=[p for p in matrix if p['divisor']==speed]
            self.assertEqual({p['pulled'] for p in selected if p['entry']==0x2840},set(range(256)))
            self.assertEqual({p['mask'] for p in selected if p['entry']==0x2800},set(range(8)))
            for entry in (0x2810,0x2820,0x2830):self.assertTrue(any(p['entry']==entry for p in selected))
            self.assertEqual({p['sp'] for p in selected},{0,1,254,255})
        self.assertTrue(all(p['count']==3 for p in matrix))

    def test_ram_contains_independent_vectors_and_wrapped_stack(self):
        for plan in plans():
            ram=initial_ram(plan)
            self.assertEqual(len(ram),8192)
            self.assertEqual(ram[0x1FF6:0x1FFC],bytes.fromhex('00 29 70 29 80 29'))
            for n,value in enumerate((plan['pulled'],0,0x28),1):
                self.assertEqual(ram[0x100+((plan['sp']+n)&255)],value)
            self.assertEqual(ram[plan['entry']&8191],{0x2800:0xEA,0x2810:0x58,0x2820:0x78,0x2830:0x28,0x2840:0x40}[plan['entry']])

    def test_numeric_plan_is_fixed_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan.txt'
            for plan in plans():
                write_plan(path,plan)
                values=list(map(int,path.read_text().split()))
                self.assertEqual(len(values),11)
                self.assertEqual(values[-1],3)
                self.assertLessEqual(values[7],7)

    def test_trace_rejects_incomplete_wrong_bank_pc_and_nonmonotonic(self):
        pcs=[0x2800,0x2980,0x2801,0x2700]
        trace=dict(count=4,overrun=False,lines=[f'@{100+i*30} CPU F8:{pc:04X} op' for i,pc in enumerate(pcs)])
        self.assertEqual(measured_ticks(trace,pcs),90)
        for bad in (trace|{'count':3},trace|{'overrun':True},trace|{'lines':trace['lines'][:-1]},
                trace|{'lines':[line.replace('F8:','FF:') for line in trace['lines']]},
                trace|{'lines':[line.replace('@190','@99') for line in trace['lines']]}):
            with self.assertRaises(RuntimeError):measured_ticks(bad,pcs)


if __name__=='__main__':unittest.main()
