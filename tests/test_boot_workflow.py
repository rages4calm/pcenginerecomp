"""Reusable authored source workflow inputs and independent fixture geometry."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from pcerecomp import project
from pcerecomp.declarations import load_compilation

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('boot_workflow',ROOT/'examples/boot-sources/workflow.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)


class BootSourceWorkflowTests(unittest.TestCase):
    def test_all_four_variants_prepare_without_manufacturing_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            for variant,count in (('cd-ram',184),('work-ram',38),('system-standard',2944),('system-super',2392)):
                out=Path(directory)/variant;w.create(out,variant);receipt=w.prepare(out);checked=project.verify(out/'consumer/project.toml')
                self.assertFalse(receipt['compiled']);self.assertFalse(receipt['executed']);self.assertNotIn('module_observation_history',checked['files'])
                manifest=json.loads(checked['files']['module_manifest'].read_text(encoding='utf-8'))
                self.assertEqual((manifest['declared_instructions'],manifest['observed_instructions']),(count,0))
                self.assertEqual(manifest['declared_roots_format'],'pce-declared-boot-roots-1')
                self.assertEqual((out/'consumer/declarations/roots.json').read_bytes(),(out/'roots.json').read_bytes())

    def test_changed_original_and_existing_destination_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'authored';w.create(out)
            with self.assertRaises(FileExistsError):w.create(out)
            raw=(out/'source.bin').read_bytes();(out/'source.bin').write_bytes(raw+b'\0')
            with self.assertRaisesRegex(ValueError,'changed'):w.prepare(out)
            self.assertFalse((out/'consumer').exists())

    def test_fixture_expectations_are_authored_not_evaluator_results(self):
        for variant in w.f.VARIANTS:
            raw,image,cases=w.f.fixture(variant)
            for c in cases:
                self.assertEqual((c['steps'],c['cycles']),(23,80))
                self.assertEqual(c['ticks'],960 if variant.startswith('system-') else 942)
                tag=9+(c['bank']%32 if variant.startswith('system-') else c['bank']-128 if variant=='cd-ram' else 0)
                ram=w.f.expected_ram(variant,c);self.assertEqual(ram[:3],bytes((0x42,tag,0x43)))
                self.assertEqual(ram[0x1FD:0x200],bytes.fromhex('04 03 42'))


if __name__=='__main__':unittest.main()
