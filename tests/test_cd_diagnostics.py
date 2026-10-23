"""Authored command traffic, never retail data, through the actual host."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
HEADLESS=Path(os.environ.get('PCE_TEST_HEADLESS', ROOT/'build'/('pce-headless.exe' if os.name=='nt' else 'pce-headless')))

@unittest.skipUnless(HEADLESS.is_file(), 'Build headless runner')
class UnknownCdDiagnosticsTests(unittest.TestCase):
    def test_strict_and_reference_attempts_retain_the_original_command_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bios=root/'authored-firmware.pce';bios.write_bytes(bytes(262144))
            # Select, allow the real 75,000-tick command deadline to pass with
            # one authored block transfer, then write the unknown CDB and ACK.
            prefix=[0xA9,0,0x8D,0,0x18,0x73,0,0x60,0,0x80,0x88,0x13,0xA9,0xFF]
            command_pc=0x4000+len(prefix)
            image=root/'authored.bin'
            image.write_bytes(bytes(prefix+[0x8D,1,0x18,0xA9,0x80,0x8D,2,0x18,0xA9,0,0x8D,2,0x18,0x80,0xFE]))
            for policy in ('fault','gear-good'):
                result=subprocess.run([str(HEADLESS),str(image),'0x100000','0x4000',
                    '255,248,128,129,130,131,132,0','40','10000000','hybrid',
                    '--bios',str(bios),'--cd-unknown-status',policy],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,3 if policy=='fault' else 0,result.stderr)
                report=json.loads(result.stdout)
                observed=report['cd_unknown']
                self.assertEqual(observed['opcodes'],[{'opcode':255,'attempts':1}])
                self.assertEqual(observed['last_command'],[255])
                self.assertEqual(observed['accepted_responses'],int(policy=='gear-good'))
                origin=observed['origin']
                self.assertEqual(origin['pc'],command_pc)
                self.assertEqual(origin['physical_pc'],0x100000+len(prefix))
                self.assertEqual(origin['mpr'],[255,248,128,129,130,131,132,0])
                self.assertEqual(origin['fetch'],[0x8D,1,0x18,0xA9,0x80,0x8D,2])
                self.assertGreaterEqual(origin['ticks'],75000)
                if policy=='fault':
                    self.assertIn('unsupported CD command $FF',result.stderr)

if __name__=='__main__':unittest.main()
