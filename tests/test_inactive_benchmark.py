"""Authored benchmark admission differences, without builds or guest execution."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest


FILE=Path(__file__).resolve().parents[1]/'examples/inactive-adapter/benchmark.py'
SPEC=importlib.util.spec_from_file_location('inactive_benchmark',FILE)
benchmark=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(benchmark)


class InactiveBenchmarkPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        self.sides={}
        self.admitted={}
        for side in ('baseline','candidate'):
            sdk=root/side/'sdk';qualification=root/side/'qualification'
            sdk.mkdir(parents=True);qualification.mkdir()
            (sdk/'CMakeLists.txt').write_bytes(b'authored shared configuration\n')
            for name in ('runtime','pcerecomp','cmake'):(sdk/name).mkdir()
            (sdk/'runtime/src').mkdir()
            (sdk/'runtime/src/headless.cpp').write_bytes(('authored '+side+' host\n').encode())
            (sdk/'runtime/src/core.cpp').write_bytes(b'authored identical core\n')
            self.sides[side]=dict(sdk=sdk,qualification=qualification)
            row=dict(config=dict(name='authored',tool=dict(path=str(sdk),revision=side),
                    payload=dict(sha256='a'*64),runtime=dict(tier='native',native_span=8),
                    limits=dict(steps=100,ticks=1000)),
                identities=dict(module_source='b'*64,title_adapter_manifest='c'*64),
                module_tree=dict(path=str(qualification/'module'),sha256='b'*64,files=4),
                audit=dict(current_audit_sha256=side,revalidated=True,producer='authored',
                    shared=dict(tool=dict(path=str(sdk),source_sha256=side,runtime_abi=29),
                        options=dict(CMAKE_BUILD_TYPE='Release'),
                        trees=dict(tool_compile=[dict(path=str(sdk/'runtime'),sha256=side,files=2)],
                                   toolchain=dict(path='same compiler',sha256='d'*64),
                                   dependencies=[dict(path='same dependency',sha256='e'*64)])),
                    effective_policy=[dict(name='pce-consumer',compile_groups=['-O3'],link=['same link'])]))
            self.admitted[side]={mode:copy.deepcopy(row) for mode in benchmark.MODES}

    def compare(self):return benchmark.cross_side_equivalence(self.admitted,self.sides)

    def test_expected_host_delta_and_root_relocation_admit_with_visible_inventory(self):
        result=self.compare()
        self.assertEqual(result['intended_changed_files'],['runtime/src/headless.cpp'])
        self.assertEqual(set(result['modes']),set(benchmark.MODES))
        self.assertTrue(all(row['equivalent'] for row in result['modes'].values()))

    def test_unrelated_sdk_code_or_membership_change_refuses(self):
        sdk=self.sides['candidate']['sdk']
        (sdk/'runtime/src/core.cpp').write_bytes(b'different core\n')
        with self.assertRaisesRegex(ValueError,'host-source change'):self.compare()
        (sdk/'runtime/src/core.cpp').write_bytes(b'authored identical core\n')
        (sdk/'pcerecomp/new.py').write_bytes(b'# unexpected extra source\n')
        with self.assertRaisesRegex(ValueError,'membership'):self.compare()

    def test_compiler_dependency_options_and_effective_link_changes_refuse(self):
        edits=(lambda r:r['audit']['shared']['trees']['toolchain'].update(sha256='f'*64),
               lambda r:r['audit']['shared']['trees']['dependencies'][0].update(sha256='f'*64),
               lambda r:r['audit']['shared']['options'].update(CMAKE_BUILD_TYPE='Debug'),
               lambda r:r['audit']['effective_policy'][0].update(link=['different link']),
               lambda r:r['audit']['effective_policy'][0].update(compile_groups=['-O0']))
        for edit in edits:
            with self.subTest(edit=edit):
                original=copy.deepcopy(self.admitted['candidate']['plain-scalar'])
                edit(self.admitted['candidate']['plain-scalar'])
                with self.assertRaisesRegex(ValueError,'effective policy'):self.compare()
                self.admitted['candidate']['plain-scalar']=original

    def test_dispatch_recipe_media_module_and_adapter_changes_refuse(self):
        edits=(lambda r:r['config']['runtime'].update(native_span=1),
               lambda r:r['config']['runtime'].update(tier='hybrid'),
               lambda r:r['config']['payload'].update(sha256='f'*64),
               lambda r:r['config']['limits'].update(ticks=2000),
               lambda r:r['identities'].update(module_source='f'*64),
               lambda r:r['module_tree'].update(sha256='f'*64),
               lambda r:r['module_tree'].update(files=5),
               lambda r:r['identities'].update(title_adapter_manifest='f'*64))
        for edit in edits:
            with self.subTest(edit=edit):
                original=copy.deepcopy(self.admitted['candidate']['plain-scalar'])
                edit(self.admitted['candidate']['plain-scalar'])
                with self.assertRaisesRegex(ValueError,'effective policy'):self.compare()
                self.admitted['candidate']['plain-scalar']=original

    def test_external_dependency_path_is_not_normalized_away(self):
        self.admitted['candidate']['plain-scalar']['audit']['shared']['trees']['dependencies'][0]['path']='different SDK'
        with self.assertRaisesRegex(ValueError,'effective policy'):self.compare()

    def test_verified_known_path_option_spelling_can_differ_but_target_cannot(self):
        base=self.sides['baseline']['sdk'].parent.parent
        same=base/'same-sdl'
        for mode in benchmark.MODES:
            self.admitted['baseline'][mode]['audit']['shared']['options']['SDL3_DIR']=str(same)
            self.admitted['candidate'][mode]['audit']['shared']['options']['SDL3_DIR']=str(same/'..'/'same-sdl')
        self.compare()
        self.admitted['candidate']['plain-scalar']['audit']['shared']['options']['SDL3_DIR']=str(base/'other-sdl')
        with self.assertRaisesRegex(ValueError,'effective policy'):self.compare()

    def test_runtime_shader_content_and_membership_are_not_hidden_by_tree_marker(self):
        for side in self.sides:
            (self.sides[side]['sdk']/'runtime/display.hlsl').write_bytes(b'authored shader\n')
        self.compare()
        path=self.sides['candidate']['sdk']/'runtime/display.hlsl'
        path.write_bytes(b'changed shader\n')
        with self.assertRaisesRegex(ValueError,'host-source change'):self.compare()
        path.unlink()
        with self.assertRaisesRegex(ValueError,'membership'):self.compare()

    def test_source_target_fixture_profile_rejects_even_self_consistent_other_program(self):
        import hashlib,json
        with tempfile.TemporaryDirectory() as temporary:
            q=Path(temporary);inputs=q/'inputs';inputs.mkdir()
            raw=bytes.fromhex('78D8D4A2FF9A8000')
            (inputs/'authored.bin').write_bytes(raw)
            (inputs/'fixture.json').write_text(json.dumps(dict(program_sha256=hashlib.sha256(raw).hexdigest())),encoding='utf-8')
            (inputs/'roots.json').write_text(json.dumps(dict(roots=[])),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'reviewed 170-byte'):benchmark.unreachable_fixture(q)


class InactiveBenchmarkAggregationTests(unittest.TestCase):
    def rows(self):
        return [dict(mode='plain-scalar',group=0,index=0,side='baseline',segment=n,
                     cpu_100ns=100+n,wall_ns=1000+n,actual_native=6000000,polls=2+n,label=str(n)) for n in range(3)]

    def test_sums_separate_intervals_and_preserves_member_names(self):
        rows=self.rows();cells=benchmark.aggregate_cells(list(reversed(rows)),3)
        self.assertEqual(cells,[dict(mode='plain-scalar',group=0,index=0,side='baseline',segments=3,
            cpu_100ns=303,wall_ns=3003,actual_native=18000000,polls=9,labels=['0','1','2'])])
        self.assertEqual(rows[0]['cpu_100ns'],100)

    def test_duplicate_missing_segments_and_side_changes_cannot_fake_complete_cell(self):
        rows=self.rows()
        for malformed in (rows[:2],rows+[rows[0]],rows[:2]+[dict(rows[2],side='candidate')]):
            with self.subTest(rows=malformed):
                with self.assertRaisesRegex(ValueError,'duplicate/missing'):benchmark.aggregate_cells(malformed,3)


if __name__=='__main__':unittest.main()
