from pathlib import Path
import tempfile
import unittest

from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit
from pcerecomp.isa import decode, physical


class InterruptFrontendTests(unittest.TestCase):
    def test_rti_is_native_and_keeps_unknown_return_explicit(self):
        mpr = (0xFF,) + (0xF8,) * 7
        ins = decode(lambda address: 0x40, 0xFFFF, mpr)
        self.assertEqual((ins.mnemonic, ins.mode, ins.data, ins.next_pc, ins.native),
                         ('RTI', 'imp', (0x40,), 0, True))
        snapshot = Snapshot(mpr, {physical(0x2840, mpr): 0x40}, (0x2840,), 'authored-rti')
        result = analyze(snapshot)
        self.assertEqual([i['pc'] for i in result['instructions']], [0x2840])
        self.assertTrue(result['instructions'][0]['native_supported'])
        self.assertTrue(any(item['reason'] == 'interrupt_return' for item in result['unresolved']))

    def test_rti_emits_real_stack_operations(self):
        mpr = (0xFF,) + (0xF8,) * 7
        snapshot = Snapshot(mpr, {physical(0x2840, mpr): 0x40}, (0x2840,), 'authored-rti')
        with tempfile.TemporaryDirectory() as directory:
            manifest = emit(analyze(snapshot), Path(directory))
            source = (Path(directory)/'module.cpp').read_text()
        self.assertEqual(manifest['native_instructions_emitted'], 1)
        self.assertFalse(manifest['execution_evidence'])
        self.assertNotIn('interpret_step', source)
        self.assertIn('pop(bus,s)', source)
        self.assertIn('s.pc=', source)
        self.assertIn('bus.retire(s,7,true)', source)


if __name__ == '__main__':
    unittest.main()
