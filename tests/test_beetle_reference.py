"""Mocked build-orchestration contracts, not original-core execution evidence."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import beetle_reference as producer


class OptionalBeetleProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'tests').mkdir()
        for name in ('beetle_cpu_probe.cpp','beetle_irq_probe.cpp','reference_trace_support.hpp','irq_trace_support.hpp'):
            (self.root/'tests'/name).write_text('authored test input '+name+'\n')
        self.tools=self.root/'tools';self.tools.mkdir()
        for name in ('clang++.exe','clang.exe','cmake.exe','ninja.exe'):(self.tools/name).write_bytes(b'mocked tool; never launched')
        self.args=Namespace(beetle_source=self.root/'upstream',compiler=self.tools/'clang++.exe',cmake=self.tools/'cmake.exe',ninja=self.tools/'ninja.exe')

    def build(self,probe=None):
        out=self.root/'output';out.mkdir()
        def snapshot(source,directory):
            tree=directory/'original-source';tree.mkdir()
            return tree,'a'*64,{}
        def command(argv,directory,label,commands,timeout=180):
            commands.append(argv)
            if '--build' in argv:
                build=Path(argv[argv.index('--build')+1]);build.mkdir()
                (build/('beetle-cpu.exe' if producer.os.name=='nt' else 'beetle-cpu')).write_bytes(b'mocked build artifact; not an executable')
        with patch.object(producer,'ROOT',self.root),patch.object(producer,'source_snapshot',snapshot),\
             patch.object(producer,'sources',return_value=([],[])),patch.object(producer,'run_command',command),\
             patch.object(producer.shutil,'which',side_effect=lambda value:str(value)):
            return producer.build(self.args,out,[],probe=probe)

    def test_default_keeps_original_observer_and_existing_epoch_inventory(self):
        path,built=self.build()
        self.assertEqual([Path(row['path']).name for row in built['authored']],
                         ['beetle_cpu_probe.cpp','reference_trace_support.hpp','beetle_reference.py'])
        self.assertEqual(producer.check_build(path),built)

    def test_new_observer_and_serializer_are_both_copied_and_pinned(self):
        probe=self.root/'tests/beetle_irq_probe.cpp';before=probe.read_bytes()
        path,built=self.build(probe)
        names=[Path(row['path']).name for row in built['authored']]
        self.assertEqual(names,['beetle_irq_probe.cpp','reference_trace_support.hpp','beetle_reference.py','irq_trace_support.hpp'])
        self.assertEqual(probe.read_bytes(),before)
        self.assertEqual(Path(built['authored'][0]['path']).read_bytes(),before)
        self.assertEqual(producer.check_build(path),built)

    def test_changed_preserved_irq_serializer_refuses_build_reuse(self):
        path,built=self.build(self.root/'tests/beetle_irq_probe.cpp')
        helper=next(row for row in built['authored'] if Path(row['path']).name=='irq_trace_support.hpp')
        Path(helper['path']).write_bytes(b'changed authored serializer')
        with self.assertRaisesRegex(ValueError,'Changed full-core build binding'):
            producer.check_build(path)


if __name__=='__main__':unittest.main()
