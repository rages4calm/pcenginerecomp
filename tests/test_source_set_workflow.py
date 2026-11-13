"""The authored consumer binds RAM/BIOS independently and keeps literal plans."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from pcerecomp import project
from pcerecomp.declarations import load_compilation
ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('source_set_workflow',ROOT/'examples/source-sets/workflow.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)


class SourceSetWorkflowTests(unittest.TestCase):
    def test_all_bank_pairs_prepare_as_unexecuted_multi_source_consumer(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'authored';w.create(out);receipt=w.prepare(out);checked=project.verify(out/'consumer/project.toml')
            m=json.loads(checked['files']['module_manifest'].read_text(encoding='utf-8'))
            self.assertFalse(receipt['compiled']);self.assertFalse(receipt['executed'])
            self.assertEqual((m['declared_instructions'],m['observed_instructions']),(5888,0))
            self.assertEqual(m['declared_roots_source']['memberships'],10752)
            self.assertEqual(m['declared_roots_source']['overlapping_identities'],4864)
            self.assertEqual(len([k for k in checked['files'] if k.startswith('module_declaration_member:')]),3)
            self.assertNotIn('module_observation_history',checked['files'])
            self.assertEqual((out/'consumer/declarations/roots.json').read_bytes(),(out/'sources/roots.json').read_bytes())

    def test_independent_literal_plans_and_offsets_cover_both_sources(self):
        payload,bios,cases=w.f.fixture();self.assertEqual(len(cases),256)
        for c in cases:
            self.assertEqual((c['steps'],c['cycles'],c['ticks']),(23,80,942))
            self.assertEqual(c['plan'][12]['code'],bytes.fromhex('20 00 E3'))
            self.assertEqual(c['plan'][13]['pc'],0xE300)
            self.assertEqual(w.f.expected_ram(c)[:3],bytes((0x42,9+c['firmware_bank'],0x43)))
            states=w.f.cpu_states(c);self.assertEqual(states[13]['pc'],0xE300);self.assertEqual(states[17]['pc'],c['resume'])
            for i,row in enumerate(c['plan']):
                address=row['mpr'][row['pc']//8192]*8192+(row['pc']&8191)
                raw=bios if 13<=i<=16 else payload;offset=address if 13<=i<=16 else address-0x100000
                self.assertEqual(raw[offset:offset+len(row['code'])],row['code'])

    def test_changed_original_refuses_without_repinning(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'authored';w.create(out);path=out/'bios.bin';path.write_bytes(path.read_bytes()+b'\0')
            with self.assertRaisesRegex(ValueError,'changed'):w.prepare(out)
            self.assertFalse((out/'consumer').exists())


if __name__=='__main__':unittest.main()
