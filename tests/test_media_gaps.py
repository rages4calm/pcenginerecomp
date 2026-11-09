"""Issue #3: authored metadata only; no compressed CHD or game bytes."""
from collections import OrderedDict
from pathlib import Path
import ctypes
import struct
import tempfile
import unittest
from unittest.mock import Mock

from pcerecomp.media import Chd, ChdReader, IsoReader, MediaError

ROWS = [
    b"TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:3 PREGAP:0 PGTYPE:MODE1 PGSUB:NONE POSTGAP:2",
    b"TRACK:2 TYPE:MODE1_RAW SUBTYPE:NONE FRAMES:5 PREGAP:2 PGTYPE:VMODE1_RAW PGSUB:NONE POSTGAP:3",
    b"TRACK:3 TYPE:MODE1 SUBTYPE:NONE FRAMES:2 PREGAP:1 PGTYPE:MODE1 PGSUB:NONE POSTGAP:4",
]


def image(records, logical_frames=16):
    header = bytearray(124)
    struct.pack_into(">8sII", header, 0, b"MComprHD", 124, 5)
    struct.pack_into(">QQQII", header, 32, logical_frames * 2448, 0, 124, 8 * 2448, 2448)
    for index, (tag, payload) in enumerate(records):
        following = len(header) + 16 + len(payload) if index + 1 < len(records) else 0
        header.extend(struct.pack(">4sIQ", tag, len(payload), following) + payload)
    return header


class ThreeTrackMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'authored.chd'

    def load(self, records=None, logical_frames=16):
        self.path.write_bytes(image(records or [(b'CHT2', r + b'\0') for r in ROWS], logical_frames))
        return Chd(self.path)

    def test_three_track_postgaps_keep_disc_and_storage_coordinates_distinct(self):
        disc = self.load()
        # Independent table: CHD tracks occupy 4, 8, 4 frames. Disc gaps consume
        # no extra stored frames; track2's first two stored frames are INDEX00.
        self.assertEqual([(t.disc_start, t.chd_start, t.index1_frame, t.data_frames)
                          for t in disc.tracks], [(0, 0, 0, 3), (7, 4, 6, 3), (14, 12, 12, 2)])
        self.assertEqual(disc.logical_bytes, 16 * 2448)
        self.assertEqual([t.postgap for t in disc.tracks], [2, 3, 4])
        reader = ChdReader.__new__(ChdReader)
        reader.disc = disc
        queries = []
        allowed = {0, 1, 2, 6, 7, 8, 12, 13}
        def frame(number):
            self.assertIn(number, allowed, 'padding/pregap must never supply user data')
            queries.append(number)
            payload = bytes([number + 32]) * 2048
            if number in (6, 7, 8):
                return b'\0' + b'\xff' * 10 + b'\0' + b'\0\0\0\x01' + payload + bytes(384)
            return payload + bytes(400)
        reader.frame = frame
        for lba, stored in ((0, 0), (1, 1), (2, 2), (7, 6), (8, 7), (9, 8), (14, 12), (15, 13)):
            self.assertEqual(reader.lba(lba), bytes([stored + 32]) * 2048)
        self.assertEqual(queries, [0, 1, 2, 6, 7, 8, 12, 13])
        for lba in (-1, 3, 4, 5, 6, 10, 11, 12, 13, 16, 17, 18, 19, 20, 0xFFFFFFFF):
            with self.subTest(lba=lba), self.assertRaises(MediaError):
                reader.lba(lba)
        for track in disc.tracks:
            for relative in (-1, track.data_frames):
                with self.assertRaises(MediaError):
                    reader.sector(track, relative)
        self.assertEqual(len(queries), 8)

    def test_multiple_metadata_records_and_legacy_track_do_not_shift_frames(self):
        records = [(b'NOTE', b'authored ignored metadata'), (b'CHTR', b'TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:3\0'),
                   (b'NOTE', b'second non-track record'),
                   (b'CHT2', ROWS[1] + b'\0'), (b'CHT2', ROWS[2] + b'\0')]
        disc = self.load(records)
        # Legacy track1 has no postgap: following disc starts are two earlier.
        self.assertEqual([(t.disc_start, t.index1_frame) for t in disc.tracks], [(0, 0), (5, 6), (12, 12)])
        self.assertEqual([t.chd_start for t in disc.tracks], [0, 4, 12])

    def test_track_order_duplicates_and_malformed_fields_refuse(self):
        for rows in ([ROWS[1], ROWS[0], ROWS[2]], [ROWS[0], ROWS[0], ROWS[2]],
                     [ROWS[0], ROWS[2]],
                     [ROWS[0], ROWS[1].replace(b'POSTGAP:3', b'POSTGAP:-1'), ROWS[2]],
                     [ROWS[0], ROWS[1] + b' POSTGAP:4', ROWS[2]],
                     [ROWS[0], ROWS[1].replace(b'FRAMES:5', b'FRAMES:no'), ROWS[2]],
                     [ROWS[0], ROWS[1] + b' malformed', ROWS[2]]):
            with self.subTest(rows=rows), self.assertRaises(MediaError):
                self.load([(b'CHT2', r + b'\0') for r in rows])

    def test_truncated_headers_payloads_and_invalid_links_refuse(self):
        good = image([(b'CHT2', r + b'\0') for r in ROWS])
        for end in (0, 8, 123, 130, len(good) - 1):
            self.path.write_bytes(good[:end])
            with self.subTest(end=end), self.assertRaises(MediaError):
                Chd(self.path)
        for offset in (1, len(good), len(good) - 15, 124):
            bad = bytearray(good); struct.pack_into('>Q', bad, 132, offset)
            self.path.write_bytes(bad)
            with self.subTest(offset=offset), self.assertRaises(MediaError):
                Chd(self.path)

    def test_noninteger_addresses_refuse_before_reading(self):
        disc = self.load()
        reader = ChdReader.__new__(ChdReader); reader.disc = disc; reader.handle = True
        reader.frame = Mock(side_effect=AssertionError('invalid request reached frame reader'))
        iso_path = Path(self.temp.name) / 'authored.iso'; iso_path.write_bytes(bytes(2048))
        iso = IsoReader(iso_path)
        for value in (True, False, 0.5, '0', None, float('inf'), float('nan')):
            with self.subTest(value=value):
                for call in (lambda: reader.lba(value), lambda: reader.sector(disc.tracks[0], value), lambda: iso.sector(value)):
                    with self.assertRaises(MediaError):
                        call()
                with self.assertRaises(MediaError):
                    ChdReader.frame(reader, value)
        reader.frame.assert_not_called()

    def test_decoder_hunk_range_is_checked_without_allocating_disc_data(self):
        # chd_read accepts uint32_t hunknum. Huge *metadata* must not wrap it.
        frames = 8 * (0x100000000 + 1)
        disc = self.load([(b'CHT2', f'TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:{frames}'.encode() + b'\0')], frames)
        reader = ChdReader.__new__(ChdReader)
        reader.disc, reader.handle = disc, True
        reader.cache, reader.hunks_read = OrderedDict(), 0
        reader.lib = Mock()
        reader.lib.chd_read.side_effect = AssertionError('unrepresentable hunk reached decoder')
        with self.assertRaisesRegex(MediaError, '32-bit'):
            reader.frame(8 * 0x100000000)
        reader.lib.chd_read.assert_not_called()
        self.assertEqual(reader.hunks_read, 0)
        # The last representable hunk is passed through unchanged, not rejected
        # by an off-by-one guard. No real decoder or giant backing file is used.
        def decode(handle, hunk, buffer):
            self.assertEqual(hunk, 0xFFFFFFFF)
            ctypes.memset(buffer, 0x5A, disc.hunk_bytes)
            return 0
        reader.lib.chd_read.side_effect = decode
        self.assertEqual(reader.frame(8 * 0xFFFFFFFF), bytes([0x5A]) * 2448)
        self.assertEqual(reader.hunks_read, 1)
