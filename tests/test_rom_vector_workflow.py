"""Authored vector fixture contracts; runtime execution is qualified separately."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp.discovery import discover_roots,load_discovery
from pcerecomp.isa import decode

SOURCE=Path(__file__).resolve().parents[1]/'examples/rom-vectors/workflow.py'
spec=importlib.util.spec_from_file_location('rom_vector_workflow',SOURCE)
workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)


class RomVectorWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.out=Path(temp.name)/'fixture';workflow.create(self.out)

    def discover(self,name='graph',**options):
        return discover_roots(self.out/'seeds.json',self.out/'card.pce',self.out/name,
            rom_ranges=workflow.CODE_RANGES,**options)

    def test_one_seed_discovers_both_vector_targets_and_exact_literal_boundaries(self):
        found=self.discover(rom_vector_ranges=workflow.VECTOR_RANGES)
        expected={(0xE100,workflow.M0),(0xE102,workflow.M0),
                  (0xE104,workflow.M1),(0xE106,workflow.M1),(0xE120,workflow.M1),
                  (0xE122,workflow.M1),(0xE125,workflow.M1),(0xE140,workflow.M1),(0xE143,workflow.M1)}
        self.assertEqual({(r['pc'],tuple(r['mpr'])) for r in found.declarations.roots},expected)
        self.assertEqual(found.report['summary']['candidate_roots'],9)
        self.assertEqual(found.report['summary']['resolved_vectors'],2)
        self.assertEqual(found.report['unresolved'],[])
        self.assertFalse(found.report['execution_evidence'])
        self.assertEqual(load_discovery(found.report_path,self.out/'card.pce').sha256,found.sha256)

    def test_legacy_stops_at_first_vector_without_implicitly_authorizing_data(self):
        found=self.discover()
        self.assertEqual({r['pc'] for r in found.declarations.roots},{0xE100,0xE102,0xE104,0xE106})
        self.assertEqual({r['reason'] for r in found.report['unresolved']},{'indirect_jump'})

    def test_literal_encoding_and_cycle_plan_are_separate_from_analysis(self):
        image=workflow.card_bytes()
        self.assertEqual(len(image),8192)
        self.assertEqual(image[0x1FF:0x201],bytes.fromhex('20 E1'))
        self.assertEqual(image[0x300:0x302],bytes.fromhex('40 E1'))
        self.assertEqual(image[0x1FFE:0x2000],bytes.fromhex('00 E1'))
        for pc,mpr,text in workflow.PLAN:
            ins=decode(lambda address:image[address&8191],pc,mpr)
            self.assertEqual(bytes(ins.data),bytes.fromhex(text))
        # Independent authored instruction costs, not costs returned by the runtime.
        self.assertEqual(sum((2,5,2,7,2,5,7,5,4)),39)
        self.assertEqual(39*12,468)

    def test_changed_original_input_and_existing_output_are_refused(self):
        with self.assertRaises(FileExistsError):workflow.create(self.out)
        data=bytearray((self.out/'card.pce').read_bytes());data[0x1FF]=0x60
        (self.out/'card.pce').write_bytes(data)
        with self.assertRaisesRegex(ValueError,'Original input changed'):workflow.inputs(self.out)
        self.assertFalse((self.out/'discovery').exists())
