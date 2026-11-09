"""Authored explicit ROM roots remain separate from historical execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp.declarations import FORMAT, load_compilation
from pcerecomp.emitter import emit_capture, emit_declarations
from pcerecomp.history import compose_history
from pcerecomp.native_catalog import load_native_catalog
from pcerecomp.native_gaps import report_native_gaps

MPR = [255, 248, 0, 0, 0, 0, 0, 0]
ROOT = Path(__file__).resolve().parents[1]


def observed(pc, data, native=0, interpreted=1):
    return dict(pc=pc, mpr=MPR.copy(), data=list(data),
        physical=[(MPR[((pc+i)&65535)>>13]<<13)|((pc+i)&8191) for i in range(len(data))],
        native_hits=native, interpreted_hits=interpreted)


def capture(rows):
    return dict(schema=1, runtime_abi=18, capacity=64, dropped_instructions=0,
        unreadable_instructions=0, complete=True,
        retired_instructions=sum(r['native_hits']+r['interpreted_hits'] for r in rows), observations=rows)


class DeclaredEmissionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.image=self.root/'authored.pce'
        rom=bytearray([0xEA])*8192
        rom[:8]=bytes.fromhex('A9 2A 8D 10 20 80 F9 0B')
        self.image.write_bytes(rom)
        self.path=self.root/'roots.json'
        changed=MPR.copy();changed[7]=1
        self.document=dict(format=FORMAT,schema=1,kind='declared',execution_evidence=False,
            image=dict(sha256=hashlib.sha256(rom).hexdigest(),profile='base',header='none',encoding='linear'),
            roots=[dict(pc=0x4000,mpr=MPR.copy(),selector=0,rom_offsets=[0,1]),
                   dict(pc=0x4002,mpr=MPR.copy(),selector=0,rom_offsets=[2,3,4]),
                   dict(pc=0x4005,mpr=MPR.copy(),selector=0,rom_offsets=[5,6]),
                   dict(pc=0x4007,mpr=MPR.copy(),selector=0,rom_offsets=[7]),
                   dict(pc=0x4000,mpr=changed,selector=0,rom_offsets=[0,1])])
        self.path.write_text(json.dumps(self.document),encoding='utf-8')

    def history(self):
        rows=[observed(0x4000,(0xA9,42),native=3,interpreted=2),
              observed(0x4002,(0x8D,0x10,0x20),interpreted=11),
              observed(0x2200,(0xEA,),interpreted=7)]
        raw=self.root/'actual-authored-claims.json'
        raw.write_text(json.dumps(capture(rows)),encoding='utf-8')
        return compose_history([raw],self.root/'history',capacity=64)

    def emit(self, **options):
        return emit_declarations(self.path,self.image,self.root/'module',**options)

    def catalog(self, history=None):
        return load_native_catalog(self.root/'module/module.json',self.path,
                                   image_path=self.image,observation_history=history)

    def test_declared_only_translates_real_operations_without_execution_claims(self):
        original=self.image.read_bytes()
        manifest=self.emit()
        self.assertEqual({k:manifest[k] for k in ('observed_instructions','declared_instructions',
            'declared_roots_count','source_identity_count','declared_only','observed_only',
            'declared_observed_overlap','emitted_instructions','native_instructions_emitted',
            'unsupported_observations','unsupported_declarations')},
            dict(observed_instructions=0,declared_instructions=5,declared_roots_count=5,
                source_identity_count=5,declared_only=5,observed_only=0,declared_observed_overlap=0,
                emitted_instructions=4,native_instructions_emitted=4,
                unsupported_observations=0,unsupported_declarations=1))
        self.assertFalse(manifest['execution_evidence'])
        for key in ('historical_totals','selected_historical_totals','observation_inputs',
                    'code_capture_sha256','capture_retired_instructions','captured_native_hits'):
            self.assertNotIn(key,manifest)
        source=(self.root/'module/module.cpp').read_text(encoding='utf-8')
        self.assertIn('from explicit declared roots and optional retired observations',source)
        self.assertIn('s.a=42;',source);self.assertIn('bus.write_timed(',source)
        self.assertNotIn('interpret_step(',source)
        catalog=self.catalog()
        self.assertEqual(len(catalog.observed),0)
        self.assertEqual((len(catalog.declared),len(catalog.emitted),len(catalog.unsupported)),(5,4,1))
        self.assertFalse(catalog.provenance['execution_evidence'])
        self.assertFalse(catalog.provenance['linked_binary_verified'])
        self.assertNotIn('original_inputs',catalog.provenance)
        self.assertEqual(self.image.read_bytes(),original)

    def test_mixed_union_overlap_exclusion_and_history_counters_are_separate(self):
        history=self.history()
        manifest=self.emit(observation_history=history.index_path,exclude_ranges=[(3,1)])
        expected=dict(observed_instructions=3,declared_instructions=5,declared_roots_count=5,
            source_identity_count=6,declared_only=3,observed_only=1,declared_observed_overlap=2,
            emitted_instructions=4,excluded_observations=1,excluded_declarations=1,
            excluded_retired_hits=11,unsupported_observations=0,unsupported_declarations=1)
        self.assertEqual({k:manifest[k] for k in expected},expected)
        self.assertEqual(manifest['historical_totals'],dict(native_hits=3,interpreted_hits=20,retired_instructions=23))
        self.assertEqual(manifest['observation_inputs'][0]['runtime_abi'],18)
        self.assertNotIn('capture_runtime_abi',manifest)
        catalog=self.catalog(history.index_path)
        self.assertEqual(len(catalog.observed),3);self.assertEqual(len(catalog.declared),5)
        self.assertEqual(len(catalog.observed & catalog.declared),2)
        self.assertEqual(catalog.emitted|catalog.excluded|catalog.unsupported,catalog.observed|catalog.declared)
        for key,value in expected.items():self.assertEqual(catalog.counts[key],value)
        history.revalidate()

    def test_excluded_pure_declarations_do_not_manufacture_retired_hits(self):
        manifest=self.emit(exclude_ranges=[(1,1)])
        self.assertEqual(manifest['excluded_declarations'],2)
        self.assertEqual(manifest['excluded_observations'],0)
        self.assertEqual(manifest['excluded_retired_hits'],0)
        self.assertEqual(manifest['native_instructions_emitted'],2)
        self.assertEqual(self.catalog().counts['excluded_retired_hits'],0)

    def test_one_numeric_root_does_not_infer_fallthrough_or_successors(self):
        self.document['roots']=self.document['roots'][:1]
        self.path.write_text(json.dumps(self.document),encoding='utf-8')
        manifest=self.emit()
        self.assertEqual(manifest['declared_instructions'],1)
        source=(self.root/'module/module.cpp').read_text()
        self.assertIn('case 16384:',source)
        self.assertNotIn('case 16386:',source)
        self.assertEqual(load_compilation(self.path,self.image).static_reachability,'not_inferred')

    def test_wrong_image_refuses_before_output_and_catalog_requires_exact_source(self):
        wrong=self.root/'wrong.pce';wrong.write_bytes(bytes(8192))
        with self.assertRaises(ValueError):emit_declarations(self.path,wrong,self.root/'bad')
        self.assertFalse((self.root/'bad').exists())
        self.emit()
        with self.assertRaisesRegex(ValueError,'source image'):
            load_native_catalog(self.root/'module/module.json',self.path)
        with self.assertRaises(ValueError):
            load_native_catalog(self.root/'module/module.json',self.path,image_path=wrong)

    def test_changed_source_during_emission_refuses_before_success_manifest(self):
        from pcerecomp import emitter
        original=emitter._emit_observations
        def mutate(*args,**kwargs):
            data=bytearray(self.image.read_bytes());data[0x100]^=1;self.image.write_bytes(data)
            return original(*args,**kwargs)
        with patch.object(emitter,'_emit_observations',side_effect=mutate):
            with self.assertRaises(ValueError):self.emit()
        self.assertTrue((self.root/'module/module.cpp').exists())
        self.assertFalse((self.root/'module/module.json').exists())

    def test_output_cannot_mutate_closed_history_graph(self):
        history=self.history()
        before={p.relative_to(history.index_path.parent).as_posix():p.read_bytes()
                for p in history.index_path.parent.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError,'outside'):
            emit_declarations(self.path,self.image,history.index_path.parent/'module',
                              observation_history=history.index_path)
        self.assertEqual(before,{p.relative_to(history.index_path.parent).as_posix():p.read_bytes()
            for p in history.index_path.parent.rglob('*') if p.is_file()})
        history.revalidate()

    def test_catalog_refuses_invented_execution_counters_and_changed_declaration_counts(self):
        self.emit();manifest_path=self.root/'module/module.json'
        original=json.loads(manifest_path.read_text())
        for fields in (dict(historical_totals=dict(native_hits=0,interpreted_hits=0,retired_instructions=0)),
                       dict(captured_native_hits=0),dict(declared_only=0),dict(observed_instructions=5),
                       dict(declared_roots_schema=2)):
            manifest_path.write_text(json.dumps(original|fields),encoding='utf-8')
            with self.subTest(fields=fields),self.assertRaises(ValueError):self.catalog()
        missing=copy.deepcopy(original);missing.pop('bus_trace')
        manifest_path.write_text(json.dumps(missing),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'bus_trace'):self.catalog()

    def test_gaps_distinguish_compiled_unexercised_from_historical_observations(self):
        self.emit();catalog=self.catalog()
        empty=self.root/'no-execution.json';empty.write_text(json.dumps(capture([])))
        result=report_native_gaps(catalog,[empty])
        self.assertFalse(result['qualification'])
        self.assertEqual(result['summary']['emitted_unexercised'],4)
        self.assertEqual(result['summary']['declared_emitted_unexercised'],4)
        self.assertEqual(result['summary']['declared_emitted_exercised'],0)
        self.assertTrue(all(not r['historically_observed'] for r in result['declared_emitted_unexercised']))
        current=self.root/'new-window.json'
        current.write_text(json.dumps(capture([observed(0x4000,(0xA9,42),native=1,interpreted=0)])))
        report=report_native_gaps(catalog,[current])
        self.assertEqual(report['summary']['declared_emitted_exercised'],1)
        row=report['identities'][0]
        self.assertEqual(row['category'],'emitted');self.assertTrue(row['declared_identity'])
        self.assertTrue(row['catalog_identity']);self.assertFalse(row['historically_observed'])
        self.assertEqual(len(catalog.observed),0)


class LegacyObservedByteCompatibilityTests(unittest.TestCase):
    def test_predeclaration_authored_workflow_cpp_and_header_golden_bytes(self):
        # Recorded from the authored native-workflow fixture before declarations
        # existed. No old SDK/emitter is imported or executed by this test.
        spec=importlib.util.spec_from_file_location('declared_legacy_workflow',ROOT/'examples/native-workflow/workflow.py')
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        value=capture(fixture.expected_observations(200))
        value.update(runtime_abi=29,capacity=128)
        expected={
            'module.cpp':'2b138214d6af20d70c03bc809e69a2fc929db13afb10280278754c58342f6e40',
            'module_parts.hpp':'62c293c1258405f81da438e569044fb93d39fd695cc5470dbc66eb400314602a',
            'module_m0000000000000000_pe000.cpp':'e19578731df5ebc79b01fdc7e401eff6c9b8812a2bf892f26543c761496f8fb0',
            'module_m00000000000000ff_pe000.cpp':'e9f35f88a8d643de958d91f5101ec184ec45d0b23b06f5b2bd9cec7b8487f068',
            'module_m000000000000f8ff_pe000.cpp':'382a14de25fb59a0000c9c76be868b84b44ec514411fab2d5a49244304572df4',
            'module_m200000000000f8ff_p2200.cpp':'c7e70fd5d5bf337b61f84c040424b602efe4b89298acfbcc6f7c45be9b55229e',
            'module_m200000000000f8ff_pe000.cpp':'f85c0410c10162bcdc35ac171efe4de23b01c1b5f16e172544bce1db40f4cf54',
            'module_m400000000000f8ff_pe000.cpp':'b5b97e45a83b2d8422b633d9742f59776a8acc11eaaf0dd9de5154fce8b53efa',
        }
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'module'
            manifest=emit_capture(value,output,partition_layout='stable')
            self.assertEqual({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in output.iterdir() if p.suffix in ('.cpp','.hpp')},expected)
            self.assertNotIn('declared_roots_sha256',manifest)
            self.assertNotIn('declared_instructions',manifest)


if __name__=='__main__':unittest.main()
