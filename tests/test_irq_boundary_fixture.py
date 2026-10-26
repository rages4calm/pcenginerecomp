"""Literal authored IRQ stack, delivery, clocks, source and fixture checks."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from generate_irq_trace_fixture import authored_fixture, generate


class IrqBoundaryFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool,items,cls.sources=authored_fixture();cls.cases={item['id']:item for item in items}

    def test_primary_low_speed_literal_cpu_stack_and_clock(self):
        case=self.cases['timer-cli-low']
        self.assertEqual((case['entry'],case['marker'],case['primer_steps'],case['steps']),(0xE000,0xE03D,795,8))
        self.assertEqual(case['initial']['state']['wram_sha256'],hashlib.sha256(bytes(8192)).hexdigest())
        first,entry=case['expected_runtime'][:2]
        self.assertEqual(first['values'][:8],[0xE03E,1,0,0,255,0,12,24])
        self.assertEqual(entry['values'][:8],[0xF800,1,0,0,252,4,12,144])
        ram=bytearray(8192);ram[0x1FF]=0xE0;ram[0x1FE]=0x3F;ram[0x1FD]=0
        self.assertEqual(entry['wram_sha256'],hashlib.sha256(ram).hexdigest())
        final=case['expected_runtime'][-1]
        self.assertEqual(final['values'][:8],[0xE040,0,0,0,255,0,12,480])
        self.assertEqual(final['values'][17:],[1,0xFFFA,1,0,0,0,1,0,0])

    def test_stack_wrap_decimal_T_and_pending_BRK_literal_frames(self):
        case=self.cases['timer-cli-wrap'];entry=case['expected_runtime'][1]
        self.assertEqual(entry['values'][4],254)
        ram=bytearray(8192);ram[0x101]=0xE2;ram[0x100]=0x40;ram[0x1FF]=0
        self.assertEqual(entry['wram_sha256'],hashlib.sha256(ram).hexdigest())
        decimal=self.cases['timer-decimal-SET-stack']['expected_runtime'][2]
        ram=bytearray(8192);ram[0x1FF]=0xE4;ram[0x1FE]=0x41;ram[0x1FD]=0x28
        self.assertEqual(decimal['wram_sha256'],hashlib.sha256(ram).hexdigest())
        self.assertEqual(decimal['state']['p'],4)
        brk=self.cases['timer-pending-BRK']['expected_runtime'][1]
        ram=bytearray(8192);ram[0x101]=0xE9;ram[0x100]=0x41;ram[0x1FF]=0x10
        ram[0x1FE]=0xF8;ram[0x1FD]=0x20;ram[0x1FC]=4
        self.assertEqual(brk['values'][:8],[0xF800,1,0,0,251,4,3,54])
        self.assertEqual(brk['wram_sha256'],hashlib.sha256(ram).hexdigest())

    def test_known_delivery_ordinals_and_discrepancies_are_explicit(self):
        wanted={'timer-cli-low':[2],'timer-cli-high':[2],'timer-cli-wrap':[2],'timer-pending-sei':[2],
                'timer-decimal-SET-stack':[3],'timer-PLP-delay':[4],'timer-RTI-held-line':[8],
                'timer-mask-during-STA':[2],'timer-unmask-during-STA':[3],'timer-pending-BRK':[2],
                'PLP-raw-B-representation':[],'timer-CSL-transition':[2],'timer-CSH-transition':[2],
                'timer-I-masked':[],'timer-remapped-vector':[4]}
        for name,ordinals in wanted.items():
            with self.subTest(name=name):
                case=self.cases[name]
                self.assertEqual([row['ordinal'] for row in case['expected_runtime'] if row['irq_count']],ordinals)
                self.assertTrue(all(row['irq_vector']==0xFFFA for row in case['expected_runtime'] if row['irq_count']))
        self.assertEqual(self.cases['timer-RTI-held-line']['known_beetle_difference']['ordinal'],7)
        self.assertEqual(self.cases['PLP-raw-B-representation']['known_beetle_difference']['field'],'p')
        self.assertIsNone(self.cases['timer-cli-high']['known_beetle_difference'])
        self.assertEqual(self.cases['timer-CSL-transition']['expected_runtime'][1]['state']['ticks'],120)
        self.assertEqual(self.cases['timer-CSL-transition']['expected_gear'][1]['state']['ticks'],138)
        self.assertEqual(self.cases['timer-CSH-transition']['expected_runtime'][1]['state']['ticks'],75)
        self.assertEqual(self.cases['timer-CSH-transition']['expected_gear'][1]['state']['ticks'],57)

    def test_whole_guest_source_hit_counts_and_MPR7_remapping(self):
        for case in self.cases.values():
            self.assertEqual(sum(row['hits'] for row in case['source_hits']),case['primer_steps']+case['steps'])
            loops=[row for row in case['source_hits'] if row['data'][0]==0xD0]
            self.assertEqual([row['hits'] for row in loops],[256])
            for row in case['source_hits']:
                self.assertEqual([self.pool[address] for address in row['physical']],row['data'])
                self.assertEqual(row['physical'],[(row['mpr'][((row['pc']+i)&65535)>>13]<<13)|((row['pc']+i)&8191) for i in range(len(row['data']))])
        remap=self.cases['timer-remapped-vector']['expected_runtime'][3]
        self.assertEqual((remap['state']['pc'],remap['state']['physical_pc']),(0xF840,0x3840))
        self.assertEqual(remap['state']['mpr'],[255,248,0,0,0,0,0,1])

    def test_known_Beetle_differences_pin_actual_values_and_first_difference_tuple(self):
        wanted={
            'timer-RTI-held-line':(7,'pc',0xF800,'irq_count',0,1),
            'timer-mask-during-STA':(2,'pc',0xE744,'irq_count',1,0),
            'timer-unmask-during-STA':(2,'pc',0xF800,'irq_count',0,1),
            'timer-pending-BRK':(2,'pc',0xF820,'irq_count',1,0),
            'PLP-raw-B-representation':(3,'p',20,'state.p',4,20),
        }
        fields=('ordinal','field','value','first_field','first_expected','first_actual')
        for name,expected in wanted.items():
            with self.subTest(name=name):
                known=self.cases[name]['known_beetle_difference']
                self.assertEqual(tuple(known[field] for field in fields),expected)

    def test_case_roms_only_change_reset_vector_and_preserve_authored_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);metadata=generate(out,emit_module=False)
            self.assertEqual(len(metadata['cases']),15)
            self.assertFalse((out/'module.cpp').exists())
            reference=None
            for case in metadata['cases']:
                raw=(out/case['rom']).read_bytes();self.assertEqual(len(raw),262144)
                self.assertEqual(hashlib.sha256(raw).hexdigest(),case['rom_sha256'])
                self.assertEqual(int.from_bytes(raw[8190:8192],'little'),case['entry'])
                without_vector=raw[:8190]+raw[8192:]
                if reference is None:reference=without_vector
                self.assertEqual(without_vector,reference)
            self.assertIn('irq_rom', (out/'irq_boundary_fixture.hpp').read_text())


if __name__=='__main__':unittest.main()
