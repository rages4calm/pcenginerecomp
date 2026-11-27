"""Authored controller/refusal fixtures; subprocess mocks are not native proof."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import checkpoint_bram as bram


def digest(data):
    return hashlib.sha256(data).hexdigest()


def runtime_receipt(checkpoint_sha='a'*64, image_sha='b'*64):
    return dict(schema=1,format=bram.RUNTIME_FORMAT,diagnostic_only=True,
        executed=False,restored=False,native_steps=0,interpreter_steps=0,
        network_started=False,presentation_started=False,game_save_validated=False,
        checkpoint_identity='c'*64,checkpoint_sha256=checkpoint_sha,
        core_sha256='d'*64,bram_sha256=image_sha,bytes=2048,physical_address=0x1EE000,
        source_state=dict(ticks=99,frame=0,raster_frames=1,native_steps=17,
            interpreter_steps=29,pending_pcm_frames=41,source_wav_frames=0))


class CheckpointBramReceiptTests(unittest.TestCase):
    def test_typed_receipt_accepts_original_counts_without_claiming_new_execution(self):
        value=runtime_receipt();before=copy.deepcopy(value)
        self.assertIs(bram._runtime_receipt(value,'a'*64,'b'*64),value)
        self.assertEqual(value,before)
        self.assertEqual(value['source_state']['interpreter_steps'],29)
        self.assertEqual(value['native_steps'],0)

    def test_unknown_missing_or_malformed_fields_are_refused(self):
        fixtures=[[],None,{},dict(runtime_receipt(),invented=True)]
        for field in runtime_receipt():
            value=runtime_receipt();del value[field];fixtures.append(value)
        value=runtime_receipt();value['source_state']['unknown']=0;fixtures.append(value)
        value=runtime_receipt();del value['source_state']['ticks'];fixtures.append(value)
        for value in fixtures:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):bram._runtime_receipt(value,'a'*64,'b'*64)

    def test_boolean_and_integer_types_cannot_substitute_for_each_other(self):
        for field,invalid in [('schema',True),('diagnostic_only',1),('executed',0),
                ('restored',0),('network_started',0),('presentation_started',0),
                ('game_save_validated',0),('native_steps',False),('interpreter_steps',False),
                ('bytes',True),('physical_address',True)]:
            with self.subTest(field=field):
                value=runtime_receipt();value[field]=invalid
                with self.assertRaises(ValueError):bram._runtime_receipt(value,'a'*64,'b'*64)
        for field in runtime_receipt()['source_state']:
            value=runtime_receipt();value['source_state'][field]=False
            with self.subTest(state=field):
                with self.assertRaises(ValueError):bram._runtime_receipt(value,'a'*64,'b'*64)

    def test_ranges_and_diagnostic_claims_fail_closed(self):
        invalid=dict(schema=2,format='other',diagnostic_only=False,executed=True,
            restored=True,network_started=True,presentation_started=True,
            game_save_validated=True,native_steps=1,interpreter_steps=1,
            bytes=2047,physical_address=0x1EE001)
        for field,item in invalid.items():
            value=runtime_receipt();value[field]=item
            with self.subTest(field=field):
                with self.assertRaises(ValueError):bram._runtime_receipt(value,'a'*64,'b'*64)
        for field in runtime_receipt()['source_state']:
            for item in (-1,1<<64,1.5,'1'):
                value=runtime_receipt();value['source_state'][field]=item
                with self.subTest(field=field,item=item):
                    with self.assertRaises(ValueError):bram._runtime_receipt(value,'a'*64,'b'*64)

    def test_every_digest_is_strict_and_source_output_hashes_are_bound(self):
        for field in ('checkpoint_identity','checkpoint_sha256','core_sha256','bram_sha256'):
            for item in ('A'*64,'x'*64,'a'*63,None,False):
                value=runtime_receipt();value[field]=item
                with self.subTest(field=field,item=item):
                    with self.assertRaises(ValueError):bram._runtime_receipt(value,'a'*64,'b'*64)
        for field in ('checkpoint_sha256','bram_sha256'):
            value=runtime_receipt();value[field]='e'*64
            with self.assertRaises(ValueError):bram._runtime_receipt(value,'a'*64,'b'*64)


class CheckpointBramPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'diagnostic';self.output.mkdir()
        info=self.output.lstat();self.identity=info.st_dev,info.st_ino

    def test_complete_receipt_is_exclusively_published_without_pending_files(self):
        report=dict(passed=True,diagnostic_only=True,nested=dict(values=[0,1,2]))
        bram._publish_receipt(self.output,self.identity,report)
        self.assertEqual(json.loads((self.output/'receipt.json').read_bytes()),report)
        self.assertEqual([p.name for p in self.output.iterdir()],['receipt.json'])

    def test_existing_receipt_is_never_overwritten(self):
        original=b'original owner receipt\n';(self.output/'receipt.json').write_bytes(original)
        with self.assertRaises((OSError,ValueError)):
            bram._publish_receipt(self.output,self.identity,dict(passed=True))
        self.assertEqual((self.output/'receipt.json').read_bytes(),original)
        self.assertEqual([p.name for p in self.output.iterdir()],['receipt.json'])

    def test_invalid_json_is_not_published(self):
        with self.assertRaises(ValueError):
            bram._publish_receipt(self.output,self.identity,dict(value=float('nan')))
        self.assertEqual(list(self.output.iterdir()),[])

    def test_missing_or_replaced_directory_is_not_recreated_or_written(self):
        self.output.rmdir()
        with self.assertRaises(OSError):bram._publish_receipt(self.output,self.identity,dict(passed=True))
        self.assertFalse(self.output.exists())
        replacement=self.root/'replacement';replacement.mkdir()
        foreign=b'foreign receipt';(replacement/'receipt.json').write_bytes(foreign)
        replacement.rename(self.output)
        with self.assertRaises(ValueError):bram._publish_receipt(self.output,self.identity,dict(passed=True))
        self.assertEqual((self.output/'receipt.json').read_bytes(),foreign)
        self.assertEqual([p.name for p in self.output.iterdir()],['receipt.json'])


class CheckpointBramControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ('sdk','consumer','build','bin','inputs'):(self.root/name).mkdir()
        self.descriptor=self.root/'consumer'/'project.toml'
        self.binary=self.root/'bin'/'authored.exe';self.binary.write_bytes(b'not an executable')
        self.checkpoint=self.root/'inputs'/'authored.pcec'
        self.checkpoint.write_bytes(b'authored opaque checkpoint; runtime is mocked')
        self.cp_sha=digest(self.checkpoint.read_bytes());self.original=self.checkpoint.read_bytes()
        self.image=bytes((i*73+(i>>3)+19)&255 for i in range(2048))
        self.output=self.root/'diagnostic'
        self.checked=dict(tool_root=self.root/'sdk',config={},files=dict(module_manifest=self.root/'consumer'/'module.json'))
        self.built=dict(binary_sha256=digest(self.binary.read_bytes()),output_files=[dict(name='authored.exe',sha256=digest(self.binary.read_bytes()))])
        self.package=(self.checked,self.built,self.binary,'e'*64)
        for target,value in (('_source',self.package),('project.command_for',['authored-runner']),
                ('project._binding',dict(context='authored-test-binding'))):
            mock=patch('pcerecomp.checkpoint_bram.'+target,return_value=value)
            setattr(self,target.replace('.','_'),mock.start());self.addCleanup(mock.stop)

    def export(self,**kwargs):
        return bram.export_checkpoint_bram(self.descriptor,self.root/'build',self.checkpoint,
            self.output,expected_checkpoint_sha256=self.cp_sha,**kwargs)

    def child(self,command,**kwargs):
        image=Path(command[command.index('--checkpoint-bram-output')+1]);image.write_bytes(self.image)
        kwargs['stdout'].write(json.dumps(runtime_receipt(self.cp_sha,digest(self.image))).encode())
        self.assertEqual(kwargs['env']['SDL_VIDEODRIVER'],'dummy')
        self.assertEqual(kwargs['env']['SDL_AUDIODRIVER'],'dummy')
        return subprocess.CompletedProcess(command,0)

    def test_success_preserves_checkpoint_and_records_only_offline_evidence(self):
        with patch('pcerecomp.checkpoint_bram.subprocess.run',side_effect=self.child) as child:
            result=self.export(reference_enabled=True)
        self.assertTrue(result['passed']);self.assertFalse(result['execution_evidence'])
        self.assertFalse(result['game_save_validated']);self.assertTrue(result['reference_enabled'])
        self.assertEqual(self.checkpoint.read_bytes(),self.original)
        self.assertEqual((self.output/'bram.bin').read_bytes(),self.image)
        self.assertEqual(json.loads((self.output/'receipt.json').read_bytes()),result)
        self.assertEqual(result['runtime']['source_state']['pending_pcm_frames'],41)
        self.assertEqual(result['runtime']['native_steps'],0)
        self.assertEqual(child.call_count,1)
        self.assertFalse(list(self.output.glob('*.pending')))

    def test_expected_digest_keyword_is_mandatory_and_bad_reference_type_is_refused(self):
        with self.assertRaises(TypeError):
            bram.export_checkpoint_bram(self.descriptor,self.root/'build',self.checkpoint,self.output)
        for item in ('',None,'A'*64):
            with self.subTest(sha=item),self.assertRaises(ValueError):
                bram.export_checkpoint_bram(self.descriptor,self.root/'build',self.checkpoint,self.output,
                    expected_checkpoint_sha256=item)
        for item in (0,1,None,'true'):
            with self.subTest(reference=item),self.assertRaises(ValueError):self.export(reference_enabled=item)
        self.assertFalse(self.output.exists());self._source.assert_not_called()

    def test_existing_output_is_left_unchanged(self):
        self.output.mkdir();(self.output/'keep').write_bytes(b'foreign')
        with self.assertRaises(ValueError):self.export()
        self.assertEqual([p.name for p in self.output.iterdir()],['keep'])
        self.assertEqual((self.output/'keep').read_bytes(),b'foreign')

    def test_changed_checkpoint_before_seal_never_gets_a_passed_receipt(self):
        before=self.checkpoint.stat()
        def child(command,**kwargs):
            done=self.child(command,**kwargs)
            changed=bytearray(self.original);changed[-1]^=1;self.checkpoint.write_bytes(changed)
            os.utime(self.checkpoint,ns=(before.st_atime_ns,before.st_mtime_ns))
            return done
        with patch('pcerecomp.checkpoint_bram.subprocess.run',side_effect=child):
            with self.assertRaises(ValueError):self.export()
        receipt=json.loads((self.output/'receipt.json').read_bytes())
        self.assertFalse(receipt['passed']);self.assertIn('error',receipt)
        self.assertNotEqual(self.checkpoint.read_bytes(),self.original)

    def test_missing_child_output_is_failure_not_qualification(self):
        with patch('pcerecomp.checkpoint_bram.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
            with self.assertRaises((ValueError,OSError)):self.export()
        self.assertFalse(json.loads((self.output/'receipt.json').read_bytes())['passed'])

    def test_nonzero_child_exit_retains_an_explicit_failure_receipt(self):
        with patch('pcerecomp.checkpoint_bram.subprocess.run',return_value=subprocess.CompletedProcess([],2)):
            with self.assertRaises(ValueError):self.export()
        receipt=json.loads((self.output/'receipt.json').read_bytes())
        self.assertFalse(receipt['passed']);self.assertEqual(receipt['exit_code'],2)
        self.assertNotIn('output',receipt)

    def test_runtime_execution_claim_or_server_announcement_prevents_success(self):
        for mode in ('execution','server'):
            self.output=self.root/('diagnostic-'+mode)
            def child(command,**kwargs):
                image=Path(command[command.index('--checkpoint-bram-output')+1]);image.write_bytes(self.image)
                metadata=runtime_receipt(self.cp_sha,digest(self.image))
                if mode=='execution':metadata['native_steps']=1
                else:kwargs['stderr'].write(b'PCE_DEV_PORT=54321\n')
                kwargs['stdout'].write(json.dumps(metadata).encode())
                return subprocess.CompletedProcess(command,0)
            with self.subTest(mode=mode),patch('pcerecomp.checkpoint_bram.subprocess.run',side_effect=child):
                with self.assertRaises(ValueError):self.export()
            receipt=json.loads((self.output/'receipt.json').read_bytes())
            self.assertFalse(receipt['passed']);self.assertNotIn('output',receipt)

    def test_rechecked_changed_package_prevents_success(self):
        changed=copy.deepcopy(self.built);changed['output_files']=[dict(name='authored.exe',sha256='f'*64)]
        self._source.side_effect=[self.package,(self.checked,changed,self.binary,'e'*64)]
        with patch('pcerecomp.checkpoint_bram.subprocess.run',side_effect=self.child):
            with self.assertRaises(ValueError):self.export()
        receipt=json.loads((self.output/'receipt.json').read_bytes())
        self.assertFalse(receipt['passed']);self.assertNotIn('output',receipt)

    def test_child_cannot_make_controller_recreate_a_missing_output_directory(self):
        def child(command,**kwargs):
            kwargs['stdout'].close();kwargs['stderr'].close();shutil.rmtree(self.output)
            return subprocess.CompletedProcess(command,0)
        with patch('pcerecomp.checkpoint_bram.subprocess.run',side_effect=child):
            with self.assertRaises((OSError,ValueError)):self.export()
        self.assertFalse(self.output.exists())

    def test_replaced_output_cannot_receive_our_success_or_failure_receipt(self):
        def child(command,**kwargs):
            kwargs['stdout'].close();kwargs['stderr'].close()
            self.output.rename(self.root/'retired-owned-output')
            self.output.mkdir();(self.output/'foreign').write_bytes(b'keep')
            return subprocess.CompletedProcess(command,0)
        with patch('pcerecomp.checkpoint_bram.subprocess.run',side_effect=child):
            with self.assertRaises(ValueError):self.export()
        self.assertEqual([p.name for p in self.output.iterdir()],['foreign'])
        self.assertEqual((self.output/'foreign').read_bytes(),b'keep')

    def test_protected_package_directory_refused_before_child(self):
        self.output=self.root/'consumer'/'diagnostic'
        with patch('pcerecomp.checkpoint_bram.subprocess.run') as child:
            with self.assertRaises(ValueError):self.export()
        self.assertFalse(self.output.exists());child.assert_not_called()


if __name__=='__main__':unittest.main()
