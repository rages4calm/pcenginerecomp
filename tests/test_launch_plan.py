"""Authored package admission; fixtures are identities, never real executables."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pcerecomp import project
from tests import test_project as helpers


class LaunchPlanTests(unittest.TestCase):
    setUp=helpers.ConsumerProjectTests.setUp
    verify=helpers.ConsumerProjectTests.verify
    replace=helpers.ConsumerProjectTests.replace
    build_fixture=helpers.ConsumerProjectTests.build_fixture

    def plan(self,directory,**options):
        return project.prepare_launch(self.descriptor,directory,allow_revision_override=True,**options)

    def test_plan_binds_actual_package_without_execution_or_output_allocation(self):
        directory,binary=self.build_fixture();original=binary.read_bytes()
        popen=project.subprocess.Popen
        def only_git(argv,*args,**kwargs):
            if Path(argv[0]).stem.lower()!='git':raise AssertionError('must not launch executable/compiler')
            return popen(argv,*args,**kwargs)
        with patch('pcerecomp.project.subprocess.Popen',side_effect=only_git):
            result=self.plan(directory,dev_port=0,start_paused=True,reference_enabled=True,
                code_capture=self.root/'capture.json',capture_limit=64,checkpoint_dir=self.root)
        self.assertEqual(result['kind'],'pce-consumer-launch-plan')
        self.assertIs(result['executed'],False);self.assertIs(result['execution_evidence'],False)
        self.assertNotIn('qualified',result)
        self.assertEqual(result['binary_sha256'],project.sha256(binary))
        self.assertEqual(result['build_receipt']['sha256'],project.sha256(directory/'build-receipt.json'))
        self.assertEqual(result['command'][0],str(binary))
        self.assertEqual(result['command'][result['command'].index('--dev-port')+1],'0')
        self.assertIn('--checkpoint-context',result['command'])
        self.assertIn('--dev-reference',result['command'])
        self.assertFalse((self.root/'capture.json').exists())
        self.assertEqual(binary.read_bytes(),original)

    def test_changed_binary_and_dependency_refuse(self):
        directory,binary=self.build_fixture();raw=binary.read_bytes()
        binary.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'executable changed'):self.plan(directory)
        binary.write_bytes(raw);(binary.parent/'authored.dll').write_bytes(b'changed dependency')
        with self.assertRaisesRegex(ValueError,'dependency identities'):self.plan(directory)

    def test_changed_descriptor_and_source_refuse(self):
        directory,binary=self.build_fixture()
        self.replace('steps = 200','steps = 201')
        with self.assertRaisesRegex(ValueError,'Build receipt'):self.plan(directory)
        self.descriptor.write_text(self.text,encoding='utf-8')
        (self.tool/'pcerecomp/logic.py').write_text('VALUE = 2\n')
        with self.assertRaises(ValueError):self.plan(directory)

    def test_duplicate_and_nonfinite_build_receipts_refuse_for_both_paths(self):
        directory,binary=self.build_fixture();path=directory/'build-receipt.json';raw=path.read_bytes()
        for bad in (b'{"schema":1,'+raw[1:],raw[:-1]+b',"x":1e9999}',b'[]',b'{"schema":true}'):
            path.write_bytes(bad)
            with self.subTest(raw=bad[:25]),self.assertRaises(ValueError):self.plan(directory)
            with self.subTest(run=bad[:25]),self.assertRaises(ValueError):
                project.run(self.descriptor,directory,self.root/'receipt.json',allow_revision_override=True)
            self.assertFalse((self.root/'receipt.json').exists())
        path.write_bytes(raw)

    def test_build_binding_numeric_lookalikes_are_not_exact_types(self):
        directory,binary=self.build_fixture();path=directory/'build-receipt.json'
        original=json.loads(path.read_text())
        changed=json.loads(json.dumps(original))
        changed['binding']['revision_override']=int(changed['binding']['revision_override'])
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'Build receipt'):self.plan(directory)
        changed=json.loads(json.dumps(original))
        changed['binding']['tool']['source_files']=float(changed['binding']['tool']['source_files'])
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'Build receipt'):self.plan(directory)

    def test_changed_receipt_during_command_derivation_refuses(self):
        directory,binary=self.build_fixture();original=project.command_for
        def changed(*args,**kwargs):
            command=original(*args,**kwargs)
            path=directory/'build-receipt.json';path.write_bytes(path.read_bytes()+b' ')
            return command
        with patch.object(project,'command_for',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed during launch'):self.plan(directory)

    def test_changed_package_during_derivation_refuses(self):
        directory,binary=self.build_fixture();original=project.command_for
        def changed(*args,**kwargs):
            command=original(*args,**kwargs);binary.write_bytes(b'changed');return command
        with patch.object(project,'command_for',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'executable changed'):self.plan(directory)

    def test_created_capture_during_derivation_refuses_without_overwriting(self):
        directory,binary=self.build_fixture();original=project.command_for
        capture=self.root/'late.json'
        def changed(*args,**kwargs):
            command=original(*args,**kwargs);capture.write_bytes(b'owner');return command
        with patch.object(project,'command_for',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'Launch output changed'):
                self.plan(directory,code_capture=capture)
        self.assertEqual(capture.read_bytes(),b'owner')

    def test_capture_path_in_argv_uses_the_admitted_absolute_destination(self):
        directory,binary=self.build_fixture()
        result=self.plan(directory,code_capture=self.root/'capture.json')
        self.assertEqual(result['command'][result['command'].index('--code-capture')+1],
                         str((self.root/'capture.json').resolve()))

    def test_existing_missing_parent_and_aliased_destinations_refuse(self):
        directory,binary=self.build_fixture()
        existing=self.root/'capture.json';existing.write_bytes(b'owner')
        for kwargs in ({'code_capture':existing},{'bus_trace':existing},
                {'code_capture':self.root/'missing/capture.json'},
                {'code_capture':self.root/'new.json','bus_trace':self.root/'new.json'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.plan(directory,**kwargs)
        self.assertEqual(existing.read_bytes(),b'owner')
        self.assertFalse((self.root/'missing').exists());self.assertFalse((self.root/'new.json').exists())

    def test_launch_control_boolean_types_cannot_enable_writes_accidentally(self):
        directory,binary=self.build_fixture()
        for field in ('start_paused','memory_write','reference_enabled'):
            for value in (1,0,'off',None):
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                    self.plan(directory,dev_port=0,**{field:value})
        with self.assertRaisesRegex(ValueError,'requires TCP'):self.plan(directory,start_paused=True)

    def test_invalid_cli_returns_failure_without_execution(self):
        directory,binary=self.build_fixture();binary.write_bytes(b'changed')
        with patch('builtins.print'):
            result=project.main(['launch-plan',str(self.descriptor),'--build-dir',str(directory),
                '--allow-revision-override'])
        self.assertEqual(result,2)

    def test_cli_forwards_supported_flags_without_run_receipt(self):
        directory,binary=self.build_fixture()
        with patch('builtins.print') as printed:
            result=project.main(['launch-plan',str(self.descriptor),'--build-dir',str(directory),
                '--allow-revision-override','--dev-port','0','--start-paused','--reference-enabled'])
        self.assertEqual(result,0)
        plan=json.loads(printed.call_args.args[0])
        self.assertFalse(plan['executed']);self.assertIn('--dev-reference',plan['command'])


if __name__=='__main__':unittest.main()
