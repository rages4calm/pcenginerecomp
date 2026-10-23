from pathlib import Path
import tempfile
import unittest

from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit
from pcerecomp.isa import decode, physical


class BlockFrontendTests(unittest.TestCase):
    def test_all_block_encodings_and_three_words_survive_decode(self):
        mpr = (0xFF, 0xF8, 0x80, 0x81, 0x82, 0x83, 0x84, 0)
        for op, mnemonic in ((0x73, 'TII'), (0xC3, 'TDD'), (0xD3, 'TIN'),
                             (0xE3, 'TIA'), (0xF3, 'TAI')):
            data = bytes([op, 0xFE, 0xFF, 1, 0, 0, 0])
            memory = {(0xFFFC+n) & 65535: value for n, value in enumerate(data)}
            ins = decode(memory.__getitem__, 0xFFFC, mpr)
            self.assertEqual((ins.mnemonic, ins.mode, ins.data, ins.next_pc, ins.native),
                             (mnemonic, 'blk', tuple(data), 3, True))
            self.assertEqual(ins.physical, (0x1FFC, 0x1FFD, 0x1FFE, 0x1FFF,
                                           0x1FE000, 0x1FE001, 0x1FE002))

    def test_analysis_keeps_block_fallthrough_and_emits_native_operations(self):
        mpr = (0xF8,) * 8
        for op in (0x73, 0xC3, 0xD3, 0xE3, 0xF3):
            data = bytes([op, 0, 0x23, 0, 0x24, 3, 0, 0x80, 0xFE])
            snapshot = Snapshot(mpr, {physical(0x2800+n, mpr): value
                                      for n, value in enumerate(data)}, (0x2800,), 'synthetic-block-front')
            result = analyze(snapshot)
            self.assertEqual({ins['pc'] for ins in result['instructions']}, {0x2800, 0x2807})
            self.assertTrue(all(ins['native_supported'] for ins in result['instructions']))
            with tempfile.TemporaryDirectory() as directory:
                manifest = emit(result, Path(directory))
                output = (Path(directory)/'module.cpp').read_text()
            self.assertEqual(manifest['native_instructions_emitted'], 2)
            self.assertFalse(manifest['execution_evidence'])
            self.assertNotIn('interpret_step', output)
            self.assertNotIn('interpret_block', output)
            self.assertIn('read_block', output)
            self.assertIn('write_block', output)
            self.assertIn('65536', output)
            # Live operands can be modified by the instruction's own stack
            # writes. Literal addresses from the initial snapshot are unsafe.
            self.assertLess(output.index('push(bus,s,s.y)'), output.index('bus.read(s,'))

    def test_truncated_block_has_no_partial_native_translation(self):
        mpr = (0xF8,) * 8
        for length in range(1, 7):
            data = bytes([0xF3, 0, 0x23, 0, 0x24, 1])[:length]
            snapshot = Snapshot(mpr, {physical(0x2800+n, mpr): value
                                      for n, value in enumerate(data)}, (0x2800,), 'truncated-authored-block')
            result = analyze(snapshot)
            self.assertEqual(result['instructions'], [])
            self.assertEqual(result['unresolved'][0]['reason'], 'bytes_not_in_snapshot')


if __name__ == '__main__':
    unittest.main()
