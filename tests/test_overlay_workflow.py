"""Authored CD loader geometry and candidate membership without invented work."""
import hashlib,importlib.util,tempfile,unittest
from pathlib import Path
from pcerecomp import project
from pcerecomp.overlay_snapshot import capture_snapshot,machine_for
from pcerecomp.overlays import discover_overlay,compose_overlays
from tests.test_overlays import ReportedRam,ORIGIN
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('overlay_workflow',ROOT/'examples/live-overlays/workflow.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)


class OverlayWorkflowTests(unittest.TestCase):
    def test_authored_cd_sectors_and_literal_ram_geometry(self):
        bios,labels=w.f.firmware();disc=w.f.disc()
        self.assertEqual(len(bios),262144);self.assertEqual(len(disc),50*2048)
        self.assertEqual(bios[8190:8192],bytes.fromhex('00 E2'))
        for phase in (1,2):
            self.assertEqual(disc[phase*2048:(phase+1)*2048],w.f.sector(phase))
            for variant in (0,1):
                raw=w.f.expected_wram(phase,variant)
                self.assertEqual(len(raw),8192);self.assertEqual(raw[0x11],w.f.TAGS[phase-1][variant])
                self.assertEqual(raw[0x12],phase);self.assertEqual(raw[0x1FE:0x200],labels[f'call_return_{phase}'].to_bytes(2,'little'))
                self.assertEqual(len(w.f.code_plan(phase,variant)),6 if variant==0 else 7)
    def test_bootstrap_preparation_has_one_unexecuted_firmware_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'authored';w.create(out)
            result=w.prepare.prepare_project(out/'bootstrap.toml',out/'bootstrap');checked=project.verify(out/'bootstrap/project.toml')
            self.assertFalse(result['compiled']);self.assertFalse(result['executed'])
            self.assertIn('module_declared_roots',checked['files']);self.assertNotIn('module_observation_history',checked['files'])
    def test_both_reported_epochs_derive_three_previously_unvisited_branch_keys(self):
        # These are authored protocol fixtures. Real host execution belongs to
        # the separate public workflow qualification receipt.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths=[]
            machine=machine_for(dict(boot=dict(mode='system-card-reset',profile='standard')),dict(bios=hashlib.sha256(w.f.firmware()[0]).hexdigest(),disc=hashlib.sha256(w.f.disc()).hexdigest()))
            observed=set()
            for phase in (1,2):
                snap=capture_snapshot(ReportedRam(w.f.expected_cd(phase),mpr=w.f.MPR),root/f'snapshot-{phase}',machine=machine,origin=ORIGIN,regions=[(0x100000,65536)])
                epoch=discover_overlay(snap.path,root/f'epoch-{phase}',code_ranges=[(0x100000,20)])
                self.assertEqual(len(epoch._instructions),8);paths.append(epoch.path)
                observed.update((r['pc'],tuple(r['mpr']),tuple(r['data'])) for r in w.f.code_plan(phase,0))
            library=compose_overlays(paths,root/'library')
            keys={(r['pc'],tuple(r['mpr']),tuple(r['data'])) for r in library.instructions}
            self.assertEqual(len(keys),11);self.assertEqual(len(keys-observed),3)
            self.assertEqual(library.source_metadata['overlapping_identities'],5)
    def test_changed_original_disc_refuses_before_build_or_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'authored';w.create(out);p=out/'disc.iso';p.write_bytes(p.read_bytes()+b'!')
            with self.assertRaisesRegex(ValueError,'changed'):w.inputs(out)
            self.assertFalse((out/'bootstrap').exists())


if __name__=='__main__':unittest.main()
