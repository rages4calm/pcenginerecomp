"""Authored single-epoch resident selections; no execution claims."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import overlay_snapshot as snapshot, resident_sources as resident
from tests.test_overlays import ReportedRam, ORIGIN


def machine(**assets):
    values=dict(bios='a'*64,disc='b'*64,toc='c'*64);values.update(assets)
    return snapshot.machine_for(dict(boot=dict(mode='system-card-reset',profile='standard')),values)


class ResidentSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.number=0

    def capture(self, raw=bytes.fromhex('a94260')+bytes(61), *, source_machine=None):
        self.number+=1
        client=ReportedRam(raw)
        return snapshot.capture_snapshot(client,self.root/f'snapshot-{self.number}',
            machine=machine() if source_machine is None else source_machine,origin=ORIGIN,
            regions=[(0x100000,len(raw))])

    def test_selected_bytes_keep_original_snapshot_provenance_and_full_machine(self):
        captured=self.capture();source=resident.admit(captured.path,[(0x100000,3),(0x100010,4)])
        self.assertEqual(source.machine,machine())
        self.assertEqual(source.ranges,((0x100000,3),(0x100010,4)))
        self.assertTrue(source.contains(0x100002));self.assertFalse(source.contains(0x100003))
        byte,where=source.read_byte(0x100001)
        self.assertEqual(byte,0x42)
        self.assertEqual(where,dict(snapshot_sha256=captured.sha256,region=0,offset=1,segment=0))
        self.assertEqual(source.document['segments'][0]['sha256'],hashlib.sha256(bytes.fromhex('a94260')).hexdigest())
        self.assertIs(source.document['execution_evidence'],False)
        with self.assertRaises(ValueError):source.read_byte(0x100003)
        with self.assertRaises(ValueError):source.read_byte(True)
        detached=source.document;detached['machine']['assets']['bios']='f'*64
        self.assertEqual(source.machine,machine())

    def test_copy_is_closed_portable_and_rederived(self):
        captured=self.capture();source=resident.admit(captured.path,[(0x100000,3)])
        copied=resident.copy_resident(source,self.root/'resident')
        self.assertEqual(copied.sha256,source.sha256)
        self.assertEqual(copied.document,source.document)
        self.assertEqual(set(p.name for p in copied.path.parent.iterdir()),{'resident.json','snapshot'})
        self.assertEqual(copied.snapshot.sha256,captured.sha256)
        second=resident.copy_resident(copied,self.root/'second')
        self.assertEqual(second.document,source.document)
        self.assertTrue(all((copied.path.parent/name).is_file() for name in copied.artifact_bindings))
        second.revalidate()

    def test_segments_cross_only_contiguous_captured_regions(self):
        client=ReportedRam(bytes.fromhex('a9426080feea'))
        captured=snapshot.capture_snapshot(client,self.root/'split',machine=machine(),origin=ORIGIN,
            regions=[(0x100000,3),(0x100003,3)])
        source=resident.admit(captured.path,[(0x100001,4)])
        self.assertEqual(source.document['segments'][0]['pieces'],[
            dict(region=0,offset=1,length=2),dict(region=1,offset=0,length=2)])
        self.assertEqual([source.read_byte(0x100001+i)[0] for i in range(4)],[0x42,0x60,0x80,0xFE])
        self.assertEqual(source.read_byte(0x100003)[1]['region'],1)
        client=ReportedRam(bytes.fromhex('a9426080feea'))
        captured=snapshot.capture_snapshot(client,self.root/'gap',machine=machine(),origin=ORIGIN,
            regions=[(0x100000,2),(0x100003,3)])
        with self.assertRaises(ValueError):resident.admit(captured.path,[(0x100001,4)])

    def test_wram_alias_fetch_retains_canonical_original_byte_location(self):
        client=ReportedRam(bytes.fromhex('a94260')+bytes(29),start=0x1F0000,pc=0x2000)
        captured=snapshot.capture_snapshot(client,self.root/'wram',machine=machine(),origin=ORIGIN,
            regions=[(0x1F0000,32)])
        source=resident.admit(captured.path,[(0x1F0000,3)])
        self.assertTrue(source.contains(0x1F2001));self.assertTrue(source.contains(0x1F6001))
        self.assertEqual(source.read_byte(0x1F2001),source.read_byte(0x1F0001))
        self.assertEqual(source.read_byte(0x1F2001)[0],0x42)

    def test_ranges_are_nonempty_disjoint_canonical_and_captured(self):
        captured=self.capture()
        bad=[[],[(0x100000,0)],[(0x100000,True)],[(0x100000,4),(0x100003,1)],
             [(0x100010,1),(0x100000,1)],[(0x10003F,2)],[(0x1F2000,1)],[(0x0D0000,1)]]
        for ranges in bad:
            with self.subTest(ranges=ranges),self.assertRaises(ValueError):resident.admit(captured.path,ranges)

    def test_only_single_system_card_media_epoch_can_supply_residency(self):
        source_machine=snapshot.machine_for(dict(payload=dict(physical_load=0x100000,pc=0x4000,
            mpr=[255,248,128,129,130,131,132,0])),dict(payload='d'*64,disc='b'*64))
        captured=self.capture(source_machine=source_machine)
        with self.assertRaises(ValueError):resident.admit(captured.path,[(0x100000,3)])
        missing=machine();del missing['assets']['disc']
        captured=self.capture(source_machine=missing)
        with self.assertRaises(ValueError):resident.admit(captured.path,[(0x100000,3)])

    def test_media_and_consumer_machine_are_independently_bound(self):
        source=resident.admit(self.capture().path,[(0x100000,3)])
        source.authenticate_cd_media(dict(image_sha256='b'*64,toc_sha256='c'*64))
        for media in (dict(image_sha256='d'*64,toc_sha256='c'*64),dict(image_sha256='b'*64,toc_sha256='d'*64),None):
            with self.subTest(media=media),self.assertRaises(ValueError):source.authenticate_cd_media(media)
        source.compatible_machine(machine())
        for target in (machine(bios='e'*64),machine(disc='e'*64),machine(toc='e'*64)):
            with self.subTest(target=target),self.assertRaises(ValueError):source.compatible_machine(target)
        altered=machine();altered['boot']['profile']='super'
        with self.assertRaises(ValueError):source.compatible_machine(altered)

    def test_load_overlap_is_rejected_even_if_bytes_might_match(self):
        source=resident.admit(self.capture().path,[(0x100000,3),(0x100010,4)])
        source.reject_overlap([(0x100003,13),(0x100014,1)])
        for spans in ([(0x100002,1)],[(0x0FFFFF,2)],[(0x100008,16)]):
            with self.subTest(spans=spans),self.assertRaises(ValueError):source.reject_overlap(spans)
        for spans in ([(True,1)],[(0x100100,0)],[(0x100100,False)],[[]],None):
            with self.subTest(spans=spans),self.assertRaises(ValueError):source.reject_overlap(spans)

    def test_changed_source_during_copy_never_publishes_a_resident_manifest(self):
        captured=self.capture();source=resident.admit(captured.path,[(0x100000,3)])
        target=captured.path.parent/'ram-000.bin';original=resident._ordinary;changed=[False]
        def mutate(path,limit):
            if path==target and not changed[0]:
                changed[0]=True;raw=target.read_bytes();target.write_bytes(bytes([raw[0]^1])+raw[1:])
            return original(path,limit)
        with patch.object(resident,'_ordinary',side_effect=mutate):
            with self.assertRaises(ValueError):resident.copy_resident(source,self.root/'changed')
        self.assertTrue(changed[0]);self.assertFalse((self.root/'changed/resident.json').exists())

    def test_bundle_metadata_and_original_read_bytes_cannot_be_changed(self):
        copied=resident.declare_resident(self.capture().path,self.root/'resident',ranges=[(0x100000,3)])
        raw=copied.path.read_bytes();original=json.loads(raw)
        mutations=[lambda d:d['ranges'].__setitem__(0,[0x100000,2]),
                   lambda d:d['segments'][0].__setitem__('sha256','f'*64),
                   lambda d:d['machine']['assets'].__setitem__('bios','f'*64),
                   lambda d:d.__setitem__('execution_evidence',True),
                   lambda d:d.__setitem__('schema',True),
                   lambda d:d.__setitem__('unexpected',1)]
        for mutate in mutations:
            value=copy.deepcopy(original);mutate(value);copied.path.write_text(json.dumps(value),encoding='utf-8')
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):resident.load_resident(copied.path)
            copied.path.write_bytes(raw)
        target=copied.path.parent/'snapshot/ram-000.bin';data=target.read_bytes();target.write_bytes(bytes([data[0]^1])+data[1:])
        with self.assertRaises(ValueError):resident.load_resident(copied.path)
        with self.assertRaises(ValueError):copied.revalidate()

    def test_extra_files_and_source_side_output_are_refused(self):
        captured=self.capture();source=resident.admit(captured.path,[(0x100000,3)])
        with self.assertRaises(ValueError):resident.copy_resident(source,captured.path.parent/'nested')
        copied=resident.copy_resident(source,self.root/'resident')
        (copied.path.parent/'extra').write_bytes(b'')
        with self.assertRaises(ValueError):resident.load_resident(copied.path)
        with self.assertRaises(ValueError):copied.revalidate()


if __name__=='__main__':unittest.main()
