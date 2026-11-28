"""Versioned symbolic-stack admission through public RAM/origin/CLI adapters."""
import contextlib,io,json,tempfile,unittest
from pathlib import Path
from pcerecomp import cli,overlays,overlay_snapshot,origin_overlay
from pcerecomp.loader_sweep import plan
from tests.test_origin_overlay import ReportedOrigins,disc_machine
from tests.test_overlays import ORIGIN

CODE=bytes.fromhex('20 08 40 A9 77 80 FE EA 7A FA DA 5A 60')+bytes(19)
POLICY='bounded-ram-cd-stack-values-v1'

class FarCallAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.client=ReportedOrigins(CODE)
        self.snapshot=overlay_snapshot.capture_snapshot(self.client,self.root/'snapshot',machine=disc_machine(),origin=ORIGIN,regions=[(0x100000,32)])

    def test_live_policy_recovers_proven_word_without_changing_old_policy(self):
        old=overlays.discover_overlay(self.snapshot.path,self.root/'old',code_ranges=[(0x100000,32)],analysis_policy=overlays.ANALYSIS_POLICY)
        new=overlays.discover_overlay(self.snapshot.path,self.root/'new',code_ranges=[(0x100000,32)],analysis_policy=POLICY)
        self.assertNotIn(0x4003,{row['pc'] for row in old._instructions})
        self.assertIn(0x4003,{row['pc'] for row in new._instructions})
        self.assertEqual(new.report['analysis_policy'],POLICY)
        self.assertTrue(any(edge['kind']=='return' for edge in new.report['edges']))
        library=overlays.compose_overlays([old.path,new.path],self.root/'library');library.revalidate()
        self.assertEqual({row['pc'] for row in library.instructions},{row['pc'] for row in new._instructions})

    def test_tampered_policy_or_stack_provenance_cannot_be_readmitted(self):
        epoch=overlays.discover_overlay(self.snapshot.path,self.root/'new',code_ranges=[(0x100000,32)],analysis_policy=POLICY)
        original=epoch.path.read_bytes();doc=json.loads(original);doc['analysis_policy']=overlays.ANALYSIS_POLICY
        epoch.path.write_text(json.dumps(doc),encoding='utf-8',newline='\n')
        with self.assertRaises(ValueError):overlays.load_overlay(epoch.path)
        doc=json.loads(original);node=next(row for row in doc['nodes'] if row['stack_values'])
        node['stack_values'][0]['value']^=1;epoch.path.write_text(json.dumps(doc),encoding='utf-8',newline='\n')
        with self.assertRaises(ValueError):overlays.load_overlay(epoch.path)

    def test_origin_filtered_policy_preserves_origin_binding(self):
        origins=origin_overlay.capture_origins(self.client,self.snapshot.path,self.root/'origins')
        epoch=overlays.discover_origin_overlay(self.snapshot.path,origins.path,self.root/'new',disc_ranges=[(2048,32)],analysis_policy=POLICY)
        self.assertEqual(epoch.report['analysis_policy'],overlays.ORIGIN_FAR_CALL_POLICY)
        self.assertEqual(epoch.report['origins_sha256'],origins.sha256)
        self.assertIn(0x4003,{row['pc'] for row in epoch._instructions});epoch.revalidate()

    def test_cli_and_loader_plan_accept_the_same_explicit_policy(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result=cli.main(['discover-overlay',str(self.snapshot.path),'--code-range','0x100000:32','--analysis-policy',POLICY,'--call-depth','4','--out',str(self.root/'cli')])
        self.assertEqual(result,0);self.assertEqual(overlays.load_overlay(self.root/'cli').report['analysis_policy'],POLICY)
        from tests.test_loader_sweep import f
        doc=f.loader_plan();doc['analysis']=dict(policy=POLICY,call_depth_limit=4,data_ranges=[])
        self.assertEqual(plan(doc),doc)

if __name__=='__main__':unittest.main()
