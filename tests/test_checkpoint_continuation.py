"""Continuation admission refusals and exact byte bindings; authored inputs only."""
import copy
import base64
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import checkpoint_continuation as continuation, prepare, project
from tests import test_prepare as prepare_fixtures
from tests import test_project as project_fixtures


class CheckpointContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def checkpoint(self,body=b'authored incomplete state; parser fixture only',identity='a'*64):
        digest=hashlib.sha256(body).hexdigest().encode()
        raw=b'PCEDEVCP'+struct.pack('<II',1,29)
        for value in (identity.encode(),digest):raw+=struct.pack('<I',len(value))+value
        raw+=struct.pack('<Q',len(body))+body
        path=self.root/'authored.pcec';path.write_bytes(raw)
        return path

    def test_checkpoint_file_digest_binds_original_bytes(self):
        path=self.checkpoint();original=path.read_bytes()
        result=continuation._checkpoint(path)
        self.assertEqual(result['identity'],'a'*64)
        self.assertEqual(result['sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(path.read_bytes(),original)

    def test_corrupt_truncated_and_wrong_abi_files_refused(self):
        path=self.checkpoint();original=path.read_bytes()
        wrong_abi=bytearray(original);struct.pack_into('<I',wrong_abi,12,28)
        for raw in (original[:-1],original+b'x',original[:-1]+b'X',bytes(wrong_abi),b''):
            with self.subTest(length=len(raw)):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):continuation._checkpoint(path)

    def prepared(self):
        fixture=prepare_fixtures.ConsumerPreparationTests();fixture.setUp();self.addCleanup(fixture.temp.cleanup)
        spec=fixture.recipe();output=self.root/'prepared'
        prepare.prepare_project(spec,output)
        return project.verify(output/'project.toml')

    def test_current_emitter_regeneration_preserves_inputs(self):
        checked=self.prepared();observations=checked['files']['module_observation_history']
        originals={path:path.read_bytes() for path in checked['files'].values()}
        result=continuation._reemit(checked,observations,{})
        self.assertEqual(result['policy'],'exact-sdk-reemission-v1')
        self.assertEqual(originals,{path:path.read_bytes() for path in originals})

    def test_membership_does_not_admit_modified_generated_operations(self):
        checked=self.prepared();observations=checked['files']['module_observation_history']
        source=checked['files']['module_source'];source.write_bytes(source.read_bytes()+b'\n// changed\n')
        with self.assertRaisesRegex(ValueError,'generated source'):
            continuation._reemit(checked,observations,{})

    def test_reemission_supports_original_extended_capture_framing(self):
        from pcerecomp.emitter import emit_capture
        from tests.test_extended_capture import extended, wire
        value=extended()
        raw=wire(value)
        source=self.root/'extended.jsonl';source.write_bytes(raw)
        output=self.root/'extended-module'
        emit_capture(value,output,hashlib.sha256(raw).hexdigest())
        checked=dict(files=dict(module_manifest=output/'module.json'))
        result=continuation._reemit(checked,source,{})
        self.assertEqual(result['policy'],'exact-sdk-reemission-v1')
        self.assertEqual(source.read_bytes(),raw)

    def test_old_ordinary_build_has_actionable_refusal(self):
        with self.assertRaisesRegex(ValueError,'new baseline.*verified cache or recoverable'):
            continuation._audit({},dict(execution_evidence=False),self.root)

    def test_unsupported_producer_cannot_authorize_continuation(self):
        with self.assertRaisesRegex(ValueError,'unsupported compiler producer'):
            continuation._audit({},dict(cache=dict(input_contract=dict(producer='invented'))),self.root)

    def test_continuation_provenance_preserves_imported_and_new_work(self):
        original=dict(resumed=True,origin=dict(sha256='a'*64,ticks=10,frame=2,native_steps=4,interpreter_steps=3),
            window=dict(ticks=2,native_steps=2,interpreter_steps=0),
            audio_origin=dict(pending_pcm_frames=17,source_wav_frames=123),
            continuation=dict(schema=1,receipt_sha256='b'*64,permit_sha256='c'*64,
                              source_identity='d'*64,destination_identity='e'*64))
        result=project._checkpoint_provenance(dict(checkpoint=original,ticks=12,native_steps=6,interpreter_steps=3))
        self.assertTrue(result['valid'])
        self.assertEqual(result['origin']['interpreter_steps'],3)
        self.assertEqual(result['audio_origin'],original['audio_origin'])
        self.assertEqual(result['continuation'],original['continuation'])
        changed=copy.deepcopy(original);changed['continuation']['receipt_sha256']='invalid'
        self.assertFalse(project._checkpoint_provenance(dict(checkpoint=changed,ticks=12,native_steps=6,interpreter_steps=3))['valid'])

    def test_output_refusal_precedes_any_probe(self):
        with patch.object(continuation,'_probe') as probe:
            with self.assertRaisesRegex(ValueError,'new output directory'):
                continuation.create_continuation(None,None,None,None,None,None,None,None,self.root)
            probe.assert_not_called()

    def test_probe_failure_retains_failed_receipt_without_permit(self):
        output=self.root/'declined'
        def decline(*args,**kwargs):
            output.mkdir()
            kwargs['_reservation']['owned']=True
            raise ValueError('authored probe refusal')
        with patch.object(continuation,'_create_continuation',side_effect=decline):
            with self.assertRaisesRegex(ValueError,'authored probe refusal'):
                continuation.create_continuation(None,None,None,None,None,None,None,None,output)
        report=json.loads((output/'receipt.json').read_bytes())
        self.assertIs(report['migration_authorized'],False)
        self.assertIs(report['qualified'],False)
        self.assertFalse((output/'permit.pcecp').exists())

    def test_receipt_schema_and_authority_are_strictly_typed_before_admission(self):
        fields=('schema','format','migration_authorized','qualified','execution_evidence','binding',
            'source_observations','destination_observations','source_checkpoint','reference_enabled',
            'source_probe','destination_probe','destination_identity','scope')
        valid=dict.fromkeys(fields)
        valid.update(schema=1,format=continuation.FORMAT,migration_authorized=True,qualified=False,
            execution_evidence=False,reference_enabled=False,destination_identity='a'*64,scope='authored')
        for change in (dict(schema=True),dict(qualified=0),dict(execution_evidence=0),
                       dict(reference_enabled=0),dict(extra_authority=True)):
            path=self.root/'receipt.json';path.write_text(json.dumps(valid|change),encoding='utf-8')
            with self.subTest(change=change),patch.object(continuation,'_admit') as admit:
                with self.assertRaises(ValueError):continuation.prepare_continuation_launch(path)
                admit.assert_not_called()

    def test_non_executable_sidecar_change_rejected_before_catalogue(self):
        sdk=project.source_identity(Path(project.__file__).resolve().parent.parent)
        checked=dict(tool_identity=sdk,config=dict(runtime={}),identities={})
        old=dict(binary='old/pce-consumer.exe',output_files={'pce-consumer.exe':'a'*64,'support.dll':'b'*64})
        new=dict(binary='new/pce-consumer.exe',output_files={'pce-consumer.exe':'c'*64,'support.dll':'d'*64})
        with patch.object(project,'_verified_package',side_effect=[(checked,old,None,'e'*64),(checked,new,None,'f'*64)]), \
             patch.object(continuation,'compare_native_extensions') as catalogue:
            with self.assertRaisesRegex(ValueError,'sidecars/DLLs differ'):
                continuation._admit('old','old-build','new','new-build','old-input','new-input')
            catalogue.assert_not_called()

    def test_raw_probe_admission_rejects_duplicate_and_nonfinite_json(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            json.loads('{"id":1,"id":1}',object_pairs_hook=continuation._strict_object)
        with self.assertRaisesRegex(ValueError,'Non-finite'):
            json.loads('{"value":NaN}',parse_constant=continuation._invalid_constant)

    def admission_fixture(self):
        original=dict(path=str(self.root/'seed.pcec'),sha256='a'*64,identity='b'*64,body_sha256='c'*64,bytes=200)
        def probe(side):
            status=dict(id=1,ok=True,host=dict(checkpoint_identity='d'*64))
            return dict(status=status,wire=[dict(request=dict(id=1,cmd='status'),response=copy.deepcopy(status)),
                dict(request=dict(id=2,cmd='quit'),response=dict(id=2,ok=True))],
                wire_sha256='e'*64,wire_file=side+'.wire.jsonl',exit_code=0)
        side=dict(descriptor=str(self.root/'project.toml'),build=str(self.root/'build'),
                  receipt_sha256='f'*64,binding={},package={'pce-consumer.exe':'a'*64})
        receipt=dict(schema=1,format=continuation.FORMAT,migration_authorized=True,qualified=False,
            execution_evidence=False,binding=dict(source=copy.deepcopy(side),destination=copy.deepcopy(side),
                comparison={},lowering=[{},{}],audits=[{},{}]),source_observations=str(self.root/'old.json'),
            destination_observations=str(self.root/'new.json'),source_checkpoint=original,
            reference_enabled=True,source_probe=probe('source'),destination_probe=probe('destination'),
            destination_identity='d'*64,scope='Authored shape/launch fixture, no producer admission')
        return receipt

    def write_admission(self,receipt,*,write_journals=True):
        if write_journals:
            for side in ('source','destination'):
                probe=receipt[side+'_probe'];records=[]
                for pair in probe['wire']:
                    for direction in ('request','response'):
                        value=pair[direction];raw=(json.dumps(value)+'\n').encode()
                        records.append(dict(direction=direction,id=value['id'],bytes=len(raw),
                            sha256=hashlib.sha256(raw).hexdigest(),raw_base64=base64.b64encode(raw).decode('ascii')))
                raw=b''.join((json.dumps(record)+'\n').encode() for record in records)
                (self.root/probe['wire_file']).write_bytes(raw)
                probe['wire_sha256']=hashlib.sha256(raw).hexdigest()
        path=self.root/'receipt.json';raw=json.dumps(receipt).encode();path.write_bytes(raw)
        original=receipt['source_checkpoint']
        permit=('PCE_CHECKPOINT_CONTINUATION 1\nsource_identity '+original['identity']+
            '\ndestination_identity '+receipt['destination_identity']+'\ncheckpoint_sha256 '+original['sha256']+
            '\nreceipt_sha256 '+hashlib.sha256(raw).hexdigest()+'\n').encode()
        (self.root/'permit.pcecp').write_bytes(permit)
        return path

    def test_malformed_nested_receipts_refuse_before_following_paths(self):
        baseline=self.admission_fixture()
        cases=[('binding',None),('binding.source',[]),('binding.destination.descriptor',None),
            ('binding.destination.package',[]),('binding.audits',[{}]),('source_checkpoint',None),
            ('source_checkpoint.path',[]),('source_checkpoint.bytes',True),('source_observations',None),
            ('source_probe',[]),('destination_probe.status',{}),('source_probe.wire',None),
            ('source_probe.wire_sha256','invalid'),('source_probe.exit_code',True)]
        for key,value in cases:
            changed=copy.deepcopy(baseline);target=changed;parts=key.split('.')
            for part in parts[:-1]:target=target[part]
            target[parts[-1]]=value;path=self.root/'receipt.json';path.write_text(json.dumps(changed))
            with self.subTest(field=key),patch.object(continuation,'_admit') as admit:
                with self.assertRaises(ValueError):continuation.prepare_continuation_launch(path)
                admit.assert_not_called()

    def test_growing_permit_reopen_is_bounded_and_never_returns_a_plan(self):
        receipt=self.admission_fixture();path=self.write_admission(receipt);permit=self.root/'permit.pcecp'
        from pcerecomp import declarations
        ordinary=declarations._ordinary;open_original=Path.open;reads=[]
        def grow(source,maximum,*args):
            ordinary(source,maximum,*args)
            if source==permit:permit.write_bytes(b'x'*65537)
        class Guard:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def read(self,count=-1):
                reads.append(count)
                if count!=513:raise AssertionError('Permit reopen must read exactly its bound plus one')
                return self.stream.read(count)
        def guarded_open(source,*args,**kwargs):
            stream=open_original(source,*args,**kwargs)
            return Guard(stream) if source==permit and args and args[0]=='rb' else stream
        with patch.object(continuation,'_admit',return_value=(None,None,receipt['binding'])), \
             patch.object(continuation,'_checkpoint',return_value=receipt['source_checkpoint']), \
             patch.object(declarations,'_ordinary',side_effect=grow),patch.object(Path,'open',guarded_open), \
             patch.object(project,'prepare_launch') as plan:
            with self.assertRaisesRegex(ValueError,'permit changed'):continuation.prepare_continuation_launch(path)
            plan.assert_not_called()
        self.assertEqual(reads,[513])

    def test_supported_capture_keeps_reference_recipe_context_and_new_output_checks(self):
        helper=project_fixtures.ConsumerProjectTests();helper.setUp();self.addCleanup(helper.temp.cleanup)
        directory,binary=helper.build_fixture();checked=project.verify(helper.descriptor,allow_revision_override=True)
        built=json.loads((directory/'build-receipt.json').read_bytes())
        receipt=self.admission_fixture()
        for side in ('source','destination'):
            receipt['binding'][side].update(descriptor=str(helper.descriptor),build=str(directory))
        path=self.write_admission(receipt);capture=self.root/'suffix.jsonl'
        with patch.object(continuation,'_admit',return_value=(None,None,receipt['binding'])), \
             patch.object(continuation,'_checkpoint',return_value=receipt['source_checkpoint']), \
             patch.object(project,'_verified_package',return_value=(checked,built,binary,'f'*64)):
            plain=project.prepare_launch(helper.descriptor,directory,checkpoint_continuation=path)
            captured=project.prepare_launch(helper.descriptor,directory,checkpoint_continuation=path,
                code_capture=capture,capture_limit=1048576,capture_profile='extended')
            argv=captured['command']
            self.assertEqual(argv[argv.index('--code-capture')+1],str(capture.resolve()))
            self.assertEqual(argv[argv.index('--capture-limit')+1],'1048576')
            self.assertEqual(argv[argv.index('--capture-profile')+1],'extended')
            for flag in ('--checkpoint-context','--dev-reference','--checkpoint-load','--checkpoint-continuation-sha'):
                self.assertEqual(argv[argv.index(flag)+1],plain['command'][plain['command'].index(flag)+1])
            for kwargs in (dict(capture_limit=1),dict(capture_profile='extended'),
                           dict(code_capture=capture,capture_limit=65537),dict(memory_write=True),
                           dict(disc_origin=True),dict(bus_trace=self.root/'bus.json'),dict(start_paused=1)):
                with self.subTest(options=kwargs),self.assertRaises(ValueError):
                    project.prepare_launch(helper.descriptor,directory,checkpoint_continuation=path,**kwargs)
            capture.write_bytes(b'owner bytes')
            with self.assertRaises(ValueError):
                project.prepare_launch(helper.descriptor,directory,checkpoint_continuation=path,code_capture=capture)
            self.assertEqual(capture.read_bytes(),b'owner bytes')

    def test_continuation_cli_forwards_only_output_capture_options(self):
        receipt=self.root/'receipt.json';capture=self.root/'new.jsonl'
        with patch.object(continuation,'prepare_continuation_launch',return_value={'executed':False}) as launch, \
             patch('builtins.print'):
            self.assertEqual(continuation.main(['launch-plan',str(receipt),'--code-capture',str(capture),
                '--capture-profile','extended','--capture-limit','262144']),0)
        launch.assert_called_once_with(receipt,dev_port=0,code_capture=capture,
            capture_limit=262144,capture_profile='extended')

    def test_missing_or_tampered_original_probe_journals_refuse_before_package_admission(self):
        for side in ('source','destination'):
            for mutation in ('missing','tampered'):
                receipt=self.admission_fixture();path=self.write_admission(receipt)
                journal=self.root/receipt[side+'_probe']['wire_file']
                if mutation=='missing':journal.unlink()
                else:journal.write_bytes(journal.read_bytes()+b' ')
                with self.subTest(side=side,mutation=mutation),patch.object(continuation,'_admit') as admit:
                    with self.assertRaises(ValueError):continuation.prepare_continuation_launch(path)
                    admit.assert_not_called()

    def test_raw_probe_hash_is_insufficient_if_parsed_evidence_names_different_bytes(self):
        receipt=self.admission_fixture();path=self.write_admission(receipt)
        journal=self.root/'source.wire.jsonl';rows=[json.loads(line) for line in journal.read_bytes().splitlines()]
        value=json.loads(base64.b64decode(rows[1]['raw_base64']));value['host']['checkpoint_identity']='e'*64
        changed=(json.dumps(value)+'\n').encode();rows[1].update(bytes=len(changed),
            sha256=hashlib.sha256(changed).hexdigest(),raw_base64=base64.b64encode(changed).decode())
        raw=b''.join((json.dumps(row)+'\n').encode() for row in rows);journal.write_bytes(raw)
        receipt['source_probe']['wire_sha256']=hashlib.sha256(raw).hexdigest()
        self.write_admission(receipt,write_journals=False)
        with patch.object(continuation,'_admit') as admit:
            with self.assertRaisesRegex(ValueError,'raw probe journal disagrees'):continuation.prepare_continuation_launch(path)
            admit.assert_not_called()

    def test_probe_journal_binding_is_revalidated_after_launch_derivation(self):
        receipt=self.admission_fixture();path=self.write_admission(receipt)
        def changed(*args,**kwargs):
            journal=self.root/'destination.wire.jsonl';journal.write_bytes(journal.read_bytes()+b' ')
            return dict(command=[])
        with patch.object(continuation,'_admit',return_value=(None,None,receipt['binding'])), \
             patch.object(continuation,'_checkpoint',return_value=receipt['source_checkpoint']), \
             patch.object(project,'prepare_launch',side_effect=changed):
            with self.assertRaises(ValueError):continuation.prepare_continuation_launch(path)

    def test_raw_probe_duplicate_inner_fields_refuse_even_with_matching_file_hash(self):
        receipt=self.admission_fixture();path=self.write_admission(receipt)
        journal=self.root/'source.wire.jsonl';rows=[json.loads(line) for line in journal.read_bytes().splitlines()]
        changed=b'{"id":1,"id":1,"cmd":"status"}\n'
        rows[0].update(bytes=len(changed),sha256=hashlib.sha256(changed).hexdigest(),
                       raw_base64=base64.b64encode(changed).decode())
        raw=b''.join((json.dumps(row)+'\n').encode() for row in rows);journal.write_bytes(raw)
        receipt['source_probe']['wire_sha256']=hashlib.sha256(raw).hexdigest()
        self.write_admission(receipt,write_journals=False)
        with self.assertRaisesRegex(ValueError,'Duplicate'):continuation.prepare_continuation_launch(path)

    def test_growing_probe_journal_is_read_only_to_explicit_bound_plus_one(self):
        receipt=self.admission_fixture();path=self.write_admission(receipt);journal=self.root/'source.wire.jsonl'
        from pcerecomp import declarations
        ordinary=declarations._ordinary;open_original=Path.open;reads=[]
        def grow(source,maximum,*args):
            ordinary(source,maximum,*args)
            if source==journal:journal.write_bytes(b'x'*4097)
        class Guard:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def read(self,count=-1):
                reads.append(count)
                if count!=4097:raise AssertionError('Probe journal reopen must retain its explicit byte bound')
                return self.stream.read(count)
        def guarded_open(source,*args,**kwargs):
            stream=open_original(source,*args,**kwargs)
            return Guard(stream) if source==journal and args and args[0]=='rb' else stream
        with patch.object(continuation,'MAX_PROBE_JOURNAL',4096), \
             patch.object(declarations,'_ordinary',side_effect=grow),patch.object(Path,'open',guarded_open), \
             patch.object(continuation,'_admit') as admit:
            with self.assertRaisesRegex(ValueError,'journal changed'):continuation.prepare_continuation_launch(path)
            admit.assert_not_called()
        self.assertEqual(reads,[4097])

class ProducerAuditTests(unittest.TestCase):
    """Writer-shaped metadata with mocked compiler closure, never producer proof."""
    def setUp(self):
        fixture=CheckpointContinuationTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root=fixture.root;self.checked=fixture.prepared()
        self.build=self.root/'audited-build';self.build.mkdir()
        self.bundle=self.root/'bundle';self.bundle.mkdir()
        module=self.checked['files']['module_manifest'].parent.resolve()
        self.contract=dict(schema=1,producer='windows-x64-llvm-mingw-ninja-v1',
            tool=dict(path=str(self.checked['tool_root']),
                source_sha256=self.checked['tool_identity']['source_sha256'],runtime_abi=29),
            module_inputs={},trees=dict(toolchain=dict(path=str(self.bundle),sha256='a'*64,files=2),
                dependencies=[],module=dict(path=str(module),sha256='b'*64,files=1),tool_compile=[]),
            desktop=False,configuration='Release',generator='Ninja',
            options=dict(CMAKE_CXX_COMPILER=str(self.bundle/'bin/clang++.exe'),
                         CMAKE_MAKE_PROGRAM=str(self.bundle/'bin/ninja.exe')),
            target='x86_64-w64-windows-gnu',host=dict(system='authored',machine='AMD64',version='authored'),
            environment_policy='minimal-windows-toolchain-v1')
        self.configuration=dict(targets=[dict(name='pce-consumer',type='EXECUTABLE',
            compile_groups=[dict(defines=['AUTHORED=1'],backtrace=9,sourceIndexes=[1])],link={})])
        self.current=dict(configuration=copy.deepcopy(self.configuration),dependencies={'authored.hpp':'c'*64})
        self.context=dict(contract=copy.deepcopy(self.contract),environment={'PATH':'authored-controlled'})
        self.built=dict(schema=1,kind='pce-consumer-build',binding=project._binding(self.checked),
            desktop=False,commands=[['authored-configure'],['authored-build']])
        options=dict(generator='Ninja',desktop=False,
            cmake_args=['-D'+key+'='+value for key,value in sorted(self.contract['options'].items())],
            toolchain_root=str(self.bundle),dependency_roots=[],allow_revision_override=False)
        info=self.build.stat()
        self.pre=self.sealed(dict(schema=1,kind='pce-recoverable-build-v1',build_dir=str(self.build),
            descriptor=str(self.checked['descriptor']),root_identity=[info.st_dev,info.st_ino],
            options=options,binding=project._binding(self.checked),input_contract=copy.deepcopy(self.contract),
            checkpoint_policy=dict(kind='pce-object-checkpoint-delta-v1',schema=2,
                maximum_updates=32,maximum_metadata_bytes=64*1024*1024),
            environment=copy.deepcopy(self.context['environment'])))
        self.configured=self.sealed(dict(schema=1,contract_sha256=self.digest(self.pre),
            configured=copy.deepcopy(self.configuration),files={},graph=dict(objects=[],links=[]),
            directories=['build','source']))
        self.evidence=dict(schema=1,resumed=False,attempt=1,contract_sha256=self.digest(self.pre),
            configured_sha256=self.digest(self.configured),input_contract=self.pre,
            configured=self.configured,input_audit=copy.deepcopy(self.current))
        self.built['recovery']=self.evidence
        (self.build/'.pce-recovery').mkdir()
        self.persist()

    @staticmethod
    def canonical(value):
        return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

    @classmethod
    def digest(cls,value):return hashlib.sha256(cls.canonical(value)).hexdigest()

    @classmethod
    def sealed(cls,value):
        value={key:item for key,item in value.items() if key!='sha256'}
        return dict(value,sha256=cls.digest(value))

    def persist(self,*,reseal=False):
        if reseal:
            self.pre=self.sealed(self.pre)
            self.evidence['input_contract']=self.pre
            self.evidence['contract_sha256']=self.digest(self.pre)
            self.configured['contract_sha256']=self.digest(self.pre)
            self.configured=self.sealed(self.configured)
            self.evidence['configured']=self.configured
            self.evidence['configured_sha256']=self.digest(self.configured)
        for name,value in (('contract',self.pre),('configured',self.configured)):
            (self.build/'.pce-recovery'/f'{name}.json').write_bytes(self.canonical(value)+b'\n')
        receipt=self.build/'build-receipt.json'
        receipt.write_bytes(self.canonical(self.built)+b'\n')
        complete=self.sealed(dict(schema=1,attempt=1,status='complete',
            contract_sha256=self.evidence['contract_sha256'],
            receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),commands=self.built['commands']))
        (self.build/'.pce-recovery/attempt-000001-result.json').write_bytes(self.canonical(complete)+b'\n')

    def audit(self):
        with patch.object(continuation.build_inputs,'prepare',return_value=copy.deepcopy(self.context)) as prepare_, \
             patch.object(continuation.build_inputs,'verify_closure',return_value=copy.deepcopy(self.current)) as closure:
            result=continuation._audit(self.checked,self.built,self.build)
        return result,prepare_,closure

    def test_recovery_unwraps_only_genuine_sealed_contract_and_retains_receipt(self):
        original=copy.deepcopy(self.built)
        originals={p:p.read_bytes() for p in (self.build/'.pce-recovery').iterdir()}
        result,prepare_,closure=self.audit()
        self.assertTrue(result['revalidated'])
        self.assertEqual(result['producer'],'windows-x64-llvm-mingw-ninja-v1')
        self.assertEqual(self.built,original)
        self.assertEqual({p:p.read_bytes() for p in originals},originals)
        prepare_.assert_called_once()
        self.assertEqual(prepare_.call_args.kwargs['generator'],'Ninja')
        self.assertEqual(Path(prepare_.call_args.kwargs['toolchain_root']),self.bundle)
        self.assertEqual(list(prepare_.call_args.kwargs['cmake_args']),self.pre['options']['cmake_args'])
        self.assertEqual(prepare_.call_args.kwargs['dependency_roots'],[])
        closure.assert_called_once()

    def test_cache_miss_path_retains_direct_contract_and_current_closure(self):
        del self.built['recovery']
        self.built['cache']=dict(schema=1,hit=False,input_contract=copy.deepcopy(self.contract),
            input_audit=copy.deepcopy(self.current))
        result,prepare_,closure=self.audit()
        self.assertTrue(result['revalidated'])
        prepare_.assert_called_once();closure.assert_called_once()

    def test_recovery_wrapper_and_configuration_checksums_fail_closed(self):
        for which in ('input_contract','configured'):
            with self.subTest(envelope=which):
                envelope=self.evidence[which];original=copy.deepcopy(envelope)
                envelope['sha256']='0'*64;self.persist()
                with patch.object(continuation.build_inputs,'prepare') as prepare_:
                    with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
                    prepare_.assert_not_called()
                envelope.clear();envelope.update(original);self.persist()

    def test_recovery_digest_links_and_strict_schema_refuse_before_compiler(self):
        for envelope,key,value in ((self.evidence,'schema',True),
                (self.evidence,'contract_sha256','0'*64),
                (self.evidence,'configured_sha256','0'*64),
                (self.pre,'schema',True),(self.pre,'kind','invented'),
                (self.configured,'schema',True),(self.configured,'contract_sha256','0'*64)):
            original=copy.deepcopy(envelope)
            with self.subTest(field=key,value=value):
                envelope[key]=value;self.persist()
                with patch.object(continuation.build_inputs,'prepare') as prepare_:
                    with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
                    prepare_.assert_not_called()
            envelope.clear();envelope.update(original);self.persist()

    def test_recovery_bound_paths_directory_identity_and_consumer_refuse_when_resealed(self):
        for key,value in (('build_dir',str(self.root/'different-build')),
                ('descriptor',str(self.root/'different.toml')),('root_identity',[0,0]),
                ('binding',dict(descriptor_sha256='0'*64))):
            original=copy.deepcopy(self.pre)
            with self.subTest(field=key):
                self.pre[key]=value;self.persist(reseal=True)
                with patch.object(continuation.build_inputs,'prepare') as prepare_:
                    with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
                    prepare_.assert_not_called()
            self.pre=original;self.persist(reseal=True)

    def test_recovery_saved_options_cannot_override_desktop_revision_or_compiler_contract(self):
        changes=(dict(desktop=True),dict(desktop=0),dict(allow_revision_override=0),
            dict(generator='Unix Makefiles'),dict(cmake_args=['-DUNSUPPORTED=1']))
        for change in changes:
            original=copy.deepcopy(self.pre)
            with self.subTest(change=change):
                self.pre['options'].update(change);self.persist(reseal=True)
                with self.assertRaises(ValueError):self.audit()
            self.pre=original;self.persist(reseal=True)

    def test_recovery_environment_and_current_input_contract_are_rechecked(self):
        for changed in ('environment','toolchain','module','options'):
            original=copy.deepcopy(self.context)
            with self.subTest(changed=changed):
                if changed=='environment':self.context['environment']['PATH']='different'
                elif changed=='options':self.context['contract']['options']['CMAKE_MAKE_PROGRAM']='unbound'
                else:self.context['contract']['trees'][changed]['sha256']='0'*64
                with self.assertRaises(ValueError):self.audit()
            self.context=original

    def test_recovery_current_configuration_and_compiled_dependency_closure_are_rechecked(self):
        for changed in ('dependencies','configuration'):
            original=copy.deepcopy(self.current)
            with self.subTest(changed=changed):
                if changed=='dependencies':self.current['dependencies']['authored.hpp']='0'*64
                else:self.current['configuration']['targets'][0]['compile_groups'][0]['defines']=['UNBOUND=1']
                with self.assertRaises(ValueError):self.audit()
            self.current=original

    def test_recovery_embedded_metadata_must_equal_durable_canonical_metadata(self):
        for name in ('contract','configured'):
            path=self.build/'.pce-recovery'/f'{name}.json';original=path.read_bytes()
            for raw in (b'{}\n',original.rstrip(),original+b' '):
                with self.subTest(name=name,raw=raw[:10]):
                    path.write_bytes(raw)
                    with self.assertRaises(ValueError):self.audit()
            path.write_bytes(original)

    def test_recovery_and_cache_without_dependency_audit_cannot_authorize(self):
        self.evidence['input_audit']=None;self.persist()
        with self.assertRaises(ValueError):self.audit()
        del self.built['recovery']
        self.built['cache']=dict(input_contract=copy.deepcopy(self.contract),input_audit=None,hit=True)
        with self.assertRaises(ValueError):self.audit()

    def test_ambiguous_cache_and_recovery_evidence_refuses_even_with_false_values(self):
        for cache in (None,False,{},dict(input_contract=self.contract)):
            with self.subTest(cache=cache),patch.object(continuation.build_inputs,'prepare') as prepare_:
                self.built['cache']=cache
                with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
                prepare_.assert_not_called()
        del self.built['cache']

    def test_recovery_resealed_schema_kind_and_checkpoint_policy_refused(self):
        changes=(dict(schema=True),dict(kind='invented'),dict(extra_authority=True),
            dict(checkpoint_policy=dict(kind='invented',schema=2,maximum_updates=32,
                maximum_metadata_bytes=64*1024*1024)))
        for change in changes:
            original=copy.deepcopy(self.pre)
            with self.subTest(change=change):
                self.pre.update(change);self.persist(reseal=True)
                with patch.object(continuation.build_inputs,'prepare') as prepare_:
                    with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
                    prepare_.assert_not_called()
            self.pre=original;self.persist(reseal=True)
        self.configured['schema']=True;self.persist(reseal=True)
        with self.assertRaises(ValueError):self.audit()

    def test_recovery_unused_revision_permission_is_valid_but_actual_override_needs_it(self):
        self.pre['options']['allow_revision_override']=True;self.persist(reseal=True)
        result,_,_=self.audit();self.assertTrue(result['revalidated'])
        self.checked['revision_override']=True
        self.built['binding']=self.pre['binding']=project._binding(self.checked)
        self.pre['options']['allow_revision_override']=False;self.persist(reseal=True)
        with patch.object(continuation.build_inputs,'prepare') as prepare_:
            with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
            prepare_.assert_not_called()

    def test_recovery_completion_must_bind_attempt_contract_receipt_and_commands(self):
        path=self.build/'.pce-recovery/attempt-000001-result.json'
        original=json.loads(path.read_bytes())
        changes=(dict(schema=True),dict(attempt=True),dict(attempt=2),dict(status='failed'),
            dict(contract_sha256='0'*64),dict(receipt_sha256='0'*64),dict(commands=[['unrecorded']]))
        for change in changes:
            with self.subTest(change=change):
                path.write_bytes(self.canonical(self.sealed(original|change))+b'\n')
                with self.assertRaises(ValueError):self.audit()
        path.write_bytes(self.canonical(original)+b'\n')
        self.assertTrue(self.audit()[0]['revalidated'])

    def test_recovery_requires_completion_and_unchanged_published_receipt(self):
        completion=self.build/'.pce-recovery/attempt-000001-result.json'
        original=completion.read_bytes();completion.unlink()
        with self.assertRaises((ValueError,OSError)):self.audit()
        completion.write_bytes(original)
        path=self.build/'build-receipt.json';receipt=path.read_bytes()
        changed=copy.deepcopy(self.built);changed['commands']=[['changed']]
        path.write_bytes(self.canonical(changed)+b'\n')
        with self.assertRaises(ValueError):self.audit()
        path.write_bytes(receipt)
        self.assertTrue(self.audit()[0]['revalidated'])

    def test_recovery_immutable_configuration_bytes_are_revalidated(self):
        path=self.build/'source/CMakeLists.txt';path.parent.mkdir()
        raw=b'# independently authored configure input\n';path.write_bytes(raw)
        self.configured['files']={'source/CMakeLists.txt':dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())}
        self.persist(reseal=True)
        self.assertTrue(self.audit()[0]['revalidated'])
        path.write_bytes(raw.replace(b'input',b'other'))
        with patch.object(continuation.build_inputs,'prepare') as prepare_:
            with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
            prepare_.assert_not_called()

    def test_recovery_metadata_and_raw_configuration_races_fail_before_admission_returns(self):
        path=self.build/'source/CMakeLists.txt';path.parent.mkdir()
        raw=b'# authored immutable configure input\n';path.write_bytes(raw)
        self.configured['files']={'source/CMakeLists.txt':dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())}
        self.persist(reseal=True)
        contract_path=self.build/'.pce-recovery/contract.json';original=contract_path.read_bytes()
        for changed in ('metadata','configure-input','receipt'):
            receipt_path=self.build/'build-receipt.json';receipt=receipt_path.read_bytes()
            def closure(*args):
                if changed=='metadata':contract_path.write_bytes(b'{}\n')
                elif changed=='receipt':receipt_path.write_bytes(b'{}\n')
                else:path.write_bytes(raw+b'# changed\n')
                return copy.deepcopy(self.current)
            with self.subTest(changed=changed), \
                 patch.object(continuation.build_inputs,'prepare',return_value=copy.deepcopy(self.context)), \
                 patch.object(continuation.build_inputs,'verify_closure',side_effect=closure):
                with self.assertRaises(ValueError):continuation._audit(self.checked,self.built,self.build)
            contract_path.write_bytes(original);path.write_bytes(raw);receipt_path.write_bytes(receipt)



if __name__=='__main__':unittest.main()
