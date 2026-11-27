"""Closed disc-origin reports bound to a previously captured paused RAM epoch."""
from copy import deepcopy
from bisect import bisect_right
from dataclasses import dataclass
import hashlib
from pathlib import Path

from .capture import integer
from .declarations import _path, _fields, _ordinary, _digest, _binding
from .discovery import _canonical, _directory
from .overlay_snapshot import load_snapshot, paused_pair, status, ram_ranges, exact
from .snapshots import SnapshotStore

FORMAT = "pce-paused-disc-origins-1"
MAX_JSON = 2 * 1024 * 1024
MAX_REPLY = 64 * 1024
MAX_GRAPH = 64 * 1024 * 1024
MAX_OFFSET = (1 << 32) * 2048 - 1
MAX_WIRE = (1 << 53) - 1


def _pages(snapshot):
    return [(start + offset, min(256, len(data) - offset))
            for start, data in snapshot.regions for offset in range(0, len(data), 256)]


def _reply(value, address, length):
    _fields(value, {"id", "ok", "disc_origin"}, "disc-origin reply")
    integer(value["id"], MAX_WIRE, "disc-origin response ID", 1)
    if value["ok"] is not True:
        raise ValueError("Disc-origin request did not succeed")
    report = value["disc_origin"]
    _fields(report, {"schema", "epoch", "address", "length", "reads", "writes", "offsets"}, "disc-origin report")
    if type(report["schema"]) is not int or report["schema"] != 1:
        raise ValueError("Unsupported disc-origin report schema")
    for key in ("epoch", "address", "length", "reads", "writes"):
        integer(report[key], MAX_WIRE, "disc-origin " + key, 1 if key == "epoch" else 0)
    if report["address"] != address or report["length"] != length:
        raise ValueError("Disc-origin response range differs")
    offsets = report["offsets"]
    if type(offsets) is not list or len(offsets) != length:
        raise ValueError("Disc-origin response extent differs")
    for offset in offsets:
        if offset is not None:
            integer(offset, MAX_OFFSET, "disc byte offset")
    return report


@dataclass(frozen=True)
class DiscOrigins:
    path: Path
    sha256: str
    snapshot: object
    offsets: tuple
    _document: dict
    _bindings: dict
    _store: SnapshotStore

    @property
    def document(self):
        return deepcopy(self._document)

    @property
    def artifact_bindings(self):
        return deepcopy(self._bindings)

    @property
    def bindings(self):
        return self.artifact_bindings

    def revalidate(self):
        _closed(self.path.parent, self._document["artifacts"])
        self.snapshot.revalidate()
        self._store.revalidate()
        _closed(self.path.parent, self._document["artifacts"])


def _closed(root, artifacts):
    _directory(root)
    if {path.name for path in root.iterdir()} != {"origins.json", "snapshot", *artifacts}:
        raise ValueError("Disc-origin artifact is not closed")
    _directory(root / "snapshot")
    _ordinary(root / "origins.json", MAX_JSON)
    for name in artifacts:
        _ordinary(root / name, MAX_JSON if name in ("before.json", "after.json") else MAX_REPLY)


def load_origins(path):
    path = _path(path)
    if path.is_dir():
        path = path / "origins.json"
    if path.name != "origins.json":
        raise ValueError("Disc-origin manifest must be origins.json")
    store = SnapshotStore()
    manifest = store.read_json(path, max_bytes=MAX_JSON)
    doc = manifest.value
    _fields(doc, {"format", "schema", "execution_evidence", "snapshot_sha256", "pages", "artifacts"}, "disc-origin manifest")
    if doc["format"] != FORMAT or type(doc["schema"]) is not int or doc["schema"] != 1 or doc["execution_evidence"] is not False:
        raise ValueError("Unsupported disc-origin artifact")
    _digest(doc["snapshot_sha256"])
    snapshot = load_snapshot(path.parent / "snapshot")
    if snapshot.sha256 != doc["snapshot_sha256"]:
        raise ValueError("Disc-origin snapshot binding differs")
    if "disc" not in snapshot.document["machine"]["assets"]:
        raise ValueError("Disc origins require an explicitly bound disc image")
    pages = _pages(snapshot)
    expected_pages = [dict(physical=address, length=length) for address, length in pages]
    if not exact(doc["pages"], expected_pages):
        raise ValueError("Disc-origin pages differ from captured RAM")
    names = {"before.json", "after.json"} | {
        f"origin-{kind}-{index:04d}.json" for index in range(len(pages)) for kind in ("read", "verify")
    }
    artifacts = doc["artifacts"]
    if type(artifacts) is not dict or set(artifacts) != names:
        raise ValueError("Disc-origin artifact namespace differs")
    _closed(path.parent, artifacts)
    bindings = {"origins.json": _binding(manifest)}
    objects = {}
    total = manifest.size_bytes
    for name, row in artifacts.items():
        _fields(row, {"sha256", "size_bytes"}, "disc-origin artifact binding")
        _digest(row["sha256"])
        limit = MAX_JSON if name in ("before.json", "after.json") else MAX_REPLY
        integer(row["size_bytes"], limit, "disc-origin artifact size", 1)
        bound = store.read_json(path.parent / name, expected_sha256=row["sha256"], max_bytes=limit)
        if bound.size_bytes != row["size_bytes"]:
            raise ValueError("Disc-origin artifact size differs")
        bindings[name] = _binding(bound)
        objects[name] = bound.value
        total += bound.size_bytes
    for name, row in snapshot.artifact_bindings.items():
        bound = store.bind(path.parent / "snapshot" / name, expected_sha256=row["sha256"])
        bindings["snapshot/" + name] = _binding(bound)
        total += bound.size_bytes
    if total > MAX_GRAPH:
        raise ValueError("Disc-origin graph exceeds 64 MiB")
    before, after = objects["before.json"], objects["after.json"]
    paused_pair(before, after)
    paused_pair(snapshot.before, before)
    identity = before["id"]
    shared_epoch = None
    reports = []
    for kind in ("read", "verify"):
        for index, (address, length) in enumerate(pages):
            response = objects[f"origin-{kind}-{index:04d}.json"]
            report = _reply(response, address, length)
            identity += 1
            if response["id"] != identity:
                raise ValueError("Disc-origin response IDs are not contiguous")
            epoch = (report["epoch"], report["reads"], report["writes"])
            if shared_epoch is None:
                shared_epoch = epoch
            if epoch != shared_epoch:
                raise ValueError("Disc-origin epoch or counters changed while paused")
            if kind == "read":
                reports.append(report)
            elif not exact(report, reports[index]):
                raise ValueError("Disc-origin reports changed between paused reads")
    if after["id"] != identity + 1:
        raise ValueError("Disc-origin final status ID differs")
    offsets = []
    cursor = 0
    for address, data in snapshot.regions:
        values = []
        for _ in range(0, len(data), 256):
            values.extend(reports[cursor]["offsets"])
            cursor += 1
        offsets.append((address, tuple(values)))
    result = DiscOrigins(path, manifest.sha256, snapshot, tuple(offsets), doc, bindings, store)
    result.revalidate()
    return result


def capture_origins(client, snapshot_path, output):
    """Capture repeated host diagnostics while the original RAM epoch stays paused."""
    snapshot = load_snapshot(snapshot_path)
    if "disc" not in snapshot.document["machine"]["assets"]:
        raise ValueError("Disc origins require an explicitly bound disc image")
    output = _path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("Disc-origin capture requires a new directory")
    if output.is_relative_to(snapshot.path.parent):
        raise ValueError("Disc-origin capture cannot modify its source snapshot")
    _directory(output.parent)
    before = client.call("status")
    status(before)
    paused_pair(snapshot.before, before)
    files = {"before.json": _canonical(before, MAX_JSON)}
    pages = _pages(snapshot)
    reports = []
    shared_epoch = None
    for kind in ("read", "verify"):
        for index, (address, length) in enumerate(pages):
            response = client.call("disc_origin", address=address, length=length)
            report = _reply(response, address, length)
            epoch = (report["epoch"], report["reads"], report["writes"])
            if shared_epoch is None:
                shared_epoch = epoch
            if epoch != shared_epoch:
                raise ValueError("Disc-origin epoch or counters changed while paused")
            if kind == "read":
                reports.append(report)
            elif not exact(report, reports[index]):
                raise ValueError("Disc-origin reports changed between paused reads")
            files[f"origin-{kind}-{index:04d}.json"] = _canonical(response, MAX_REPLY)
    after = client.call("status")
    paused_pair(before, after)
    files["after.json"] = _canonical(after, MAX_JSON)
    snapshot.revalidate()
    doc = dict(format=FORMAT, schema=1, execution_evidence=False, snapshot_sha256=snapshot.sha256,
               pages=[dict(physical=address, length=length) for address, length in pages],
               artifacts={name: dict(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                          for name, raw in files.items()})
    manifest = _canonical(doc, MAX_JSON)
    if len(manifest) + sum(map(len, files.values())) + sum(row["size_bytes"] for row in snapshot.artifact_bindings.values()) > MAX_GRAPH:
        raise ValueError("Disc-origin graph exceeds 64 MiB")
    output.mkdir()
    (output / "snapshot").mkdir()
    for name, row in snapshot.artifact_bindings.items():
        source = snapshot.path.parent / name
        with source.open("rb") as stream:
            raw = stream.read(row["size_bytes"] + 1)
        if len(raw) != row["size_bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Source RAM snapshot changed during copy")
        with (output / "snapshot" / name).open("xb") as stream:
            stream.write(raw)
    snapshot.revalidate()
    for name, raw in files.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
    with (output / "origins.json").open("xb") as stream:
        stream.write(manifest)
    return load_origins(output)


def select_ranges(admitted, disc_ranges):
    """Derive allowed RAM spans solely from reported offsets inside explicit disc ranges."""
    if type(disc_ranges) not in (list, tuple) or not 1 <= len(disc_ranges) <= 256:
        raise ValueError("Select one to 256 explicit disc byte ranges")
    spans = []
    for row in disc_ranges:
        if type(row) not in (list, tuple) or len(row) != 2:
            raise ValueError("Disc byte range requires offset and length")
        start = integer(row[0], MAX_OFFSET, "disc byte range start")
        length = integer(row[1], MAX_OFFSET - start + 1, "disc byte range length", 1)
        spans.append((start, length))
    if spans != sorted(spans) or any(a + n > b for (a, n), (b, _) in zip(spans, spans[1:])):
        raise ValueError("Disc byte ranges must be sorted and disjoint")
    starts = [start for start, _ in spans]
    result = []
    for start, offsets in admitted.offsets:
        for index, offset in enumerate(offsets):
            if offset is None:
                continue
            match = bisect_right(starts, offset) - 1
            if match < 0 or offset >= spans[match][0] + spans[match][1]:
                continue
            address = start + index
            if result and result[-1][0] + result[-1][1] == address and result[-1][1] < 65536:
                result[-1] = (result[-1][0], result[-1][1] + 1)
            else:
                result.append((address, 1))
            if len(result) > 32:
                raise ValueError("Selected disc origins fragment into more than 32 RAM ranges")
    if not result:
        raise ValueError("Selected disc ranges have no observed RAM origins")
    admitted.revalidate()
    return ram_ranges(admitted.snapshot.document["machine"], result)
