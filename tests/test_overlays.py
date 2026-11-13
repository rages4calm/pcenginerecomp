"""Authored reported RAM epochs: rederivation, guards and evidence separation."""
import copy,contextlib,hashlib,io,json,tempfile,tomllib,unittest
from pathlib import Path
from unittest.mock import patch
from pcerecomp import overlays as o,overlay_snapshot as s,project,prepare,incremental as inc,cli
from pcerecomp.declarations import load_compilation
from pcerecomp.emitter import emit_declarations
from pcerecomp.native_catalog import load_native_catalog,OVERLAY_PRODUCER_CONTRACT
from tests import test_project

MPR=[255,248,128,129,130,131,132,0]
ORIGIN=dict(tool=dict(revision='1'*40,source_sha256='2'*64,source_files=1),descriptor_sha256='3'*64,build_receipt_sha256='4'*64,binary_sha256='5'*64)


class ReportedRam:
    """Authored protocol fixture, not a real host or execution qualification."""
    def __init__(self,data,*,start=0x100000,pc=0x4000,mpr=None):
        self.data=data;self.start=start;self.pc=pc;self.mpr=list(mpr or MPR);self.calls=[];self.identity=0
    def call(self,command,**args):
        self.identity+=1;self.calls.append((command,args));i=self.identity
        if command=='status':
            physical=[(self.mpr[((self.pc+n)&65535)>>13]<<13)|((self.pc+n)&8191) for n in range(7)]
            fetch=[self.data[s.canonical(a)-self.start] if self.start<=s.canonical(a)<self.start+len(self.data) else None for a in physical]
            return dict(id=i,ok=True,paused=True,local_paused=False,frame=0,ticks=0,
                host=dict(pc=self.pc,native_steps=0,interpreter_steps=0,cpu=dict(a=42,x=0,y=0,sp=255,p=4,mpr=self.mpr.copy(),physical_pc=physical[0],instruction_physical=physical,instruction_bytes=fetch)))
        assert command=='read_memory_block'
        offset=args['address']-self.start;raw=self.data[offset:offset+args['length']]
        return dict(id=i,ok=True,address=args['address'],length=args['length'],data=raw.hex())


def machine(sha='a'*64):
    return s.machine_for(dict(payload=dict(physical_load=0x100000,pc=0x4000,mpr=MPR)),dict(payload=sha))


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.number=0
    def snapshot(self,code=bytes.fromhex('A9 2A 8D 00 20 A2 03 E8 80 FE'),**kwargs):
        self.number+=1;data=code+bytes(max(0,32-len(code)));client=ReportedRam(data,**kwargs)
        captured=s.capture_snapshot(client,self.root/f'snapshot-{self.number}',machine=machine(),origin=ORIGIN,regions=[(client.start,len(data))])
        self.assertEqual([c[0] for c in client.calls],['status','read_memory_block','read_memory_block','status'])
        return captured
    def epoch(self,code=None,**options):
        snap=self.snapshot() if code is None else self.snapshot(code)
        return o.discover_overlay(snap.path,self.root/f'epoch-{self.number}',code_ranges=[(0x100000,len(snap.regions[0][1]))],**options)
    def library(self):
        a=self.epoch();b=self.epoch(bytes.fromhex('A9 33 8D 00 20 A2 03 E8 80 FE'))
        return o.compose_overlays([a.path,b.path],self.root/'library')

    def test_closed_snapshot_replays_typed_reads_and_retains_original_source_epoch(self):
        snap=self.snapshot();self.assertFalse(snap.document['execution_evidence']);self.assertEqual(snap.document['origin'],ORIGIN)
        self.assertEqual(snap.regions[0][0],0x100000);self.assertEqual(snap.before['host']['native_steps'],0);snap.revalidate()
    def test_format_probe_preserves_large_existing_declaration_admission(self):
        path=self.root/'large-existing.json';path.write_bytes(b' '*s.MAX_JSON+b'{}')
        self.assertFalse(o.is_library(path))
        epoch=self.epoch();options=epoch.report['options'];options['entries']=[[]]
        with self.assertRaises(ValueError):o._derive(epoch.snapshot,options['entries'],options['code_ranges'],100,10)
    def test_two_byte_variants_keep_same_mapping_and_distinct_guarded_identities(self):
        lib=self.library();c=load_compilation(lib.path)
        self.assertEqual((len(lib.instructions),len(lib.roots)),(6,10));self.assertEqual(lib.source_metadata['overlapping_identities'],4)
        self.assertEqual(lib.source_metadata['memberships'],10);self.assertFalse(c.observed_keys)
        variants=[r for r in c.instructions if r['pc']==0x4000];self.assertEqual({tuple(v['data']) for v in variants},{(0xA9,42),(0xA9,51)})
        self.assertTrue(all('native_hits' not in ins for ins in c.instructions));self.assertEqual(lib.source_metadata['loader_attribution'],'not_inferred')
    def test_direct_branches_include_unexecuted_both_sides(self):
        e=self.epoch(bytes.fromhex('D0 02 A9 11 A9 22 80 FE'))
        self.assertEqual({r['pc'] for r in e._instructions},{0x4000,0x4002,0x4004,0x4006})
        self.assertFalse(e.report['routine_closure']);self.assertEqual(e.report['static_reachability'],'candidates_only')
    def test_proven_tam_changes_source_context_and_unknown_tam_stops(self):
        data=bytearray(16384);data[:4]=bytes.fromhex('A9 81 53 04');data[8196:8200]=bytes.fromhex('A9 55 80 FE')
        snap=self.snapshot(bytes(data));e=o.discover_overlay(snap.path,self.root/'tam',code_ranges=[(0x100000,16384)])
        self.assertEqual({(r['pc'],r['mpr'][2]) for r in e._instructions},{(0x4000,128),(0x4002,128),(0x4004,129),(0x4006,129)})
        bad=self.epoch(bytes.fromhex('53 04 EA 80 FE'));self.assertEqual(len(bad._instructions),1)
        self.assertEqual(bad.report['unresolved'][0]['reason'],'unknown_mapping_value')
    def test_scalar_code_write_stops_before_stale_successor(self):
        e=self.epoch(bytes.fromhex('A9 EA 8D 05 40 EA 80 FE'))
        self.assertEqual({r['pc'] for r in e._instructions},{0x4000,0x4002})
        self.assertEqual(e.report['unresolved'][0]['reason'],'possible_code_write')
    def test_indirect_device_block_and_interrupt_frontiers_are_explicit(self):
        cases=[('91 00','unknown_write_target'),('8D 01 18','write_not_proven_ram'),('03 00','opaque_device_write'),
            ('73 00 20 00 30 01 00','block_transfer_changes_memory'),('6C 00 20','indirect_jump'),('40','interrupt_return'),('00 00','interrupt_vector'),('0B','unsupported_instruction')]
        for text,reason in cases:
            with self.subTest(text=text):e=self.epoch(bytes.fromhex(text));self.assertEqual(e.report['unresolved'][0]['reason'],reason)
    def test_call_target_does_not_invent_return_continuation(self):
        e=self.epoch(bytes.fromhex('20 08 40 A9 FF 80 FE EA A9 42 60'))
        self.assertEqual({r['pc'] for r in e._instructions},{0x4000,0x4008,0x400A})
        self.assertIn('return_continuation_unproven',{r['reason'] for r in e.report['unresolved']})
    def test_state_and_context_limits_preserve_frontier(self):
        e=self.epoch(instruction_limit=2);self.assertEqual(len(e._instructions),2)
        self.assertIn('state_limit',{r['reason'] for r in e.report['unresolved']})
        with self.assertRaises(ValueError):self.epoch(entries=[0x4000,0x4002],instruction_limit=1)
    def test_denied_or_uncaptured_ranges_and_partial_seed_refuse(self):
        snap=self.snapshot()
        for ranges in ([(0x100000,1)],[(0x100000,33)],[(0x1FE000,1)],[(0x100004,8)]):
            self.number+=1
            with self.subTest(ranges=ranges),self.assertRaises(ValueError):o.discover_overlay(snap.path,self.root/f'denied-{self.number}',code_ranges=ranges)
    def test_wram_alias_fetch_and_aliasing_write_use_canonical_backing(self):
        mpr=MPR.copy();mpr[1]=249;mpr[2]=250
        code=bytes.fromhex('A9 EA 8D 00 20 80 FE')+bytes(25)
        client=ReportedRam(code,start=0x1F0000,mpr=mpr)
        snap=s.capture_snapshot(client,self.root/'wram',machine=machine(),origin=ORIGIN,regions=[(0x1F0000,32)])
        e=o.discover_overlay(snap.path,self.root/'wram-code',code_ranges=[(0x1F0000,32)])
        self.assertEqual(e._instructions[0]['physical'][0],250*8192)
        self.assertEqual(e.report['unresolved'][0]['reason'],'possible_code_write')
    def test_changed_snapshot_readback_status_or_binary_refuses(self):
        snap=self.snapshot()
        for name in ('before.json','after.json','read-000.json','verify-000.json','ram-000.bin','snapshot.json'):
            p=snap.path.parent/name;raw=p.read_bytes()
            if name=='snapshot.json':
                doc=json.loads(raw);doc['execution_evidence']=True;p.write_text(json.dumps(doc),encoding='utf-8')
            else:p.write_bytes(raw+b' ')
            with self.subTest(name=name),self.assertRaises(ValueError):s.load_snapshot(snap.path)
            with self.assertRaises(ValueError):snap.revalidate()
            p.write_bytes(raw)
    def test_changed_memory_with_unchanged_status_refuses_before_publication(self):
        class Changed(ReportedRam):
            def call(self,command,**args):
                reply=super().call(command,**args)
                if command=='read_memory_block' and self.identity==3:reply['data']='00'*args['length']
                return reply
        out=self.root/'bad-readback'
        with self.assertRaisesRegex(ValueError,'RAM changed'):s.capture_snapshot(Changed(bytes.fromhex('80 FE')+bytes(30)),out,machine=machine(),origin=ORIGIN,regions=[(0x100000,32)])
        self.assertFalse(out.exists())
    def test_recomputed_hashes_do_not_authorize_forged_derivation(self):
        e=self.epoch();p=e.path;doc=json.loads(p.read_text(encoding='utf-8'));doc['nodes'][0]['mnemonic']='NOP';p.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'rederivation'):o.load_overlay(p)
    def test_extra_graph_members_and_duplicate_epochs_refuse(self):
        e=self.epoch();extra=e.path.parent/'extra';extra.write_bytes(b'!')
        with self.assertRaises(ValueError):o.load_overlay(e.path)
        extra.unlink()
        with self.assertRaises(ValueError):o.compose_overlays([e.path,e.path],self.root/'duplicates')
        lib=o.compose_overlays([e.path],self.root/'one');extra=lib.path.parent/'epochs/e9999';extra.mkdir()
        with self.assertRaises(ValueError):o.load_library(lib.path)
    def test_origin_machine_types_ids_and_limits_are_strict(self):
        for item in (dict(machine(),runtime_abi=True),dict(machine(),schema=1.0)):
            with self.assertRaises(ValueError):s.validate_machine(item)
        for ranges in ([(0x1F2000,1)],[(0x100000,65537)],[(0x100000,16),(0x100008,16)],[(0x100000,True)]):
            with self.assertRaises(ValueError):s.ram_ranges(machine(),ranges)
        origin=copy.deepcopy(ORIGIN);origin['tool']['source_files']=True
        with self.assertRaises(ValueError):s.validate_origin(origin)
        with self.assertRaises(ValueError):self.epoch(entries=[0x4000,True])
    def test_incompatible_machine_and_mutated_library_refuse(self):
        a=self.epoch();snap=s.capture_snapshot(ReportedRam(bytes.fromhex('80 FE')+bytes(30)),self.root/'other-machine',machine=machine('b'*64),origin=ORIGIN,regions=[(0x100000,32)])
        b=o.discover_overlay(snap.path,self.root/'other-code',code_ranges=[(0x100000,32)])
        with self.assertRaises(ValueError):o.compose_overlays([a.path,b.path],self.root/'incompatible')
        lib=o.compose_overlays([a.path],self.root/'valid');p=next(row['path'] for name,row in lib.artifact_bindings.items() if name.endswith('ram-000.bin'));raw=p.read_bytes();p.write_bytes(raw+b' ')
        with self.assertRaises(ValueError):lib.revalidate()
    def test_copy_and_emission_preserve_graph_and_versioned_catalogue(self):
        lib=self.library();copied=o.copy_library(lib.path,self.root/'copied');self.assertEqual(copied.sha256,lib.sha256)
        out=self.root/'module';m=emit_declarations(copied.path,None,out,partition_layout='stable')
        self.assertEqual((m['declared_instructions'],m['observed_instructions']),(6,0))
        catalog=load_native_catalog(out/'module.json',copied.path,producer_contract=OVERLAY_PRODUCER_CONTRACT)
        self.assertEqual(catalog.provenance['format'],'pce-native-catalog-4');self.assertEqual(len(catalog.declared),6)
        self.assertNotIn(str(self.root),json.dumps(catalog.provenance));self.assertTrue(catalog.provenance['overlay_artifacts'])
    def test_existing_outputs_and_original_epoch_namespaces_are_protected(self):
        e=self.epoch()
        with self.assertRaises(ValueError):o.compose_overlays([e.path],e.path.parent/'nested')
        lib=o.compose_overlays([e.path],self.root/'safe')
        with self.assertRaises(ValueError):o.copy_library(lib.path,lib.path.parent/'epochs/output')
        with self.assertRaises(ValueError):emit_declarations(lib.path,None,lib.path.parent/'epochs/module')
    def test_consumer_preparation_and_managed_archive_bind_ram_graph_not_boot_payload(self):
        fixture=test_project.ConsumerProjectTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        config=tomllib.loads(fixture.text);payload=self.root/'boot.bin';payload.write_bytes(bytes.fromhex('80 FE'));config['payload']=dict(path=str(payload),sha256=project.sha256(payload),physical_load=0x100000,pc=0x4000,mpr=MPR)
        contract=s.machine_for(config,dict(payload=project.sha256(payload)))
        snap=s.capture_snapshot(ReportedRam(bytes.fromhex('A9 42 80 FE')+bytes(28)),self.root/'live',machine=contract,origin=ORIGIN,regions=[(0x100000,32)])
        epoch=o.discover_overlay(snap.path,self.root/'live-code',code_ranges=[(0x100000,32)]);lib=o.compose_overlays([epoch.path],self.root/'live-library')
        recipe=dict(schema=1,format=prepare.FORMAT,name='live-overlay',sdk=dict(revision='0'*40,allow_revision_override=True),module=dict(kind='overlay',path=str(lib.path)),payload=config['payload'],runtime=config['runtime'],limits=config['limits'])
        spec=self.root/'recipe.toml';spec.write_text(prepare._toml(recipe),encoding='utf-8')
        with patch.object(prepare,'TOOL_ROOT',fixture.tool):result=prepare.prepare_project(spec,self.root/'prepared')
        self.assertFalse(result['compiled']);checked=project.verify(self.root/'prepared/project.toml',allow_revision_override=True)
        files=inc._module(checked);self.assertTrue(any(name.startswith('epochs/') for name in files));self.assertNotIn(payload,files.values())
        owned=self.root/'owned';owned.mkdir();inc._sync(files,owned)
        binding=dict(file='declared-roots.json',sha256=lib.sha256,members=[dict(file=name,sha256=project.sha256(path),size_bytes=path.stat().st_size) for name,path in sorted(files.items()) if name.startswith('epochs/')])
        inc._check_declared_archive(owned,binding)
        changed=owned/binding['members'][0]['file'];raw=changed.read_bytes();changed.write_bytes(raw+b' ')
        with self.assertRaises(ValueError):inc._check_declared_archive(owned,binding)
        changed.write_bytes(raw);bad=copy.deepcopy(binding);bad['members'][0]['size_bytes']=True
        with self.assertRaises(ValueError):inc._check_declared_archive(owned,bad)
        wrong=copy.deepcopy(config);wrong['payload']['sha256']='f'*64
        with self.assertRaises(ValueError):project._overlay_machine(wrong,dict(payload='f'*64),lib)
    def test_cli_discovery_composition_verification_and_emission(self):
        snap=self.snapshot();epoch=self.root/'cli-epoch';library=self.root/'cli-library'
        commands=[['discover-overlay',str(snap.path),'--code-range','0x100000:32','--out',str(epoch)],
            ['compose-overlays',str(epoch),'--out',str(library)],['verify-overlays',str(library)],
            ['emit-overlays',str(library),'--out',str(self.root/'cli-module')]]
        for args in commands:
            with self.subTest(args=args),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(cli.main(args),0)


if __name__=='__main__':unittest.main()
