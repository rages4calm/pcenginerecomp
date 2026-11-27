"""Authored reports exercise closed disc ancestry artifacts and range selection."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pcerecomp import origin_overlay as origins, overlay_snapshot as snapshots
from tests.test_overlays import ReportedRam, ORIGIN, machine


class ReportedOrigins(ReportedRam):
    """Synthetic protocol fixture with explicit per-byte disc ancestry."""
    def __init__(self, data, *, offsets=None, **kwargs):
        super().__init__(data, **kwargs)
        self.offsets = list(range(2048, 2048 + len(data))) if offsets is None else list(offsets)
        self.epoch = 1
        self.origin_calls = 0
        self.change = None

    def call(self, command, **args):
        if command != "disc_origin":
            return super().call(command, **args)
        self.identity += 1
        self.calls.append((command, args))
        self.origin_calls += 1
        offset = args["address"] - self.start
        report = dict(schema=1, epoch=self.epoch, address=args["address"], length=args["length"],
                      reads=4000, writes=2000, offsets=self.offsets[offset:offset + args["length"]])
        if self.change:
            self.change(self, report)
        return dict(id=self.identity, ok=True, disc_origin=report)


def disc_machine():
    result = machine()
    result["assets"]["disc"] = "b" * 64
    return result


def make_snapshot(root, *, data=None, offsets=None):
    data = data or bytes.fromhex("A9 2A 8D 00 20 A2 03 E8 80 FE") + bytes(22)
    client = ReportedOrigins(data, offsets=offsets)
    snapshot = snapshots.capture_snapshot(client, root / "snapshot", machine=disc_machine(),
                                          origin=ORIGIN, regions=[(client.start, len(data))])
    return client, snapshot


class OriginOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def capture(self, *, data=None, offsets=None):
        client, snapshot = make_snapshot(self.root, data=data, offsets=offsets)
        admitted = origins.capture_origins(client, snapshot.path, self.root / "origins")
        return client, snapshot, admitted

    def rewrite_binding(self, admitted, name, mutate):
        path = admitted.path.parent / name
        value = json.loads(path.read_bytes())
        mutate(value)
        raw = json.dumps(value).encode("utf-8")
        path.write_bytes(raw)
        manifest = json.loads(admitted.path.read_bytes())
        manifest["artifacts"][name] = dict(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        admitted.path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_original_replies_snapshot_and_offsets_survive_loading(self):
        client, snapshot, admitted = self.capture()
        self.assertEqual(admitted.snapshot.sha256, snapshot.sha256)
        self.assertFalse(admitted.document["execution_evidence"])
        self.assertEqual(admitted.offsets, ((0x100000, tuple(range(2048, 2080))),))
        self.assertEqual(origins.select_ranges(admitted, [(2048, 10), (4096, 10)]), [(0x100000, 10)])
        self.assertIn("snapshot/ram-000.bin", admitted.artifact_bindings)
        self.assertEqual([name for name, _ in client.calls[-4:]],
                         ["status", "disc_origin", "disc_origin", "status"])
        admitted.revalidate()

    def test_unknown_origins_are_excluded_from_selected_spans(self):
        _, _, admitted = self.capture(offsets=[2048, 2049, None, 2051, None] + [None] * 27)
        self.assertEqual(origins.select_ranges(admitted, [(2048, 32)]),
                         [(0x100000, 2), (0x100003, 1)])
        with self.assertRaisesRegex(ValueError, "no observed"):
            origins.select_ranges(admitted, [(9000, 2)])

    def test_unbound_disc_and_changed_paused_state_refuse_capture(self):
        client = ReportedOrigins(bytes(32))
        snapshot = snapshots.capture_snapshot(client, self.root / "no-disc",
                                              machine=machine(), origin=ORIGIN, regions=[(client.start, 32)])
        with self.assertRaisesRegex(ValueError, "bound disc"):
            origins.capture_origins(client, snapshot.path, self.root / "refused")
        client, snapshot = make_snapshot(self.root)
        client.pc += 1
        with self.assertRaisesRegex(ValueError, "state changed"):
            origins.capture_origins(client, snapshot.path, self.root / "changed")
        self.assertFalse((self.root / "changed").exists())

    def test_report_epoch_counter_and_offset_drift_refuse_capture(self):
        for field, value in (("epoch", 2), ("reads", 4001), ("writes", 2001),
                             ("offsets", [None] * 32)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                client, snapshot = make_snapshot(root)
                def change(peer, report):
                    if peer.origin_calls == 2:
                        report[field] = value
                client.change = change
                with self.assertRaises(ValueError):
                    origins.capture_origins(client, snapshot.path, root / "origin")
                self.assertFalse((root / "origin").exists())

    def test_bool_offsets_and_counter_types_refuse_capture(self):
        for field, value in (("schema", True), ("epoch", True), ("reads", False),
                             ("length", True), ("offsets", [True] + [None] * 31),
                             ("offsets", [-1] + [None] * 31)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                client, snapshot = make_snapshot(root)
                client.change = lambda peer, report: report.update({field: value})
                with self.assertRaises(ValueError):
                    origins.capture_origins(client, snapshot.path, root / "origin")

    def test_tampering_original_report_or_embedded_ram_revokes_admission(self):
        for name in ("origin-read-0000.json", "snapshot/ram-000.bin", "origins.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                client, snapshot = make_snapshot(root)
                admitted = origins.capture_origins(client, snapshot.path, root / "origin")
                path = admitted.path.parent / name
                path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaises(ValueError):
                    admitted.revalidate()
                if name == "origins.json":
                    self.assertNotEqual(origins.load_origins(admitted.path).sha256, admitted.sha256)
                else:
                    with self.assertRaises(ValueError):
                        origins.load_origins(admitted.path)

    def test_updated_binding_cannot_hide_disagreeing_repeat_or_response_id(self):
        for mutate in (lambda row: row["disc_origin"]["offsets"].__setitem__(0, None),
                       lambda row: row["disc_origin"].update(epoch=2),
                       lambda row: row.update(id=999)):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                client, snapshot = make_snapshot(root)
                admitted = origins.capture_origins(client, snapshot.path, root / "origin")
                self.rewrite_binding(admitted, "origin-verify-0000.json", mutate)
                with self.assertRaises(ValueError):
                    origins.load_origins(admitted.path)

    def test_ranges_are_strict_and_fragmentation_has_explicit_limit(self):
        _, _, admitted = self.capture()
        for ranges in ([], [(True, 1)], [(0, False)], [(-1, 2)],
                       [(10, 3), (11, 2)], [(10, 1), (0, 1)], [(origins.MAX_OFFSET, 2)]):
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                origins.select_ranges(admitted, ranges)
        with tempfile.TemporaryDirectory() as temporary:
            client, snapshot = make_snapshot(Path(temporary), data=bytes(80),
                                             offsets=[2048 if i % 2 == 0 else None for i in range(80)])
            sparse = origins.capture_origins(client, snapshot.path, Path(temporary) / "origins")
            with self.assertRaisesRegex(ValueError, "more than 32"):
                origins.select_ranges(sparse, [(2048, 1)])

    def test_large_regions_use_bounded_repeated_pages(self):
        _, _, admitted = self.capture(data=bytes(512))
        self.assertEqual(len(admitted.document["pages"]), 2)
        self.assertEqual(origins.select_ranges(admitted, [(2048, 512)]), [(0x100000, 512)])
        self.assertEqual(admitted.offsets[0][1][-1], 2559)
