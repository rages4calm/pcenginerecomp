"""Authored RAM sources qualify the opt-in shared call/data analysis policy."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp import overlays as o, overlay_snapshot as s, origin_overlay
from tests.test_overlays import ReportedRam, ORIGIN, machine
from tests.test_origin_overlay import ReportedOrigins, disc_machine


class SharedOverlayAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.serial=0

    def snapshot(self,text,*,origin=False):
        self.serial+=1;data=bytes.fromhex(text);data+=bytes(max(0,32-len(data)))
        client=(ReportedOrigins if origin else ReportedRam)(data)
        snapshot=s.capture_snapshot(client,self.root/f'snapshot{self.serial}',
            machine=disc_machine() if origin else machine(),origin=ORIGIN,regions=[(0x100000,len(data))])
        return client,snapshot

    def discover(self,text,**kwargs):
        _,snap=self.snapshot(text)
        return o.discover_overlay(snap.path,self.root/f'epoch{self.serial}',
            code_ranges=[(0x100000,len(snap.regions[0][1]))],analysis_policy=o.ANALYSIS_POLICY,**kwargs)

    def pcs(self,epoch):return {row['pc'] for row in epoch._instructions}
    def reasons(self,epoch):return {row['reason'] for row in epoch.report['unresolved']}

    def test_balanced_call_and_return_reach_real_continuation(self):
        epoch=self.discover('20 08 40 A9 11 80 FE EA 48 A9 22 68 60')
        self.assertEqual(self.pcs(epoch),{0x4000,0x4003,0x4005,0x4008,0x4009,0x400B,0x400C})
        self.assertNotIn('return_continuation_unproven',self.reasons(epoch))
        self.assertTrue(any(edge['kind']=='return' and edge['target']['pc']==0x4003 for edge in epoch.report['edges']))
        self.assertFalse(epoch.report['execution_evidence']);self.assertFalse(epoch.report['routine_closure'])
        self.assertEqual(epoch.report['options']['call_depth_limit'],16)
        self.assertEqual(epoch.report['options']['data_ranges'],[])
        o.load_overlay(epoch.path).revalidate()

    def test_legacy_report_and_graph_remain_identical(self):
        _,snap=self.snapshot('20 08 40 A9 FF 80 FE EA A9 42 60')
        a=o.discover_overlay(snap.path,self.root/'legacy-a',code_ranges=[(0x100000,32)])
        b=o.discover_overlay(snap.path,self.root/'legacy-b',code_ranges=[(0x100000,32)])
        self.assertEqual(a.path.read_bytes(),b.path.read_bytes())
        graph,ins,roots=o._derive(snap,[0x4000],[(0x100000,32)],10000,256)
        for key,value in graph.items():self.assertEqual(a.report[key],value)
        self.assertEqual(a._instructions,ins);self.assertEqual(a._roots,roots)
        self.assertNotIn(0x4003,self.pcs(a));self.assertIn('return_continuation_unproven',self.reasons(a))
        self.assertNotIn('call_depth_limit',a.report['options'])

    def test_explicit_captured_data_excludes_fetch_and_permits_known_store(self):
        epoch=self.discover('A9 EA 8D 10 40 A9 2A 80 FE',data_ranges=[(0x100010,1)])
        self.assertEqual(self.pcs(epoch),{0x4000,0x4002,0x4005,0x4007})
        self.assertNotIn('possible_code_write',self.reasons(epoch))
        blocked=self.discover('A9 EA 8D 10 40 A9 2A 80 FE')
        self.assertEqual(self.pcs(blocked),{0x4000,0x4002})
        self.assertIn('possible_code_write',self.reasons(blocked))
        with self.assertRaisesRegex(ValueError,'seed'):
            self.discover('EA 80 FE',data_ranges=[(0x100000,1)])
        target=self.discover('4C 10 40',data_ranges=[(0x100010,1)])
        self.assertEqual(self.pcs(target),{0x4000});self.assertIn('outside_allowed_code',self.reasons(target))

    def test_data_does_not_authorize_saved_return_mutation(self):
        epoch=self.discover('20 08 40 A9 FF 80 FE EA A9 00 8D FF 21 60')
        self.assertNotIn(0x4003,self.pcs(epoch));self.assertIn('stack_write_barrier',self.reasons(epoch))
        indirect=self.discover('20 08 40 A9 FF 80 FE EA A9 00 91 10 60')
        self.assertNotIn(0x4003,self.pcs(indirect));self.assertIn('unknown_write_target',self.reasons(indirect))

    def test_data_policy_and_bound_types_are_closed(self):
        for kwargs in ({'call_depth_limit':True},{'call_depth_limit':0},{'call_depth_limit':65},
                       {'data_ranges':[(0x100020,1)]},{'data_ranges':[(0x1F2000,1)]},
                       {'data_ranges':[(0x100010,2),(0x100011,1)]},{'data_ranges':False}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.discover('80 FE',**kwargs)
        _,snap=self.snapshot('80 FE')
        for kwargs in ({'data_ranges':[]},{'call_depth_limit':2},{'analysis_policy':'unknown'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                o.discover_overlay(snap.path,self.root/'no-optin',code_ranges=[(0x100000,32)],**kwargs)

    def test_report_policy_options_and_graph_are_rederived(self):
        epoch=self.discover('20 08 40 A9 FF 80 FE EA A9 42 60')
        raw=epoch.path.read_bytes();original=json.loads(raw)
        mutations=[lambda d:d['options'].__setitem__('data_ranges',None),
                   lambda d:d['options'].__setitem__('call_depth_limit',None),
                   lambda d:d.__setitem__('analysis_policy',o.POLICY),
                   lambda d:d['nodes'][0].__setitem__('mnemonic','NOP'),
                   lambda d:d['options'].__setitem__('unknown',1),
                   lambda d:d['options'].__setitem__('data_ranges',[[0x100000,1]])]
        for mutate in mutations:
            doc=copy.deepcopy(original);mutate(doc);epoch.path.write_text(json.dumps(doc),encoding='utf-8')
            with self.subTest(doc=mutate),self.assertRaises(ValueError):o.load_overlay(epoch.path)
            epoch.path.write_bytes(raw)
        lib=o.compose_overlays([epoch.path],self.root/'library')
        self.assertEqual(len(lib.instructions),len(epoch._instructions));lib.revalidate()

    def test_origin_filtered_analysis_preserves_bound_origin_closure(self):
        client,snap=self.snapshot('20 08 40 A9 FF 80 FE EA A9 42 60',origin=True)
        origins=origin_overlay.capture_origins(client,snap.path,self.root/'origins')
        epoch=o.discover_origin_overlay(snap.path,origins.path,self.root/'origin-analysis',
            disc_ranges=[(2048,32)],analysis_policy=o.ANALYSIS_POLICY,data_ranges=[(0x10001F,1)])
        self.assertEqual(epoch.report['analysis_policy'],o.ORIGIN_ANALYSIS_POLICY)
        self.assertIn(0x4003,self.pcs(epoch));self.assertEqual(epoch.report['origins_sha256'],origins.sha256)
        o.load_overlay(epoch.path).revalidate()


if __name__=='__main__':unittest.main()
