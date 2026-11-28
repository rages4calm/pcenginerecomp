"""Authored known-vector source candidates, never execution/closure evidence."""
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import cd_loads as cd, overlays, overlay_snapshot as snapshots, origin_overlay, prepare, project, incremental
from pcerecomp.toc import Toc
from tests.test_cd_loads import MPR, load, digest
from tests.test_overlays import ReportedRam, ORIGIN, machine
from tests.test_origin_overlay import ReportedOrigins, disc_machine
from tests import test_project


POLICY = 'bounded-ram-cd-vectors-v1'


class MultiRam(ReportedRam):
    def __init__(self, chunks, mpr=None):
        self.chunks = sorted(chunks)
        super().__init__(self.chunks[0][1], start=self.chunks[0][0], mpr=mpr)

    def call(self, command, **args):
        if command != 'read_memory_block': return super().call(command, **args)
        self.identity += 1;self.calls.append((command,args))
        start, length = args['address'], args['length']
        for base, raw in self.chunks:
            if base <= start < start+length <= base+len(raw):
                return dict(id=self.identity,ok=True,address=start,length=length,data=raw[start-base:start-base+length].hex())
        raise AssertionError('Authored read crossed a source gap')


def body(opcode='6c2040'):
    raw=bytearray(34);raw[:len(bytes.fromhex(opcode))]=bytes.fromhex(opcode)
    raw[16:18]=bytes.fromhex('80fe');raw[32:34]=bytes.fromhex('1040')
    return bytes(raw)


class VectorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.number=0

    def snapshot(self, chunks=None, mpr=None):
        self.number+=1
        client=MultiRam(chunks or [(0x100000,body())],mpr)
        captured=snapshots.capture_snapshot(client,self.root/f'snapshot{self.number}',machine=machine(),origin=ORIGIN,
            regions=[(start,len(raw)) for start,raw in client.chunks])
        return captured

    def overlay(self,snapshot=None,name='overlay',**options):
        snapshot=snapshot or self.snapshot()
        return overlays.discover_overlay(snapshot.path,self.root/name,code_ranges=options.pop('code_ranges',[(0x100000,34)]),
            analysis_policy=options.pop('analysis_policy',POLICY),vector_ranges=options.pop('vector_ranges',[(0x100020,2)]),**options)

    def cd_fixture(self, groups=None, raw=None):
        raw=raw or body();disc=self.root/'disc.iso'
        disc.write_bytes(bytes(2048)+raw+bytes((-len(raw))%2048))
        toc=self.root/'disc.toc';toc.write_text(Toc.from_image(disc).text(),encoding='ascii',newline='\n')
        self.images=dict(disc=disc,toc=toc)
        self.document=dict(format=cd.MAP_FORMAT,schema=1,coordinate=cd.COORDINATE,policy=cd.POLICY,
            media=dict(format='iso',image_sha256=Toc.from_image(disc).image_sha256,toc_sha256=digest(toc.read_bytes())),
            groups=groups or [dict(id='area',mpr=MPR.copy(),loads=[load('body',1,raw)],roots=[0x4000])])
        self.map=self.root/'map.json';self.write_map()

    def write_map(self):self.map.write_text(json.dumps(self.document),encoding='utf-8')

    def cd(self,name='declared',**options):
        return cd.declare(self.map,self.root/name,**self.images,
            analysis_policy=options.pop('analysis_policy',POLICY),
            vector_ranges=options.pop('vector_ranges',[(0x100020,2)]),**options)

    def vector_edge(self, graph):return next(e for e in graph['edges'] if e['kind']=='vector_jump')

    def test_overlay_pointer_data_is_not_code_and_each_byte_binds_the_snapshot(self):
        epoch=self.overlay();report=epoch.report;edge=self.vector_edge(report)
        self.assertEqual({i['pc'] for i in epoch._instructions},{0x4000,0x4010})
        self.assertEqual(report['options']['vector_ranges'],[[0x100020,2]])
        word=edge['vector_word'];self.assertEqual((word['pointer'],word['target']),(0x4020,0x4010))
        for side,logical,offset,value in [('low',0x4020,32,16),('high',0x4021,33,64)]:
            self.assertEqual(word[side],dict(logical=logical,physical=0x100000+offset,
                canonical_physical=0x100000+offset,value=value,
                provenance=dict(snapshot_sha256=epoch.snapshot.sha256,region=0,offset=offset)))
        self.assertFalse(report['execution_evidence']);self.assertFalse(report['routine_closure'])
        self.assertEqual(overlays.load_overlay(epoch.path).report,report)

    def test_known_index_unknown_index_and_missing_high_permission_remain_distinct(self):
        indexed=self.overlay(self.snapshot([(0x100000,body('a2027c1e40'))]),name='known')
        word=self.vector_edge(indexed.report)['vector_word'];self.assertEqual((word['index'],word['pointer']),(2,0x4020))
        unknown=self.overlay(self.snapshot([(0x100000,body('7c2040'))]),name='unknown')
        self.assertEqual({r['reason'] for r in unknown.report['unresolved']},{'unknown_vector_index'})
        self.assertEqual({i['pc'] for i in unknown._instructions},{0x4000})
        missing=self.overlay(self.snapshot(),name='missing',vector_ranges=[(0x100020,1)])
        failure=missing.report['unresolved'][0]
        self.assertEqual((failure['reason'],failure['detail']),('vector_read_unproven','vector_byte_outside_authenticated_range'))
        self.assertEqual(len(failure['reads']),1)

    def test_overlay_cross_mpr_and_ffff_wrap_reads_have_separate_regions(self):
        for label,opcode,mpr,low,high,logicals in [
            ('cross','6cff5f',MPR,0x101fff,0x102000,(0x5fff,0x6000)),
            ('wrap','6cffff',[130,*MPR[1:7],129],0x103fff,0x104000,(0xffff,0))]:
            snap=self.snapshot([(0x100000,body(opcode)[:32]),(low,b'\x10'),(high,b'\x40')],mpr=mpr)
            epoch=self.overlay(snap,name=label,code_ranges=[(0x100000,32)],vector_ranges=[(low,1),(high,1)])
            word=self.vector_edge(epoch.report)['vector_word']
            self.assertEqual((word['low']['logical'],word['high']['logical']),logicals)
            self.assertEqual((word['low']['physical'],word['high']['physical']),(low,high))
            self.assertEqual((word['low']['provenance']['region'],word['high']['provenance']['region']),(1,2))

    def test_canonical_wram_vector_permission_allows_a_mapped_read_alias(self):
        mapping=MPR.copy();mapping[3]=249
        snapshot=self.snapshot([(0x100000,body('6c2060')[:32]),(0x1f0020,b'\x10\x40')],mapping)
        epoch=self.overlay(snapshot,name='read-alias',code_ranges=[(0x100000,32)],vector_ranges=[(0x1f0020,2)])
        word=self.vector_edge(epoch.report)['vector_word']
        self.assertEqual(word['low']['physical'],0x1f2020)
        self.assertEqual(word['low']['canonical_physical'],0x1f0020)
        self.assertEqual(word['low']['provenance']['region'],1)
        self.assertEqual(word['target'],0x4010)

    def test_vector_ranges_are_explicit_canonical_nonempty_wholly_captured_data(self):
        snap=self.snapshot()
        for index,ranges in enumerate((None,[],[(0x100020,0)],[(0x1f2020,2)],[(0x100020,2),(0x100021,1)],
                                       [(0x100020,3)],[(True,2)],[(0x100020,True)])):
            with self.subTest(ranges=ranges),self.assertRaises(ValueError):self.overlay(snap,name=f'bad{index}',vector_ranges=ranges)
            self.assertFalse((self.root/f'bad{index}').exists())
        with self.assertRaises(ValueError):self.overlay(snap,name='entry-data',entries=[0x4020])
        self.assertFalse((self.root/'entry-data').exists())
        allowed=self.overlay(snap,name='ordinary-data-overlap',data_ranges=[(0x100020,2)])
        self.assertEqual(self.vector_edge(allowed.report)['vector_word']['target'],0x4010)
        for policy in (None,overlays.ANALYSIS_POLICY,overlays.FAR_CALL_POLICY):
            with self.assertRaises(ValueError):self.overlay(snap,name='legacy-refusal',analysis_policy=policy)

    def test_overlay_vector_writes_aliases_stack_and_t_stop_before_later_reads(self):
        alias=MPR.copy();alias[3]=249
        cases=[('a9018d2040',0x100020,2,None),('a9018d2020',0x1f0020,2,None),
               ('a9018d2060',0x1f0020,2,alias),('a201f46900',0x1f0001,1,None),('48',0x1f0100,1,None)]
        for index,(code,start,length,mpr) in enumerate(cases):
            raw=body(code);chunks=[(0x100000,raw)]
            if start>=0x1f0000:chunks.append((start,bytes(length)))
            epoch=self.overlay(self.snapshot(chunks,mpr),name=f'write{index}',code_ranges=[(0x100000,32)],
                               vector_ranges=[(start,length)])
            self.assertEqual(epoch.report['unresolved'][0]['reason'],'possible_vector_write')

    def test_origin_policy_keeps_full_epoch_and_source_binding(self):
        client=ReportedOrigins(body());snapshot=snapshots.capture_snapshot(client,self.root/'origin-snapshot',
            machine=disc_machine(),origin=ORIGIN,regions=[(0x100000,34)])
        origins=origin_overlay.capture_origins(client,snapshot.path,self.root/'origins')
        epoch=overlays.discover_origin_overlay(snapshot.path,origins.path,self.root/'origin-vector',disc_ranges=[(2048,34)],
            analysis_policy=POLICY,vector_ranges=[(0x100020,2)])
        self.assertEqual(epoch.report['analysis_policy'],'observed-disc-offset-vectors-v1')
        self.assertEqual(epoch.report['origins_sha256'],origins.sha256)
        self.assertEqual(self.vector_edge(epoch.report)['vector_word']['low']['provenance']['snapshot_sha256'],snapshot.sha256)
        epoch.revalidate()

    def test_overlay_forged_pointer_value_or_provenance_is_rederived_and_refused(self):
        epoch=self.overlay();original=epoch.path.read_bytes()
        for edit in (lambda w:w['low'].update(value=17),lambda w:w['low']['provenance'].update(offset=31),
                     lambda w:w['high']['provenance'].update(snapshot_sha256='a'*64),lambda w:w.update(target=0x4012)):
            document=json.loads(original);edit(self.vector_edge(document)['vector_word'])
            epoch.path.write_text(json.dumps(document),encoding='utf-8')
            with self.assertRaises(ValueError):overlays.load_overlay(epoch.path)
        epoch.path.write_bytes(original);epoch.revalidate()

    def test_cd_source_witnesses_bind_original_media_load_and_each_offset(self):
        self.cd_fixture();admitted=self.cd();document=json.loads(admitted.path.read_text())
        word=self.vector_edge(document['groups'][0]['analysis'])['vector_word']
        for side,offset in [('low',32),('high',33)]:
            provenance=word[side]['provenance']
            self.assertEqual((provenance['group'],provenance['load'],provenance['offset']),('area','body',offset))
            self.assertEqual(provenance['disc_byte_offset'],2048+offset)
            self.assertEqual(provenance['image_sha256'],self.document['media']['image_sha256'])
            self.assertEqual(provenance['load_sha256'],digest(body()))
            self.assertEqual(provenance['sectors_sha256'],digest(body()+bytes(2048-len(body()))))
        self.assertEqual({i['pc'] for i in admitted.instructions},{0x4000,0x4010})
        copied=cd.copy_declarations(admitted.path,self.root/'copied',self.images)
        self.assertEqual(copied.source_metadata,admitted.source_metadata)

    def test_cd_alternative_group_must_bind_even_unread_declared_vectors(self):
        self.cd_fixture()
        self.document['groups'].append(dict(id='missing',mpr=MPR.copy(),loads=[load('short',1,body()[:18])],roots=[0x4010]))
        self.write_map()
        with self.assertRaisesRegex(ValueError,'every load group'):self.cd()
        self.assertFalse((self.root/'declared').exists())

    def test_cd_cross_mpr_and_word_wrap_keep_independent_load_identities(self):
        for index,(opcode,mapping,low,high,logicals) in enumerate([
            ('6cff5f',MPR,0x101fff,0x102000,(0x5fff,0x6000)),
            ('6cffff',[130,*MPR[1:7],129],0x103fff,0x104000,(0xffff,0))]):
            code=body(opcode)[:32]
            raw=code+bytes(2048-len(code))+b'\x10'+bytes(2047)+b'\x40'+bytes(2047)
            groups=[dict(id='cross',mpr=mapping.copy(),loads=[load('code',1,code),
                load('low',2,b'\x10',low),load('high',3,b'\x40',high)],roots=[0x4000])]
            self.cd_fixture(groups=groups,raw=raw)
            admitted=self.cd(name=f'cross{index}',vector_ranges=[(low,1),(high,1)])
            word=self.vector_edge(json.loads(admitted.path.read_text())['groups'][0]['analysis'])['vector_word']
            self.assertEqual((word['low']['logical'],word['high']['logical']),logicals)
            self.assertEqual((word['low']['physical'],word['high']['physical']),(low,high))
            self.assertEqual((word['low']['provenance']['load'],word['high']['provenance']['load']),('low','high'))
            self.assertEqual((word['low']['provenance']['disc_byte_offset'],word['high']['provenance']['disc_byte_offset']),(4096,6144))
            self.assertEqual(word['target'],0x4010)

    def test_cd_vector_ranges_and_report_schema_reject_forged_provenance(self):
        self.cd_fixture();admitted=self.cd();original=admitted.path.read_bytes()
        for edit in (lambda d:d['analysis'].update(vector_ranges=[]),
                     lambda d:d['analysis'].update(policy=cd.FAR_CALL_POLICY),
                     lambda d:self.vector_edge(d['groups'][0]['analysis'])['vector_word']['low']['provenance'].update(disc_byte_offset=0),
                     lambda d:self.vector_edge(d['groups'][0]['analysis'])['vector_word']['high']['provenance'].update(image_sha256='0'*64)):
            document=json.loads(original);edit(document);admitted.path.write_text(json.dumps(document),encoding='utf-8')
            with self.assertRaises(ValueError):cd.load(admitted.path,self.images)
        admitted.path.write_bytes(original);admitted.revalidate()

    def test_resident_vector_word_can_split_its_two_bytes_from_a_cd_load(self):
        # Low byte is the final loaded byte at4020; high byte4021 comes from one
        # explicitly selected resident snapshot byte, with separate provenance.
        raw=body()[:33];self.cd_fixture(raw=raw)
        machine_doc=snapshots.machine_for(dict(boot=dict(mode='system-card-reset',profile='standard')),
            dict(bios='a'*64,disc=self.document['media']['image_sha256'],toc=self.document['media']['toc_sha256']))
        resident=ReportedRam(b'\x40'+bytes(7),start=0x100021,pc=0x4021)
        snapshot=snapshots.capture_snapshot(resident,self.root/'resident-input',machine=machine_doc,origin=ORIGIN,regions=[(0x100021,8)])
        admitted=self.cd(resident_snapshot=snapshot.path,resident_ranges=[(0x100021,1)])
        graph=json.loads(admitted.path.read_text())['groups'][0]['analysis'];word=self.vector_edge(graph)['vector_word']
        self.assertIn('load',word['low']['provenance']);self.assertIn('resident',word['high']['provenance'])
        self.assertEqual(word['high']['provenance']['resident']['snapshot_sha256'],snapshot.sha256)
        self.assertEqual(word['high']['provenance']['resident']['offset'],0)
        self.assertEqual(word['target'],0x4010)
        copied=cd.copy_declarations(admitted.path,self.root/'resident-copy',self.images)
        self.assertEqual(copied.instructions,admitted.instructions)
        members=copied.artifact_bindings
        self.assertIn('member:resident/snapshot/ram-000.bin',members)

    def test_prepared_consumer_and_managed_members_keep_resident_vector_provenance(self):
        bios=self.root/'bios.pce';bios.write_bytes(bytes(262144))
        raw=body()[:33];self.cd_fixture(raw=raw)
        machine_doc=snapshots.machine_for(dict(boot=dict(mode='system-card-reset',profile='standard')),
            dict(bios=digest(bios.read_bytes()),disc=self.document['media']['image_sha256'],toc=self.document['media']['toc_sha256']))
        client=ReportedRam(b'\x40'+bytes(7),start=0x100021,pc=0x4021)
        snapshot=snapshots.capture_snapshot(client,self.root/'resident-prepare',machine=machine_doc,origin=ORIGIN,regions=[(0x100021,8)])
        admitted=self.cd(resident_snapshot=snapshot.path,resident_ranges=[(0x100021,1)])
        fixture=test_project.ConsumerProjectTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        config=tomllib.loads(fixture.text)
        recipe=dict(schema=1,format=prepare.FORMAT,name='vector-cd',sdk=dict(revision='0'*40,allow_revision_override=True),
            module=dict(kind='cd-loads',path=str(admitted.path)),boot=dict(mode='system-card-reset',profile='standard'),
            bios=dict(path=str(bios)),disc=dict(path=str(self.images['disc'])),toc=dict(path=str(self.images['toc'])),
            runtime=config['runtime'],limits=config['limits'])
        spec=self.root/'consumer.toml';spec.write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
        with patch.object(prepare,'TOOL_ROOT',fixture.tool):receipt=prepare.prepare_project(spec,self.root/'consumer')
        self.assertFalse(receipt['compiled']);self.assertFalse(receipt['executed'])
        checked=project.verify(self.root/'consumer/project.toml',allow_revision_override=True)
        module=incremental._module(checked)
        self.assertIn('resident/resident.json',module)
        self.assertIn('resident/snapshot/ram-000.bin',module)
        archive=self.root/'managed';archive.mkdir();incremental._sync(module,archive)
        members=[dict(file=name.removeprefix('member:'),sha256=row['sha256'],size_bytes=row['size_bytes'])
                 for name,row in sorted(admitted.artifact_bindings.items()) if name.startswith('member:')]
        binding=dict(file='declared-roots.json',sha256=admitted.sha256,members=members)
        incremental._check_declared_archive(archive,binding)
        # Even an unused byte outside the selected one-byte vector range belongs
        # to the complete authenticated source member and cannot silently change.
        (archive/'resident/snapshot/ram-000.bin').write_bytes(b'\x40'+bytes(6)+b'\x01')
        with self.assertRaises(ValueError):incremental._check_declared_archive(archive,binding)


if __name__=='__main__':unittest.main()
