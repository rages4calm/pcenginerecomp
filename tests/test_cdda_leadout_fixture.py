"""Original authored CD media/firmware shape, not runtime execution evidence."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

from pcerecomp.toc import Toc

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('leadout_fixture_tests',ROOT/'examples/cdda-leadout/fixture.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)


class LeadoutFixtureTests(unittest.TestCase):
    def test_media_uses_exact_last_track_and_following_leadout_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);info=f.create_media(root);toc=Toc.from_image(info['disc'])
            self.assertEqual((len(toc.tracks),toc.tracks[-1].index1_lba,toc.leadout_lba),(25,50,52))
            self.assertEqual(info['last_track_lba'],50);self.assertEqual(info['leadout_lba'],52)
            self.assertEqual(toc.tracks[0].type,4)
            self.assertTrue(all(track.type==0 for track in toc.tracks[1:]))
            self.assertEqual((root/'data.bin').read_bytes(),bytes(8192))
            raw=(root/'audio-25.bin').read_bytes();self.assertEqual(len(raw),4704)
            self.assertEqual(struct.unpack('<hh',raw[:4]),(5001,-5001))
            self.assertEqual(struct.unpack('<hh',raw[-4:]),(6176,-6176))
            with self.assertRaises(FileExistsError):f.create_media(root)

    def test_firmware_uses_guest_packet_builder_and_preserves_host_mode_byte(self):
        code,labels=f.program();raw=f.firmware()
        self.assertEqual(len(raw),262144);self.assertEqual(raw[8190:8192],bytes.fromhex('00 E2'))
        self.assertEqual(raw[512:512+len(code)],code)
        self.assertNotIn(bytes.fromhex('9C 02 20'),code)
        self.assertIn(bytes.fromhex('AD 02 20 8D 41 20 A9 26 8D 42 20'),code)
        self.assertIn(bytes.fromhex('E0 0A'),code)
        self.assertEqual(code[labels['send']-0xE200:labels['send']-0xE200+5],bytes.fromhex('9C 00 18 A2 00'))
        for name in ('gate','done','send','drain','status','message','free'):
            self.assertTrue(0xE200<=labels[name]<0xE200+len(code))

    def test_audio_track_argument_is_strict(self):
        for value in (True,1,26,25.0):
            with self.subTest(value=value),self.assertRaises(ValueError):f.audio_bytes(value)


if __name__=='__main__':unittest.main()
