"""Explicit, single-epoch resident RAM sources for authenticated CD composition.

Selecting resident bytes is a consumer assertion about residency, not proof of
simultaneous execution with a later disc load. Bytes stay mutable and guarded.
"""
from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path

from .capture import integer
from .declarations import _binding, _fields, _ordinary, _path
from .discovery import _canonical, _directory
from .overlay_snapshot import (MAX_JSON, MAX_RAM, canonical, exact, load_snapshot,
                               ram_ranges, validate_machine)
from .snapshots import SnapshotStore

FORMAT = 'pce-resident-source-1'
POLICY = 'explicit-snapshot-residency-v1'
NAME = 'resident.json'


def _new_directory(path):
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise ValueError('Resident output requires a new directory')
    _directory(path.parent)
    return path


def _machine(machine):
    validate_machine(machine)
    if machine['boot']['mode'] != 'system-card-reset' or 'disc' not in machine['assets']:
        raise ValueError('Resident CD sources require a System Card snapshot bound to original disc media')


def _derive(snapshot, ranges):
    machine = snapshot.document['machine']
    _machine(machine)
    spans = ram_ranges(machine, ranges)
    for start, length in spans:
        end = start + length
        if not (0x100000 <= start < end <= 0x110000 or 0x1F0000 <= start < end <= 0x1F2000):
            raise ValueError('Resident composition supports canonical standard CD RAM and WRAM only')
    starts = [start for start, _ in snapshot.regions]
    segments = []
    for start, length in spans:
        cursor, chunks, pieces = start, [], []
        while cursor < start + length:
            region = bisect_right(starts, cursor) - 1
            if region < 0:
                raise ValueError('Resident range is not wholly in the original captured epoch')
            base, raw = snapshot.regions[region]
            offset = cursor - base
            if offset >= len(raw):
                raise ValueError('Resident range crosses an uncaptured source gap')
            size = min(len(raw)-offset, start+length-cursor)
            chunks.append(raw[offset:offset+size])
            pieces.append(dict(region=region, offset=offset, length=size))
            cursor += size
        raw = b''.join(chunks)
        segments.append(dict(physical=start, length=length,
                             sha256=hashlib.sha256(raw).hexdigest(), pieces=pieces))
    document = dict(format=FORMAT, schema=1, policy=POLICY, execution_evidence=False,
                    snapshot_sha256=snapshot.sha256, machine=deepcopy(machine),
                    ranges=[list(row) for row in spans], segments=segments)
    return document, tuple(spans)


@dataclass(frozen=True)
class ResidentSource:
    path: Path
    sha256: str
    snapshot: object
    _document: dict
    _ranges: tuple
    _bindings: dict
    _store: object = None

    @property
    def document(self): return deepcopy(self._document)
    @property
    def source_metadata(self): return self.document
    @property
    def machine(self): return deepcopy(self._document['machine'])
    @property
    def ranges(self): return self._ranges
    @property
    def regions(self): return self.snapshot.regions
    @property
    def artifact_bindings(self): return deepcopy(self._bindings)

    def contains(self, physical):
        if type(physical) is not int or not 0 <= physical <= 0x1FFFFF:
            return False
        address = canonical(physical)
        return any(start <= address < start+length for start, length in self._ranges)

    def read_byte(self, physical):
        integer(physical, 0x1FFFFF, 'resident physical fetch')
        address = canonical(physical)
        for index, segment in enumerate(self._document['segments']):
            if not segment['physical'] <= address < segment['physical'] + segment['length']:
                continue
            for piece in segment['pieces']:
                region, offset = piece['region'], piece['offset']
                base, raw = self.snapshot.regions[region]
                if base+offset <= address < base+offset+piece['length']:
                    location = address-base
                    return raw[location], dict(snapshot_sha256=self.snapshot.sha256,
                        region=region, offset=location, segment=index)
            raise ValueError('Resident source segment disagrees with its source pieces')
        raise ValueError('Resident fetch is outside explicitly selected source bytes')

    def authenticate_cd_media(self, media):
        if type(media) is not dict:
            raise ValueError('Resident composition requires authenticated CD media metadata')
        assets = self._document['machine']['assets']
        if assets['disc'] != media.get('image_sha256'):
            raise ValueError('Resident snapshot belongs to different complete CD media')
        if 'toc' in assets and assets['toc'] != media.get('toc_sha256'):
            raise ValueError('Resident snapshot belongs to a different CD TOC')
        self.revalidate()

    def compatible_machine(self, expected_machine):
        validate_machine(expected_machine)
        if not exact(self._document['machine'], expected_machine):
            raise ValueError('Resident source boot, profile or asset machine contract differs')
        self.revalidate()

    def reject_overlap(self, ranges):
        if type(ranges) not in (list, tuple):
            raise ValueError('CD overlay ranges require explicit physical start/length pairs')
        for row in ranges:
            if type(row) not in (list, tuple) or len(row) != 2:
                raise ValueError('CD overlay range requires physical start and length')
            start = integer(row[0], 0x1FFFFF, 'CD overlay physical start')
            length = integer(row[1], min(65536, 0x200000-start), 'CD overlay byte length', 1)
            for base, size in self._ranges:
                if start < base+size and base < start+length:
                    raise ValueError('CD overlay load overlaps explicit resident source bytes')

    def revalidate(self):
        self.snapshot.revalidate()
        if self._store is not None:
            _closed(self.path.parent)
            self._store.revalidate()
        _machine(self._document['machine'])
        if not exact(self._document['machine'], self.snapshot.document['machine']):
            raise ValueError('Resident machine changed after source admission')


def admit(snapshot_path, ranges):
    """Select nonempty explicit resident spans from exactly one closed snapshot."""
    snapshot = load_snapshot(snapshot_path)
    document, spans = _derive(snapshot, ranges)
    raw = _canonical(document, MAX_JSON)
    bindings = {'snapshot/'+name: row for name, row in snapshot.artifact_bindings.items()}
    result = ResidentSource(snapshot.path, hashlib.sha256(raw).hexdigest(), snapshot,
                            document, spans, bindings)
    result.revalidate()
    return result


def _closed(root):
    _directory(root)
    if {path.name for path in root.iterdir()} != {NAME, 'snapshot'}:
        raise ValueError('Resident source bundle is not closed')
    _ordinary(root/NAME, MAX_JSON)
    _directory(root/'snapshot')


def load_resident(path):
    path = _path(path)
    if path.is_dir(): path = path/NAME
    if path.name != NAME:
        raise ValueError('Resident source manifest must be resident.json')
    _closed(path.parent)
    store = SnapshotStore(); bound = store.read_json(path, max_bytes=MAX_JSON)
    document = bound.value
    _fields(document, {'format','schema','policy','execution_evidence','snapshot_sha256',
                       'machine','ranges','segments'}, 'resident source')
    if (document['format'] != FORMAT or type(document['schema']) is not int or document['schema'] != 1
            or document['policy'] != POLICY or document['execution_evidence'] is not False):
        raise ValueError('Unsupported resident source policy')
    snapshot = load_snapshot(path.parent/'snapshot')
    expected, spans = _derive(snapshot, document['ranges'])
    if not exact(document, expected):
        raise ValueError('Resident source metadata disagrees with original snapshot rederivation')
    bindings = {NAME: _binding(bound)}
    for name, row in snapshot.artifact_bindings.items():
        source = store.bind(path.parent/'snapshot'/name, expected_sha256=row['sha256'])
        if source.size_bytes != row['size_bytes']:
            raise ValueError('Resident copied snapshot size differs')
        bindings['snapshot/'+name] = _binding(source)
    result = ResidentSource(path, bound.sha256, snapshot, document, spans, bindings, store)
    result.revalidate()
    return result


def copy_resident(source, output):
    """Copy the exact closed snapshot; never rebase or merge its provenance."""
    if not isinstance(source, ResidentSource):
        raise ValueError('Resident copy requires an admitted source')
    output = _new_directory(output)
    if output.is_relative_to(source.snapshot.path.parent):
        raise ValueError('Resident output cannot modify its source snapshot')
    if source._store is not None and output.is_relative_to(source.path.parent):
        raise ValueError('Resident output cannot modify its admitted bundle')
    source.revalidate()
    document = source.document
    raw = _canonical(document, MAX_JSON)
    output.mkdir(); (output/'snapshot').mkdir()
    for name, binding in source.snapshot.artifact_bindings.items():
        path = source.snapshot.path.parent/name
        _ordinary(path, MAX_RAM if name.endswith('.bin') else MAX_JSON)
        with path.open('rb') as stream: data = stream.read(binding['size_bytes']+1)
        if len(data) != binding['size_bytes'] or hashlib.sha256(data).hexdigest() != binding['sha256']:
            raise ValueError('Resident snapshot changed while copying')
        with (output/'snapshot'/name).open('xb') as stream: stream.write(data)
    source.revalidate()
    with (output/NAME).open('xb') as stream: stream.write(raw)
    return load_resident(output)


def declare_resident(snapshot_path, output, *, ranges):
    return copy_resident(admit(snapshot_path, ranges), output)
