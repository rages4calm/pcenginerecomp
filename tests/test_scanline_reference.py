"""Authored live-rendering plan and bounded PNG decoder checks."""
import struct
import unittest
import zlib
from scripts.scanline_reference import decode_png,fixture,palette,plans,FRAME


def png(width,height,color,rows):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xFFFFFFFF)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,color,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


class ScanlineReferenceTests(unittest.TestCase):
    def test_bounded_distinct_temporal_matrix(self):
        matrix=plans()
        self.assertEqual(len(matrix),4)
        self.assertEqual(len({p['id'] for p in matrix}),4)
        self.assertEqual({p['mwr'] for p in matrix},{0,16,64,84})
        self.assertEqual({p['cr'] for p in matrix},{128,192})
        self.assertEqual(FRAME,357630)
        for plan in matrix:
            vram,sat,colors=fixture(plan)
            self.assertEqual(tuple(map(len,(vram,sat,colors))),(65536,512,1024))
            self.assertNotEqual(colors,palette(plan,1))
            self.assertEqual(int.from_bytes(sat[:2],'little'),88)
            self.assertTrue(all(int.from_bytes(colors[i:i+2],'little')<512 for i in range(0,1024,2)))

    def test_png_rgb_rgba_and_all_filter_types(self):
        expected=bytes((3,7,11,19,23,29,31,37,41))
        for channels,color in ((3,2),(4,6)):
            row=expected if channels==3 else bytes((3,7,11,255,19,23,29,255,31,37,41,255))
            for method in range(5):
                previous=bytes(len(row));encoded=bytearray()
                for x,value in enumerate(row):
                    left=row[x-channels] if x>=channels else 0
                    if method in (1,4):predictor=left
                    elif method==3:predictor=left//2
                    else:predictor=0
                    encoded.append((value-predictor)&255)
                self.assertEqual(decode_png(png(3,1,color,bytes((method,))+encoded)),(3,1,expected))
        # Nonzero upper row exercises Up, Average, and Paeth predictors.
        for method in (2,3,4):
            row2=bytes((4,8,12,20,24,30,32,38,42));encoded=bytearray()
            for x,value in enumerate(row2):
                left=row2[x-3] if x>=3 else 0;up=expected[x];ul=expected[x-3] if x>=3 else 0
                if method==2:pred=up
                elif method==3:pred=(left+up)//2
                else:
                    p=left+up-ul;d=(abs(p-left),abs(p-up),abs(p-ul));pred=(left,up,ul)[d.index(min(d))]
                encoded.append((value-pred)&255)
            self.assertEqual(decode_png(png(3,2,2,b'\0'+expected+bytes((method,))+encoded)),(3,2,expected+row2))

    def test_png_extent_crc_filter_and_format_refusals(self):
        valid=png(1,1,2,b'\0\x01\x02\x03')
        invalid=[b'',valid[:-1],valid+b'junk',png(1025,1,2,b'\0'),png(1,513,2,b'\0'),
            png(1,1,0,b'\0\0'),png(1,1,2,b'\5\x01\x02\x03'),png(1,1,2,b'\0\x01\x02'),
            png(1,1,2,b'\0\x01\x02\x03\x04')]
        damaged=bytearray(valid);damaged[20]^=1;invalid.append(bytes(damaged))
        for data in invalid:
            with self.assertRaises(ValueError):decode_png(data)


if __name__=='__main__':unittest.main()
