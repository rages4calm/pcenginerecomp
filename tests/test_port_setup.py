"""Authored player-media profiles, immutable kits and genuine feedback admission."""
import copy,hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from pcerecomp import project,prepare
from pcerecomp.port_setup import profile,export_kit,verify_kit,setup_port
from pcerecomp.feedback import prepare_feedback
from pcerecomp.capture import load_capture
from tests.test_capture import capture,observation,MPR
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('setup_fixture_tests',ROOT/'examples/loader-sweep/fixture.py');f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
class PortSetupTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def spec(self):
        path=self.root/'profile.json';path.write_text(json.dumps(f.setup_profile()),encoding='utf-8');return path
    def test_original_numeric_profile_contains_no_code_or_media(self):
        value=profile(f.setup_profile());self.assertEqual(set(value['assets']),{'bios','disc'});self.assertNotIn('data',value['bootstrap']['roots'][0]);self.assertEqual(value['bootstrap']['roots'][0]['source_offsets'],[512])
    def test_private_paths_code_rows_and_owner_save_slots_refuse(self):
        variants=[];doc=f.setup_profile();doc['assets']['bram']=['a'*64];variants.append(doc)
        doc=f.setup_profile();doc['recipe']['bios']['path']='private/firmware.pce';variants.append(doc)
        doc=f.setup_profile();doc['bootstrap']['roots'][0]['data']=[0xEA];variants.append(doc)
        doc=f.setup_profile();doc['bootstrap']['image']['data']='private';variants.append(doc)
        for doc in variants:
            with self.assertRaises(ValueError):profile(doc)
    def test_sdk_export_verifies_without_git_and_contains_no_player_inputs(self):
        out=self.root/'kit';result=export_kit(self.spec(),out);self.assertTrue(result['passed']);self.assertFalse(result['toolchain_bundled'])
        self.assertEqual(project.source_identity(out/'sdk'),project.source_identity(ROOT));self.assertFalse((out/'sdk/.git').exists());self.assertFalse(any(p.suffix in ('.chd','.iso','.bin','.pce','.jsonl') for p in out.rglob('*')))
        self.assertEqual(verify_kit(out)['files'],result['files'])
    def test_changed_sdk_and_extra_files_refuse(self):
        out=self.root/'kit';export_kit(self.spec(),out);p=out/'sdk/runtime/include/pce/runtime.hpp';old=p.read_bytes();p.write_bytes(old+b'\n')
        with self.assertRaises(ValueError):verify_kit(out)
        with self.assertRaises(ValueError):project.source_identity(out/'sdk')
        p.write_bytes(old);extra=out/'extra';extra.write_bytes(b'!')
        with self.assertRaises(ValueError):verify_kit(out)
    def test_exported_pin_works_without_a_git_executable(self):
        out=self.root/'kit';result=export_kit(self.spec(),out)
        with patch.object(project.subprocess,'run',side_effect=FileNotFoundError('Git intentionally absent')):
            self.assertEqual(project.source_identity(out/'sdk'),result['tool'])
    def test_typed_size_metadata_does_not_accept_float_equivalence(self):
        out=self.root/'kit';export_kit(self.spec(),out);p=out/'KIT.json';doc=json.loads(p.read_text(encoding='utf-8'));key=next(iter(doc['files']));doc['files'][key]['size_bytes']=float(doc['files'][key]['size_bytes']);p.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaises(ValueError):verify_kit(out)
    def test_launcher_does_not_mutate_its_source_kit(self):
        out=self.root/'kit';export_kit(self.spec(),out)
        run=subprocess.run([sys.executable,str(out/'setup_port.py'),'--out',str(self.root/'new-port'),'--asset','bios=missing','--asset','disc=missing'],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,2,run.stdout+run.stderr);self.assertFalse((self.root/'new-port').exists());self.assertTrue(verify_kit(out)['passed'])
    def test_unrecognized_media_refuses_before_outputs(self):
        bad=self.root/'bad.pce';bad.write_bytes(b'unknown');out=self.root/'new-port'
        with self.assertRaises(ValueError):setup_port(self.spec(),dict(bios=bad,disc=bad),out,self.root/'missing-compiler')
        self.assertFalse(out.exists())
    def test_existing_destinations_and_unlicensed_toolchain_export_refuse(self):
        spec=self.spec();out=self.root/'kit';out.mkdir()
        with self.assertRaises(ValueError):export_kit(spec,out)
        tool=self.root/'toolchain';tool.mkdir();(tool/'compiler').write_bytes(b'fixture')
        with self.assertRaises(ValueError):export_kit(spec,self.root/'other-kit',toolchain_root=tool)
    def test_supplied_toolchain_and_notices_are_bound_without_execution(self):
        tool=self.root/'toolchain';(tool/'bin').mkdir(parents=True)
        for name in ('clang++','cmake','ninja'):(tool/'bin'/(name+('.exe' if os.name=='nt' else ''))).write_bytes(b'authored non-executable toolchain fixture')
        (tool/'LICENSE.txt').write_text('Original test data, not a compiler',encoding='utf-8')
        (tool/'empty-marker').write_bytes(b'')
        out=self.root/'kit'
        with patch('pcerecomp.port_setup.shutil.copymode',wraps=__import__('shutil').copymode) as modes:
            result=export_kit(self.spec(),out,toolchain_root=tool)
        self.assertEqual(modes.call_count,5)
        self.assertEqual((out/'toolchain/empty-marker').read_bytes(),b'')
        self.assertTrue(result['toolchain_bundled']);self.assertEqual((out/'toolchain/LICENSE.txt').read_bytes(),(tool/'LICENSE.txt').read_bytes())
    def test_feedback_preserves_original_bytes_and_real_capture_provenance(self):
        payload=self.root/'payload.bin';payload.write_bytes(bytes.fromhex('A9 01 80 FE'));paths=[]
        for i,value in enumerate((1,2)):
            path=self.root/f'capture-{i}.json';path.write_text(json.dumps(capture([observation(raw=(0xA9,value))])),encoding='utf-8');paths.append(path)
        recipe=dict(schema=1,format=prepare.FORMAT,name='feedback-fixture',module=dict(kind='capture',path=str(paths[0])),payload=dict(path=str(payload),physical_load=0x100000,pc=0x4000,mpr=MPR),
            runtime=dict(tier='native',video='continuous',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),limits=dict(steps=100,ticks=10000,wall_seconds=5))
        path=self.root/'recipe.toml';path.write_text(prepare._toml(recipe),encoding='utf-8');originals=[p.read_bytes() for p in paths];out=self.root/'feedback'
        # The output is a sibling of capture inputs; input ownership protects
        # their files, not unrelated directories in a consumer workspace.
        result=prepare_feedback(path,[paths[1]],out);self.assertFalse(result['compiled']);self.assertFalse(result['executed']);self.assertEqual([p.read_bytes() for p in paths],originals)
        checked=project.verify(out/'consumer/project.toml');self.assertTrue(checked['files']);self.assertTrue((out/'history/history.json').exists())
