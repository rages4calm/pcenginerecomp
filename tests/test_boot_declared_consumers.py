"""Boot declarations through preparation, manifest rebinding and managed copies."""
import copy,json,tomllib,unittest
from unittest.mock import patch
from pcerecomp import prepare,project,incremental as inc
from pcerecomp.emitter import emit_declarations
from tests.test_boot_declarations import document
from tests import test_project, test_declared_consumers


class BootDeclaredConsumerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_project.ConsumerProjectTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.image=self.root/'payload.bin';self.image.write_bytes(bytes.fromhex('A9 42 80 FE'))
        self.roots=self.root/'roots.json';self.value=document(self.image.read_bytes());self.write_roots()
        self.config=tomllib.loads(self.fixture.text)
        self.config['payload']=dict(path=str(self.image),sha256=project.sha256(self.image),physical_load=0x100000,pc=0x4000,mpr=[0,248,128,0,0,0,0,0])
        self.descriptor=self.emit('payload');self.workspace=self.root/'managed'

    def write_roots(self):self.roots.write_text(json.dumps(self.value),encoding='utf-8')
    def emit(self,name):
        directory=self.root/name;emit_declarations(self.roots,self.image,directory,partition_layout='stable')
        self.config['module']=dict(source=dict(path=str(directory/'module.cpp'),sha256=project.sha256(directory/'module.cpp')),
            manifest=dict(path=str(directory/'module.json'),sha256=project.sha256(directory/'module.json')),
            declared_roots=dict(path=str(self.roots),sha256=project.sha256(self.roots)))
        path=self.root/(name+'.toml');path.write_text(prepare._toml(self.config),encoding='utf-8');return path
    def checked(self,path=None):return project.verify(path or self.descriptor,allow_revision_override=True)

    def bios(self,profile='super'):
        data=bytearray(262144);data[0x200:0x204]=bytes.fromhex('A9 42 80 FE');data[0x1FFE:0x2000]=bytes.fromhex('00 E2')
        self.image=self.root/'bios.pce';self.image.write_bytes(data)
        self.value=document(data,'system-card',profile=profile,pc=0xE200,mpr=[0]*8,offsets=(512,513));self.write_roots()
        self.config.pop('payload',None);self.config['boot']=dict(mode='system-card-reset',profile=profile)
        self.config['bios']=dict(path=str(self.image),sha256=project.sha256(self.image))
        self.descriptor=self.emit('bios-'+profile)

    def test_payload_binding_and_command_keep_raw_source_fixed(self):
        c=self.checked();self.assertEqual(c['files']['payload'],self.image)
        self.assertNotIn(self.image,inc._module(c).values())
        cmd=project.command_for(c,self.root/'runner');self.assertEqual(cmd[1],str(self.image));self.assertEqual(cmd[2],'1048576')
        self.assertNotIn('module_observation_history',c['files'])

    def test_system_card_profiles_bind_firmware_without_cartridge(self):
        for profile in ('standard','super'):
            self.bios(profile);c=self.checked();self.assertEqual(c['files']['bios'],self.image)
            self.assertNotIn('cartridge',c['files']);self.assertNotIn(self.image,inc._module(c).values())
            self.assertEqual(project.command_for(c,self.root/'runner')[1:3],['--system-card-reset',profile])

    def test_wrong_payload_location_or_firmware_profile_refuses(self):
        for load in (0x102000,0x1F0000):
            config=copy.deepcopy(self.config);config['payload']['physical_load']=load
            path=self.root/f'wrong-{load}.toml';path.write_text(prepare._toml(config),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'source contract'):self.checked(path)
        self.bios();config=copy.deepcopy(self.config);config['boot']['profile']='standard'
        path=self.root/'wrong-profile.toml';path.write_text(prepare._toml(config),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source contract'):self.checked(path)

    def test_changed_source_even_with_updated_asset_hash_refuses(self):
        self.image.write_bytes(bytes.fromhex('A9 43 80 FE'));self.config['payload']['sha256']=project.sha256(self.image)
        self.descriptor.write_text(prepare._toml(self.config),encoding='utf-8')
        with self.assertRaises(ValueError):self.checked()

    def test_source_format_and_work_counters_cannot_be_forged_in_manifest(self):
        original=json.loads((self.root/'payload/module.json').read_text(encoding='utf-8'))
        for i,changes in enumerate((dict(declared_roots_format='pce-declared-roots-1'),dict(observed_instructions=1),dict(execution_evidence=True))):
            manifest=self.root/'payload/module.json';manifest.write_text(json.dumps(original|changes),encoding='utf-8')
            config=copy.deepcopy(self.config);config['module']['manifest']['sha256']=project.sha256(manifest)
            path=self.root/f'forged-{i}.toml';path.write_text(prepare._toml(config),encoding='utf-8')
            with self.assertRaises(ValueError):self.checked(path)

    def test_prepare_payload_and_firmware_copy_only_numeric_roots(self):
        for kind in ('payload','bios'):
            if kind=='bios':self.bios()
            spec=dict(schema=1,format=prepare.FORMAT,name='authored-boot-'+kind,sdk=dict(revision='0'*40,allow_revision_override=True),
                module=dict(kind='declared',path=str(self.roots)),runtime=self.config['runtime'],limits=self.config['limits'])
            spec.update({k:copy.deepcopy(self.config[k]) for k in ('payload','boot','bios') if k in self.config})
            path=self.root/(kind+'-recipe.toml');path.write_text(prepare._toml(spec),encoding='utf-8')
            original=self.image.read_bytes();output=self.root/(kind+'-prepared')
            with patch.object(prepare,'TOOL_ROOT',self.fixture.tool):receipt=prepare.prepare_project(path,output)
            self.assertFalse(receipt['compiled']);self.assertFalse(receipt['executed'])
            self.assertFalse((output/'observation-history').exists());self.assertEqual(self.image.read_bytes(),original)
            self.assertEqual((output/'declarations/roots.json').read_bytes(),self.roots.read_bytes());self.checked(output/'project.toml')

    def test_managed_annotation_copy_archive_and_tampering_stay_supported(self):
        owned,archive=test_declared_consumers.DeclaredConsumerTests.retained(self);inc._state(self.workspace)
        for path in (owned/'declared-roots.json',archive/'declared-roots.json'):
            raw=path.read_bytes();path.write_bytes(raw+b' ')
            with self.assertRaises(ValueError):inc._state(self.workspace)
            path.write_bytes(raw)
        c=self.checked();conf=inc._config(c,self.workspace,inc._module(c))
        self.assertEqual(conf['payload']['path'],str(self.image));self.assertEqual(conf['module']['declared_roots']['path'],str(self.workspace/'module/declared-roots.json'))
        other=copy.deepcopy(conf);other['payload']['physical_load']+=8192
        self.assertNotEqual(inc._fixed_config(conf),inc._fixed_config(other))


if __name__=='__main__':unittest.main()
