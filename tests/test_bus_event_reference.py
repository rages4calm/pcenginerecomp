import copy
import tempfile
import unittest
from pathlib import Path

from scripts.bus_event_reference import binding,compare_nonperturbation,instrument,verify_bindings
from bus_reference_fixture import expected_accesses,fixture,expected_event_cycles


class OriginalBusReferenceTests(unittest.TestCase):
    def test_low_high_share_measured_code_and_independent_data_order(self):
        low, first = fixture('low')
        high, second = fixture('high')
        self.assertEqual(first['marker'], second['marker'])
        self.assertEqual(first['instructions'], second['instructions'])
        self.assertNotEqual(low, high)
        self.assertEqual(expected_accesses('low'), expected_accesses('high'))
        # The RAM alias route changes slot two for the access, then restores it.
        self.assertEqual(expected_accesses('low')[6]['mpr'][2], 248)
        self.assertEqual(expected_accesses('low')[14]['mpr'][2], 128)

    def test_block_literal_preserves_each_stack_and_transfer_access(self):
        rows = expected_accesses('block')
        self.assertEqual(len(rows), 15)
        self.assertEqual([row['logical']for row in rows[3:6]], [0x21FF,0x21FE,0x21FD])
        self.assertEqual([row['logical']for row in rows[-3:]], [0x21FD,0x21FE,0x21FF])
        self.assertEqual([row['value']for row in rows[7:12:2]], [0x19,0x37,0x91])

    def test_reference_nonperturbation_does_not_ignore_clock_or_ram_changes(self):
        raw=[dict(type='initial',state=dict(ticks=0,wram='a')),
             dict(type='entry',instruction=1,state=dict(ticks=0,wram='a')),
             dict(type='retired',instruction=1,state=dict(ticks=6,wram='b'),retired=1),
             dict(type='closure',calls=1,retired=1,events=0,direct_reads=0,handler_reads=0)]
        self.assertTrue(compare_nonperturbation(raw,raw,raw)['equal'])
        for field,value in [('ticks',7),('wram','wrong')]:
            bad=copy.deepcopy(raw);bad[2]['state'][field]=value
            with self.assertRaisesRegex(ValueError,'observation changes'):
                compare_nonperturbation(raw,raw,bad)

    def test_nonperturbation_refuses_hidden_calls_and_disabled_accesses(self):
        raw=[dict(type='initial'),dict(type='entry'),dict(type='retired',retired=1),
             dict(type='closure',calls=2,retired=1,events=0,direct_reads=0,handler_reads=0)]
        with self.assertRaisesRegex(ValueError,'accounting'):
            compare_nonperturbation(raw,raw,raw)
        raw.insert(2,dict(type='access'))
        with self.assertRaisesRegex(ValueError,'Disabled reference'):
            compare_nonperturbation(raw,raw,raw)

    def test_original_source_hook_refuses_anchor_drift(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);(root/'mednafen/pce').mkdir(parents=True)
            (root/'mednafen/pce/huc6280.h').write_text('changed original source')
            with self.assertRaisesRegex(ValueError,'anchor differs'):
                instrument(root,'beetle-pce')

    def test_receipt_binding_rejects_mutation_before_reuse(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'source';path.write_bytes(b'original')
            saved=binding(path);verify_bindings(dict(source=[saved]))
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Changed retained execution binding'):
                verify_bindings(dict(source=[saved]))

    def test_declared_block_callback_profiles_keep_real_six_cycle_difference(self):
        gear=expected_event_cycles('block','Geargrafx')
        beetle=expected_event_cycles('block','beetle-pce')
        self.assertEqual([right-left for left,right in zip(gear[6:12],beetle[6:12])],[6]*6)
        self.assertEqual(gear[-3:],beetle[-3:])


if __name__=='__main__':unittest.main()
