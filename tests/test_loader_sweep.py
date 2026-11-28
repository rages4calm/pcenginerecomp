"""Authored plan and CPU-edit admission; actual execution is in the example."""
import copy,contextlib,importlib.util,json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from pcerecomp.loader_sweep import plan,seed
from scripts.dev_client import DevClient
from tests.test_overlays import ReportedRam,machine,ORIGIN,MPR
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('loader_fixture_tests',ROOT/'examples/loader-sweep/fixture.py');f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
class LoaderSweepTests(unittest.TestCase):
    def test_known_vector_plan_is_explicit_and_range_bounded(self):
        doc=f.loader_plan()
        doc['analysis']=dict(policy='bounded-ram-cd-vectors-v1',call_depth_limit=8,
            data_ranges=[],vector_ranges=[[0x100010,2]])
        self.assertEqual(plan(doc),doc)
        for value in ([],[[0x100010,True]],[[0x100010,2],[0x100011,2]]):
            changed=copy.deepcopy(doc);changed['analysis']['vector_ranges']=value
            with self.subTest(value=value),self.assertRaises(ValueError):plan(changed)
        changed=copy.deepcopy(doc);changed['analysis']['policy']='bounded-ram-cd-stack-values-v1'
        with self.assertRaises(ValueError):plan(changed)

    def test_sweep_forwards_authenticated_known_vector_policy(self):
        from pcerecomp.loader_sweep import sweep
        from pcerecomp.overlays import load_overlay
        raw=bytearray(32);raw[:5]=bytes.fromhex('A2 02 7C 0E 40')
        raw[8:12]=bytes.fromhex('A9 07 80 FE');raw[16:18]=bytes.fromhex('08 40')
        @contextlib.contextmanager
        def session(*args,**kwargs):yield ReportedRam(bytes(raw)),{}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);options=f.loader_plan();options['groups']=[1];options['passes']=['independent']
            options['snapshot']=dict(ranges=[[0x100000,32]],code_ranges=[[0x100000,16]],entries=[0x4000])
            options['analysis']=dict(policy='bounded-ram-cd-vectors-v1',call_depth_limit=8,
                data_ranges=[],vector_ranges=[[0x100010,2]])
            source=root/'plan.json';source.write_text(json.dumps(options),encoding='utf-8')
            with patch('pcerecomp.loader_sweep.consumer_session',session),patch('pcerecomp.loader_sweep.probe',return_value=dict(group=1)),patch('pcerecomp.loader_sweep.package_binding',return_value=(machine(),ORIGIN)):
                result=sweep(root/'consumer/project.toml',root/'build',root,'baseline.pcec',source,root/'sweep')
            epoch=load_overlay(root/'sweep/epoch-0000')
            self.assertTrue(result['passed'])
            self.assertEqual(epoch.report['analysis_policy'],options['analysis']['policy'])
            self.assertEqual(epoch.report['options']['vector_ranges'],[[0x100010,2]])
            edges=[edge for edge in epoch.report['edges'] if edge['kind']=='vector_jump']
            self.assertEqual(len(edges),1)
            self.assertEqual(edges[0]['vector_word']['target'],0x4008)

    def test_shared_analysis_is_explicit_closed_and_bounded(self):
        doc=f.loader_plan();doc['analysis']=dict(policy='bounded-ram-cd-candidates-v1',call_depth_limit=8,data_ranges=[[0x100010,1]])
        self.assertEqual(plan(doc),doc)
        for key,value in (('call_depth_limit',True),('call_depth_limit',65),('policy','unknown'),('data_ranges',[[0x100010,2],[0x100011,1]]),('data_ranges',[[0x100010,False]])):
            changed=copy.deepcopy(doc);changed['analysis'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):plan(changed)
        doc['analysis']['invented']=True
        with self.assertRaises(ValueError):plan(doc)

    def test_sweep_preserves_opt_in_return_edges_in_composed_library(self):
        from pcerecomp.loader_sweep import sweep
        from pcerecomp.overlays import load_library,load_overlay
        @contextlib.contextmanager
        def session(*args,**kwargs):yield ReportedRam(bytes.fromhex('20 08 40 A9 07 80 FE EA 60')+bytes(23)),{}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);options=f.loader_plan();options['groups']=[1];options['passes']=['independent']
            options['snapshot']=dict(ranges=[[0x100000,32]],code_ranges=[[0x100000,32]],entries=[0x4000])
            options['analysis']=dict(policy='bounded-ram-cd-candidates-v1',call_depth_limit=8,data_ranges=[[0x100010,16]])
            source=root/'plan.json';source.write_text(json.dumps(options),encoding='utf-8')
            with patch('pcerecomp.loader_sweep.consumer_session',session),patch('pcerecomp.loader_sweep.probe',return_value=dict(group=1)),patch('pcerecomp.loader_sweep.package_binding',return_value=(machine(),ORIGIN)):
                result=sweep(root/'consumer/project.toml',root/'build',root,'baseline.pcec',source,root/'sweep')
            epoch=load_overlay(root/'sweep/epoch-0000');library=load_library(root/'sweep/library')
            self.assertTrue(result['passed']);self.assertEqual(epoch.report['analysis_policy'],options['analysis']['policy'])
            self.assertTrue(any(edge['kind']=='return' for edge in epoch.report['edges']))
            self.assertEqual({row['pc'] for row in library.instructions},{0x4000,0x4003,0x4005,0x4008})
    def test_changed_sweep_package_is_refused_before_process_start(self):
        from pcerecomp.loader_sweep import consumer_session

        launch = {
            'binding': {'tool': ORIGIN['tool'], 'descriptor_sha256': ORIGIN['descriptor_sha256']},
            'build_receipt': {'sha256': ORIGIN['build_receipt_sha256']},
            'binary_sha256': '8'*64,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('pcerecomp.loader_sweep.project.prepare_launch', return_value=launch):
                with patch('pcerecomp.loader_sweep.subprocess.Popen') as process:
                    with self.assertRaisesRegex(ValueError, 'original sweep package'):
                        with consumer_session(root/'project.toml', root/'build', root/'call',
                                              root/'checkpoints', 'baseline.pcec', expected_origin=ORIGIN):
                            self.fail('Unexpected mismatched checkpoint launch')
                    process.assert_not_called()

    def test_independent_and_cumulative_plan_is_explicit_and_detached(self):
        original=f.loader_plan();value=plan(original);self.assertEqual(value,original);value['groups'].append(3);self.assertEqual(original['groups'],[1,2])
        for register in ('a','x','y'):
            doc=f.loader_plan();doc['loader'][register]='group';self.assertEqual(plan(doc)['loader'][register],'group')
    def test_numeric_types_and_bounds_refuse_before_execution(self):
        for section,key,value in (('loader','pc',True),('loader','p',1.0),('limits','ticks',0),('limits','instructions',100000001),('limits','states',True)):
            doc=f.loader_plan();doc[section][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):plan(doc)
    def test_return_condition_binds_its_source_window(self):
        doc=f.loader_plan();doc['loader']['return_mpr_mask']=1
        with self.assertRaises(ValueError):plan(doc)
    def test_duplicate_groups_passes_and_excess_epochs_refuse(self):
        for key,value in (('groups',[1,1]),('groups',[True]),('passes',['cumulative','cumulative']),('passes',['mystery']),('groups',list(range(256)))):
            doc=f.loader_plan();doc[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):plan(doc)
    def test_cpu_seed_does_not_include_clocks_or_retired_counters(self):
        client=ReportedRam(bytes.fromhex('80 FE')+bytes(30));status=client.call('status');value=seed(status)
        self.assertEqual(len(value),15);self.assertEqual(value[:2],bytes.fromhex('00 40'));self.assertEqual(value[7:],bytes(status['host']['cpu']['mpr']))
        status['host']['native_steps']=999;status['ticks']=123456;self.assertEqual(seed(status),value)
    def test_cpu_edit_requires_exact_bytes_and_equal_lengths(self):
        client=object.__new__(DevClient);calls=[];client.call=lambda command,**args:(calls.append((command,args)) or dict(ok=True,id=1,length=15))
        for a,b in ((bytes(14),bytes(15)),(list(range(15)),bytes(15)),(bytes(15),bytes(16))):
            with self.assertRaises(ValueError):client.write_cpu(a,b)
        self.assertFalse(calls);client.write_cpu(bytes(15),bytes((1,))*15);self.assertEqual(calls[0][0],'write_cpu')
    def test_authored_loader_entry_writes_group_then_calls_actual_cd_loader(self):
        bios,labels=f.firmware();target=labels['load'];self.assertEqual(bios[0x700:0x706],bytes((0x85,0x27,0x20,target&255,target>>8,0x60)))
        self.assertEqual(len(bios),262144);self.assertEqual(len(f.disc()),50*2048)
    def test_probe_client_rejects_bad_mapping_before_network(self):
        client=object.__new__(DevClient);client.call=lambda *a,**k:self.fail('Invalid probe reached network')
        for kwargs in (dict(pc=True,mpr=f.MPR,instructions=1,ticks=1),dict(pc=0x4000,mpr=f.MPR,instructions=1,ticks=1,mpr_mask=1),dict(pc=0x4000,mpr=f.MPR,instructions=0,ticks=1)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):client.run_until(**kwargs)
    def test_identical_reported_sources_share_a_member_but_keep_every_call(self):
        # Admission test only: no guest execution is claimed by this protocol
        # fixture. Real guest sweeps are qualified separately in the example.
        from pcerecomp.loader_sweep import sweep
        from pcerecomp.overlays import load_library
        @contextlib.contextmanager
        def session(*args,**kwargs):yield ReportedRam(bytes.fromhex('80 FE')+bytes(30)),{}
        def probe(client,group,options):return dict(group=group,after=client.call('status'))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);options=f.loader_plan();options['loader']['mpr']=MPR
            options['snapshot']=dict(ranges=[[0x100000,32]],code_ranges=[[0x100000,32]],entries=[0x4000])
            path=root/'plan.json';path.write_text(json.dumps(options),encoding='utf-8')
            with patch('pcerecomp.loader_sweep.consumer_session',session),patch('pcerecomp.loader_sweep.probe',probe),patch('pcerecomp.loader_sweep.package_binding',return_value=(machine(),ORIGIN)):
                result=sweep(root/'consumer/project.toml',root/'build',root,'baseline.pcec',path,root/'sweep')
            library=load_library(root/'sweep/library/library.json')
            self.assertEqual(len(result['calls']),4);self.assertEqual(result['epochs'],4)
            members=library.source_metadata['epochs']
            self.assertLess(result['library_epochs'],4);self.assertEqual(result['library_epochs'],len(members))
            for i,row in enumerate(result['calls']):
                self.assertTrue((root/f'sweep/snapshot-{i:04d}/snapshot.json').exists())
                self.assertTrue((root/f'sweep/epoch-{i:04d}/overlay.json').exists())
                self.assertEqual(members[row['library_epoch']]['sha256'],row['epoch_sha256'])
