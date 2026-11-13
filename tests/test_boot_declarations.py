"""Authored boot sources: exact mappings, no invented observations or RAM bytes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import boot_sources as b, declarations as d, discovery
from pcerecomp.emitter import emit_declarations
from pcerecomp.history import compose_history
from tests.test_capture import capture, observation


def document(data,kind='payload',*,load=0x100000,profile='super',pc=0x4000,mpr=None,offsets=(0,1)):
    image=dict(kind=kind,sha256=hashlib.sha256(data).hexdigest())
    image.update(physical_load=load) if kind=='payload' else image.update(profile=profile)
    return dict(format=b.FORMAT,schema=1,execution_evidence=False,kind='declared',image=image,
        roots=[dict(pc=pc,mpr=mpr or [0,248,128,0,0,0,0,0],selector=0,source_offsets=list(offsets))])


class BootDeclarationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.image=self.root/'source.bin';self.roots=self.root/'roots.json'
        self.data=bytes.fromhex('A9 42 80 FE');self.write(document(self.data))

    def write(self,value,data=None):
        self.value=value;self.image.write_bytes(self.data if data is None else data)
        self.roots.write_text(json.dumps(value),encoding='utf-8');return self.load

    def load(self):return d.load_compilation(self.roots,self.image)

    def test_tiny_payload_has_exact_source_membership_and_no_hits(self):
        c=self.load();self.assertEqual(c.declarations.format,b.FORMAT)
        self.assertEqual(c.provenance['declared_roots_format'],b.FORMAT)
        self.assertEqual(c.declarations.source_metadata,dict(kind='payload',physical_load=0x100000,image_sha256=hashlib.sha256(self.data).hexdigest(),file_bytes=4))
        ins=c.instructions[0];self.assertEqual(ins['physical'],(0x100000,0x100001));self.assertEqual(ins['data'],(0xA9,0x42))
        self.assertNotIn('native_hits',ins);self.assertNotIn('interpreted_hits',ins);self.assertFalse(c.observed_keys)
        self.assertEqual(c.counts()['declared_only'],1);c.revalidate()

    def test_work_ram_alias_keeps_mapped_identity_and_same_source_offsets(self):
        self.value['image']['physical_load']=0x1F0000
        for bank in range(248,252):
            self.value['roots'][0].update(pc=0x4000,mpr=[0,248,bank,0,0,0,0,0]);self.write(self.value)
            self.assertEqual(self.load().instructions[0]['physical'],(bank*8192,bank*8192+1))

    def test_each_fetch_byte_uses_current_logical_page_including_wrap(self):
        data=bytearray(16384);data[8191]=0xA9;data[8192]=0x42
        mpr=[0,248,128,129,0,0,0,0]
        self.write(document(data,pc=0x5FFF,mpr=mpr,offsets=(8191,8192)),data)
        self.assertEqual(self.load().instructions[0]['physical'],(0x101FFF,0x102000))
        # System Card full-word PC wrap fetches bank0 after bank1.
        data=bytearray(262144);data[16383]=0xA9;data[0]=0x42
        self.write(document(data,'system-card',pc=65535,mpr=[0,248,0,0,0,0,0,1],offsets=(16383,0)),data)
        self.assertEqual(self.load().instructions[0]['physical'],(16383,0))

    def test_system_card_rom_mirrors_and_super_ram_aperture(self):
        data=bytes.fromhex('A9 42')+bytes(262142)
        for profile,bank in (('standard',0),('super',32),('super',64),('standard',96)):
            self.write(document(data,'system-card',profile=profile,mpr=[0,248,bank,0,0,0,0,0]),data)
            self.assertEqual(self.load().instructions[0]['physical'][0],bank*8192)
        for bank in (0x68,0x7F,0x80,0xF8,0xFF):
            value=document(data,'system-card',mpr=[0,248,bank,0,0,0,0,0]);self.write(value,data)
            with self.assertRaises(ValueError):self.load()
        data=bytearray(data);data[0x10000:0x10002]=bytes.fromhex('A9 42')
        self.write(document(data,'system-card',profile='standard',mpr=[0,248,0x68,0,0,0,0,0],offsets=(0x10000,0x10001)),data)
        self.load()

    def test_unloaded_fetch_and_truncated_operand_refuse(self):
        for pc,offsets in ((0x4004,(0,)),(0x4003,(3,)),(0x3FFF,(0,1))):
            self.write(document(self.data,pc=pc,offsets=offsets))
            with self.assertRaises(ValueError):self.load()
        data=b'\xA9';self.write(document(data),data)
        with self.assertRaises(ValueError):self.load()

    def test_standard_ram_load_limits_and_source_roles_are_strict(self):
        for load in (0,0xD0000,0x10FFFF,0x1F1FFF,0x1F2000,0x1FE000,True,-1):
            self.write(document(self.data,load=load))
            with self.assertRaises(ValueError):self.load()
        for kind in ('system-card','disc','memory',True):
            value=document(self.data);value['image']['kind']=kind;self.write(value)
            with self.assertRaises(ValueError):self.load()
        data=bytes(262144);self.write(document(data,'system-card',profile='arcade'),data)
        with self.assertRaises(ValueError):self.load()

    def test_wrong_digest_offsets_lengths_selectors_and_duplicates_refuse(self):
        for mutate in (lambda v:v['image'].update(sha256='0'*64),lambda v:v['roots'][0].update(source_offsets=[1,2]),
                lambda v:v['roots'][0].update(source_offsets=[0]),lambda v:v['roots'][0].update(source_offsets=[False,1]),
                lambda v:v['roots'][0].update(selector=1),lambda v:v['roots'][0].update(selector=False),
                lambda v:v['roots'].append(copy.deepcopy(v['roots'][0]))):
            value=document(self.data);mutate(value);self.write(value)
            with self.assertRaises(ValueError):self.load()

    def test_exact_fields_reject_fabricated_work_and_role_conversions(self):
        for group,key in (('root','native_hits'),('root','rom_offsets'),('image','encoding'),('image','profile'),('top','checkpoint_origin')):
            value=document(self.data);obj=value['roots'][0] if group=='root' else value['image'] if group=='image' else value
            obj[key]=1;self.write(value)
            with self.assertRaises(ValueError):self.load()
        for key,val in (('schema',True),('schema',2),('execution_evidence',True),('kind','observed')):
            value=document(self.data);value[key]=val;self.write(value)
            with self.assertRaises(ValueError):self.load()

    def test_bound_source_and_numeric_annotation_tampering_refuse(self):
        c=self.load();self.image.write_bytes(bytes.fromhex('A9 43 80 FE'))
        with self.assertRaises(ValueError):c.revalidate()
        self.write(document(self.data));c=self.load();self.roots.write_bytes(self.roots.read_bytes()+b' ')
        with self.assertRaises(ValueError):c.revalidate()

    def test_file_size_race_between_metadata_and_snapshot_refuses(self):
        from pcerecomp.snapshots import SnapshotStore
        larger=self.data+b'\xEA';self.value['image']['sha256']=hashlib.sha256(larger).hexdigest();self.write(self.value)
        original=SnapshotStore.bind
        def bind(store,path,**options):
            if path==self.image:self.image.write_bytes(larger)
            return original(store,path,**options)
        with patch.object(SnapshotStore,'bind',bind),self.assertRaisesRegex(ValueError,'size changed'):self.load()

    def test_dynamic_operations_and_mixed_history_keep_separate_provenance(self):
        original=capture([observation(0x4000,(0xA9,0x42),mpr=[0,248,128,0,0,0,0,0],interpreted=7)])
        path=self.root/'observed.json';path.write_text(json.dumps(original),encoding='utf-8')
        history=compose_history([path],self.root/'history');c=d.load_compilation(self.roots,self.image,observation_history=history.index_path)
        self.assertEqual((c.counts()['declared_observed_overlap'],c.accounting['historical_totals']['interpreted_hits']),(1,7))
        output=self.root/'module';manifest=emit_declarations(self.roots,self.image,output,observation_history=history.index_path)
        self.assertEqual(manifest['declared_roots_format'],b.FORMAT);self.assertFalse(manifest['execution_evidence'])
        self.assertIn('s.a=66', (output/'module.cpp').read_text(encoding='utf-8'))
        self.assertNotIn('interpret_one', (output/'module.cpp').read_text(encoding='utf-8'))

    def test_static_rom_discovery_refuses_boot_roots_before_output(self):
        output=self.root/'discovery'
        with self.assertRaisesRegex(ValueError,'HuCard ROM'):
            discovery.discover_roots(self.roots,self.image,output,rom_ranges=[(0,4)])
        self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
