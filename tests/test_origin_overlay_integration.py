"""Origin-bound overlay graphs retain diagnostic witnesses through consumers."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from pcerecomp import cli, incremental, origin_overlay, overlay_snapshot, overlays, prepare, project
from pcerecomp.emitter import emit_declarations
from pcerecomp.native_catalog import load_native_catalog, OVERLAY_PRODUCER_CONTRACT
from tests.test_overlays import MPR, ORIGIN
from tests.test_origin_overlay import ReportedOrigins
from tests import test_project


class OriginOverlayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.machine = overlay_snapshot.machine_for(
            dict(payload=dict(physical_load=0x100000, pc=0x4000, mpr=MPR)),
            dict(payload="a" * 64, disc="b" * 64))

    def epoch(self, prefix="one", *, machine=None, known=True):
        client = ReportedOrigins(bytes.fromhex("A9 2A 80 FE") + bytes(28),
                                 offsets=list(range(2048, 2052)) + [None] * 28)
        snapshot = overlay_snapshot.capture_snapshot(
            client, self.root / (prefix + "-snapshot"), machine=machine or self.machine,
            origin=ORIGIN, regions=[(0x100000, 32)])
        if not known:
            return overlays.discover_overlay(snapshot.path, self.root / prefix,
                                             code_ranges=[(0x100000, 4)], entries=[0x4000])
        origins = origin_overlay.capture_origins(client, snapshot.path, self.root / (prefix + "-origins"))
        return overlays.discover_origin_overlay(snapshot.path, origins.path, self.root / prefix,
                                                disc_ranges=[(2048, 4)], entries=[0x4000])

    def test_origin_evidence_survives_mixed_library_copy_and_emission(self):
        current, legacy = self.epoch(), self.epoch("legacy", known=False)
        library = overlays.compose_overlays([current.path, legacy.path], self.root / "library")
        copied = overlays.copy_library(library.path, self.root / "copied")
        self.assertEqual(copied.sha256, library.sha256)
        names = set(copied.artifact_bindings)
        self.assertTrue(any(name.endswith("/origins/origins.json") for name in names))
        self.assertTrue(any(name.endswith("/origins/origin-read-0000.json") for name in names))
        self.assertTrue(any(name.endswith("/snapshot/snapshot.json") for name in names))
        self.assertEqual({epoch.report["format"] for epoch in copied._epochs},
                         {overlays.FORMAT, overlays.ORIGIN_FORMAT})
        manifest = emit_declarations(copied.path, None, self.root / "module", partition_layout="stable")
        self.assertEqual((manifest["declared_instructions"], manifest["observed_instructions"]), (2, 0))
        catalog = load_native_catalog(self.root / "module/module.json", copied.path,
                                      producer_contract=OVERLAY_PRODUCER_CONTRACT)
        self.assertEqual(len(catalog.declared), 2)
        self.assertFalse(catalog.observed)
        self.assertTrue(catalog.provenance["overlay_artifacts"])

    def test_selected_disc_ranges_cannot_override_observed_ram_ranges(self):
        epoch = self.epoch()
        original = epoch.path.read_bytes()
        for update in (dict(disc_ranges=[[4096, 4]]), dict(code_ranges=[[0x100000, 32]])):
            doc = json.loads(original)
            doc["options"].update(update)
            epoch.path.write_text(json.dumps(doc), encoding="utf-8")
            with self.subTest(update=update), self.assertRaises(ValueError):
                overlays.load_overlay(epoch.path)
        epoch.path.write_bytes(original)
        overlays.load_overlay(epoch.path)

    def test_rehashed_inconsistent_origin_pages_refuse_before_graph_authority(self):
        epoch = self.epoch()
        root = epoch.path.parent / "origins"
        report = root / "origin-read-0000.json"
        value = json.loads(report.read_bytes())
        value["disc_origin"]["offsets"][0] = 4096
        raw = json.dumps(value).encode("utf-8")
        report.write_bytes(raw)
        manifest = root / "origins.json"
        origins = json.loads(manifest.read_bytes())
        origins["artifacts"][report.name] = dict(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        original_manifest = json.dumps(origins).encode("utf-8")
        manifest.write_bytes(original_manifest)
        graph = json.loads(epoch.path.read_bytes())
        graph["origins_sha256"] = hashlib.sha256(original_manifest).hexdigest()
        epoch.path.write_text(json.dumps(graph), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed between paused reads"):
            overlays.load_overlay(epoch.path)

    def test_unrelated_snapshot_cannot_reuse_origin_report(self):
        current, other = self.epoch(), self.epoch("other")
        different = ReportedOrigins(bytes.fromhex("A9 33 80 FE") + bytes(28))
        snapshot = overlay_snapshot.capture_snapshot(
            different, self.root / "different", machine=self.machine, origin=ORIGIN,
            regions=[(0x100000, 32)])
        with self.assertRaisesRegex(ValueError, "different RAM snapshot"):
            overlays.discover_origin_overlay(snapshot.path, current.path.parent / "origins",
                                             self.root / "bad", disc_ranges=[(2048, 4)], entries=[0x4000])
        self.assertNotEqual(current.sha256, "")
        other.revalidate()

    def test_cli_capture_binds_package_then_disc_selection_derives_graph(self):
        client = ReportedOrigins(bytes.fromhex("A9 2A 80 FE") + bytes(28))
        snapshot = overlay_snapshot.capture_snapshot(
            client, self.root / "snapshot", machine=self.machine, origin=ORIGIN,
            regions=[(0x100000, 32)])
        output = self.root / "cli-origins"
        arguments = ["capture-disc-origins", str(snapshot.path), str(self.root / "project.toml"),
                     "--build-dir", str(self.root / "build"), "--port", "1234",
                     "--journal", str(self.root / "journal.jsonl"), "--out", str(output)]
        with patch("pcerecomp.overlay_snapshot.package_binding", return_value=(self.machine, ORIGIN)) as binding:
            with patch("scripts.dev_client.DevClient", return_value=contextlib.nullcontext(client)) as tcp:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(arguments), 0)
        self.assertEqual(binding.call_count, 2)
        tcp.assert_called_once_with(1234, journal=self.root / "journal.jsonl")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["discover-origin-overlay", str(output),
                "--disc-range", "2048:4", "--entry", "0x4000", "--out", str(self.root / "cli-epoch")]), 0)
        epoch = overlays.load_overlay(self.root / "cli-epoch")
        self.assertEqual(epoch.report["options"]["code_ranges"], [[0x100000, 4]])
        self.assertEqual(len(epoch._instructions), 2)
        with self.assertRaises(SystemExit) as exited, contextlib.redirect_stdout(io.StringIO()):
            cli.main(["discover-origin-overlay", "--help"])
        self.assertEqual(exited.exception.code, 0)

    def test_consumer_and_managed_archive_retain_origin_artifacts(self):
        fixture = test_project.ConsumerProjectTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        config = tomllib.loads(fixture.text)
        payload = self.root / "payload.bin"
        payload.write_bytes(bytes.fromhex("80 FE"))
        disc = self.root / "disc.iso"
        disc.write_bytes(bytes(2048))
        config["payload"] = dict(path=str(payload), sha256=project.sha256(payload),
                                 physical_load=0x100000, pc=0x4000, mpr=MPR)
        machine = overlay_snapshot.machine_for(config, dict(payload=project.sha256(payload), disc=project.sha256(disc)))
        epoch = self.epoch(machine=machine)
        library = overlays.compose_overlays([epoch.path], self.root / "library")
        recipe = dict(schema=1, format=prepare.FORMAT, name="origin-consumer",
                      sdk=dict(revision="0" * 40, allow_revision_override=True),
                      module=dict(kind="overlay", path=str(library.path)), payload=config["payload"],
                      disc=dict(path=str(disc), sha256=project.sha256(disc)),
                      runtime=config["runtime"], limits=config["limits"])
        path = self.root / "prepare.toml"
        path.write_text(prepare._toml(recipe), encoding="utf-8")
        with patch.object(prepare, "TOOL_ROOT", fixture.tool):
            prepare.prepare_project(path, self.root / "prepared")
        checked = project.verify(self.root / "prepared/project.toml", allow_revision_override=True)
        files = incremental._module(checked)
        origin_files = [name for name in files if "/origins/" in name]
        self.assertTrue(origin_files)
        owned = self.root / "owned"
        owned.mkdir()
        incremental._sync(files, owned)
        binding = dict(file="declared-roots.json", sha256=library.sha256, members=[
            dict(file=name, sha256=project.sha256(source), size_bytes=source.stat().st_size)
            for name, source in sorted(files.items()) if name.startswith("epochs/")])
        incremental._check_declared_archive(owned, binding)
        modified = owned / origin_files[0]
        modified.write_bytes(modified.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            incremental._check_declared_archive(owned, binding)
