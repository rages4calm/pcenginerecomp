"""Public host/controller checks use authored opcodes and synthetic firmware only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
NAME = "pce-headless.exe" if os.name == "nt" else "pce-headless"
CANDIDATES = ([Path(os.environ["PCE_TEST_HEADLESS"])] if "PCE_TEST_HEADLESS" in os.environ else
              [ROOT / "build" / NAME, ROOT / "build/Release" / NAME])
BINARY = next((p for p in CANDIDATES if p.is_file()), None)
TOC = "PCE_TOC 1\nimage_sha256 " + "a" * 64 + "\nleadout_lba 300\ntrack 1 0 4\n"


def write_port(value, address=0x1000):
    return bytes([0xA9, value, 0x8D, address & 255, address >> 8])


def read_port(address=0x1000):
    return bytes([0xAD, address & 255, address >> 8])


@unittest.skipUnless(BINARY, "Build pce-headless for synthetic controller host checks")
class HeadlessJoypadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.image = self.root / "authored.bin"
        self.firmware = self.root / "synthetic.pce"
        self.toc = self.root / "metadata.toc"
        self.toc.write_text(TOC, encoding="ascii")

    def tearDown(self):
        self.tmp.cleanup()

    def run_program(self, program=bytes([0xEA]), steps=1, options=()):
        self.image.write_bytes(program)
        before = {p: p.read_bytes() for p in (self.image, self.toc, self.firmware) if p.exists()}
        result = subprocess.run([str(BINARY), str(self.image), "0x100000", "0x4000",
                                 "255,248,128,129,130,131,132,0", str(steps), "100000", "hybrid",
                                 *options], capture_output=True, text=True, timeout=5)
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents, str(path))
        return result

    def state(self, program=bytes([0xEA]), steps=1, options=()):
        result = self.run_program(program, steps, options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_disabled_profile_refuses_controller_access(self):
        state = self.state()
        self.assertFalse(state["joypad"]["enabled"])
        result = self.run_program(read_port())
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["stop"], "bus_fault")

    def test_each_controller_option_enables_profile(self):
        for options in (["--joypad", "2"], ["--joypad-region", "usa"],
                        ["--multitap", "off"], ["--buttons", "0"]):
            with self.subTest(options=options):
                state = self.state(options=options)
                self.assertTrue(state["joypad"]["enabled"])
                self.assertFalse(state["scsi"]["enabled"])
                self.assertFalse(state["vdc"]["enabled"])

    def test_bios_and_metadata_profiles_enable_released_usa_pad(self):
        self.firmware.write_bytes(bytes(262144))
        for options in (["--bios", str(self.firmware)], ["--toc", str(self.toc)]):
            with self.subTest(options=options):
                state = self.state(write_port(0) + read_port(), 3, options)
                self.assertEqual(state["a"], 0x3F)
                self.assertTrue(state["joypad"]["enabled"])

    def test_region_presence_and_opposite_directions_remain_explicit(self):
        for region, expected in (("usa", 0xBF), ("japan", 0xFF)):
            with self.subTest(region=region):
                state = self.state(write_port(0) + read_port(0x13FF), 3,
                                   ["--joypad-region", region])
                self.assertEqual(state["a"], expected)
        state = self.state(write_port(1) + read_port(), 3,
                           ["--joypad", "2", "--joypad-region", "usa", "--buttons", "0xF0"])
        self.assertEqual(state["a"], 0xB0)

    def test_two_button_pressed_snapshot_and_full_window_alias(self):
        state = self.state(write_port(0xFC, 0x13FF) + read_port(0x1000), 3,
                           ["--joypad", "2", "--joypad-region", "usa", "--buttons", "0x5"])
        self.assertEqual(state["a"], 0xBA)
        self.assertEqual(state["interpreter_steps"], 3)

    def test_six_button_bank_and_identifier(self):
        options = ["--joypad", "6", "--joypad-region", "usa", "--buttons", "0x500"]
        state = self.state(write_port(0) + read_port(), 3, options)
        self.assertEqual(state["a"], 0xBA)
        state = self.state(write_port(0) + write_port(1) + read_port(), 5, options)
        self.assertEqual(state["a"], 0xB0)

    def test_multitap_scans_second_snapshot_without_wrap(self):
        options = ["--joypad", "2", "--joypad-region", "usa", "--multitap", "on",
                   "--buttons", "1,8,0,0,0"]
        state = self.state(write_port(0) + write_port(1) + write_port(0) + read_port(), 7, options)
        self.assertEqual(state["a"], 0xB7)
        program = write_port(0) + (write_port(1) + write_port(0)) * 5 + read_port()
        state = self.state(program, 23, options)
        self.assertEqual(state["a"], 0xBF)

    def test_invalid_duplicate_and_missing_options_are_rejected(self):
        for options in (["--joypad", "3"], ["--joypad", "mouse"],
                        ["--joypad-region", "auto"], ["--multitap", "yes"],
                        ["--buttons", "4096"], ["--buttons", "-1"],
                        ["--buttons", ""], ["--buttons", "1,"], ["--buttons", ",1"],
                        ["--buttons", "1,,2"], ["--buttons", "1,2,3,4,5,6"],
                        ["--buttons", "0junk"], ["--joypad"],
                        ["--joypad", "2", "--joypad", "6"],
                        ["--buttons", "0", "--buttons", "1"]):
            with self.subTest(options=options):
                result = self.run_program(options=options)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
