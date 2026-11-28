"""Authored mixed-source RAM/CD candidates; no retail bytes or execution claims."""
import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import cd_loads as cd, overlay_snapshot as snapshots, prepare, project, incremental
from pcerecomp.emitter import emit_declarations
from pcerecomp.native_catalog import load_native_catalog
from pcerecomp.toc import Toc
from tests.test_cd_loads import MPR, load, digest
from tests.test_overlays import ReportedRam, ORIGIN
from tests import test_project


class ResidentCdLoadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def fixture(self,raw=bytes.fromhex('201040a92280fe'),resident=bytes.fromhex('a94260'),*,start=0x100010,machine_change=None):
        disc=self.root/'disc.iso';disc.write_bytes(bytes(2048)+raw+bytes((-len(raw))%2048))
        toc=self.root/'disc.toc';toc.write_text(Toc.from_image(disc).text(),encoding='ascii',newline='\n')
        self.images=dict(disc=disc,toc=toc)
        self.document=dict(format=cd.MAP_FORMAT,schema=1,coordinate=cd.COORDINATE,policy=cd.POLICY,
            media=dict(format='iso',image_sha256=Toc.from_image(disc).image_sha256,toc_sha256=digest(toc.read_bytes())),
            groups=[dict(id='area',mpr=MPR.copy(),loads=[load('body',1,raw)],roots=[0x4000])])
        self.map=self.root/'map.json';self.write_map()
        machine=snapshots.machine_for(dict(boot=dict(mode='system-card-reset',profile='standard')),
            dict(bios='a'*64,disc=self.document['media']['image_sha256'],toc=self.document['media']['toc_sha256']))
        if machine_change:machine_change(machine)
        client=ReportedRam(resident+bytes(max(0,32-len(resident))),start=start,pc=0x4000+(start-0x100000),mpr=MPR)
        self.snapshot=snapshots.capture_snapshot(client,self.root/'snapshot',machine=machine,origin=ORIGIN,regions=[(start,len(client.data))])
        self.ranges=[(start,len(resident))]

    def write_map(self):self.map.write_text(json.dumps(self.document),encoding='utf-8')

    def declare(self,name='declared',**options):
        policy=options.pop('analysis_policy',cd.ANALYSIS_POLICY)
        return cd.declare(self.map,self.root/name,**self.images,analysis_policy=policy,
            resident_snapshot=self.snapshot.path,resident_ranges=self.ranges,**options)

    def test_branch_and_return_cross_resident_source_with_byte_provenance(self):
        self.fixture();admitted=self.declare();doc=json.loads(admitted.path.read_text())
        self.assertEqual({row['pc'] for row in admitted.instructions},{0x4000,0x4003,0x4005,0x4010,0x4012})
        self.assertFalse(doc['groups'][0]['analysis']['unresolved'])
        resident_node=next(row for row in doc['groups'][0]['analysis']['nodes'] if row['pc']==0x4010)
        self.assertTrue(all('resident' in row for row in resident_node['fetch']))
        self.assertEqual(resident_node['fetch'][0]['resident']['snapshot_sha256'],self.snapshot.sha256)
        self.assertEqual(doc['resident'],admitted.source_metadata['resident'])
        self.assertTrue(any(name.startswith('member:resident/') for name in admitted.artifact_bindings))
        admitted.revalidate()

    def test_copy_is_closed_and_original_source_namespace_is_not_required(self):
        self.fixture();admitted=self.declare();copied=cd.copy_declarations(admitted.path,self.root/'copied',self.images)
        self.assertEqual(copied.sha256,admitted.sha256);self.assertEqual(copied.source_metadata,admitted.source_metadata)
        # A source change cannot affect a copied closed bundle.
        (self.snapshot.path.parent/'ram-000.bin').write_bytes(bytes(32))
        self.assertEqual(cd.load(copied.path,self.images).instructions,copied.instructions)
        with self.assertRaises(ValueError):self.snapshot.revalidate()

    def test_copy_cannot_create_output_inside_its_original_resident_graph(self):
        self.fixture();admitted=self.declare();output=admitted.path.parent/'resident'/'accidental-copy'
        with self.assertRaisesRegex(ValueError,'source namespace'):cd.copy_declarations(admitted.path,output,self.images)
        self.assertFalse(output.exists());admitted.revalidate()

    def test_overlap_is_refused_even_if_the_overlapping_bytes_match(self):
        self.fixture(start=0x100000,resident=bytes.fromhex('201040'))
        with self.assertRaisesRegex(ValueError,'overwrite'):self.declare()
        self.assertFalse((self.root/'declared').exists())

    def test_wrong_disc_binding_is_refused(self):
        self.fixture(machine_change=lambda machine:machine['assets'].__setitem__('disc','f'*64))
        with self.assertRaisesRegex(ValueError,'disc|media'):self.declare()
        self.assertFalse((self.root/'declared').exists())

    def test_unbound_resident_target_remains_frontier(self):
        self.fixture(raw=bytes.fromhex('202040a92280fe'))
        admitted=self.declare();graph=json.loads(admitted.path.read_text())['groups'][0]['analysis']
        self.assertEqual({row['pc'] for row in admitted.instructions},{0x4000})
        self.assertTrue(graph['unresolved'])

    def test_instruction_bytes_can_cross_disjoint_cd_and_resident_segments(self):
        self.fixture(raw=bytes.fromhex('a9'),resident=bytes.fromhex('4280fe'),start=0x100001)
        admitted=self.declare();graph=json.loads(admitted.path.read_text())['groups'][0]['analysis']
        node=graph['nodes'][0];self.assertEqual(node['pc'],0x4000)
        self.assertEqual(node['fetch'][0],dict(load='body',offset=0,disc_byte_offset=2048))
        self.assertIn('resident',node['fetch'][1]);self.assertEqual({row['pc'] for row in admitted.instructions},{0x4000,0x4002})

    def test_resident_data_exclusion_removes_fetch_without_inventing_constant(self):
        self.fixture()
        admitted=self.declare(data_ranges=[(0x100010,1)])
        self.assertEqual({row['pc'] for row in admitted.instructions},{0x4000})
        graph=json.loads(admitted.path.read_text())['groups'][0]['analysis'];self.assertTrue(graph['unresolved'])

    def test_alternative_cd_groups_keep_resident_source_and_distinct_variants(self):
        self.fixture();second=copy.deepcopy(self.document['groups'][0]);second['id']='alternative';second['roots']=[0x4010]
        self.document['groups'].append(second);self.write_map();admitted=self.declare()
        doc=json.loads(admitted.path.read_text());self.assertEqual({row['group'] for row in admitted.roots},{'area','alternative'})
        self.assertEqual({row['pc'] for row in doc['groups'][1]['analysis']['nodes']},{0x4010,0x4012})

    def test_metadata_graph_snapshot_and_extra_members_are_fail_closed(self):
        self.fixture();admitted=self.declare();raw=admitted.path.read_bytes();original=json.loads(raw)
        for mutate in (lambda doc:doc['resident'].__setitem__('snapshot_sha256','f'*64),
                       lambda doc:doc['groups'][0]['analysis']['nodes'][0]['fetch'][0].__setitem__('offset',1)):
            document=copy.deepcopy(original);mutate(document);admitted.path.write_text(json.dumps(document),encoding='utf-8')
            with self.assertRaises(ValueError):cd.load(admitted.path,self.images)
            admitted.path.write_bytes(raw)
        extra=admitted.path.parent/'resident'/'extra';extra.write_bytes(b'extra')
        with self.assertRaises(ValueError):admitted.revalidate()
        extra.unlink()
        member=admitted.path.parent/'resident'/'snapshot'/'ram-000.bin';member.write_bytes(bytes(32))
        with self.assertRaises(ValueError):admitted.revalidate()

    def test_declared_only_emission_and_catalog_retain_resident_closure(self):
        self.fixture();admitted=self.declare()
        manifest=emit_declarations(admitted.path,None,self.root/'module',source_images=self.images)
        catalog=load_native_catalog(self.root/'module/module.json',admitted.path,source_images=self.images)
        self.assertEqual(len(catalog.declared),5);self.assertFalse(catalog.observed)
        self.assertEqual(manifest['declared_roots_sha256'],admitted.sha256)
        renamed=admitted.path.with_name('declared-roots.json');admitted.path.rename(renamed)
        self.assertEqual(len(cd.load(renamed,self.images).instructions),5)

    def test_prepare_and_managed_archive_preserve_the_full_resident_graph(self):
        bios=self.root/'bios.pce';bios.write_bytes(bytes(262144));bios_sha=digest(bios.read_bytes())
        self.fixture(machine_change=lambda machine:machine['assets'].__setitem__('bios',bios_sha))
        admitted=self.declare()
        fixture=test_project.ConsumerProjectTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        config=tomllib.loads(fixture.text)
        recipe=dict(schema=1,format=prepare.FORMAT,name='resident-cd',sdk=dict(revision='0'*40,allow_revision_override=True),
            module=dict(kind='cd-loads',path=str(admitted.path)),boot=dict(mode='system-card-reset',profile='standard'),
            bios=dict(path=str(bios)),disc=dict(path=str(self.images['disc'])),toc=dict(path=str(self.images['toc'])),
            runtime=config['runtime'],limits=config['limits'])
        spec=self.root/'consumer.toml';spec.write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
        invalid_output=admitted.path.parent/'resident'/'accidental-consumer'
        with patch.object(prepare,'TOOL_ROOT',fixture.tool):
            with self.assertRaisesRegex(ValueError,'resident source namespace'):
                prepare.prepare_project(spec,invalid_output)
        self.assertFalse(invalid_output.exists());admitted.revalidate()
        with patch.object(prepare,'TOOL_ROOT',fixture.tool):receipt=prepare.prepare_project(spec,self.root/'consumer')
        self.assertFalse(receipt['compiled']);self.assertFalse(receipt['executed'])
        checked=project.verify(self.root/'consumer/project.toml',allow_revision_override=True)
        module=incremental._module(checked)
        self.assertIn('resident/resident.json',module);self.assertIn('resident/snapshot/ram-000.bin',module)
        archive=self.root/'managed';archive.mkdir();incremental._sync(module,archive)
        members=[dict(file=name.removeprefix('member:'),sha256=row['sha256'],size_bytes=row['size_bytes'])
                 for name,row in sorted(admitted.artifact_bindings.items()) if name.startswith('member:')]
        binding=dict(file='declared-roots.json',sha256=admitted.sha256,members=members)
        incremental._check_declared_archive(archive,binding)
        from pcerecomp import declarations
        numeric=(archive/'declared-roots.json').stat().st_size+(archive/cd.MAP_NAME).stat().st_size
        with patch.object(declarations,'MAX_DECLARATION_BYTES',numeric):
            with self.assertRaisesRegex(ValueError,'bound'):incremental._check_declared_archive(archive,binding)
        with self.assertRaises(ValueError):incremental._check_declared_archive(archive,binding|dict(members=members[:-1]))
        extra=archive/'resident'/'extra.bin';extra.write_bytes(b'extra')
        with self.assertRaises(ValueError):incremental._check_declared_archive(archive,binding)
        extra.unlink()
        (archive/'resident/snapshot/ram-000.bin').write_bytes(bytes(32))
        with self.assertRaises(ValueError):incremental._check_declared_archive(archive,binding)

    def test_complete_copied_resident_graph_counts_toward_declaration_byte_bound(self):
        self.fixture();admitted=self.declare()
        numeric=admitted.path.stat().st_size+(admitted.path.parent/cd.MAP_NAME).stat().st_size
        self.assertGreater(cd._resident_bytes(admitted._resident),0)
        with patch.object(cd,'MAX_DECLARATION_BYTES',numeric):
            with self.assertRaisesRegex(ValueError,'bound'):cd.load(admitted.path,self.images)
            with self.assertRaisesRegex(ValueError,'bound'):self.declare('oversized')
        self.assertFalse((self.root/'oversized').exists())

    def test_consumer_must_match_the_resident_firmware_profile_and_assets(self):
        self.fixture();admitted=self.declare();machine=admitted.source_metadata['resident']['machine']
        config=dict(boot=copy.deepcopy(machine['boot']),**{name:dict(sha256=sha) for name,sha in machine['assets'].items()})
        project._cd_load_source(config,self.images,admitted)
        for mutate in (lambda value:value['bios'].__setitem__('sha256','b'*64),
                       lambda value:value['boot'].__setitem__('profile','super'),
                       lambda value:value.__setitem__('bram',dict(sha256='c'*64))):
            changed=copy.deepcopy(config);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):project._cd_load_source(changed,self.images,admitted)

    def test_options_require_explicit_source_and_traversal(self):
        self.fixture()
        for options in (dict(resident_snapshot=self.snapshot.path),dict(resident_ranges=self.ranges),
                        dict(resident_snapshot=self.snapshot.path,resident_ranges=self.ranges)):
            with self.subTest(options=options),self.assertRaises(ValueError):
                cd.declare(self.map,self.root/'invalid',**self.images,**options)
        self.assertFalse((self.root/'invalid').exists())

    def test_far_call_reconstructs_only_a_known_resident_return_word(self):
        # Consume the original JSR word, push a proven replacement and RTS $4008.
        self.fixture(raw=bytes.fromhex('201040ffffffffffa97780fe'),resident=bytes.fromhex('68faa94048a9074860'))
        legacy=self.declare('legacy',data_ranges=[(0x100003,5)])
        self.assertNotIn(0x4008,{row['pc'] for row in legacy.instructions})
        admitted=self.declare('far',analysis_policy=cd.FAR_CALL_POLICY,data_ranges=[(0x100003,5)])
        pcs={row['pc'] for row in admitted.instructions}
        self.assertIn(0x4008,pcs);self.assertIn(0x400a,pcs);self.assertNotIn(0x4003,pcs)
        doc=json.loads(admitted.path.read_text());self.assertEqual(doc['analysis']['policy'],cd.FAR_CALL_POLICY)
        self.assertTrue(any(edge['kind']=='reconstructed_return' for edge in doc['groups'][0]['analysis']['edges']))
        doc['analysis']['policy']=cd.ANALYSIS_POLICY;admitted.path.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaises(ValueError):cd.load(admitted.path,self.images)

    def test_far_call_unknown_stack_byte_does_not_invent_a_target(self):
        self.fixture(raw=bytes.fromhex('201040ffffffffffa97780fe'),resident=bytes.fromhex('68faad002048a9074860'))
        admitted=self.declare(analysis_policy=cd.FAR_CALL_POLICY,data_ranges=[(0x100003,5)])
        graph=json.loads(admitted.path.read_text())['groups'][0]['analysis']
        self.assertNotIn(0x4008,{row['pc'] for row in admitted.instructions})
        self.assertTrue(graph['unresolved'])


if __name__=='__main__':unittest.main()
