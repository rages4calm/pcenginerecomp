"""Explicit offline CD direct-copy declarations, never fabricated live snapshots.

Disc LBAs exclude the lead-in. Cooked offsets name MODE1 user bytes, not raw
file offsets or CHD storage frames. Alternative groups are admitted separately;
only disjoint loads within one group are composed. Each root declares one
instruction, without routine traversal, pointer guesses or invented retirements.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .capture import integer
from .declarations import (_ordinary, _path, _fields, _digest, _binding,
                           instruction_key, _sort_key, MAX_DECLARATION_BYTES, MAX_ROOTS,
                           _diagnostics)
from .isa import decode, physical
from .media import Chd, ChdReader, IsoReader
from .cue import Cue
from .snapshots import SnapshotStore
from .toc import Toc, MAX_DESCRIPTOR_BYTES, MAX_LEADOUT_LBA
from .overlay_snapshot import exact

FORMAT = 'pce-declared-cd-loads-1'
MAP_FORMAT = 'pce-cd-load-map-1'
COORDINATE = 'disc-lba-mode1-2048-v1'
POLICY = 'explicit-contiguous-byte-copy-v1'
MAP_NAME = 'cd-load-map.json'
MAX_GROUPS = 256
MAX_LOADS = 64
MAX_MEDIA_BYTES = 4 * 1024 * 1024 * 1024
MAX_TOTAL_LOAD_BYTES = 64 * 1024 * 1024
MEDIA_ASSETS = frozenset(('disc', 'toc', 'libchdr'))


def _identifier(value, label):
    if type(value) is not str or re.fullmatch('[a-z][a-z0-9_-]{0,63}', value) is None:
        raise ValueError(label + ' requires a portable lowercase identifier')
    return value


def _inputs(source_images):
    if (type(source_images) is not dict or not {'disc', 'toc'} <= source_images.keys()
            or source_images.keys() - MEDIA_ASSETS):
        raise ValueError('CD loads require explicit disc/toc and optional libchdr source_images')
    result = {name: _path(value) for name, value in source_images.items()}
    for name, path in result.items():
        _ordinary(path, MAX_DESCRIPTOR_BYTES if name == 'toc' else MAX_MEDIA_BYTES)
    return result


def is_cd_loads(path):
    path = _path(path)
    _ordinary(path, MAX_DECLARATION_BYTES)
    value = SnapshotStore().read_json(path, max_bytes=MAX_DECLARATION_BYTES).value
    return type(value) is dict and value.get('format') == FORMAT


def _map(document):
    _fields(document, {'format', 'schema', 'coordinate', 'policy', 'media', 'groups'}, 'CD load map')
    if (document['format'] != MAP_FORMAT or type(document['schema']) is not int or document['schema'] != 1
            or document['coordinate'] != COORDINATE or document['policy'] != POLICY):
        raise ValueError('Unsupported CD load map format/coordinate/copy policy')
    media = document['media']
    if type(media) is not dict:
        raise ValueError('CD load map requires explicit media identities')
    expected = {'format', 'image_sha256', 'toc_sha256'}
    if media.get('format') == 'chd':
        expected.add('libchdr_sha256')
    _fields(media, expected, 'CD load media')
    if media['format'] not in ('iso', 'cue', 'chd'):
        raise ValueError('CD load reader supports only ISO, CUE and CHD')
    for key in expected - {'format'}:
        _digest(media[key])
    groups = document['groups']
    if type(groups) is not list or not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError('CD load maps require one to 256 alternative groups')
    group_ids, total, roots = set(), 0, 0
    for group in groups:
        _fields(group, {'id', 'mpr', 'loads', 'roots'}, 'CD load group')
        name = _identifier(group['id'], 'CD group ID')
        if name in group_ids:
            raise ValueError('Duplicate CD load group ID')
        group_ids.add(name)
        if type(group['mpr']) is not list or len(group['mpr']) != 8:
            raise ValueError('CD load groups require all eight MPR bytes')
        for bank in group['mpr']:
            integer(bank, 255, 'CD load MPR')
        if type(group['roots']) is not list or not group['roots']:
            raise ValueError('CD groups require explicit instruction root PCs')
        for pc in group['roots']:
            integer(pc, 65535, 'CD root logical PC')
        if group['roots'] != sorted(set(group['roots'])):
            raise ValueError('CD root PCs must be sorted and unique within each group')
        roots += len(group['roots'])
        if roots > MAX_ROOTS:
            raise ValueError('CD root count exceeds its bound; no roots dropped')
        loads = group['loads']
        if type(loads) is not list or not 1 <= len(loads) <= MAX_LOADS:
            raise ValueError('CD groups require one to 64 disjoint loads')
        ids, disc_spans, ram_spans = set(), [], []
        for load in loads:
            _fields(load, {'id', 'lba', 'byte_offset', 'sectors', 'length', 'destination', 'sha256'}, 'CD direct-copy load')
            name = _identifier(load['id'], 'CD load ID')
            if name in ids:
                raise ValueError('Duplicate CD load ID within group')
            ids.add(name)
            lba = integer(load['lba'], MAX_LEADOUT_LBA - 1, 'CD load disc LBA')
            offset = integer(load['byte_offset'], 2047, 'CD load initial cooked-sector byte offset')
            sectors = integer(load['sectors'], 33, 'CD load sector count', 1)
            length = integer(load['length'], 65536, 'CD load byte length', 1)
            if sectors != (offset + length + 2047) // 2048:
                raise ValueError('CD sector count must exactly cover byte_offset plus copied length')
            if lba + sectors > MAX_LEADOUT_LBA:
                raise ValueError('CD load extent exceeds the supported disc coordinate')
            destination = integer(load['destination'], 0x1fffff, 'CD load physical RAM destination')
            if not (0x100000 <= destination < destination + length <= 0x110000
                    or 0x1f0000 <= destination < destination + length <= 0x1f2000):
                raise ValueError('CD load destination must be canonical standard CD RAM or WRAM; mirrors and other windows unsupported')
            _digest(load['sha256'])
            for spans, start, end, label in ((disc_spans, lba*2048+offset, lba*2048+offset+length, 'disc'),
                                            (ram_spans, destination, destination + length, 'RAM')):
                if any(start < old_end and old_start < end for old_start, old_end in spans):
                    raise ValueError('Overlapping ' + label + ' load definitions within one group')
                spans.append((start, end))
            total += length
            if total > MAX_TOTAL_LOAD_BYTES:
                raise ValueError('Combined CD load bytes exceed the offline bound')
    return document


def _media(document, images, store, stack):
    expected = document['media']
    fmt = expected['format']
    if images['disc'].suffix.lower() != '.' + fmt:
        raise ValueError('CD media suffix disagrees with explicit reader format')
    if (fmt == 'chd') != ('libchdr' in images):
        raise ValueError('CHD loads require an explicit libchdr; other readers forbid an unused decoder')
    bindings = {}
    for name, path in sorted(images.items()):
        expected_hash = expected['toc_sha256'] if name == 'toc' else expected.get('libchdr_sha256') if name == 'libchdr' else None
        bindings['source_image:' + name] = _binding(store.bind(path, expected_sha256=expected_hash))
    toc = Toc.from_image(images['disc'])
    if toc.image_sha256 != expected['image_sha256']:
        raise ValueError('CD complete media identity mismatch')
    with images['toc'].open('rb') as stream:
        toc_bytes = stream.read(MAX_DESCRIPTOR_BYTES + 1)
    toc_binding = bindings['source_image:toc']
    if (len(toc_bytes) != toc_binding['size_bytes']
            or hashlib.sha256(toc_bytes).hexdigest() != toc_binding['sha256']):
        raise ValueError('CD TOC changed after binding or exceeded its byte bound')
    if toc_bytes != toc.text().encode('ascii') or hashlib.sha256(toc_bytes).hexdigest() != expected['toc_sha256']:
        raise ValueError('CD TOC does not exactly describe the selected original media')
    if fmt == 'iso':
        reader = IsoReader(images['disc']).sector
    elif fmt == 'cue':
        cue = Cue(images['disc'])
        for name, path in cue.referenced_files.items():
            # Keep the original component spelling so this narrower source
            # contract can refuse symlink/reparse aliases at every use boundary.
            path = _path(images['disc'].parent / name)
            _ordinary(path, MAX_MEDIA_BYTES)
            bindings['disc_component:' + name] = _binding(store.bind(path))
        if cue.image_sha256() != expected['image_sha256']:
            raise ValueError('CUE closure changed during CD load admission')
        reader = cue.read
    else:
        disc = Chd(images['disc'])
        reader = stack.enter_context(ChdReader(disc, images['libchdr'])).lba
    numeric = dict(format=fmt, image_sha256=toc.image_sha256, toc_sha256=expected['toc_sha256'],
                   leadout_lba=toc.leadout_lba,
                   tracks=[dict(number=t.number, index1_lba=t.index1_lba, type=t.type) for t in toc.tracks],
                   components={key: {field: value[field] for field in ('sha256', 'size_bytes')}
                               for key, value in sorted(bindings.items())})
    return reader, numeric, bindings


def _derive(document, images, store):
    document = _map(document)
    union, roots, diagnostics, members, membership = {}, [], [], [], 0
    with ExitStack() as stack:
        reader, media, bindings = _media(document, images, store, stack)
        for group in document['groups']:
            buffers, loads = {}, []
            for load in group['loads']:
                chunks = []
                for lba in range(load['lba'], load['lba'] + load['sectors']):
                    sector = reader(lba)
                    if type(sector) is not bytes or len(sector) != 2048:
                        raise ValueError('CD load reader returned an incomplete cooked MODE1 sector')
                    chunks.append(sector)
                cooked = b''.join(chunks)
                data = cooked[load['byte_offset']:load['byte_offset'] + load['length']]
                if hashlib.sha256(data).hexdigest() != load['sha256']:
                    raise ValueError('Cooked CD direct-copy source digest mismatch')
                buffers[load['id']] = data
                loads.append(dict(load, sectors_sha256=hashlib.sha256(cooked).hexdigest()))
            def location(logical):
                address = physical(logical, group['mpr'])
                # Fetch identities still retain the original MPR/physical
                # address. Only lookup of mirrored WRAM storage is canonical.
                if 0x1f0000 <= address < 0x1f8000:
                    address = 0x1f0000 + (address & 8191)
                for load in group['loads']:
                    if load['destination'] <= address < load['destination'] + load['length']:
                        return load, address - load['destination']
                raise ValueError('CD instruction fetch is not wholly within its own authenticated load group')
            def read(logical):
                load, offset = location(logical)
                return buffers[load['id']][offset]
            group_roots = []
            for pc in group['roots']:
                instruction = decode(read, pc, tuple(group['mpr']))
                fetch = []
                for i in range(len(instruction.data)):
                    load, offset = location((pc + i) & 65535)
                    fetch.append(dict(load=load['id'], offset=offset, disc_byte_offset=load['lba'] * 2048 + load['byte_offset'] + offset))
                root = dict(group=group['id'], pc=pc, mpr=list(group['mpr']), fetch=fetch)
                roots.append(root)
                group_roots.append(root)
                report = instruction.report() | dict(mpr=tuple(group['mpr']))
                union[instruction_key(report)] = report
                membership += 1
                for row in _diagnostics(dict(pc=pc, mpr=group['mpr'], selector=0), report, 'standard'):
                    row.pop('selector')
                    diagnostics.append(dict(group=group['id'], **row))
                if (instruction.mode == 'blk' or instruction.mnemonic in ('STA', 'STX', 'STY', 'STZ', 'ASL', 'LSR', 'ROL', 'ROR', 'INC', 'DEC', 'TSB', 'TRB', 'PHA', 'PHP', 'PHX', 'PHY', 'JSR', 'BSR', 'BRK', 'ADC', 'AND', 'EOR', 'ORA')
                        or instruction.mnemonic.startswith(('RMB','SMB'))):
                    diagnostics.append(dict(group=group['id'], pc=pc, mpr=list(group['mpr']),
                        reason='RAM_write_effects_not_inferred', static_reachability='not_inferred'))
            members.append(dict(id=group['id'], mpr=group['mpr'], loads=loads, roots=group_roots))
    source = dict(format=FORMAT, coordinate=COORDINATE, copy_policy=POLICY, media=media,
        groups=[dict(id=g['id'], mpr=g['mpr'], loads=g['loads'], roots=len(g['roots'])) for g in members],
        memberships=membership, distinct_identities=len(union), static_reachability='not_inferred')
    return dict(media=media, groups=members), sorted(union.values(), key=_sort_key), roots, diagnostics, source, bindings


@dataclass(frozen=True)
class AdmittedCdLoads:
    path: Path
    sha256: str
    _instructions: list
    _roots: list
    _source_metadata: dict
    _artifact_bindings: dict
    _diagnostics: list
    _store: SnapshotStore
    _images: dict
    format: str = FORMAT

    @property
    def instructions(self): return deepcopy(self._instructions)
    @property
    def roots(self): return deepcopy(self._roots)
    @property
    def source_metadata(self): return deepcopy(self._source_metadata)
    @property
    def artifact_bindings(self): return deepcopy(self._artifact_bindings)
    @property
    def diagnostics(self): return deepcopy(self._diagnostics)
    @property
    def static_reachability(self): return 'not_inferred'

    def revalidate(self):
        _ordinary(self.path, MAX_DECLARATION_BYTES)
        _ordinary(self.path.parent / MAP_NAME, MAX_DECLARATION_BYTES)
        for path in self._images.values():
            _ordinary(path, MAX_MEDIA_BYTES)
        for name, value in self._artifact_bindings.items():
            if name.startswith('disc_component:'):
                _ordinary(value['path'], MAX_MEDIA_BYTES)
        self._store.revalidate()
        _ordinary(self.path, MAX_DECLARATION_BYTES)
        _ordinary(self.path.parent / MAP_NAME, MAX_DECLARATION_BYTES)
        for path in self._images.values():
            _ordinary(path, MAX_MEDIA_BYTES)
        for name, value in self._artifact_bindings.items():
            if name.startswith('disc_component:'):
                _ordinary(value['path'], MAX_MEDIA_BYTES)


def admit(path, source_images, store, snapshot):
    images = _inputs(source_images)
    document = snapshot.value
    _fields(document, {'format', 'schema', 'kind', 'execution_evidence', 'map', 'media', 'groups'}, 'CD load declarations')
    if (document['format'] != FORMAT or type(document['schema']) is not int or document['schema'] != 1
            or document['kind'] != 'declared' or document['execution_evidence'] is not False):
        raise ValueError('Unsupported CD load declaration format/schema/kind/evidence')
    reference = document['map']
    _fields(reference, {'path', 'sha256', 'size_bytes'}, 'CD load map binding')
    if reference['path'] != MAP_NAME:
        raise ValueError('CD load map requires its fixed portable member path')
    _digest(reference['sha256'])
    integer(reference['size_bytes'], MAX_DECLARATION_BYTES, 'CD load map byte length', 1)
    map_path = path.parent / MAP_NAME
    _ordinary(map_path, MAX_DECLARATION_BYTES)
    bound = store.read_json(map_path, expected_sha256=reference['sha256'], max_bytes=MAX_DECLARATION_BYTES)
    if bound.size_bytes != reference['size_bytes'] or bound.size_bytes + snapshot.size_bytes > MAX_DECLARATION_BYTES:
        raise ValueError('CD load numeric graph byte bound mismatch')
    derived, instructions, roots, diagnostics, source, bindings = _derive(bound.value, images, store)
    if not exact(document['media'], derived['media']) or not exact(document['groups'], derived['groups']):
        raise ValueError('CD load declaration graph disagrees with rederived original media/mapping')
    source['map_sha256'] = bound.sha256
    bindings.update(declarations=_binding(snapshot), **{'member:' + MAP_NAME: _binding(bound)})
    admitted = AdmittedCdLoads(path, snapshot.sha256, instructions, roots, source, bindings, diagnostics, store, images)
    admitted.revalidate()
    return admitted


def declare(map_path, output, *, disc, toc, libchdr=None):
    """Derive a closed declaration graph from an explicit numeric map and media."""
    from .discovery import _directory
    map_path, output = _path(map_path), _path(output)
    _ordinary(map_path, MAX_DECLARATION_BYTES)
    if output.exists() or output.is_symlink():
        raise ValueError('CD declaration output requires a new directory')
    _directory(output.parent)
    store = SnapshotStore()
    snapshot = store.read_json(map_path, max_bytes=MAX_DECLARATION_BYTES)
    images = _inputs(dict(disc=disc, toc=toc, **(dict(libchdr=libchdr) if libchdr is not None else {})))
    derived, _, _, _, _, _ = _derive(snapshot.value, images, store)
    document = dict(format=FORMAT, schema=1, kind='declared', execution_evidence=False,
        map=dict(path=MAP_NAME, sha256=snapshot.sha256, size_bytes=snapshot.size_bytes), **derived)
    # The original bounded JSON snapshot already retains the exact admitted
    # bytes. Do not reopen with an unbounded read after an earlier size check.
    raw = snapshot.raw
    encoded = (json.dumps(document, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if len(encoded) + len(raw) > MAX_DECLARATION_BYTES:
        raise ValueError('CD load numeric graph exceeds its byte bound')
    store.revalidate()
    output.mkdir()
    with (output / MAP_NAME).open('xb') as stream:
        stream.write(raw)
    with (output / 'roots.json').open('xb') as stream:
        stream.write(encoded)
    admitted = load(output / 'roots.json', images)
    store.revalidate()
    return admitted


def load(path, source_images):
    path = _path(path)
    _ordinary(path, MAX_DECLARATION_BYTES)
    store = SnapshotStore()
    snapshot = store.read_json(path, max_bytes=MAX_DECLARATION_BYTES)
    return admit(path, source_images, store, snapshot)


def copy_declarations(path, output, source_images):
    from .discovery import _directory
    admitted = load(path, source_images)
    output = _path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('CD declarations copy requires a new directory')
    _directory(output.parent)
    output.mkdir()
    for name, source, sha in (('roots.json', admitted.path, admitted.sha256),
                              (MAP_NAME, admitted.path.parent / MAP_NAME,
                               admitted.artifact_bindings['member:' + MAP_NAME]['sha256'])):
        copied_snapshot = admitted._store.read_json(source, expected_sha256=sha,
                                                    max_bytes=MAX_DECLARATION_BYTES)
        raw = copied_snapshot.raw
        with (output / name).open('xb') as stream:
            stream.write(raw)
    admitted.revalidate()
    copied = load(output / 'roots.json', source_images)
    if copied.sha256 != admitted.sha256 or copied.source_metadata != admitted.source_metadata:
        raise ValueError('CD declarations copy changed source closure')
    return copied
