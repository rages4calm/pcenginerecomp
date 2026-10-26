"""Consumer/cache wiring; real compiler/runtime qualification is separate."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import project


class ConsumerCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.descriptor=self.root/'project.toml';self.descriptor.write_text('authored test binding')
        self.checked=dict(descriptor=self.descriptor, descriptor_sha256='a'*64,
            tool_root=self.root/'tool', tool_identity=dict(revision='b'*40,source_sha256='c'*64,source_files=68),
            revision_override=False, config=dict(runtime=dict(video='continuous')),
            identities=dict(module_source='d'*64,bios='e'*64), files={})
        self.context=dict(contract=dict(schema=1,producer='authored-cache-wiring',input='a'*64),
                          environment={},tools={})
        self.verify=patch.object(project,'verify',return_value=self.checked).start()
        self.prepare=patch('pcerecomp.build_inputs.prepare',return_value=self.context).start()
        self.audit=patch('pcerecomp.build_inputs.verify_closure',return_value=dict(checked=True)).start()
        self.configuration=patch('pcerecomp.build_inputs.configuration_identity',return_value=dict(graph='a'*64)).start()
        self.configure=patch.object(project,'_configure_build',return_value=[['authored-configure']]).start()
        self.compile=patch.object(project,'_compile_configured',side_effect=self.compile_fixture).start()
        self.addCleanup(patch.stopall)

    def compile_fixture(self, checked, directory, **options):
        package=directory/'build/bin';package.mkdir(parents=True,exist_ok=True)
        # A binary-format marker for cache transport tests, never executed.
        binary=package/'pce-consumer.exe';binary.write_bytes(b'MZ'+b'authored transport fixture'*20)
        (package/'runtime.dll').write_bytes(b'MZ'+b'authored DLL transport fixture'*20)
        return dict(schema=1,kind='pce-consumer-build',binding=project._binding(checked),
            binary=str(binary),binary_sha256=project.sha256(binary),desktop=options['desktop'],
            output_files={p.name:project.sha256(p)for p in package.iterdir()},
            commands=[['authored-configure'],['authored-compile']],execution_evidence=False)

    def build(self,name,**options):
        return project.build(self.descriptor,self.root/name,generator='Ninja',
            cache_root=self.cache,cache_toolchain_root=self.root/'bundle',**options)

    def test_hit_issues_fresh_build_receipt_without_compiling_or_execution_claim(self):
        cold=self.build('cold');warm=self.build('warm')
        self.assertFalse(cold['cache']['hit']);self.assertTrue(warm['cache']['hit'])
        self.assertEqual(self.compile.call_count,1)
        self.assertEqual(self.audit.call_count,1)
        self.assertEqual(self.configure.call_count,2)
        self.assertEqual(warm['commands'],[['authored-configure']])
        self.assertFalse(warm['execution_evidence'])
        self.assertEqual(cold['output_files'],warm['output_files'])
        self.assertNotEqual(cold['binary'],warm['binary'])
        self.assertEqual(json.loads((self.root/'warm/build-receipt.json').read_text()),warm)
        self.assertEqual(set(Path(warm['binary']).parent.iterdir()),
                         {Path(warm['binary']),Path(warm['binary']).parent/'runtime.dll'})

    def test_warm_receipt_rebinds_current_assets_without_reusing_run_receipt(self):
        cold=self.build('cold')
        self.checked=copy.deepcopy(self.checked)
        self.checked['descriptor_sha256']='f'*64
        self.checked['identities']['bios']='0'*64
        self.verify.return_value=self.checked
        warm=self.build('new-assets')
        self.assertTrue(warm['cache']['hit'])
        self.assertNotEqual(cold['binding'],warm['binding'])
        self.assertEqual(warm['binding'],project._binding(self.checked))
        self.assertFalse((self.root/'new-assets/run-receipt.json').exists())

    def test_changed_compilation_contract_is_a_real_miss(self):
        cold=self.build('cold')
        self.context=copy.deepcopy(self.context);self.context['contract']['input']='b'*64
        self.prepare.return_value=self.context
        changed=self.build('changed')
        self.assertFalse(changed['cache']['hit'])
        self.assertNotEqual(cold['cache']['key'],changed['cache']['key'])
        self.assertEqual(self.compile.call_count,2)

    def test_corruption_stops_without_silent_recompile(self):
        cold=self.build('cold')
        cached=self.cache/cold['cache']['key']/'pce-consumer.exe'
        cached.write_bytes(b'MZ damaged')
        with self.assertRaises(ValueError):self.build('corrupt')
        self.assertEqual(self.compile.call_count,1)
        self.assertFalse((self.root/'corrupt/build-receipt.json').exists())

    def test_fresh_configure_output_changes_key_even_when_tree_contract_is_equal(self):
        cold=self.build('cold')
        self.configuration.return_value=dict(graph='b'*64)
        changed=self.build('changed-configure')
        self.assertFalse(changed['cache']['hit'])
        self.assertNotEqual(cold['cache']['key'],changed['cache']['key'])
        self.assertEqual(self.compile.call_count,2)

    def test_configuration_graph_changed_during_build_refuses_publication(self):
        self.configuration.side_effect=[dict(graph='a'*64),dict(graph='b'*64)]
        with self.assertRaisesRegex(ValueError,'changed'):
            self.build('raced-graph')
        self.assertFalse((self.root/'raced-graph/build-receipt.json').exists())
        self.assertFalse(any(p.is_dir() for p in self.cache.iterdir()))

    def test_changed_source_never_publishes_cache_or_success_receipt(self):
        after=copy.deepcopy(self.checked);after['descriptor_sha256']='f'*64
        self.verify.side_effect=[self.checked,after]
        with self.assertRaisesRegex(ValueError,'changed'):
            self.build('raced')
        self.assertFalse((self.root/'raced/build-receipt.json').exists())
        self.assertFalse(any(p.is_dir() and not p.name.startswith('.') for p in self.cache.iterdir()))

    def test_cache_options_cannot_silently_enable_or_modify_ordinary_builds(self):
        with self.assertRaisesRegex(ValueError,'require --cache-root'):
            project.build(self.descriptor,self.root/'bad',cache_toolchain_root=self.root/'bundle')
        self.assertFalse((self.root/'bad').exists())


if __name__=='__main__':unittest.main()
