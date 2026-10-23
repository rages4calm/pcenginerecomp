"""Authored video-reference input boundaries, without the emulator."""
import tempfile
from pathlib import Path
import unittest
from scripts.video_reference import plans,register_program,vram_bytes,write_plan


class VideoReferenceTests(unittest.TestCase):
    def test_matrix_is_bounded_and_covers_directions_irq_wrap(self):
        matrix=plans()
        self.assertEqual(len(matrix),12)
        self.assertEqual(len({p['id'] for p in matrix}),12)
        self.assertEqual({p['dcr']&12 for p in matrix if p['mode']==0},{0,4,8,12})
        self.assertEqual({p['dcr'] for p in matrix if p['mode']==1},{0,1,17})
        self.assertTrue(any(p['destination']==65535 for p in matrix))
        self.assertTrue(any(p['mode']==2 and p['length']==512 for p in matrix))
        self.assertTrue(all(1<=p['length']<=1024 for p in matrix))

    def test_authored_vram_is_complete_little_endian(self):
        for seed in (0,7,255):
            data=vram_bytes(seed)
            self.assertEqual(len(data),65536)
            for i in (0,1,255,256,32767):
                self.assertEqual(int.from_bytes(data[i*2:i*2+2],'little'),(i*73+seed*257)&65535)

    def test_probe_format_and_guest_trigger_program(self):
        self.assertEqual(register_program(18,0x1234),bytes.fromhex('03 12 13 34 23 12'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan.txt'
            for plan in plans():
                write_plan(path,plan)
                self.assertEqual(len(path.read_text().split()),6)


if __name__=='__main__':unittest.main()
