"""Authored plan and CPU-edit admission; actual execution is in the example."""
import copy,importlib.util,tempfile,unittest
from pathlib import Path
from pcerecomp.loader_sweep import plan,seed
from scripts.dev_client import DevClient
from tests.test_overlays import ReportedRam
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('loader_fixture_tests',ROOT/'examples/loader-sweep/fixture.py');f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
class LoaderSweepTests(unittest.TestCase):
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
