"""Public CLI selects the shared analyzer explicitly and retains legacy output."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from pcerecomp import cli, overlays, cd_loads, overlay_snapshot, origin_overlay
from tests.test_overlays import ReportedRam, ORIGIN, machine
from tests.test_origin_overlay import ReportedOrigins, disc_machine
from tests.test_cd_loads import fixture


POLICY='bounded-ram-cd-candidates-v1'


class RamCdCliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.data=bytes.fromhex('20 08 40 A9 11 80 FE EA A9 22 60')+bytes(21)

    def run_cli(self,args):
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            try:return cli.main([str(arg) for arg in args])
            except SystemExit as error:return error.code

    def snapshot(self,origins=False):
        client=(ReportedOrigins if origins else ReportedRam)(self.data)
        snap=overlay_snapshot.capture_snapshot(client,self.root/'snapshot',
            machine=disc_machine() if origins else machine(),origin=ORIGIN,regions=[(0x100000,32)])
        return client,snap

    def test_live_cli_calls_data_and_legacy_bytes(self):
        _,snap=self.snapshot();bounded=self.root/'bounded'
        self.assertEqual(self.run_cli(['discover-overlay',snap.path,'--out',bounded,
            '--code-range','0x100000:32','--analysis-policy',POLICY,'--call-depth','3',
            '--data-range','0x10001F:1']),0)
        admitted=overlays.load_overlay(bounded)
        self.assertIn(0x4003,{ins['pc'] for ins in admitted._instructions})
        self.assertEqual(admitted.report['options']['call_depth_limit'],3)
        self.assertEqual(admitted.report['options']['data_ranges'],[[0x10001F,1]])
        direct=overlays.discover_overlay(snap.path,self.root/'direct',code_ranges=[(0x100000,32)])
        self.assertEqual(self.run_cli(['discover-overlay',snap.path,'--out',self.root/'legacy',
            '--code-range','0x100000:32']),0)
        self.assertEqual(direct.path.read_bytes(),(self.root/'legacy/overlay.json').read_bytes())

    def test_origin_cli_rederives_new_policy_and_legacy_bytes(self):
        client,snap=self.snapshot(True)
        origins=origin_overlay.capture_origins(client,snap.path,self.root/'origins')
        base=['discover-origin-overlay',origins.path,'--disc-range','2048:32']
        self.assertEqual(self.run_cli(base+['--out',self.root/'bounded','--analysis-policy',POLICY,
            '--call-depth','2','--data-range','0x10001F:1']),0)
        admitted=overlays.load_overlay(self.root/'bounded')
        self.assertEqual(admitted.report['analysis_policy'],overlays.ORIGIN_ANALYSIS_POLICY)
        self.assertIn(0x4003,{ins['pc'] for ins in admitted._instructions})
        direct=overlays.discover_origin_overlay(snap.path,origins.path,self.root/'direct',disc_ranges=[(2048,32)])
        self.assertEqual(self.run_cli(base+['--out',self.root/'legacy']),0)
        self.assertEqual(direct.path.read_bytes(),(self.root/'legacy/overlay.json').read_bytes())

    def test_invalid_cli_policy_ranges_and_depth_do_not_publish(self):
        _,snap=self.snapshot()
        base=['discover-overlay',snap.path,'--code-range','0x100000:32']
        cases=[['--analysis-policy','unknown'],['--analysis-policy',POLICY,'--call-depth','0'],
               ['--analysis-policy',POLICY,'--call-depth','65'],['--call-depth','3'],
               ['--data-range','0x100010:1'],['--analysis-policy',POLICY,'--data-range','broken'],
               ['--analysis-policy',POLICY,'--data-range','0x100020:1']]
        for i,options in enumerate(cases):
            output=self.root/f'denied{i}'
            with self.subTest(options=options):
                self.assertEqual(self.run_cli(base+['--out',output]+options),2)
                self.assertFalse(output.exists())

    def test_cd_cli_opt_in_and_legacy_bytes(self):
        spec,images,_=fixture(self.root)
        base=['declare-cd-loads',spec,'--disc',images['disc'],'--toc',images['toc']]
        self.assertEqual(self.run_cli(base+['--out',self.root/'bounded','--analysis-policy',POLICY,
            '--call-depth','2','--limit','100','--context-limit','16']),0)
        bounded=cd_loads.load(self.root/'bounded/roots.json',images)
        self.assertEqual(bounded.static_reachability,'candidates_only')
        self.assertEqual(self.run_cli(['verify-cd-loads',bounded.path,'--disc',images['disc'],'--toc',images['toc']]),0)
        direct=cd_loads.declare(spec,self.root/'direct',**images)
        self.assertEqual(self.run_cli(base+['--out',self.root/'legacy']),0)
        self.assertEqual(direct.path.read_bytes(),cd_loads.load(self.root/'legacy/roots.json',images).path.read_bytes())
        self.assertEqual(self.run_cli(base+['--out',self.root/'denied','--call-depth','2']),2)
        self.assertFalse((self.root/'denied').exists())


if __name__=='__main__':unittest.main()
