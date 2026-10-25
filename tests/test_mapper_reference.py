"""Independent mapper-adapter expectation boundaries, authored inputs only."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import mapper_reference as reference


class MapperReferenceTests(unittest.TestCase):
    def test_cmake_paths_reject_interpolation_and_list_separators(self):
        for path in ('source;other', 'source$other', 'source"other', 'source\nother'):
            with self.assertRaisesRegex(ValueError,'represented safely'):
                reference.cmake_quote(path)

    def test_sf2_four_bit_selector_alias_and_ignored_data(self):
        rom = bytearray(0x280000)
        rom[128*8192+35] = 0x92
        cases = [dict(operations=[('r',0,0,0,0),('w',0,0x1FFD,0xFE),('q',64,35),('p',64,35)])]
        records = [dict(kind=kind,values=[64,35,0x92]) for kind in ('memory','peek')]
        self.assertEqual(reference.expected_memory(records,cases,'sf2',rom),2)
        records[1]['values'][2] = 0x91
        with self.assertRaisesRegex(ValueError,'Literal mapper expectation'):
            reference.expected_memory(records,cases,'sf2',rom)

    def test_populous_ram_alias_isolated_from_other_pages_and_rom(self):
        rom = bytearray(0x80000)
        rom[32*8192+17] = 0x6A
        cases = [dict(operations=[('r',0,0,0,0xA5),('w',0x41,31,37),
                                   ('q',0x5D,31),('p',0x5E,31),('q',0x60,17)])]
        records = [dict(kind='memory',values=[0x5D,31,37]),
                   dict(kind='peek',values=[0x5E,31,0xA5]),
                   dict(kind='memory',values=[0x60,17,0x6A])]
        self.assertEqual(reference.expected_memory(records,cases,'populous',rom),3)

    def test_boolean_observation_is_not_an_integer(self):
        cases = [dict(operations=[('r',0,0,0,0),('q',0,0)])]
        with self.assertRaisesRegex(ValueError,'Malformed'):
            reference.expected_memory([dict(kind='memory',values=[0,0,True])],cases,'sf2',bytes(0x280000))

    def test_missing_and_extra_observations_refused(self):
        cases = [dict(operations=[('r',0,0,0,0),('p',0,0)])]
        for records in ([], [dict(kind='peek',values=[0,0,0])]*2):
            with self.assertRaisesRegex(ValueError,'observation count'):
                reference.expected_memory(records,cases,'populous',bytes(0x80000))

    def test_normalized_compile_snapshot_verifies_git_blob_and_preserves_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);source=base/'source';source.mkdir()
            def git(*arguments):
                return subprocess.check_output(['git','-C',str(source),*arguments],stderr=subprocess.DEVNULL,text=True).strip()
            git('init')
            git('config','core.autocrlf','false')
            path=source/'src/authored.cpp';path.parent.mkdir();path.write_bytes(b'int authored = 17;\n')
            git('add','src/authored.cpp')
            git('-c','user.name=Authored Fixture','-c','user.email=fixture@example.invalid','commit','-m','Authored fixture')
            commit=git('rev-parse','HEAD')
            path.write_bytes(b'int authored = 17;\r\n')
            out=base/'out';out.mkdir();bindings={}
            with patch.object(reference,'COMMIT',commit):
                saved, files=reference.pinned_snapshot(source,out,bindings)
            self.assertEqual((saved/'src/authored.cpp').read_bytes(),b'int authored = 17;\n')
            self.assertEqual(path.read_bytes(),b'int authored = 17;\r\n')
            self.assertEqual(list(files),['src/authored.cpp'])
            path.write_bytes(b'int authored = 18;\r\n')
            bad=base/'bad';bad.mkdir()
            with patch.object(reference,'COMMIT',commit), self.assertRaisesRegex(ValueError,'Git blob differs'):
                reference.pinned_snapshot(source,bad,{})


if __name__=='__main__':
    unittest.main()
