"""Authored end-to-end CLI admission and exclusive output preservation."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from pcerecomp.cli import main
from pcerecomp.observations import load_observation_profile


class ObservationCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = []
        for abi, pc, value in ((18, 0x4000, 42), (26, 0x4002, 43)):
            path = self.root / f'original-{abi}.json'
            item = dict(pc=pc, mpr=[255, 248, 128, 129, 130, 131, 132, 0],
                        physical=[0x100000 + pc - 0x4000, 0x100001 + pc - 0x4000],
                        data=[0xa9, value], native_hits=0, interpreted_hits=1)
            capture = dict(schema=1, runtime_abi=abi, capacity=2, complete=True,
                           dropped_instructions=0, unreadable_instructions=0,
                           retired_instructions=1, observations=[item])
            path.write_text(json.dumps(capture), encoding='utf-8')
            self.inputs.append(path)
        self.originals = [p.read_bytes() for p in self.inputs]

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(map(str, arguments)))
        self.assertEqual([p.read_bytes() for p in self.inputs], self.originals)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_compose_emit_and_deterministic_input_order(self):
        one, two = self.root/'one.json', self.root/'two.json'
        code, output, error = self.invoke('compose-observations', *self.inputs, '--out', one)
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertEqual(report['identities'], 2)
        self.assertEqual(report['inputs'], 2)
        self.assertFalse(report['execution_evidence'])
        self.assertEqual(report['sha256'], hashlib.sha256(one.read_bytes()).hexdigest())
        self.assertEqual(self.invoke('compose-observations', *reversed(self.inputs), '--out', two)[0], 0)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        profile, digest = load_observation_profile(one)
        module = self.root/'module'
        code, output, error = self.invoke('emit-profile', one, '--out', module,
                                          '--partition-layout', 'stable', '--native-span')
        self.assertEqual(code, 0, error)
        manifest = json.loads(output)
        self.assertEqual(manifest['native_instructions_emitted'], 2)
        self.assertFalse(manifest['execution_evidence'])
        self.assertNotIn('capture_runtime_abi', manifest)
        self.assertNotIn('capture_checkpoint_origin', manifest)
        self.assertIn(digest, json.dumps(manifest))
        self.assertEqual(len(profile['observations']), 2)

    def test_duplicate_file_is_idempotent(self):
        destination = self.root/'profile.json'
        result = self.invoke('compose-observations', self.inputs[0], self.inputs[0], '--out', destination)
        self.assertEqual(result[0], 0, result[2])
        self.assertEqual(json.loads(result[1])['inputs'], 1)

    def test_existing_input_hardlink_and_symlink_outputs_preserved(self):
        existing = self.root/'existing.json'
        existing.write_bytes(b'owner file')
        hardlink = self.root/'hardlink.json'
        os.link(self.inputs[0], hardlink)
        targets = [existing, self.inputs[0], hardlink]
        symlink = self.root/'link.json'
        try:
            symlink.symlink_to(self.inputs[0])
            targets.append(symlink)
        except OSError:
            pass
        for path in targets:
            before = path.read_bytes()
            code, _, _ = self.invoke('compose-observations', *self.inputs, '--out', path)
            self.assertEqual(code, 2)
            self.assertEqual(path.read_bytes(), before)

    def test_capacity_and_malformed_input_create_no_output(self):
        for capacity in ('0', '1', '65537'):
            output = self.root/f'capacity-{capacity}.json'
            code, _, _ = self.invoke('compose-observations', *self.inputs, '--out', output,
                                     '--capacity', capacity)
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())
        malformed = self.root/'malformed.json'
        malformed.write_text('{"schema":1,"schema":1}', encoding='utf-8')
        output = self.root/'absent-parent'/'profile.json'
        self.assertEqual(self.invoke('compose-observations', self.inputs[0], malformed,
                                     '--out', output)[0], 2)
        self.assertFalse(output.parent.exists())

    def test_dangling_output_symlink_is_not_followed(self):
        target = self.root/'absent-owner-target.json'
        link = self.root/'dangling-output.json'
        try:
            link.symlink_to(target)
        except OSError:
            return  # Windows without symlink privileges still runs all other preservation cases.
        self.assertTrue(link.is_symlink())
        code, _, _ = self.invoke('compose-observations', *self.inputs, '--out', link)
        self.assertEqual(code, 2)
        self.assertFalse(target.exists())
        self.assertTrue(link.is_symlink())

    def test_wrong_commands_and_invalid_emission_preserve_inputs(self):
        profile = self.root/'profile.json'
        self.assertEqual(self.invoke('compose-observations', *self.inputs, '--out', profile)[0], 0)
        for command, source, options in (
                ('emit-profile', self.inputs[0], []),
                ('emit-capture', profile, []),
                ('emit-profile', profile, ['--native-span']),
                ('emit-profile', profile, ['--partition-size', '0']),
                ('emit-profile', profile, ['--exclude-range', '0x1fffff:2'])):
            output = self.root/'refused-module'
            result = self.invoke(command, source, '--out', output, *options)
            self.assertEqual(result[0], 2, result)
            self.assertFalse(output.exists())
        module = self.root/'existing-module'
        module.mkdir()
        (module/'owner').write_bytes(b'untouched')
        self.assertEqual(self.invoke('emit-profile', profile, '--out', module)[0], 2)
        self.assertEqual((module/'owner').read_bytes(), b'untouched')


if __name__ == '__main__':
    unittest.main()
