import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.cli import protect_input
from pcerecomp.emitter import emit
from pcerecomp.isa import decode, physical, _ROWS
from pcerecomp.media import Chd, ChdReader, Ipl, IsoReader, MediaError

MPR = (0xFF, 0xF8, 0x80, 0x81, 0x82, 0x83, 0x84, 0)


def snapshot(data, pc=0x4000):
    return Snapshot(MPR, {physical(pc+i, MPR): value for i, value in enumerate(data)}, (pc,), "synthetic")


def chd_bytes(tracks, trailing=b""):
    """Metadata-only fixture, not a real compressed CHD."""
    metadata = bytearray()
    logical_frames = 0
    for i, fields in enumerate(tracks):
        text = fields.encode()+b"\0"
        next_offset = 124+len(metadata)+16+len(text) if i < len(tracks)-1 else 0
        metadata += struct.pack(">4sIQ", b"CHT2", 0x01000000 | len(text), next_offset)+text
        frames = int(fields.split("FRAMES:")[1].split()[0])
        logical_frames += (frames+3)//4*4
    header = bytearray(124)
    struct.pack_into(">8sII", header, 0, b"MComprHD", 124, 5)
    struct.pack_into(">QQQII", header, 32, logical_frames*2448, 124+len(metadata), 124, 8*2448, 2448)
    return header+metadata+trailing


class IsaTests(unittest.TestCase):
    def test_all_opcode_slots_and_special_lengths(self):
        self.assertEqual(len(_ROWS), 256)
        sizes = []
        for op in range(256):
            ins = decode(lambda pc: op if pc == 0x4000 else 0, 0x4000, MPR)
            sizes.append(len(ins.data))
        self.assertEqual(sizes[0x73], 7)
        self.assertEqual(sizes[0x93], 4)
        self.assertEqual(sizes[0x83], 3)
        self.assertEqual(sizes[0xB2], 2)
        self.assertEqual(sizes[0x0F], 3)

    def test_fetch_across_mpr_boundary(self):
        s = snapshot(bytes([0x4C, 0, 0x40]), 0x5FFF)
        ins = decode(s.read, 0x5FFF, MPR)
        self.assertEqual(ins.physical, (0x101FFF, 0x102000, 0x102001))

    def test_fetch_wraps_logical_address(self):
        s = snapshot(bytes([0x4C, 0, 0x40]), 0xFFFF)
        ins = decode(s.read, 0xFFFF, MPR)
        self.assertEqual(ins.physical, (0x1FFF, 0x1FE000, 0x1FE001))

    def test_signed_branch_wrap(self):
        s = snapshot(bytes([0x80, 0xFC]), 0)
        self.assertEqual(decode(s.read, 0, MPR).target, 0xFFFE)


class AnalysisTests(unittest.TestCase):
    def test_output_must_not_alias_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"input.chd"; path.write_bytes(b"owner input")
            with self.assertRaisesRegex(ValueError, "aliases"):
                protect_input(path, path)
            alias = Path(tmp)/"alias.chd"
            try:
                alias.hardlink_to(path)
            except OSError:
                return  # same-path check above is portable; hardlinks may be unavailable
            with self.assertRaisesRegex(ValueError, "aliases"):
                protect_input(path, alias)
            self.assertEqual(path.read_bytes(), b"owner input")

    def test_conditional_follows_both_edges(self):
        result = analyze(snapshot(bytes.fromhex("D0 02 EA 60 60")))
        self.assertEqual({i["pc"] for i in result["instructions"]}, {0x4000, 0x4002, 0x4003, 0x4004})

    def test_tam_terminates_snapshot(self):
        result = analyze(snapshot(bytes.fromhex("53 04 EA")))
        self.assertEqual(len(result["instructions"]), 1)
        self.assertEqual(result["unresolved"][0]["reason"], "mapping_change")

    def test_unseen_bytes_are_explicit(self):
        result = analyze(snapshot(bytes([0x4C, 0, 0x60])))
        self.assertEqual(result["unresolved"], [{"pc": 0x6000, "reason": "bytes_not_in_snapshot"}])

    def test_indirect_jump_not_guessed(self):
        result = analyze(snapshot(bytes.fromhex("6C 00 40")))
        self.assertEqual(result["unresolved"][0]["reason"], "indirect_jump")

    def test_truncated_instruction(self):
        result = analyze(snapshot(bytes([0xA9])))
        self.assertEqual(result["summary"]["instructions"], 0)

    def test_limit_is_enforced(self):
        result = analyze(snapshot(bytes([0xEA]*100)), 5)
        self.assertEqual(result["summary"]["instructions"], 5)
        self.assertIn("instruction_limit", [x["reason"] for x in result["unresolved"]])

    def test_overlapping_decode_refuses_emission(self):
        s = snapshot(bytes.fromhex("4C 01 40"))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "overlapping"):
                emit(analyze(s), Path(tmp))

    def test_native_output_is_direct_and_reproducible(self):
        s = snapshot(bytes.fromhex("A9 2A 85 20 60"))
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            manifest = emit(analyze(s), Path(a))
            emit(analyze(s), Path(b))
            text = (Path(a)/"module.cpp").read_text()
            self.assertEqual(text, (Path(b)/"module.cpp").read_text())
            self.assertNotIn("interpret_step", text)
            self.assertIn("s.a=42", text)
            self.assertIn("bus.peek", text)
            self.assertFalse(manifest["execution_evidence"])

    def test_snapshot_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path/"data.bin").write_bytes(b"\x60")
            (path/"snapshot.toml").write_text('schema=1\nmpr=[255,248,128,129,130,131,132,0]\nentry_points=[16384]\n[[segments]]\nphysical=1048576\nfile="data.bin"\nsha256="wrong"\n')
            with self.assertRaisesRegex(ValueError, "SHA256"):
                Snapshot.load(path/"snapshot.toml")


class MediaTests(unittest.TestCase):
    TRACKS = ["TRACK:1 TYPE:AUDIO SUBTYPE:NONE FRAMES:10 PREGAP:0 PGTYPE:MODE1 PGSUB:NONE POSTGAP:0",
              "TRACK:2 TYPE:MODE1_RAW SUBTYPE:NONE FRAMES:20 PREGAP:3 PGTYPE:VMODE1_RAW PGSUB:NONE POSTGAP:0"]

    def load(self, data):
        path = Path(self.tmp.name)/"test.chd"
        path.write_bytes(data)
        return Chd(path)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_stored_pregap_and_padding_are_distinct(self):
        disc = self.load(chd_bytes(self.TRACKS))
        track = disc.tracks[1]
        self.assertEqual((track.chd_start, track.index1_frame, track.disc_start, track.data_frames), (12, 15, 13, 17))

    def test_virtual_pregap_not_added_to_chd_frame(self):
        tracks = [self.TRACKS[0], self.TRACKS[1].replace("VMODE1_RAW", "MODE1_RAW")]
        track = self.load(chd_bytes(tracks)).tracks[1]
        self.assertEqual((track.index1_frame, track.disc_start, track.data_frames), (12, 13, 20))

    def test_metadata_cycle_rejected(self):
        data = chd_bytes(self.TRACKS)
        struct.pack_into(">Q", data, 132, 124)
        with self.assertRaisesRegex(MediaError, "cyclic"):
            self.load(data)

    def test_parent_chd_rejected(self):
        data = chd_bytes(self.TRACKS); data[104] = 1
        with self.assertRaisesRegex(MediaError, "Parent"):
            self.load(data)

    def test_truncated_metadata_rejected(self):
        with self.assertRaises(MediaError):
            self.load(chd_bytes(self.TRACKS)[:-10])

    def test_logical_size_mismatch(self):
        data = chd_bytes(self.TRACKS); struct.pack_into(">Q", data, 32, 2448)
        with self.assertRaisesRegex(MediaError, "disagree"):
            self.load(data)

    def test_invalid_geometry(self):
        data = chd_bytes(self.TRACKS); struct.pack_into(">I", data, 56, 0xFFFFFFFF)
        with self.assertRaisesRegex(MediaError, "bounded"):
            self.load(data)

    def test_iso_bounded_read(self):
        path = Path(self.tmp.name)/"test.iso"; path.write_bytes(bytes(4096))
        reader = IsoReader(path)
        self.assertEqual(len(reader.sector(1)), 2048)
        for n in (-1, 2):
            with self.assertRaises(MediaError):
                reader.sector(n)

    def test_ipl_fields_endianness(self):
        data = bytearray(2048)
        data[:14] = bytes.fromhex("00 01 23 02 00 40 EB 40 00 01 02 03 04 00")
        data[32:56] = b"PC Engine CD-ROM SYSTEM\0"
        data[0x6A:0x6E] = b"TEST"
        ipl = Ipl.parse(data)
        self.assertEqual((ipl.start_sector, ipl.sector_count, ipl.load_address, ipl.entry_address), (0x123, 2, 0x4000, 0x40EB))
        self.assertEqual(ipl.title, "TEST")

    def test_ipl_signature_required(self):
        with self.assertRaisesRegex(MediaError, "signature"):
            Ipl.parse(bytes(2048))

    def test_raw_mode1_payload(self):
        disc = self.load(chd_bytes(self.TRACKS))
        reader = ChdReader.__new__(ChdReader)
        raw = b"\0"+b"\xff"*10+b"\0"+b"\0\0\0\x01"+b"X"*2048+bytes(384)
        reader.frame = lambda number: raw
        self.assertEqual(reader.sector(disc.tracks[1], 0), b"X"*2048)
        with self.assertRaises(MediaError):
            reader.sector(disc.tracks[1], 17)


if __name__ == "__main__":
    unittest.main()
