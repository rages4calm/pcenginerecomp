"""Synthetic firmware boundary checks for the compiled developer sandbox."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
NAME = "pce-headless.exe" if os.name=="nt" else "pce-headless"
CANDIDATES = ([Path(os.environ["PCE_TEST_HEADLESS"])] if "PCE_TEST_HEADLESS" in os.environ else
              [ROOT/"build"/NAME, ROOT/"build/Release"/NAME])
BINARY = next((p for p in CANDIDATES if p.is_file()), None)


@unittest.skipUnless(BINARY, "Build pce-headless for the synthetic firmware checks")
class HeadlessFirmwareTests(unittest.TestCase):
    def run_case(self, rom, steps=4, payload=bytes([0x20,0x5A,0xE0,0x80,0xFE])):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            image=root/"program.bin"; image.write_bytes(payload)
            firmware=root/"synthetic.pce"; firmware.write_bytes(rom)
            command=[str(BINARY),str(image),"0x100000","0x4000",
                     "255,248,128,129,130,131,132,0",str(steps),"10000","hybrid","--bios",str(firmware)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=5)
            self.assertEqual(image.read_bytes(),payload)
            self.assertEqual(firmware.read_bytes(),rom)
            return result

    def test_executes_supplied_firmware_service_and_returns(self):
        rom=bytearray(262144)
        rom[0x5A:0x5D]=bytes([0xA9,0x73,0x60])
        result=self.run_case(rom)
        self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads(result.stdout)
        self.assertEqual((state["a"],state["pc"],state["sp"],state["stop"]),(0x73,0x4003,255,"step_limit"))
        self.assertEqual(state["native_steps"]+state["interpreter_steps"],4)

    def test_firmware_is_read_only(self):
        rom=bytearray(262144)
        rom[0x5A:0x5D]=bytes([0x8D,0x5A,0xE0])
        result=self.run_case(rom,steps=2)
        self.assertEqual(result.returncode,3)
        state=json.loads(result.stdout)
        self.assertEqual((state["stop"],state["pc"]),("bus_fault",0xE05A))
        self.assertIn("write to ROM",result.stderr)
        self.assertEqual(state["native_steps"]+state["interpreter_steps"],1)

    def test_rejects_truncated_and_headered_firmware(self):
        for size in (262143,262144+512):
            with self.subTest(size=size):
                result=self.run_case(bytes(size))
                self.assertEqual(result.returncode,2)
                self.assertIn("raw 256 KiB",result.stderr)
