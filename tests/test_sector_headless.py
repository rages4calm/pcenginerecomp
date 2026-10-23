"""Authored image attachment and identity boundaries for the headless host."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
BINARY=Path(os.environ.get("PCE_TEST_HEADLESS",str(ROOT/"build"/("pce-headless.exe" if os.name=="nt" else "pce-headless"))))

@unittest.skipUnless(BINARY.is_file(),"Build pce-headless for image attachment checks")
class SectorHostTests(unittest.TestCase):
    def test_disc_identity_and_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); program=root/"program.bin"; program.write_bytes(bytes([0xEA]))
            disc=root/"disc.iso"; payload=bytes(range(256))*16; disc.write_bytes(payload)
            digest=hashlib.sha256(payload).hexdigest()
            descriptor=root/"disc.toc"
            base=[str(BINARY),str(program),"0x100000","0x4000","255,248,128,129,130,131,132,0","1","1000","hybrid"]
            def run(flags):return subprocess.run(base+flags,capture_output=True,text=True,timeout=5)
            ok=run(["--disc",str(disc)])
            self.assertEqual(ok.returncode,0,ok.stderr)
            state=json.loads(ok.stdout)
            self.assertTrue(state["scsi"]["provider_attached"])
            self.assertEqual(state["toc"]["image_sha256"],digest)
            self.assertEqual(state["toc"]["leadout_lba"],2)
            for identity,leadout,track_type in [(digest,2,4),("0"*64,2,4),(digest,3,4),(digest,2,0)]:
                descriptor.write_text(f"PCE_TOC 1\nimage_sha256 {identity}\nleadout_lba {leadout}\ntrack 1 0 {track_type}\n",encoding="ascii")
                result=run(["--toc",str(descriptor),"--disc",str(disc)])
                self.assertEqual(result.returncode,0 if (identity,leadout,track_type)==(digest,2,4) else 2,result.stderr)
                if result.returncode:self.assertIn("mismatch",result.stderr)
            for flags in [["--libchdr","unused"],["--disc",str(disc),"--disc",str(disc)],["--disc",str(root/"missing.iso")]]:
                self.assertEqual(run(flags).returncode,2)
            self.assertEqual(disc.read_bytes(),payload)
