"""Untrusted TOC descriptor and option boundaries using authored inputs only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from pcerecomp.toc import Toc

ROOT = Path(__file__).resolve().parent.parent
NAME = "pce-headless.exe" if os.name == "nt" else "pce-headless"
CANDIDATES = ([Path(os.environ["PCE_TEST_HEADLESS"])] if "PCE_TEST_HEADLESS" in os.environ else
              [ROOT / "build" / NAME, ROOT / "build/Release" / NAME])
BINARY = next((p for p in CANDIDATES if p.is_file()), None)
VALID = "PCE_TOC 1\nimage_sha256 " + "e" * 64 + "\nleadout_lba 600\ntrack 1 0 4\ntrack 2 300 0\n"


@unittest.skipUnless(BINARY, "Build pce-headless for the synthetic TOC boundary checks")
class HeadlessTocTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.image = self.root / "program.bin"
        self.image.write_bytes(bytes([0xEA]))  # Authored NOP, not a disc excerpt.
        self.toc = self.root / "disc.toc"
        self.firmware = self.root / "synthetic.pce"

    def tearDown(self):
        self.tmp.cleanup()

    def run_case(self, descriptor=VALID, options=None):
        raw = descriptor.encode("ascii") if isinstance(descriptor, str) else descriptor
        self.toc.write_bytes(raw)
        extras = ["--toc", str(self.toc)] if options is None else options
        command = [str(BINARY), str(self.image), "0x100000", "0x4000",
                   "255,248,128,129,130,131,132,0", "1", "1000", "hybrid", *extras]
        original_firmware = self.firmware.read_bytes() if self.firmware.exists() else None
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        self.assertEqual(self.image.read_bytes(), bytes([0xEA]))
        self.assertEqual(self.toc.read_bytes(), raw)
        if original_firmware is not None:
            self.assertEqual(self.firmware.read_bytes(), original_firmware)
        return result

    def assert_invalid(self, descriptor):
        result = self.run_case(descriptor)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())

    def test_toc_without_bios_enables_only_the_transport_profile(self):
        result = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["stop"], "step_limit")
        self.assertEqual(state["pc"], 0x4001)
        self.assertTrue(state["cd_control"]["enabled"])
        self.assertTrue(state["scsi"]["enabled"])
        self.assertFalse(state["vdc"]["enabled"])
        self.assertEqual(state["toc"], {"attached": True, "image_sha256": "e" * 64,
                                       "track_count": 2, "leadout_lba": 600})

    def test_exported_iso_descriptor_is_accepted_without_opening_a_sector_backend(self):
        iso = self.root / "authored.iso"
        iso.write_bytes(bytes(7 * 2048))
        exported = Toc.from_image(iso)
        result = self.run_case(exported.text())
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["toc"], {"attached": True, "image_sha256": exported.image_sha256,
                                       "track_count": 1, "leadout_lba": 7})
        self.assertEqual(iso.read_bytes(), bytes(7 * 2048))

    def test_bios_and_toc_options_work_in_both_orders(self):
        self.firmware.write_bytes(bytes(262144))
        for order in (["--bios", str(self.firmware), "--toc", str(self.toc)],
                      ["--toc", str(self.toc), "--bios", str(self.firmware)]):
            with self.subTest(order=order):
                result = self.run_case(options=order)
                self.assertEqual(result.returncode, 0, result.stderr)
                state = json.loads(result.stdout)
                self.assertTrue(state["toc"]["attached"])
                self.assertTrue(state["scsi"]["enabled"])
                self.assertTrue(state["raster"]["enabled"])

    def test_absent_options_keep_original_firmware_free_profile(self):
        result = self.run_case(options=[])
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertFalse(state["toc"]["attached"])
        self.assertFalse(state["cd_control"]["enabled"])
        self.assertFalse(state["scsi"]["enabled"])

    def test_descriptor_size_limit_accepts_8192_and_rejects_8193(self):
        padded = VALID + " " * (8192 - len(VALID))
        result = self.run_case(padded)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_invalid(padded + " ")
        self.assert_invalid(b"")

    def test_version_keywords_truncation_and_trailing_tokens_are_rejected(self):
        for text in (VALID.replace("PCE_TOC 1", "PCE_TOC 2"),
                     VALID.replace("image_sha256", "image_hash"),
                     VALID.replace("leadout_lba", "leadout"),
                     VALID.rsplit(" 0", 1)[0],
                     VALID + "extra\n", VALID + "leadout_lba 700\n"):
            with self.subTest(text=text):
                self.assert_invalid(text)

    def test_invalid_hashes_and_non_ascii_or_control_bytes_are_rejected(self):
        for text in (VALID.replace("e" * 64, "e" * 63),
                     VALID.replace("e" * 64, "E" * 64),
                     VALID.replace("e" * 64, "g" * 64),
                     VALID.encode("ascii") + b"\0",
                     VALID.encode("ascii") + b"\x1b",
                     VALID.encode("ascii") + "é".encode("utf-8")):
            with self.subTest(text=text):
                self.assert_invalid(text)

    def test_invalid_decimal_range_order_numbers_and_types_are_rejected(self):
        for text in (VALID.replace("leadout_lba 600", "leadout_lba 0"),
                     VALID.replace("leadout_lba 600", "leadout_lba 449850"),
                     VALID.replace("leadout_lba 600", "leadout_lba 4294967296"),
                     VALID.replace("track 1 0 4", "track 1 -1 4"),
                     VALID.replace("track 1 0 4", "track 1 0x0 4"),
                     VALID.replace("track 1 0 4", "track 0 0 4"),
                     VALID.replace("track 2 300 0", "track 3 300 0"),
                     VALID.replace("track 2 300 0", "track 2 0 0"),
                     VALID.replace("track 2 300 0", "track 2 600 0"),
                     VALID.replace("track 1 0 4", "track 1 400 4"),
                     VALID.replace("track 1 0 4", "track 1 0 1"),
                     VALID.split("track", 1)[0]):
            with self.subTest(text=text):
                self.assert_invalid(text)

    def test_track_count_and_maximum_bcd_geometry_boundaries(self):
        header = "PCE_TOC 1\nimage_sha256 " + "a" * 64 + "\nleadout_lba 449849\n"
        tracks = "".join(f"track {i + 1} {i} 4\n" for i in range(99))
        result = self.run_case(header + tracks)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual((state["toc"]["track_count"], state["toc"]["leadout_lba"]), (99, 449849))
        self.assert_invalid(header + tracks + "track 100 100 4\n")

    def test_duplicate_unknown_and_missing_option_values_are_rejected(self):
        for options in (["--toc", str(self.toc), "--toc", str(self.toc)],
                        ["--bios", str(self.firmware), "--bios", str(self.firmware)],
                        ["--disc", str(self.toc)], ["--toc"]):
            with self.subTest(options=options):
                result = self.run_case(options=options)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
