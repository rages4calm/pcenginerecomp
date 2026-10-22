import tempfile
from pathlib import Path
import unittest

from generate_io_fixture import make_fixture, MPR_IO
from scripts.cd_reference import plans, prepare_media


class CdReferenceTests(unittest.TestCase):
    def test_cpu_and_device_sequence_coverage(self):
        snapshot,cases=make_fixture()
        sequences=plans();sites={pc:(op,address) for pc,op,address in cases}
        self.assertEqual(len(sequences),48)
        self.assertEqual(len({p['id'] for p in sequences}),48)
        self.assertEqual(sum(len(p['steps']) for p in sequences),720)
        self.assertEqual(snapshot.mpr,MPR_IO)
        self.assertEqual(snapshot.mpr[4],snapshot.mpr[6])
        self.assertEqual(snapshot.mpr[0],snapshot.mpr[5])
        used=set()
        for plan in sequences:
            self.assertLessEqual(len(plan['steps']),32)
            self.assertEqual(sites[plan['steps'][-1][0]],(0x43,0))
            for pc,_ in plan['steps']:
                self.assertEqual(pc>>13,1)
                used.add(sites[pc])
        self.assertTrue({(0x0C,0x1803),(0x1C,0x1803),(0xBD,0x87FF),(0x9D,0x87FF)}<=used)
        self.assertFalse({(0xAD,0x1807),(0xAD,0xB807)}&used)
        self.assertEqual([len(sequences[i::2]) for i in range(2)],[24,24])

    def test_synthetic_cd_media_is_bounded_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            cue,bios=prepare_media(out,bytes((0x80,0xFE)))
            self.assertEqual(bios.stat().st_size,262144)
            self.assertEqual((out/'synthetic-disc.bin').stat().st_size,2352*300)
            self.assertIn('MODE1/2352',cue.read_text())
            identity=bios.read_bytes()
            self.assertEqual(prepare_media(out,bytes((0x80,0xFE))),(cue,bios))
            self.assertEqual(bios.read_bytes(),identity)
            with self.assertRaises(ValueError):prepare_media(out,bytes((0xEA,)))
            with self.assertRaises(ValueError):prepare_media(out,bytes(8191))


if __name__=='__main__':unittest.main()
