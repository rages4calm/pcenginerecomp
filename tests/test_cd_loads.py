"""Authored offline CD sources preserve load variants, media closure and evidence roles."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import cd_loads as cd, declarations, project, prepare, incremental, cli
from pcerecomp.emitter import emit_declarations
from pcerecomp.history import compose_history
from pcerecomp.native_catalog import load_native_catalog, CD_LOADS_PRODUCER_CONTRACT, DECLARED_PRODUCER_CONTRACT
from pcerecomp.toc import Toc
from tests.test_capture import capture, observation
from tests import test_project

MPR = [255, 248, 128, 129, 130, 131, 132, 0]


def digest(raw): return hashlib.sha256(raw).hexdigest()


def load(id, lba, raw, destination=0x100000):
    return dict(id=id, lba=lba, byte_offset=0, sectors=(len(raw)+2047)//2048,
                length=len(raw), destination=destination, sha256=digest(raw))


def fixture(directory, cue=False):
    raw = bytes(2048) + bytes.fromhex('a94280fe') + bytes(2044)
    raw += bytes.fromhex('a90980fe') + bytes(2044) + bytes.fromhex('a90b') + bytes(2046)
    if cue:
        (directory/'tracks.bin').write_bytes(raw)
        disc = directory/'disc.cue'
        disc.write_text('FILE "tracks.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n', encoding='ascii')
    else:
        disc = directory/'disc.iso';disc.write_bytes(raw)
    toc = directory/'toc.txt';toc.write_text(Toc.from_image(disc).text(),encoding='ascii',newline='\n')
    map = dict(format=cd.MAP_FORMAT, schema=1, coordinate=cd.COORDINATE, policy=cd.POLICY,
        media=dict(format='cue' if cue else 'iso', image_sha256=Toc.from_image(disc).image_sha256, toc_sha256=project.sha256(toc)),
        groups=[dict(id='first', mpr=MPR.copy(), loads=[load('body',1,bytes.fromhex('a94280fe'))], roots=[0x4000,0x4002]),
                dict(id='second', mpr=MPR.copy(), loads=[load('body',2,bytes.fromhex('a90980fe'))], roots=[0x4000,0x4002]),
                dict(id='split', mpr=MPR.copy(), loads=[load('body',1,bytes.fromhex('a942')),
                    load('work',3,bytes.fromhex('a90b'),0x1f0000)], roots=[0x2000,0x4000])])
    path=directory/'map.json';path.write_text(json.dumps(map),encoding='utf-8')
    return path, dict(disc=disc,toc=toc), map


class CdLoadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.spec,self.images,self.map=fixture(self.root)
        self.admitted=cd.declare(self.spec,self.root/'declared',**self.images)
        self.path=self.admitted.path

    def write_map(self, value):
        self.spec.write_text(json.dumps(value),encoding='utf-8')

    def guard_reads(self, watched, requests):
        """Independent I/O guard: an unbounded reopen must fail this test."""
        original=Path.open
        class Guard:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def __getattr__(self,name):return getattr(self.stream,name)
            def read(self,size=-1):
                requests.append(size)
                if type(size) is not int or not 0<=size<=64*1024*1024+1:
                    raise AssertionError('Unbounded read after source size check')
                return self.stream.read(size)
        def open(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return Guard(stream) if path in watched and args and args[0]=='rb' else stream
        return patch.object(Path,'open',open)

    def test_declare_uses_original_snapshot_and_refuses_map_growth_after_derivation(self):
        requests=[];derive=cd._derive
        def grow(*args,**kwargs):
            value=derive(*args,**kwargs)
            with self.spec.open('ab') as stream:stream.write(b'x'*65537)
            return value
        out=self.root/'grown-map'
        with patch.object(cd,'MAX_DECLARATION_BYTES',65536), patch.object(cd,'_derive',grow), self.guard_reads({self.spec},requests):
            with self.assertRaises(ValueError):cd.declare(self.spec,out,**self.images)
        self.assertTrue(requests)
        self.assertFalse(out.exists())

    def test_copy_refuses_numeric_growth_between_admission_and_copy_without_unbounded_read(self):
        for index,target in enumerate((self.path,self.path.parent/cd.MAP_NAME)):
            raw=target.read_bytes();requests=[];load_original=cd.load
            def grow(*args,**kwargs):
                admitted=load_original(*args,**kwargs)
                with target.open('ab') as stream:stream.write(b'x'*65537)
                return admitted
            out=self.root/f'grown-copy-{index}'
            try:
                with patch.object(cd,'MAX_DECLARATION_BYTES',65536),patch.object(cd,'load',grow),self.guard_reads({target},requests):
                    with self.assertRaises(ValueError):cd.copy_declarations(self.path,out,self.images)
                self.assertTrue(requests)
                self.assertFalse((out/target.name).exists())
            finally:target.write_bytes(raw)

    def test_toc_growth_after_binding_reads_only_its_explicit_bound(self):
        requests=[];toc=self.images['toc'];from_image=cd.Toc.from_image;grown=[False]
        def grow(path):
            value=from_image(path)
            if not grown[0]:
                grown[0]=True
                with toc.open('ab') as stream:stream.write(b'x'*(cd.MAX_DESCRIPTOR_BYTES+1))
            return value
        with patch.object(cd.Toc,'from_image',grow),self.guard_reads({toc},requests):
            with self.assertRaisesRegex(ValueError,'TOC changed'):cd.declare(self.spec,self.root/'grown-toc',**self.images)
        self.assertIn(cd.MAX_DESCRIPTOR_BYTES+1,requests)
        self.assertFalse((self.root/'grown-toc').exists())

    def test_alternative_groups_disjoint_loads_and_exact_fetch_identities(self):
        compilation=declarations.load_compilation(self.path,source_images=self.images)
        self.assertEqual((len(compilation.instructions),len(compilation.declared_keys)),(4,4))
        self.assertEqual(compilation.counts()['declared_roots_count'],6)
        self.assertFalse(compilation.observed_keys)
        self.assertTrue(all('native_hits' not in row and 'interpreted_hits' not in row for row in compilation.instructions))
        self.assertEqual(self.admitted.source_metadata['memberships'],6)
        roots=self.admitted.roots
        self.assertEqual(roots[0]['fetch'],[dict(load='body',offset=0,disc_byte_offset=2048),dict(load='body',offset=1,disc_byte_offset=2049)])
        self.assertEqual(roots[2]['fetch'][0]['disc_byte_offset'],4096)
        self.assertTrue(any(tuple(row['data'])==(169,11) and tuple(row['physical'])==(0x1f0000,0x1f0001) for row in compilation.instructions))
        self.assertEqual(compilation.static_reachability,'not_inferred')
        self.assertTrue(any(row['reason']=='control_successors_not_traversed' for row in compilation.diagnostics))
        self.assertEqual(self.spec.read_bytes(),(self.path.parent/cd.MAP_NAME).read_bytes())

    def test_wram_fetch_mirror_preserves_original_physical_key(self):
        value=copy.deepcopy(self.map)
        mirrored=copy.deepcopy(value['groups'][2]);mirrored['id']='mirror';mirrored['mpr'][1]=249
        value['groups'].append(mirrored);self.write_map(value)
        a=cd.declare(self.spec,self.root/'mirrors',**self.images)
        keys={(row['pc'],tuple(row['mpr']),tuple(row['physical'])) for row in a.instructions}
        self.assertIn((0x2000,tuple(MPR), (0x1f0000,0x1f0001)),keys)
        self.assertIn((0x2000,tuple(mirrored['mpr']),(0x1f2000,0x1f2001)),keys)
        self.assertEqual([r for r in a.roots if r['group']=='mirror'][0]['fetch'][0],
                         dict(load='work',offset=0,disc_byte_offset=6144))

    def test_unaligned_direct_copy_crosses_sectors_with_exact_disc_offsets(self):
        raw=bytearray(self.images['disc'].read_bytes());raw[4095:4098]=bytes.fromhex('a942ea')
        self.images['disc'].write_bytes(raw)
        self.images['toc'].write_text(Toc.from_image(self.images['disc']).text(),encoding='ascii',newline='\n')
        value=copy.deepcopy(self.map)
        value['media'].update(image_sha256=project.sha256(self.images['disc']),toc_sha256=project.sha256(self.images['toc']))
        value['groups']=[dict(id='unaligned',mpr=MPR.copy(),loads=[dict(id='body',lba=1,byte_offset=2047,sectors=2,
            length=3,destination=0x100000,sha256=digest(bytes.fromhex('a942ea')))],roots=[0x4000,0x4002])]
        self.write_map(value);a=cd.declare(self.spec,self.root/'unaligned',**self.images)
        self.assertEqual(a.roots[0]['fetch'],[dict(load='body',offset=0,disc_byte_offset=4095),dict(load='body',offset=1,disc_byte_offset=4096)])
        self.assertEqual(a.roots[1]['fetch'],[dict(load='body',offset=2,disc_byte_offset=4097)])
        value['groups'][0]['loads'][0]['sectors']=1;self.write_map(value)
        with self.assertRaises(ValueError):cd.declare(self.spec,self.root/'bad-unaligned',**self.images)

    def test_invalid_numeric_maps_refuse_before_output(self):
        edits=[lambda m:m.update(policy='decompress'),lambda m:m.update(coordinate='track-relative'),
            lambda m:m.update(execution_evidence=True),lambda m:m['groups'][0].update(guessed=True),
            lambda m:m['groups'][0]['loads'][0].update(destination=0x1f2000),
            lambda m:m['groups'][0]['loads'][0].update(destination=0x10ffff),
            lambda m:m['groups'][0]['loads'][0].update(lba=True),
            lambda m:m['groups'][0]['loads'][0].update(byte_offset=2048),
            lambda m:m['groups'][0]['loads'][0].update(lba=2**64),
            lambda m:m['groups'][0]['loads'][0].update(length=0),
            lambda m:m['groups'][0]['loads'][0].update(sectors=2),
            lambda m:m['groups'][0]['loads'][0].update(sha256='0'*64),
            lambda m:m['groups'][0].update(roots=[0x4000,0x4000]),
            lambda m:m['groups'][0].update(roots=[True]),
            lambda m:m['groups'][0].update(mpr=[128]),
            lambda m:m['groups'][0]['mpr'].__setitem__(2,255),
            lambda m:m['groups'][0].update(roots=[0x4003]), # BRA operand is opcode FE: missing operands.
            lambda m:m['groups'][0].update(roots=[0x4004]),
            lambda m:m['groups'][0]['loads'].append(load('overlap',1,b'\xea',0x100010)),
            lambda m:m['groups'][0]['loads'].append(load('overlap',3,b'\xea',0x100001)),
            lambda m:m['groups'][0]['loads'][0].update(lba=4)]
        for index,edit in enumerate(edits):
            value=copy.deepcopy(self.map);edit(value);self.write_map(value);out=self.root/f'bad-{index}'
            with self.subTest(index=index),self.assertRaises(ValueError):cd.declare(self.spec,out,**self.images)
            self.assertFalse(out.exists())

    def test_media_toc_and_numeric_members_cannot_change_after_admission(self):
        for path in (self.path,self.path.parent/cd.MAP_NAME,self.images['disc'],self.images['toc']):
            raw=path.read_bytes();path.write_bytes(raw+b' ')
            with self.subTest(path=path),self.assertRaises(ValueError):self.admitted.revalidate()
            path.write_bytes(raw)
        self.admitted.revalidate()

    def test_wrong_media_wrong_toc_and_short_reader_refuse(self):
        for key in ('image_sha256','toc_sha256'):
            value=copy.deepcopy(self.map);value['media'][key]='0'*64;self.write_map(value)
            with self.subTest(key=key),self.assertRaises(ValueError):cd.declare(self.spec,self.root/key,**self.images)
        self.write_map(self.map)
        with patch('pcerecomp.cd_loads.IsoReader.sector',return_value=b'\xea'):
            with self.assertRaisesRegex(ValueError,'incomplete'):cd.declare(self.spec,self.root/'short',**self.images)
        toc=self.images['toc'];toc.write_text(toc.read_text().replace('track 1 0 4','track 1 0 0'),encoding='ascii')
        value=copy.deepcopy(self.map);value['media']['toc_sha256']=project.sha256(toc);self.write_map(value)
        with self.assertRaisesRegex(ValueError,'TOC'):cd.declare(self.spec,self.root/'audio-toc',**self.images)

    def test_declared_graph_tamper_is_rederived_with_typed_equality(self):
        original=self.path.read_bytes()
        edits=[lambda v:v['groups'][0]['roots'][0]['fetch'][0].update(offset=1),
               lambda v:v['groups'][0]['roots'][0]['fetch'][0].update(offset=False),
               lambda v:v['groups'][0]['loads'][0].update(sha256='0'*64),
               lambda v:v['media'].update(leadout_lba=100),
               lambda v:v.update(execution_evidence=True)]
        for edit in edits:
            value=json.loads(original);edit(value);self.path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(ValueError):declarations.load_compilation(self.path,source_images=self.images)
        self.path.write_bytes(original)

    def test_exact_media_key_selection_refuses_boot_impersonation_and_unused_decoder(self):
        for images in (None,dict(disc=self.images['disc']),dict(payload=self.images['disc']),
                       self.images|dict(libchdr=self.images['disc'])):
            with self.subTest(images=images),self.assertRaises(ValueError):declarations.load_compilation(self.path,source_images=images)
        with self.assertRaises(ValueError):declarations.load_compilation(self.path,self.images['disc'])

    def test_cue_complete_component_identity_and_changed_bin(self):
        directory=self.root/'cue';directory.mkdir();spec,images,map=fixture(directory,cue=True)
        a=cd.declare(spec,directory/'declared',**images)
        self.assertEqual([row['data'] for row in a.instructions],[row['data'] for row in self.admitted.instructions])
        self.assertIn('disc_component:tracks.bin',a.artifact_bindings)
        self.assertNotEqual(project.sha256(images['disc']),a.source_metadata['media']['image_sha256'])
        (directory/'tracks.bin').write_bytes(bytes(8192))
        with self.assertRaises(ValueError):a.revalidate()
        with self.assertRaises(ValueError):cd.load(a.path,images)

    def test_cue_audio_and_virtual_gaps_refused_as_data(self):
        for name,body in (('audio','FILE "tracks.bin" BINARY\n TRACK 01 AUDIO\n INDEX 01 00:00:00\n'),
                          ('gap','FILE "tracks.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n TRACK 02 MODE1/2048\n PREGAP 00:00:02\n INDEX 01 00:00:02\n')):
            directory=self.root/name;directory.mkdir();(directory/'tracks.bin').write_bytes(bytes(2352*4) if name=='audio' else bytes(2048*4))
            disc=directory/'disc.cue';disc.write_text(body,encoding='ascii');toc=directory/'toc.txt';toc.write_text(Toc.from_image(disc).text(),encoding='ascii',newline='\n')
            value=copy.deepcopy(self.map);value['media']=dict(format='cue',image_sha256=Toc.from_image(disc).image_sha256,toc_sha256=project.sha256(toc))
            if name=='gap':value['groups']=[dict(id='gap',mpr=MPR.copy(),loads=[load('body',2,b'\xea')],roots=[0x4000])]
            spec=directory/'map.json';spec.write_text(json.dumps(value),encoding='utf-8')
            with self.subTest(name=name),self.assertRaises(ValueError):cd.declare(spec,directory/'out',disc=disc,toc=toc)

    def test_emission_catalogue_and_genuine_history_union(self):
        emitted=self.root/'module';manifest=emit_declarations(self.path,None,emitted,source_images=self.images,partition_layout='stable')
        self.assertEqual((manifest['declared_instructions'],manifest['observed_instructions']),(4,0))
        self.assertIn('s.a=66;', '\n'.join(p.read_text() for p in emitted.glob('*.cpp')))
        c=load_native_catalog(emitted/'module.json',self.path,source_images=self.images,producer_contract=CD_LOADS_PRODUCER_CONTRACT)
        self.assertEqual(c.provenance['format'],'pce-native-catalog-5');self.assertEqual(c.emitted,c.declared)
        self.assertFalse(c.observed);self.assertEqual(set(c.provenance['cd_media_inputs']),{'source_image:disc','source_image:toc'})
        self.assertEqual(c.provenance['declaration_members'][0]['relative'],cd.MAP_NAME)
        with self.assertRaises(ValueError):load_native_catalog(emitted/'module.json',self.path,source_images=self.images,producer_contract=DECLARED_PRODUCER_CONTRACT)
        cap=self.root/'actual.json';cap.write_text(json.dumps(capture([observation(0x4000,(0xa9,0x42),MPR,native=0,interpreted=7)])),encoding='utf-8')
        history=compose_history([cap],self.root/'history')
        union=declarations.load_compilation(self.path,source_images=self.images,observation_history=history)
        self.assertEqual((len(union.observed_keys),len(union.declared_keys)),(1,4))
        self.assertEqual(next(row for row in union.instructions if row.get('interpreted_hits'))['interpreted_hits'],7)
        mixed=emit_declarations(self.path,None,self.root/'mixed',source_images=self.images,observation_history=history)
        self.assertEqual((mixed['declared_only'],mixed['declared_observed_overlap']),(3,1))
        self.assertEqual(mixed['historical_totals'],dict(native_hits=0,interpreted_hits=7,retired_instructions=7))

    def test_consumer_preparation_managed_archive_and_generic_reemission_arguments(self):
        fixture=test_project.ConsumerProjectTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        config=tomllib.loads(fixture.text)
        recipe=dict(schema=1,format=prepare.FORMAT,name='offline-cd',sdk=dict(revision='0'*40,allow_revision_override=True),
            module=dict(kind='cd-loads',path=str(self.path)),payload=config['payload'],runtime=config['runtime'],limits=config['limits'],
            disc=dict(path=str(self.images['disc'])),toc=dict(path=str(self.images['toc'])))
        recipe['payload']['path']=str(fixture.root/'program.bin')
        spec=self.root/'consumer.toml';spec.write_text(prepare._toml(recipe),encoding='utf-8')
        with patch.object(prepare,'TOOL_ROOT',fixture.tool):receipt=prepare.prepare_project(spec,self.root/'consumer')
        self.assertFalse(receipt['executed']);self.assertFalse(receipt['compiled'])
        checked=project.verify(self.root/'consumer/project.toml',allow_revision_override=True)
        args=project.declaration_arguments(checked);self.assertIsNone(args['image_path']);self.assertEqual(args['source_images'],self.images)
        module=incremental._module(checked)
        self.assertIn(cd.MAP_NAME,module);self.assertIn('declared-roots.json',module)
        self.assertNotIn(self.images['disc'],module.values());self.assertNotIn(self.images['toc'],module.values())
        archive=self.root/'archive';archive.mkdir();incremental._sync(module,archive)
        member=dict(file=cd.MAP_NAME,sha256=project.sha256(module[cd.MAP_NAME]),size_bytes=module[cd.MAP_NAME].stat().st_size)
        binding=dict(file='declared-roots.json',sha256=project.sha256(module['declared-roots.json']),members=[member])
        incremental._check_declared_archive(archive,binding)
        for bad in (binding|dict(members=[]),binding|dict(members=[member|dict(file='../outside')])):
            with self.assertRaises(ValueError):incremental._check_declared_archive(archive,bad)
        (archive/cd.MAP_NAME).write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):incremental._check_declared_archive(archive,binding)

    def test_cli_declares_verifies_emits_and_accepts_cd_catalogue_bindings(self):
        common=['--disc',str(self.images['disc']),'--toc',str(self.images['toc'])]
        out=self.root/'cli'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['declare-cd-loads',str(self.spec),*common,'--out',str(out)]),0)
            self.assertEqual(cli.main(['verify-cd-loads',str(out/'roots.json'),*common]),0)
            self.assertEqual(cli.main(['emit-cd-loads',str(out/'roots.json'),*common,'--out',str(self.root/'cli-module')]),0)
            self.assertEqual(cli.main(['declared-roots',str(out/'roots.json'),'--cd-source','disc='+str(self.images['disc']),
                                      '--cd-source','toc='+str(self.images['toc'])]),0)
        self.assertEqual(cli.cd_source_images(['disc=C:\\disc.iso','toc=C:\\toc.txt'])['disc'],Path('C:\\disc.iso'))
        for values in (['disc=x'],['disc=x','disc=y','toc=z'],['payload=x','toc=z']):
            with self.assertRaises(ValueError):cli.cd_source_images(values)


if __name__=='__main__':unittest.main()
