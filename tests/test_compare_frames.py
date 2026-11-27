"""Authored regression cases for the adapted peer frame comparator."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compare_frames.py"
if not SCRIPT.exists():
    SCRIPT = Path(__file__).with_name("compare_frames.py")
spec = importlib.util.spec_from_file_location("frame_comparison", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FrameComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def image(self, name, data):
        path = self.directory / name
        path.write_bytes(data)
        return path

    def test_raster_whitespace_and_hash_are_pixels(self):
        path = self.image("literal.ppm", b"P6\n1 1\n255\n\x0a\x20#")
        self.assertEqual(module.read_ppm(path), (1, 1, b"\x0a\x20#"))

    def test_comments_crlf(self):
        path = self.image("comment.ppm", b"P6\r\n# authored\r\n1 1\r\n255\r\n\x00\x01\x02")
        self.assertEqual(module.read_ppm(path), (1, 1, b"\x00\x01\x02"))

    def test_invalid_files_fail(self):
        for data in (b"", b"P6", b"P6\n#unterminated", b"P6\n0 1\n255\n",
                     b"P6\n1 1\n65535\n123", b"P6\n1 1\n255\n12",
                     b"P6\n1 1\n255\n1234", b"P6\n999999999 3\n255\n123"):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    module.read_ppm(self.image("bad.ppm", data))

    def test_cli_equal_difference_and_exclusive_output(self):
        left = self.image("left.ppm", b"P6\n2 1\n255\n" + b"\x01\x02\x03" * 2)
        right = self.image("right.ppm", b"P6\n2 1\n255\n" + b"\x01\x02\x03\xff\x00\x00")
        same = subprocess.run([sys.executable, str(SCRIPT), str(left), str(left)], capture_output=True)
        self.assertEqual(same.returncode, 0, same.stderr)
        out = self.directory / "diff"
        args = [sys.executable, str(SCRIPT), str(left), str(right), "--png", str(out)]
        different = subprocess.run(args, capture_output=True)
        self.assertEqual(different.returncode, 1, different.stderr)
        self.assertIn(b"x=1, y=0", different.stdout)
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        self.assertEqual(set(before), {"reference.png", "ours.png", "diff.png"})
        subprocess.run(args, capture_output=True)
        self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})


if __name__ == "__main__":
    unittest.main()
