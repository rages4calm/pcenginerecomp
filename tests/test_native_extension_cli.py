"""CLI admission and create-new output boundaries for module comparisons."""
import contextlib
import io
import json
import unittest

from pcerecomp.cli import main
from tests import test_native_extension as fixtures


class NativeExtensionCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeExtensionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.module([fixtures.row()])
        self.destination = self.fixture.module([fixtures.row(), fixtures.row(0x4001)])
        self.output = self.fixture.root/'comparison.json'
        self.args = ['compare-native-extensions', '--source-manifest', str(self.source[0]),
            '--source-observations', str(self.source[1]), '--destination-manifest', str(self.destination[0]),
            '--destination-observations', str(self.destination[1]), '--out', str(self.output)]

    def invoke(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(self.args)

    def test_actual_admission_and_existing_output_refusal(self):
        self.assertEqual(self.invoke(), 0)
        original = self.output.read_bytes()
        result = json.loads(original)
        self.assertEqual(result['relation'], 'strict-additive')
        self.assertEqual(result['added']['count'], 1)
        self.assertFalse(result['migration_authorized'])
        self.assertEqual(self.invoke(), 2)
        self.assertEqual(self.output.read_bytes(), original)

    def test_invalid_source_never_creates_report(self):
        (self.source[0].parent/'module.cpp').write_text('// tampered', encoding='utf-8')
        self.assertEqual(self.invoke(), 2)
        self.assertFalse(self.output.exists())

    def test_report_cannot_replace_original_input(self):
        original = self.source[1].read_bytes()
        self.args[-1] = str(self.source[1])
        self.assertEqual(self.invoke(), 2)
        self.assertEqual(self.source[1].read_bytes(), original)

    def test_declared_only_module_keeps_unexecuted_provenance(self):
        from examples.widescreen.fixture import emit_fixture
        directory = self.fixture.root/'authored'
        emit_fixture(directory)
        self.args = ['compare-native-extensions', '--out', str(self.output)]
        for side in ('source', 'destination'):
            self.args += ['--'+side+'-manifest', str(directory/'module/module.json'),
                          '--'+side+'-observations', str(directory/'roots.json'),
                          '--'+side+'-image', str(directory/'authored-card.pce')]
        self.assertEqual(self.invoke(), 0)
        result = json.loads(self.output.read_bytes())
        self.assertEqual(result['relation'], 'unchanged')
        self.assertGreater(result['source']['identities']['declared']['count'], 0)
        self.assertEqual(result['source']['identities']['observed']['count'], 0)
        self.assertFalse(result['execution_evidence'])


if __name__ == '__main__':
    unittest.main()
