"""Authored geometry and source-protection checks for metadata-only TOC export."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest

from pcerecomp.cli import main
from pcerecomp.media import MediaError
from pcerecomp.toc import MAX_LEADOUT_LBA, Toc, TocTrack


def chd_metadata(tracks):
    """Metadata-only authored CHD; it contains no compressed/retail sectors."""
    blocks = []
    position = 124
    for i, (kind, frames, pregap, stored, postgap) in enumerate(tracks):
        text = (f"TRACK:{i+1} TYPE:{kind} SUBTYPE:NONE FRAMES:{frames} "
                f"PREGAP:{pregap} PGTYPE:{'V' if stored else ''}MODE1 "
                f"PGSUB:NONE POSTGAP:{postgap}\0").encode("ascii")
        following = position + 16 + len(text) if i + 1 < len(tracks) else 0
        blocks.append(struct.pack(">4sIQ", b"CHT2", len(text), following) + text)
        position += 16 + len(text)
    header = bytearray(124)
    struct.pack_into(">8sII", header, 0, b"MComprHD", 124, 5)
    logical = sum((frames + 3) // 4 * 4 for _, frames, _, _, _ in tracks) * 2448
    struct.pack_into(">QQQII", header, 32, logical, position, 124, 8 * 2448, 2448)
    return bytes(header) + b"".join(blocks)


class TocTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def image(self, tracks):
        path = self.root / "authored.chd"
        path.write_bytes(chd_metadata(tracks))
        return path

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(map(str, args)))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_stored_virtual_and_postgaps_use_disc_time_without_chd_padding(self):
        path = self.image([("AUDIO", 10, 0, False, 2),
                           ("MODE1_RAW", 20, 3, True, 4),
                           ("AUDIO", 8, 5, False, 0)])
        toc = Toc.from_image(path)
        # Track 1: [0,10), gap 2. Track 2: pregap [12,15),
        # data [15,32), postgap [32,36). Track 3: pregap [36,41), data [41,49).
        self.assertEqual(toc.tracks, (TocTrack(1, 0, 0), TocTrack(2, 15, 4), TocTrack(3, 41, 0)))
        self.assertEqual(toc.leadout_lba, 49)
        self.assertEqual(toc.image_sha256, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_virtual_gap_does_not_subtract_program_frames(self):
        path = self.image([("MODE1", 7, 3, False, 0)])
        toc = Toc.from_image(path)
        self.assertEqual((toc.tracks[0].index1_lba, toc.leadout_lba), (3, 10))

    def test_first_stored_pregap_has_no_implicit_150_frame_correction(self):
        path = self.image([("AUDIO", 9, 2, True, 0)])
        toc = Toc.from_image(path)
        self.assertEqual((toc.tracks[0].index1_lba, toc.leadout_lba), (2, 9))

    def test_trailing_postgap_is_excluded_by_explicit_gear_reference_rule(self):
        path = self.image([("MODE1", 7, 0, False, 11)])
        self.assertEqual(Toc.from_image(path).leadout_lba, 7)

    def test_exact_canonical_descriptor_has_no_paths_or_150_frame_offset(self):
        value = Toc("a" * 64, 12001, (TocTrack(1, 0, 4), TocTrack(2, 9000, 0)))
        self.assertEqual(value.text(), "PCE_TOC 1\nimage_sha256 " + "a" * 64 +
                         "\nleadout_lba 12001\ntrack 1 0 4\ntrack 2 9000 0\n")

    def test_iso_is_single_data_track_and_original_is_unchanged(self):
        path = self.root / "authored.iso"
        before = bytes(3 * 2048)
        path.write_bytes(before)
        toc = Toc.from_image(path)
        self.assertEqual((toc.leadout_lba, toc.tracks), (3, (TocTrack(1, 0, 4),)))
        self.assertEqual(path.read_bytes(), before)

    def test_empty_and_partial_iso_are_refused(self):
        path = self.root / "bad.iso"
        for length in (0, 2049):
            path.write_bytes(bytes(length))
            with self.subTest(length=length), self.assertRaises(MediaError):
                Toc.from_image(path)

    def test_unsupported_media_and_chd_track_type_are_refused(self):
        with self.assertRaisesRegex(MediaError, "accepts CHD"):
            Toc.from_image(self.root / "image.unsupported")
        path = self.image([("MODE2_RAW", 10, 0, False, 0)])
        with self.assertRaisesRegex(MediaError, "Unsupported TOC track type"):
            Toc.from_image(path)

    def test_bcd_limit_and_99_tracks_are_accepted_without_sector_generation(self):
        toc = Toc("0" * 64, MAX_LEADOUT_LBA, tuple(TocTrack(i + 1, i, i % 2 * 4) for i in range(99)))
        self.assertLessEqual(len(toc.text().encode("ascii")), 8192)
        path = self.image([("MODE1", MAX_LEADOUT_LBA, 0, False, 0)])
        self.assertEqual(Toc.from_image(path).leadout_lba, MAX_LEADOUT_LBA)

    def test_invalid_descriptor_fields_are_refused(self):
        base = Toc("a" * 64, 10, (TocTrack(1, 0, 4),))
        invalid = ({"image_sha256": "A" * 64}, {"image_sha256": "a" * 63},
                   {"leadout_lba": 0}, {"leadout_lba": -1},
                   {"leadout_lba": MAX_LEADOUT_LBA + 1}, {"leadout_lba": True},
                   {"tracks": ()}, {"tracks": tuple(TocTrack(i+1, i, 0) for i in range(100))},
                   {"tracks": (TocTrack(2, 0, 4),)}, {"tracks": (TocTrack(1, 0, 1),)},
                   {"tracks": (TocTrack(1, -1, 4),)}, {"tracks": (TocTrack(1, 10, 4),)},
                   {"tracks": (TocTrack(1, 0, 4), TocTrack(2, 0, 0))},
                   {"tracks": (TocTrack(1, 2, 4), TocTrack(2, 1, 0))})
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(MediaError):
                replace(base, **fields)

    def test_invalid_image_geometry_is_refused(self):
        path = self.image([("MODE1", MAX_LEADOUT_LBA + 1, 0, False, 0)])
        with self.assertRaisesRegex(MediaError, "BCD"):
            Toc.from_image(path)
        path = self.image([("AUDIO", 1, 0, False, 0)] * 100)
        with self.assertRaisesRegex(MediaError, "99 tracks"):
            Toc.from_image(path)

    def test_cli_writes_descriptor_only_and_preserves_source(self):
        path = self.image([("MODE1", 7, 0, False, 0)])
        before = path.read_bytes()
        out = self.root / "metadata" / "disc.toc"
        code, stdout, stderr = self.cli("toc", path, "--out", out)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(out.read_text(encoding="ascii"), stdout)
        self.assertEqual(out.read_bytes().count(b"\n"), 4)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(str(path), stdout)

    def test_cli_refuses_same_path_and_hardlink_output(self):
        path = self.image([("MODE1", 7, 0, False, 0)])
        before = path.read_bytes()
        code, _, error = self.cli("toc", path, "--out", path)
        self.assertEqual(code, 2)
        self.assertIn("aliases", error)
        alias = self.root / "alias.toc"
        try:
            alias.hardlink_to(path)
        except OSError:
            self.assertEqual(path.read_bytes(), before)
            return
        code, _, error = self.cli("toc", path, "--out", alias)
        self.assertEqual(code, 2)
        self.assertIn("aliases", error)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
