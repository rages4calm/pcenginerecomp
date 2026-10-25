"""Adapter-boundary tests using authored text, never external source excerpts."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import video_modes_reference as reference


class VideoModesReferenceTests(unittest.TestCase):
    def test_extraction_keeps_bytes_and_one_based_span(self):
        definition=(b'  void PceVdc::Authored(unsigned x)\r\n{\r\n'
                    b'    if(x) { x = 4; }\r\n}\r\n')
        source=b'// Authored diagnostic text.\r\n\r\n'+definition+b'// following text\r\n'
        actual,span=reference.extract(source,'Authored')
        self.assertEqual(actual,definition[:-2])
        self.assertEqual(span['first_line'],3)
        self.assertEqual(span['last_line'],6)
        import hashlib
        self.assertEqual(span['sha256'],hashlib.sha256(actual).hexdigest())

    def test_incomplete_definition_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unbalanced'):
            reference.extract(b'void PceVdc::Authored() { if(true) { }','Authored')

    def test_missing_definition_is_rejected(self):
        with self.assertRaises(ValueError):
            reference.extract(b'void PceVdc::Other() {}','Authored')

    def test_changed_source_rejected_before_output_or_execution(self):
        # No C++ compiler or real probe is needed: pin validation precedes
        # generated files and all subprocess execution.
        with tempfile.TemporaryDirectory(prefix='video-reference-test-',dir=ROOT/'.local') as temporary:
            base=Path(temporary);source=base/'source';source.mkdir()
            for name in reference.SOURCES:
                (source/name).write_bytes(b'// Authored changed-input negative.\n')
            probe=base/'probe.exe';probe.write_bytes(b'not an executable')
            out=base/'new-output'
            args=argparse.Namespace(mesen_source=source,out=out,probe=probe,compiler=sys.executable)
            with self.assertRaisesRegex(ValueError,'source bytes differ'):
                reference.run(args)
            self.assertFalse(out.exists())
            self.assertEqual(probe.read_bytes(),b'not an executable')

    def test_existing_output_is_never_reused(self):
        with tempfile.TemporaryDirectory(prefix='video-reference-test-',dir=ROOT/'.local') as temporary:
            base=Path(temporary);out=base/'output';out.mkdir()
            marker=out/'result.json';marker.write_bytes(b'authored retained receipt')
            probe=base/'probe.exe';probe.write_bytes(b'not an executable')
            args=argparse.Namespace(mesen_source=base/'missing',out=out,probe=probe,compiler=sys.executable)
            with self.assertRaisesRegex(ValueError,'NEW output directory'):
                reference.run(args)
            self.assertEqual(marker.read_bytes(),b'authored retained receipt')


if __name__=='__main__':
    unittest.main()
