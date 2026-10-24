"""Authored BIN/CUE geometry, source identity, refusal and CLI checks."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from pcerecomp.cli import main
from pcerecomp.cue import Cue
from pcerecomp.media import MediaError
from pcerecomp.toc import Toc
from cue_fixture import definitions, expected, write_case, composite_identity


def data(seed):
    return bytes((seed + n * 17 + (n >> 8)) & 255 for n in range(2048))


def raw_data(seed):
    return b"\0" + b"\xff" * 10 + b"\0" + b"\0\0\0\1" + data(seed) + bytes(288)


def audio(seed):
    return struct.pack("<1176h", *(int((seed + n * 131) % 65536) - 32768 for n in range(1176)))


class CueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cue = self.root / "disc.cue"
        (self.root / "data.bin").write_bytes(data(1) + data(2) + data(3))
        (self.root / "audio.bin").write_bytes(audio(7) + audio(8))

    def write(self, text):
        self.cue.write_text(text, encoding="utf-8", newline="\n")
        return Cue(self.cue)

    def multi(self):
        return self.write('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n  INDEX 01 00:00:00\n'
                          'FILE "audio.bin" BINARY\n TRACK 02 AUDIO\n  PREGAP 00:00:02\n  INDEX 01 00:00:00\n')

    def cli(self, *args):
        out, error = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(error):
            code = main(list(map(str, args)))
        return code, out.getvalue(), error.getvalue()

    def test_mixed_files_and_virtual_gap_use_disc_not_file_offsets(self):
        disc = self.multi()
        self.assertEqual([(t.number, t.type, t.disc_start, t.data_frames) for t in disc.tracks],
                         [(1, "MODE1", 0, 3), (2, "AUDIO", 5, 2)])
        self.assertEqual(disc.leadout_lba, 7)
        self.assertEqual(disc.read(0), data(1))
        self.assertEqual(disc.read(2), data(3))
        self.assertEqual(disc.read_audio(5), struct.unpack("<1176h", audio(7)))
        self.assertFalse(disc.audio_playable(3))
        self.assertFalse(disc.audio_playable(4))
        self.assertTrue(disc.audio_playable(5))
        for lba in (-1, 3, 4, 5, 7, True):
            with self.subTest(lba=lba), self.assertRaises(MediaError):
                disc.read(lba)
        for lba in (0, 3, 4, 7, True):
            with self.subTest(lba=lba), self.assertRaises(MediaError):
                disc.read_audio(lba)

    def test_shared_authored_media_match_independently_declared_geometry_and_bytes(self):
        for case in definitions():
            with self.subTest(case=case["id"]):
                path = write_case(self.root / case["id"], case)
                disc = Cue(path)
                wanted = expected(case)
                self.assertEqual(disc.leadout_lba, wanted["leadout"])
                self.assertEqual([[t.disc_start, 0 if t.type == "AUDIO" else 4] for t in disc.tracks], wanted["tracks"])
                self.assertEqual(disc.image_sha256(), composite_identity(path, case))
                for observation in wanted["observations"]:
                    op, lba = observation["op"], observation["lba"]
                    if op == "p":
                        self.assertIs(disc.audio_playable(lba), observation["playable"])
                    elif op == "d":
                        self.assertEqual(disc.read(lba).hex(), observation["bytes"])
                    else:
                        self.assertEqual(list(disc.read_audio(lba)), observation["samples"])

    def test_stored_pregap_retains_audio_bytes_but_gates_data_to_audio(self):
        frames = raw_data(11) + raw_data(12) + b"".join(audio(n) for n in range(2, 8))
        (self.root / "mixed.bin").write_bytes(frames)
        disc = self.write('FILE "mixed.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n'
                          ' TRACK 02 AUDIO\n INDEX 00 00:00:02\n INDEX 01 00:00:03\n'
                          ' TRACK 03 AUDIO\n INDEX 00 00:00:05\n INDEX 01 00:00:06\n')
        self.assertEqual([t.disc_start for t in disc.tracks], [0, 3, 6])
        self.assertEqual([t.data_frames for t in disc.tracks], [2, 2, 2])
        self.assertEqual(disc.leadout_lba, 8)
        self.assertEqual(disc.read(1), data(12))
        self.assertEqual(disc.read_audio(2), struct.unpack("<1176h", audio(2)))
        self.assertEqual(disc.read_audio(5), struct.unpack("<1176h", audio(5)))
        self.assertFalse(disc.audio_playable(2))
        self.assertTrue(disc.audio_playable(3))
        self.assertTrue(disc.audio_playable(5))
        self.assertFalse(disc.audio_playable(8))

    def test_compound_digest_is_independent_literal_encoding_and_relocatable(self):
        disc = self.multi()
        h = lambda raw: hashlib.sha256(raw).hexdigest()
        cue_raw = self.cue.read_bytes()
        expected = f"PCE-CUE-1\ncue\t{len(cue_raw)}\t{h(cue_raw)}\n"
        for name in ("data.bin", "audio.bin"):
            raw = (self.root / name).read_bytes()
            expected += f"file\t{name}\t{len(raw)}\t{h(raw)}\n"
        expected = h(expected.encode("utf-8"))
        self.assertEqual(disc.image_sha256(), expected)
        elsewhere = self.root / "relocated"
        elsewhere.mkdir()
        for name in ("data.bin", "audio.bin"):
            shutil.copyfile(self.root / name, elsewhere / name)
        shutil.copyfile(self.cue, elsewhere / "renamed.cue")
        self.assertEqual(Cue(elsewhere / "renamed.cue").image_sha256(), expected)
        (elsewhere / "renamed.cue").write_bytes(cue_raw + b"REM geometry unchanged\n")
        self.assertNotEqual(Cue(elsewhere / "renamed.cue").image_sha256(), expected)

    def test_identity_includes_audio_and_all_source_files(self):
        original = self.multi().image_sha256()
        (self.root / "audio.bin").write_bytes(audio(99) + audio(8))
        self.assertNotEqual(Cue(self.cue).image_sha256(), original)

    def test_every_read_checks_unselected_component_mutation(self):
        disc = self.multi()
        target = self.root / "audio.bin"
        stamp = target.stat()
        target.write_bytes(audio(99) + audio(8))
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
        for operation in (lambda: disc.read(0), lambda: disc.read_audio(5),
                          lambda: disc.audio_playable(0), disc.image_sha256, disc.report):
            with self.subTest(operation=operation), self.assertRaisesRegex(MediaError, "changed"):
                operation()

    def test_descriptor_mutation_invalidates_reads(self):
        disc = self.multi()
        self.cue.write_bytes(self.cue.read_bytes() + b"REM mutation\n")
        with self.assertRaisesRegex(MediaError, "changed"):
            disc.read(0)

    def test_utf8_bom_case_and_backslash_filename_normalization(self):
        directory = self.root / "sub"
        directory.mkdir()
        (directory / "audio snowman \N{SNOWMAN}.bin").write_bytes(audio(0))
        text = 'file "sub\\audio snowman \N{SNOWMAN}.bin" binary\n track 1 audio\n index 1 00:00:00\n'
        self.cue.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        disc = Cue(self.cue)
        self.assertEqual(list(disc.referenced_files), ["sub/audio snowman \N{SNOWMAN}.bin"])
        self.assertEqual(disc.read_audio(0)[0], -32768)
        self.assertEqual(Toc.from_image(self.cue).tracks[0].type, 0)

    def test_raw_header_refusal_before_returning_user_data(self):
        (self.root / "bad.bin").write_bytes(bytes(2352))
        disc = self.write('FILE "bad.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n')
        with self.assertRaisesRegex(MediaError, "raw sector header"):
            disc.read(0)

    def test_explicit_unsupported_and_malformed_layouts_refuse(self):
        prefix = 'FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n'
        good = prefix + ' INDEX 01 00:00:00\n'
        cases = [
            "", 'FILE "data.bin" WAVE\n', 'FILE "data.bin" BINARY\n',
            prefix, prefix + 'INDEX 01 00:00:01\n', prefix + 'INDEX 01 00:60:00\n',
            prefix + 'INDEX 01 00:00:75\n', prefix + 'INDEX 01 0:00:00\n',
            prefix + 'INDEX 01 00:00:00\nINDEX 01 00:00:01\n',
            prefix + 'INDEX 01 00:00:00\nINDEX 00 00:00:00\n',
            good + 'INDEX 02 00:00:01\n', good + 'POSTGAP 00:00:01\n',
            good + 'FLAGS PRE\n', good + 'UNKNOWN value\n',
            good + 'TITLE\n', good + 'REM\x01 control\n', good + 'TITLE "embedded\rcarriage"\n',
            good + 'TRACK 03 MODE1/2048\nINDEX 01 00:00:01\n',
            good + 'TRACK 02 AUDIO\nINDEX 01 00:00:01\n',
            good + 'TRACK 02 MODE1/2048\nINDEX 01 00:00:00\n',
            good + 'TRACK 02 MODE1/2048\nINDEX 01 00:00:03\n',
            good + 'TRACK 02 MODE1/2048\nINDEX 00 00:00:02\nINDEX 01 00:00:01\n',
            good + 'TRACK 02 MODE1/2048\nPREGAP 00:00:01\nINDEX 00 00:00:01\nINDEX 01 00:00:02\n',
            good + 'PREGAP 00:00:01\n', prefix + 'PREGAP 00:00:01\nPREGAP 00:00:02\nINDEX 01 00:00:00\n',
            good + 'FILE "data.bin" BINARY\nTRACK 02 MODE1/2048\nINDEX 01 00:00:00\n',
            good + 'FILE "DATA.BIN" BINARY\nTRACK 02 MODE1/2048\nINDEX 01 00:00:00\n',
            prefix + 'INDEX 01 00:00:00\x00\n', 'FILE "data.bin BINARY\n',
            'FILE "data.bin"x BINARY\n', 'INDEX 01 00:00:00\n',
            good.replace("FILE", '"FILE"'), good.replace("TRACK", '"TRACK"'),
            good.replace("FILE", "f\u0131le"), good.replace("BINARY", "b\u0131nary"),
            good + 'FILE "audio.bin" BINARY\nTRACK 02 AUDIO\nINDEX 01 00:00:01\n',
            good.replace("MODE1/2048", "MODE2/2352"), good.replace("TRACK 01", "TRACK 001"),
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises((MediaError, OSError)):
                self.write(text)

    def test_unsafe_component_names_refuse(self):
        for name in ("../data.bin", "/data.bin", "C:drive.bin", "sub/../data.bin", "./data.bin",
                     "sub//data.bin", "NUL.bin", "sub/COM1.extra.bin", "data.bin ", "data.bin.",
                     "data?.bin", "data\t.bin", "sub|bad.bin"):
            with self.subTest(name=name), self.assertRaises(MediaError):
                self.write(f'FILE "{name}" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n')

    def test_bounds_empty_partial_and_descriptor_encoding(self):
        for size in (0, 2049):
            (self.root / "wrong.bin").write_bytes(bytes(size))
            with self.subTest(size=size), self.assertRaises(MediaError):
                self.write('FILE "wrong.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n')
        self.cue.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaisesRegex(MediaError, "1 MiB"):
            Cue(self.cue)
        self.cue.write_bytes(b"\xff")
        with self.assertRaisesRegex(MediaError, "UTF-8"):
            Cue(self.cue)

    def test_symlink_escape_and_retarget_refuse(self):
        target = self.root / "link.bin"
        outside = self.root.parent / (self.root.name + "-external.bin")
        outside.write_bytes(data(9))
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        try:
            target.symlink_to(self.root / "data.bin")
        except OSError:
            self.skipTest("Symlink creation unavailable")
        disc = self.write('FILE "link.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n')
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(MediaError, "target changed"):
            disc.read(0)
        with self.assertRaisesRegex(MediaError, "escapes"):
            Cue(self.cue)

    def test_cli_inspect_and_toc_include_complete_image_identity(self):
        disc = self.multi()
        code, output, _ = self.cli("inspect", self.cue, "--hash")
        self.assertEqual(code, 0)
        report = json.loads(output)
        self.assertEqual(report["image_sha256"], disc.image_sha256())
        self.assertEqual(report["file_sha256"], hashlib.sha256(self.cue.read_bytes()).hexdigest())
        self.assertEqual([item["name"] for item in report["files"]], ["data.bin", "audio.bin"])
        code, output, _ = self.cli("toc", self.cue, "--out", self.root / "toc.txt")
        self.assertEqual(code, 0)
        self.assertIn(f"image_sha256 {disc.image_sha256()}\nleadout_lba 7\ntrack 1 0 4\ntrack 2 5 0\n", output)

    def test_cli_outputs_cannot_replace_referenced_input_or_hardlink(self):
        self.multi()
        original = (self.root / "data.bin").read_bytes()
        alias = self.root / "hardlink.out"
        os.link(self.root / "data.bin", alias)
        for command in ("inspect", "toc"):
            for output in (self.root / "data.bin", alias):
                with self.subTest(command=command, output=output):
                    code, _, error = self.cli(command, self.cue, "--out", output)
                    self.assertEqual(code, 2)
                    self.assertIn("aliases", error)
                    self.assertEqual((self.root / "data.bin").read_bytes(), original)

    def test_cli_boot_extracts_authored_raw_ipl_with_track_relative_coordinates(self):
        ipl = bytearray(2048)
        ipl[:4] = bytes((0, 0, 2, 1))
        struct.pack_into("<HH", ipl, 4, 0x4000, 0x4000)
        ipl[8:13] = bytes(range(5))
        ipl[32:56] = b"PC Engine CD-ROM SYSTEM\0"
        sectors = [bytes(2048), bytes(ipl), data(67)]
        frames = [b"\0" + b"\xff" * 10 + b"\0" + b"\0\0\0\1" + part + bytes(288) for part in sectors]
        (self.root / "boot.bin").write_bytes(b"".join(frames))
        disc = self.write('FILE "audio.bin" BINARY\nTRACK 01 AUDIO\nINDEX 01 00:00:00\n'
                          'FILE "boot.bin" BINARY\nTRACK 02 MODE1/2352\nPREGAP 00:00:02\nINDEX 01 00:00:00\n')
        output = self.root / "extracted"
        code, text, error = self.cli("boot", self.cue, "--out", output)
        self.assertEqual(code, 0, error)
        result = json.loads(text)
        self.assertEqual(result["image_sha256"], disc.image_sha256())
        self.assertEqual(result["transport"]["disc_index1_lba"], 4)
        self.assertEqual(result["transport"]["cue_index1_frame"], 0)
        self.assertEqual((output / "boot-0.bin").read_bytes(), data(67))
        self.assertTrue((output / "snapshot.toml").is_file())


if __name__ == "__main__":
    unittest.main()
