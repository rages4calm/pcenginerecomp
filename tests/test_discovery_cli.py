"""Authored CLI checks for bounded static candidates and derivation admission."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pcerecomp.cli import main


class DiscoveryCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.image = self.directory / 'authored.pce'
        data = bytearray([0xEA] * 8192)
        data[:3] = bytes.fromhex('EA 80 FD')  # NOP; BRA back to the NOP.
        self.image.write_bytes(data)
        self.seeds = self.directory / 'seeds.json'
        self.seeds.write_text(json.dumps(dict(format='pce-declared-roots-1', schema=1,
            kind='declared', execution_evidence=False,
            image=dict(sha256=hashlib.sha256(data).hexdigest(), profile='base', header='none', encoding='linear'),
            roots=[dict(pc=0xE000, mpr=[0]*8, selector=0, rom_offsets=[0])])), encoding='utf-8')
        self.originals = {p: p.read_bytes() for p in (self.image, self.seeds)}
        self.output = self.directory / 'discovery'

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(map(str, arguments)))
        return code, stdout.getvalue(), stderr.getvalue()

    def discover(self, *extra):
        return self.invoke('discover-roots', self.seeds, '--image', self.image,
            '--rom-range', '0x0:3', '--out', self.output, *extra)

    def assert_originals(self):
        self.assertEqual({p: p.read_bytes() for p in self.originals}, self.originals)

    def test_actual_discovery_and_recomputed_closure_keep_execution_separate(self):
        code, stdout, stderr = self.discover()
        self.assertEqual(code, 0, stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary['declaration_entries'], 2)
        self.assertEqual(summary['source_identities'], 2)
        self.assertTrue(summary['derivation_verified'])
        for field in ('execution_evidence', 'emitted', 'compiled', 'executed'):
            self.assertIs(summary[field], False)
        self.assertEqual({p.name for p in self.output.iterdir()}, {'seed-roots.json', 'roots.json', 'discovery.json'})
        self.assertEqual((self.output/'seed-roots.json').read_bytes(), self.originals[self.seeds])
        code, verified, stderr = self.invoke('verify-discovery', self.output, '--image', self.image)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(verified), summary)
        self.assertNotIn(str(self.directory), stdout)
        self.assert_originals()

    def test_ranges_are_mandatory_and_invalid_limits_do_not_create_output(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['discover-roots', str(self.seeds), '--image', str(self.image), '--out', str(self.output)])
        self.assertEqual(error.exception.code, 2)
        for option in ('--limit', '--context-limit'):
            code, stdout, stderr = self.discover(option, '0')
            self.assertEqual(code, 2)
            self.assertEqual(stdout, '')
            self.assertTrue(stderr)
            self.assertFalse(self.output.exists())
        self.assert_originals()

    def test_expansion_stops_at_allowed_source_boundary(self):
        code, stdout, stderr = self.invoke('discover-roots', self.seeds, '--image', self.image,
            '--rom-range', '0:1', '--out', self.output)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)['source_identities'], 1)
        report = json.loads((self.output/'discovery.json').read_text())
        self.assertTrue(report['unresolved'])
        self.assert_originals()

    def test_changed_expanded_roots_refuse_verification_without_rewriting_graph(self):
        code, _, stderr = self.discover()
        self.assertEqual(code, 0, stderr)
        path = self.output/'roots.json'
        document = json.loads(path.read_text())
        document['roots'].pop()
        path.write_text(json.dumps(document), encoding='utf-8')
        changed = {p.name: p.read_bytes() for p in self.output.iterdir()}
        code, stdout, stderr = self.invoke('verify-discovery', self.output/'discovery.json', '--image', self.image)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, '')
        self.assertTrue(stderr)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, changed)
        self.assert_originals()

    def test_subprocess_cli_exercises_packaged_entry_point(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-m', 'pcerecomp', 'discover-roots', str(self.seeds),
            '--image', str(self.image), '--rom-range', '0:3', '--out', str(self.output)],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['source_identities'], 2)
        self.assert_originals()
