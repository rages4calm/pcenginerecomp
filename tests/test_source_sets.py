"""Closed, independently admitted source sets preserve source and evidence roles."""
import copy,json,hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from pcerecomp import declarations as d,source_sets as s,prepare,project,incremental as inc,cli
from pcerecomp.emitter import emit_declarations
from pcerecomp.history import compose_history
from tests.test_boot_declarations import document
from tests.test_capture import capture,observation
from tests import test_project


class SourceSetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.payload=self.root/'payload.bin';self.payload.write_bytes(bytes.fromhex('A9 42 80 FE'))
        self.bios=self.root/'bios.bin';self.bios.write_bytes(bytes.fromhex('A9 09 60')+bytes(262141))
        self.images=dict(payload=self.payload,bios=self.bios)
        self.program=self.root/'program.json';self.firmware=self.root/'firmware.json'
        self.program.write_text(json.dumps(document(self.payload.read_bytes())),encoding='utf-8')
        firmware=document(self.bios.read_bytes(),'system-card',pc=0xE000,mpr=[0,248,128,0,0,0,0,0],offsets=(0,1))
        firmware['image'].pop('profile');firmware['image']['kind']='bios'
        self.firmware.write_text(json.dumps(firmware),encoding='utf-8')
        self.rows=[dict(id='program',asset='payload',path=self.program),dict(id='firmware',asset='bios',path=self.firmware)]
        self.admitted=s.compose_source_set(self.rows,self.root/'set',self.images);self.path=self.admitted.path

    def load(self):return d.load_compilation(self.path,source_images=self.images)
    def mutate(self,callback):
        value=json.loads(self.path.read_text(encoding='utf-8'));callback(value);self.path.write_text(json.dumps(value),encoding='utf-8')

    def test_two_independent_sources_union_without_observed_work(self):
        c=self.load();self.assertEqual(c.counts()['declared_only'],2);self.assertFalse(c.observed_keys)
        self.assertEqual(c.provenance['declared_roots_format'],s.FORMAT)
        self.assertEqual([v['asset'] for v in c.declarations.members],['payload','bios'])
        self.assertTrue(all('native_hits' not in ins for ins in c.instructions));c.revalidate()

    def test_overlap_keeps_all_source_membership(self):
        rows=self.rows+[dict(id='program_alias',asset='payload',path=self.program)]
        a=s.compose_source_set(rows,self.root/'overlap',self.images)
        self.assertEqual(len(a.instructions),2);self.assertEqual(len(a.roots),3)
        self.assertEqual(a.source_metadata['memberships'],3);self.assertEqual(a.source_metadata['overlapping_identities'],1)

    def test_copy_preserves_exact_numeric_bytes_and_external_images(self):
        a=s.copy_source_set(self.path,self.root/'copy',self.images)
        self.assertEqual(a.sha256,self.admitted.sha256);self.assertEqual(a.source_metadata,self.admitted.source_metadata)
        self.assertEqual(len(list((self.root/'copy').rglob('*.*'))),3)
        for _,_,member in a._members:self.assertEqual(member.path.read_bytes(),(self.path.parent/s.MEMBER_DIR/member.path.name).read_bytes())

    def test_history_preserves_authentic_hits_and_overlap(self):
        ins=self.load().instructions[0];row=observation(ins['pc'],ins['data'],ins['mpr'],native=2,interpreted=3)
        cap=self.root/'capture.json';cap.write_text(json.dumps(capture([row])),encoding='utf-8')
        h=compose_history([cap],self.root/'history')
        c=d.load_compilation(self.path,source_images=self.images,observation_history=h.index_path)
        self.assertEqual(c.counts()['declared_observed_overlap'],1);self.assertEqual(c.accounting,h.accounting)
        self.assertEqual(c.history.input_metadata,h.input_metadata)

    def test_source_images_are_explicit_and_typed(self):
        for images in (None,{},dict(unknown=self.payload),dict(payload=self.payload)):
            with self.subTest(images=images),self.assertRaises(ValueError):d.load_declarations(self.path,source_images=images)
        with self.assertRaises(ValueError):d.load_declarations(self.path,self.payload)
        with self.assertRaises(ValueError):d.load_declarations(self.program,self.payload,source_images=self.images)

    def test_member_fields_paths_ids_and_versions_refuse(self):
        raw=self.path.read_bytes()
        edits=[lambda v:v.update(schema=True),lambda v:v.update(execution_evidence=0),lambda v:v.update(extra=1),
            lambda v:v['sources'][0].update(id='../escape'),lambda v:v['sources'][0].update(asset='disc'),
            lambda v:v['sources'][0].update(path='../program.json'),lambda v:v['sources'][0].update(path='declared-sources/PROGRAM.json'),
            lambda v:v['sources'][0].update(sha256='A'*64),lambda v:v['sources'].append(copy.deepcopy(v['sources'][0])),
            lambda v:v.update(sources=[]),lambda v:v.update(sources=v['sources']*33)]
        for edit in edits:
            self.path.write_bytes(raw);self.mutate(edit)
            with self.subTest(edit=edit),self.assertRaises(ValueError):self.load()

    def test_member_and_image_changes_refuse_at_use(self):
        for path in (self.path,self.path.parent/'declared-sources/program.json',self.payload,self.bios):
            raw=path.read_bytes();path.write_bytes(raw+b' ')
            with self.subTest(path=path),self.assertRaises(ValueError):self.admitted.revalidate()
            path.write_bytes(raw)
        self.admitted.revalidate()

    def test_extra_member_and_hash_updated_forgery_refuse(self):
        extra=self.path.parent/'declared-sources/extra.json';extra.write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):self.load()
        extra.unlink();member=self.path.parent/'declared-sources/program.json'
        value=json.loads(member.read_text(encoding='utf-8'));value['roots'][0]['source_offsets']=[1,2]
        member.write_text(json.dumps(value),encoding='utf-8')
        self.mutate(lambda v:v['sources'][0].update(sha256=project.sha256(member)))
        with self.assertRaises(ValueError):self.load()

    def test_aggregate_numeric_and_root_bounds_refuse(self):
        with patch.object(s,'MAX_DECLARATION_BYTES',self.path.stat().st_size+1):
            with self.assertRaises(ValueError):self.load()
        with patch.object(s,'MAX_ROOTS',1):
            with self.assertRaises(ValueError):self.load()

    def test_nested_source_sets_and_existing_destinations_refuse(self):
        with self.assertRaises(ValueError):s.compose_source_set([dict(id='nested',asset='payload',path=self.path)],self.root/'nested',self.images)
        with self.assertRaises(ValueError):s.compose_source_set(self.rows,self.path.parent,self.images)
        with self.assertRaises(ValueError):s.copy_source_set(self.path,self.path.parent,self.images)

    def test_emission_has_translated_bodies_and_per_member_provenance(self):
        out=self.root/'module';m=emit_declarations(self.path,None,out,source_images=self.images,partition_layout='stable')
        self.assertEqual(m['declared_roots_source'],self.admitted.source_metadata)
        self.assertEqual((m['declared_instructions'],m['observed_instructions']),(2,0));self.assertFalse(m['execution_evidence'])
        self.assertEqual(m['native_instructions_emitted'],2)

    def test_sandbox_bios_does_not_invent_system_card_mirrors(self):
        value=json.loads(self.firmware.read_text(encoding='utf-8'));value['roots'][0]['mpr'][7]=32
        self.firmware.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'sandbox BIOS'):d.load_declarations(self.firmware,self.bios)

    def test_cli_asset_bindings_preserve_windows_paths_and_refuse_duplicates(self):
        self.assertEqual(cli.source_images(['payload=C:\\test\\program.bin'])['payload'],Path('C:\\test\\program.bin'))
        for values in (['payload=x','payload=y'],['disc=x'],['payload='],['payload']):
            with self.assertRaises(ValueError):cli.source_images(values)

    def test_copy_read_is_bounded_and_hash_checked(self):
        with self.assertRaises(ValueError):s._numeric_bytes(self.program,'0'*64)
        with patch.object(s,'MAX_DECLARATION_BYTES',1):
            with self.assertRaises(ValueError):s._numeric_bytes(self.program,project.sha256(self.program))

    def test_producers_cannot_modify_original_member_namespace(self):
        out=self.path.parent/s.MEMBER_DIR/'output'
        with self.assertRaises(ValueError):s.copy_source_set(self.path,out,self.images)
        with self.assertRaises(ValueError):emit_declarations(self.path,None,out,source_images=self.images)
        self.assertFalse(out.exists());self.admitted.revalidate()

    def test_cli_composition_and_validation_are_non_execution(self):
        import contextlib,io
        out=self.root/'cli-composed';argv=['compose-roots','--source','program:payload:'+str(self.program),
            '--source','firmware:bios:'+str(self.firmware),'--source-image','payload='+str(self.payload),
            '--source-image','bios='+str(self.bios),'--out',str(out)]
        stdout=io.StringIO()
        with contextlib.redirect_stdout(stdout):self.assertEqual(cli.main(argv),0)
        value=json.loads(stdout.getvalue());self.assertFalse(value['executed']);self.assertEqual(value['identities'],2)
        stdout=io.StringIO()
        with contextlib.redirect_stdout(stdout):self.assertEqual(cli.main(['declared-roots',str(out/'roots.json'),
                '--source-image','payload='+str(self.payload),'--source-image','bios='+str(self.bios)]),0)
        self.assertFalse(json.loads(stdout.getvalue())['execution_evidence'])

    def test_catalogue_reconstructs_member_graph_with_distinct_contract(self):
        from pcerecomp.native_catalog import load_native_catalog,SOURCE_SET_PRODUCER_CONTRACT
        out=self.root/'catalog-module';emit_declarations(self.path,None,out,source_images=self.images)
        c=load_native_catalog(out/'module.json',self.path,source_images=self.images,producer_contract=SOURCE_SET_PRODUCER_CONTRACT)
        self.assertEqual(len(c.declared),2);self.assertEqual(c.emitted,c.declared);self.assertFalse(c.observed)
        self.assertEqual(c.provenance['format'],'pce-native-catalog-3')
        self.assertEqual(c.provenance['selection_contract'],SOURCE_SET_PRODUCER_CONTRACT)
        self.assertEqual(len(c.provenance['declaration_members']),2)
        self.assertEqual(set(c.provenance['source_images']),{'payload','bios'})
        self.assertNotIn(str(self.root),json.dumps(c.provenance));self.assertNotIn('source_image',c.provenance)

    def test_catalogue_refuses_wrong_images_members_provenance_and_old_contract(self):
        from pcerecomp.native_catalog import load_native_catalog,DECLARED_PRODUCER_CONTRACT
        out=self.root/'strict-catalog';emit_declarations(self.path,None,out,source_images=self.images)
        with self.assertRaises(ValueError):load_native_catalog(out/'module.json',self.path,source_images=self.images,producer_contract=DECLARED_PRODUCER_CONTRACT)
        with self.assertRaises(ValueError):load_native_catalog(out/'module.json',self.path,image_path=self.payload)
        with self.assertRaises(ValueError):load_native_catalog(out/'module.json',self.path,source_images=dict(payload=self.bios,bios=self.payload))
        m=out/'module.json';value=json.loads(m.read_text(encoding='utf-8'));value['declared_roots_source']['members'][0]['asset']='bios'
        m.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaises(ValueError):load_native_catalog(m,self.path,source_images=self.images)

    def test_gap_report_and_cli_keep_unexecuted_member_entries_separate(self):
        from pcerecomp.native_catalog import load_native_catalog
        from pcerecomp.native_gaps import report_native_gaps
        import contextlib,io
        out=self.root/'gap-module';emit_declarations(self.path,None,out,source_images=self.images)
        c=load_native_catalog(out/'module.json',self.path,source_images=self.images)
        ins=self.load().instructions[0];cap=self.root/'window.json';cap.write_text(json.dumps(capture([observation(ins['pc'],ins['data'],ins['mpr'],native=1,interpreted=0)])),encoding='utf-8')
        report=report_native_gaps(c,[cap]);self.assertEqual(report['summary']['declared_emitted_exercised'],1)
        self.assertEqual(report['summary']['declared_emitted_unexercised'],1);self.assertFalse(c.observed)
        stdout=io.StringIO();report_path=self.root/'gaps.json'
        with contextlib.redirect_stdout(stdout):self.assertEqual(cli.main(['native-gaps',str(out/'module.json'),str(cap),
            '--observations',str(self.path),'--source-image','payload='+str(self.payload),'--source-image','bios='+str(self.bios),'--out',str(report_path)]),0)
        self.assertEqual(json.loads(report_path.read_text(encoding='utf-8'))['summary']['declared_emitted_exercised'],1)

    def test_managed_numeric_sync_and_archive_reads_are_bounded(self):
        files={'declared-roots.json':self.path}
        files.update({key.removeprefix('member:'):row['path'] for key,row in self.admitted.artifact_bindings.items() if key.startswith('member:')})
        owned=self.root/'bounded-owned';owned.mkdir();inc._sync(files,owned)
        binding=dict(file='declared-roots.json',sha256=self.admitted.sha256,members=[dict(file=name,sha256=project.sha256(path),size_bytes=path.stat().st_size) for name,path in files.items() if name.startswith('declared-sources/')])
        original=Path.open;requests=[]
        class Guard:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def __getattr__(self,name):return getattr(self.stream,name)
            def read(self,size=-1):
                requests.append(size)
                if not 0<=size<=d.MAX_DECLARATION_BYTES+1:raise AssertionError('Unbounded managed numeric read during possible source growth')
                return self.stream.read(size)
        def guarded(path,*args,**kwargs):return Guard(original(path,*args,**kwargs))
        with patch.object(Path,'open',guarded):
            inc._check_declared_archive(owned,binding);inc._sync(files,owned,old=files)
        self.assertTrue(requests)

    def test_consumer_and_prepare_bind_all_members_without_copying_images(self):
        fixture=test_project.ConsumerProjectTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        import tomllib
        config=tomllib.loads(fixture.text)
        config['payload']=dict(path=str(self.payload),sha256=project.sha256(self.payload),physical_load=0x100000,pc=0x4000,mpr=[0,248,128,0,0,0,0,0])
        config['bios']=dict(path=str(self.bios),sha256=project.sha256(self.bios))
        recipe=dict(schema=1,format=prepare.FORMAT,name='two-sources',sdk=dict(revision='0'*40,allow_revision_override=True),
            module=dict(kind='declared',path=str(self.path)),payload=config['payload'],bios=config['bios'],runtime=config['runtime'],limits=config['limits'])
        spec=self.root/'recipe.toml';spec.write_text(prepare._toml(recipe),encoding='utf-8')
        with patch.object(prepare,'TOOL_ROOT',fixture.tool):result=prepare.prepare_project(spec,self.root/'prepared')
        self.assertFalse(result['compiled']);checked=project.verify(self.root/'prepared/project.toml',allow_revision_override=True)
        module=inc._module(checked)
        self.assertTrue({'declared-roots.json','declared-sources/program.json','declared-sources/firmware.json'}<=module.keys())
        self.assertNotIn(self.payload,module.values());self.assertNotIn(self.bios,module.values())
        owned=self.root/'owned';owned.mkdir();inc._sync(module,owned)
        binding=dict(file='declared-roots.json',sha256=self.admitted.sha256,members=[dict(file=name,sha256=project.sha256(path),size_bytes=path.stat().st_size) for name,path in module.items() if name.startswith('declared-sources/')])
        inc._check_declared_archive(owned,binding)
        for change in ('tamper','missing-binding','extra'):
            bad=copy.deepcopy(binding);path=owned/'declared-sources/program.json';raw=path.read_bytes()
            if change=='tamper':path.write_bytes(raw+b' ')
            elif change=='missing-binding':bad.pop('members')
            else:(owned/'declared-sources/extra.json').write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):inc._check_declared_archive(owned,bad)
            path.write_bytes(raw);(owned/'declared-sources/extra.json').unlink(missing_ok=True)
        declarations=self.admitted
        wrong=copy.deepcopy(config);wrong['payload']['physical_load']=0x102000
        with self.assertRaisesRegex(ValueError,'contract'):project._declared_source_set(wrong,self.images,declarations)
        wrong=copy.deepcopy(config);wrong.pop('payload');wrong['boot']=dict(mode='system-card-reset',profile='standard')
        with self.assertRaises(ValueError):project._declared_source_set(wrong,self.images,declarations)


if __name__=='__main__':unittest.main()
