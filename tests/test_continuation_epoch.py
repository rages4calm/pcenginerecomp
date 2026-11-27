"""Authored continuation final-seal refusal; no binaries or probes execute."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pcerecomp import checkpoint_continuation as continuation
from pcerecomp.verification_epoch import VerifiedInputEpoch, current_epoch
from tests import test_project


class ContinuationEpochTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_project.ConsumerProjectTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def alter_payload(self):
        path = self.root/'program.bin'
        stamp = path.stat()
        path.write_bytes(b'\x00'+path.read_bytes()[1:])
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    def test_final_seal_failure_revokes_permit_and_preserves_unissued_receipt(self):
        output = self.root/'admission'
        original = dict(identity='a'*64, sha256='b'*64)
        binding = dict(authored_fixture=True)
        source = dict(host=dict(checkpoint=dict(resumed=True, origin=dict(sha256='b'*64),
            window=dict(ticks=0,native_steps=0,interpreter_steps=0)), checkpoint_identity='a'*64))
        destination = dict(host=dict(native_steps=0,interpreter_steps=0,checkpoint_identity='c'*64))
        issued = []
        revalidate = VerifiedInputEpoch.revalidate
        def seal(epoch):
            receipt = output/'receipt.json'
            if (output/'permit.pcecp').exists() and receipt.exists() and not issued:
                issued.append(receipt.read_bytes())
                self.alter_payload()
            return revalidate(epoch)
        def admit(*args):
            self.fixture.verify()
            return None, None, binding
        with patch.object(continuation,'_checkpoint',return_value=original), \
             patch.object(continuation,'_admit',side_effect=admit), \
             patch.object(continuation.project,'prepare_launch',return_value=dict(command=['authored-no-execution'])), \
             patch.object(continuation,'_probe',side_effect=[dict(status=source),dict(status=destination)]) as probes, \
             patch.object(VerifiedInputEpoch,'revalidate',new=seal):
            with self.assertRaises(ValueError):
                continuation.create_continuation(self.fixture.descriptor,self.root/'source-build',
                    self.fixture.descriptor,self.root/'destination-build',self.root/'source-observations',
                    self.root/'destination-observations',self.root,'source.pcec',output)
        self.assertEqual(probes.call_count,2)
        self.assertEqual(len(issued),1)
        self.assertFalse((output/'permit.pcecp').exists())
        self.assertEqual((output/'unissued-receipt.json').read_bytes(),issued[0])
        unissued=json.loads(issued[0]);self.assertIs(unissued['migration_authorized'],True)
        failure=json.loads((output/'receipt.json').read_bytes())
        self.assertIs(failure['migration_authorized'],False)
        self.assertIs(failure['qualified'],False)
        self.assertIs(failure['execution_evidence'],False)
        self.assertIsNone(current_epoch())

    def test_launch_final_seal_failure_never_returns_argv_or_modifies_receipt(self):
        receipt=self.root/'receipt.json';receipt.write_bytes(b'authored retained receipt\n')
        def prepared(*args,**kwargs):
            self.fixture.verify()
            self.alter_payload()
            return dict(command=['authored-must-not-be-returned'])
        with patch.object(continuation,'_prepare_continuation_launch',side_effect=prepared):
            with self.assertRaises(ValueError):
                continuation.prepare_continuation_launch(receipt)
        self.assertEqual(receipt.read_bytes(),b'authored retained receipt\n')
        self.assertIsNone(current_epoch())

    def test_racing_existing_output_is_not_this_operations_property(self):
        output=self.root/'someone-else'
        def other_owner(*args,**kwargs):
            output.mkdir()
            (output/'permit.pcecp').write_bytes(b'other operation permit\n')
            (output/'receipt.json').write_bytes(b'other operation receipt\n')
            raise ValueError('requires a new output directory')
        with patch.object(continuation,'_create_continuation',side_effect=other_owner):
            with self.assertRaises(ValueError):
                continuation.create_continuation(None,None,None,None,None,None,None,None,output)
        self.assertEqual((output/'permit.pcecp').read_bytes(),b'other operation permit\n')
        self.assertEqual((output/'receipt.json').read_bytes(),b'other operation receipt\n')
        self.assertFalse((output/'unissued-receipt.json').exists())

    def test_final_seal_keyboard_interrupt_retires_only_owned_artifacts(self):
        output=self.root/'interrupted';issued=b'{"authored_unissued_fixture":true}\n'
        def reserve(*args,**kwargs):
            output.mkdir();kwargs['_reservation']['owned']=True
            (output/'permit.pcecp').write_bytes(b'authored unissued permit\n')
            (output/'receipt.json').write_bytes(issued)
            return dict(authored_fixture=True)
        with patch.object(continuation,'_create_continuation',side_effect=reserve), \
             patch.object(VerifiedInputEpoch,'revalidate',side_effect=KeyboardInterrupt('authored interrupt')):
            with self.assertRaises(KeyboardInterrupt):
                continuation.create_continuation(None,None,None,None,None,None,None,None,output)
        self.assertFalse((output/'permit.pcecp').exists())
        self.assertEqual((output/'unissued-receipt.json').read_bytes(),issued)
        failure=json.loads((output/'receipt.json').read_bytes())
        self.assertIs(failure['migration_authorized'],False)
        self.assertEqual(failure['error']['type'],'KeyboardInterrupt')
        self.assertIsNone(current_epoch())


if __name__ == '__main__':
    unittest.main()
