"""Authored protocol traffic verifies the explicit unknown-command CLI policy."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
NAME = 'pce-headless.exe' if os.name == 'nt' else 'pce-headless'
CANDIDATES = ([Path(os.environ['PCE_TEST_HEADLESS'])] if 'PCE_TEST_HEADLESS' in os.environ else
              [ROOT/'build'/NAME, ROOT/'build/Release'/NAME])
BINARY = next((p for p in CANDIDATES if p.is_file()), None)


@unittest.skipUnless(BINARY, 'Build pce-headless for protocol policy checks')
class HeadlessScsiPolicyTests(unittest.TestCase):
    def run_case(self, options):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Select, poll REQ, submit one unknown byte, raise/lower ACK,
            # then leave the returned status byte unacknowledged.
            program = bytes([0xA9, 0, 0x8D, 0, 0x18,
                             0xAD, 0, 0x18, 0x29, 0x40, 0xF0, 0xF9,
                             0xA9, 0xFF, 0x8D, 1, 0x18,
                             0xA9, 0x80, 0x8D, 2, 0x18,
                             0xA9, 0, 0x8D, 2, 0x18, 0xAD, 0, 0x18, 0x80, 0xFE])
            image = root/'authored.bin'
            image.write_bytes(program)
            toc_text = 'PCE_TOC 1\nimage_sha256 ' + 'a'*64 + '\nleadout_lba 300\ntrack 1 0 4\n'
            toc = root/'metadata.toc'
            toc.write_text(toc_text, encoding='ascii')
            result = subprocess.run([str(BINARY), str(image), '0x100000', '0x4000',
                                     '255,248,128,129,130,131,132,0', '10000', '200000',
                                     'hybrid', '--toc', str(toc), *options],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(image.read_bytes(), program)
            self.assertEqual(toc.read_text(), toc_text)
            return result

    def test_strict_default_and_explicit_fault_refuse_unknown_command(self):
        for options in ([], ['--cd-unknown-status', 'fault']):
            with self.subTest(options=options):
                result = self.run_case(options)
                self.assertEqual(result.returncode, 3, result.stdout+result.stderr)
                state = json.loads(result.stdout)
                self.assertEqual(state['stop'], 'bus_fault')
                self.assertFalse(state['scsi']['reference_unknown_status'])
                self.assertEqual(state['scsi']['unknown_commands'], 0)
                self.assertEqual(state['scsi']['last_command'], [255])
                self.assertIn('unsupported CD command $FF', result.stderr)

    def test_reference_good_response_requires_explicit_selection(self):
        result = self.run_case(['--cd-unknown-status', 'gear-good'])
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        state = json.loads(result.stdout)
        self.assertTrue(state['scsi']['reference_unknown_status'])
        self.assertEqual(state['scsi']['unknown_commands'], 1)
        self.assertEqual(state['scsi']['last_command'], [255])
        self.assertEqual(state['scsi']['command_size'], 0)
        self.assertEqual((state['scsi']['phase'], state['scsi']['drive_data'], state['a']), (7, 0, 0xD8))

    def test_invalid_or_duplicate_policy_is_rejected(self):
        for options in (['--cd-unknown-status', 'good'],
                        ['--cd-unknown-status', 'gear-good', '--cd-unknown-status', 'fault']):
            with self.subTest(options=options):
                result = self.run_case(options)
                self.assertEqual(result.returncode, 2, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
