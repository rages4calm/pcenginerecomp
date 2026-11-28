"""Explicit offline CD direct-copy declarations, never fabricated live snapshots.

Disc LBAs exclude the lead-in. Cooked offsets name MODE1 user bytes, not raw
file offsets or CHD storage frames. Alternative groups are admitted separately;
only disjoint loads within one group are composed. An explicit single-epoch
resident source may supply additional disjoint RAM bytes. Legacy roots declare one
instruction. Explicit opt-in analysis traverses bounded candidates with symbolic
call frames and conservative write barriers, never invented retirements.
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
ANALYSIS_POLICY = 'bounded-ram-cd-candidates-v1'
FAR_CALL_POLICY = 'bounded-ram-cd-stack-values-v1'
MAP_NAME = 'cd-load-map.json'
MAX_GROUPS = 256
MAX_LOADS = 64
MAX_MEDIA_BYTES = 4 * 1024 * 1024 * 1024
MAX_TOTAL_LOAD_BYTES = 64 * 1024 * 1024
MEDIA_ASSETS = frozenset(('disc', 'toc', 'libchdr'))


def _resident_bytes(resident):
    """Count the entire copied graph, including an as-yet unpublished manifest."""
    if resident is None:
        return 0
    bindings = resident.artifact_bindings
    size = sum(row['size_bytes'] for row in bindings.values())
    if 'resident.json' not in bindings:
        from .discovery import _canonical
        size += len(_canonical(resident.document, MAX_DECLARATION_BYTES))
    return size


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


def _canonical(address):
    return 0x1f0000 + (address & 8191) if 0x1f0000 <= address < 0x1f8000 else address


def _ram(address):
    return 0x100000 <= address < 0x110000 or 0x1f0000 <= address < 0x1f8000


def _analysis_options(analysis_policy, call_depth_limit, data_ranges, instruction_limit, context_limit):
    integer(instruction_limit, 100000, 'CD analysis instruction limit', 1)
    integer(context_limit, 4096, 'CD analysis context limit', 1)
    if analysis_policy is None:
        if call_depth_limit is not None or data_ranges is not None or instruction_limit != 10000 or context_limit != 256:
            raise ValueError('CD traversal options require an explicit analysis policy')
        return None
    if analysis_policy not in (ANALYSIS_POLICY, FAR_CALL_POLICY):
        raise ValueError('Unsupported CD analysis policy')
    depth = 16 if call_depth_limit is None else integer(call_depth_limit, 64, 'CD call depth', 1)
    spans = []
    if data_ranges is not None:
        if type(data_ranges) not in (list, tuple) or len(data_ranges) > 4096:
            raise ValueError('CD analysis data ranges exceed their bound')
        for row in data_ranges:
            if type(row) not in (list, tuple) or len(row) != 2:
                raise ValueError('CD data ranges require start/length pairs')
            start = integer(row[0], 0x1fffff, 'CD data range start')
            length = integer(row[1], 65536, 'CD data range length', 1)
            end = start + length
            if not (0x100000 <= start < end <= 0x110000 or 0x1f0000 <= start < end <= 0x1f2000):
                raise ValueError('CD data ranges require canonical standard CD RAM or WRAM')
            if any(start < old + size and old < end for old, size in spans):
                raise ValueError('Overlapping CD data ranges')
            spans.append([start, length])
    return dict(policy=analysis_policy, call_depth_limit=depth, data_ranges=sorted(spans),
                instruction_limit=instruction_limit, context_limit=context_limit)


def _admit_analysis(value):
    _fields(value, {'policy', 'call_depth_limit', 'data_ranges', 'instruction_limit', 'context_limit'}, 'CD analysis options')
    result = _analysis_options(value['policy'], value['call_depth_limit'], value['data_ranges'],
                               value['instruction_limit'], value['context_limit'])
    if result is None or not exact(value, result):
        raise ValueError('CD analysis options must be canonical')
    return result


def _derive(document, images, store, analysis=None, resident=None):
    document = _map(document)
    if analysis is not None:
        analysis = _admit_analysis(analysis)
    if resident is not None and analysis is None:
        raise ValueError('Resident composition requires an explicit bounded analysis policy')
    union, roots, diagnostics, members, membership = {}, [], [], [], 0
    with ExitStack() as stack:
        reader, media, bindings = _media(document, images, store, stack)
        if resident is not None:
            resident.authenticate_cd_media(media)
        for group in document['groups']:
            buffers, loads = {}, []
            for load in group['loads']:
                if resident is not None and any(load['destination'] < start + length and start < load['destination'] + load['length']
                                                for start, length in resident.ranges):
                    raise ValueError('CD loads may not overwrite any declared resident source byte')
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
            def location(logical, mapping=None):
                address = physical(logical, group['mpr'] if mapping is None else mapping)
                # Fetch identities still retain the original MPR/physical
                # address. Only lookup of mirrored WRAM storage is canonical.
                if 0x1f0000 <= address < 0x1f8000:
                    address = 0x1f0000 + (address & 8191)
                for load in group['loads']:
                    if load['destination'] <= address < load['destination'] + load['length']:
                        return load, address - load['destination']
                if resident is not None:
                    value, provenance = resident.read_byte(address)
                    return None, (value, provenance)
                raise ValueError('CD instruction fetch is not wholly within its own authenticated load group')
            def read(logical):
                load, offset = location(logical)
                return buffers[load['id']][offset]
            group_roots = []
            if analysis is not None:
                from .ram_cd_analysis import derive
                def permitted(address):
                    address = _canonical(address)
                    return ((any(load['destination'] <= address < load['destination'] + load['length'] for load in group['loads'])
                            or resident is not None and any(start <= address < start + length for start, length in resident.ranges))
                            and not any(start <= address < start + length for start, length in analysis['data_ranges']))
                def fetch_instruction(pc, mapping):
                    def read_bound(logical):
                        address = physical(logical, mapping)
                        if not permitted(address):
                            raise ValueError('CD instruction fetch is outside authenticated executable load bytes')
                        load, offset = location(logical, mapping)
                        return offset[0] if load is None else buffers[load['id']][offset]
                    instruction = decode(read_bound, pc, mapping)
                    provenance = []
                    for i in range(len(instruction.data)):
                        load, offset = location((pc+i)&65535, mapping)
                        provenance.append(dict(resident=offset[1]) if load is None else dict(load=load['id'], offset=offset,
                            disc_byte_offset=load['lba']*2048+load['byte_offset']+offset))
                    return instruction, provenance
                graph, instructions, derived_roots = derive(group['roots'], tuple(group['mpr']),
                    fetch=fetch_instruction, is_code=permitted, is_ram=_ram, canonical=_canonical,
                    instruction_limit=analysis['instruction_limit'], context_limit=analysis['context_limit'],
                    call_depth_limit=analysis['call_depth_limit'],
                    **(dict(far_calls=True) if analysis['policy']==FAR_CALL_POLICY else {}))
                for row in instructions:
                    union[instruction_key(row)] = row
                membership += len(instructions)
                for row in derived_roots:
                    root = dict(group=group['id'], **row)
                    roots.append(root)
                    group_roots.append(root)
                diagnostics.extend(dict(group=group['id'], **row) for row in graph['unresolved'])
                members.append(dict(id=group['id'], mpr=group['mpr'], loads=loads, roots=group_roots, analysis=graph))
                continue
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
    if analysis is not None:
        source.update(analysis=analysis, static_reachability='candidates_only', routine_closure=False)
    if resident is not None:
        source['resident'] = resident.document
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
    _resident: object = None
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
    def static_reachability(self): return self._source_metadata['static_reachability']

    def revalidate(self):
        if self._resident is not None:
            self._resident.revalidate()
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
        if self._resident is not None:
            self._resident.revalidate()


def admit(path, source_images, store, snapshot):
    images = _inputs(source_images)
    document = snapshot.value
    expected = {'format', 'schema', 'kind', 'execution_evidence', 'map', 'media', 'groups'}
    if type(document) is dict and 'analysis' in document:
        expected.add('analysis')
    if type(document) is dict and 'resident' in document:
        expected.add('resident')
    _fields(document, expected, 'CD load declarations')
    analysis = _admit_analysis(document['analysis']) if 'analysis' in document else None
    resident = None
    if 'resident' in document:
        from .resident_sources import load_resident
        if analysis is None:
            raise ValueError('Resident composition requires recorded bounded analysis')
        resident = load_resident(path.parent / 'resident')
        if not exact(document['resident'], resident.document):
            raise ValueError('Resident CD source descriptor differs from its authenticated snapshot graph')
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
    if bound.size_bytes != reference['size_bytes'] or bound.size_bytes + snapshot.size_bytes + _resident_bytes(resident) > MAX_DECLARATION_BYTES:
        raise ValueError('CD load numeric graph byte bound mismatch')
    derived, instructions, roots, diagnostics, source, bindings = (_derive(bound.value, images, store, analysis) if resident is None
                                                                 else _derive(bound.value, images, store, analysis, resident))
    if not exact(document['media'], derived['media']) or not exact(document['groups'], derived['groups']):
        raise ValueError('CD load declaration graph disagrees with rederived original media/mapping')
    source['map_sha256'] = bound.sha256
    bindings.update(declarations=_binding(snapshot), **{'member:' + MAP_NAME: _binding(bound)})
    if resident is not None:
        for name, row in resident.artifact_bindings.items():
            bindings['member:resident/' + name] = _binding(store.bind(row['path'], expected_sha256=row['sha256']))
    admitted = AdmittedCdLoads(path, snapshot.sha256, instructions, roots, source, bindings, diagnostics, store, images, resident)
    admitted.revalidate()
    return admitted


def declare(map_path, output, *, disc, toc, libchdr=None, analysis_policy=None, call_depth_limit=None,
            data_ranges=None, instruction_limit=10000, context_limit=256, resident_snapshot=None, resident_ranges=None):
    """Derive a closed declaration graph from an explicit numeric map and media.

    The optional analysis policy binds all traversal options into the declaration.
    It proves neither execution nor closure of routines or indirect control flow.
    Data exclusions may cover canonical RAM outside some alternative groups. They
    supply no bytes or constants: fetch requires an authenticated group load or
    an explicitly selected resident byte. Selecting residency is a consumer
    assertion, not evidence that these alternative sources were live together.
    """
    from .discovery import _directory
    analysis = _analysis_options(analysis_policy, call_depth_limit, data_ranges, instruction_limit, context_limit)
    resident = None
    if resident_snapshot is not None or resident_ranges is not None:
        from .resident_sources import admit as admit_resident
        if resident_snapshot is None or resident_ranges is None or analysis is None:
            raise ValueError('Resident composition requires snapshot, explicit ranges and bounded analysis policy')
        resident = admit_resident(resident_snapshot, resident_ranges)
    map_path, output = _path(map_path), _path(output)
    _ordinary(map_path, MAX_DECLARATION_BYTES)
    if output.exists() or output.is_symlink():
        raise ValueError('CD declaration output requires a new directory')
    if resident is not None and output.is_relative_to(resident.path.parent):
        raise ValueError('Resident CD output cannot modify its source snapshot namespace')
    _directory(output.parent)
    store = SnapshotStore()
    snapshot = store.read_json(map_path, max_bytes=MAX_DECLARATION_BYTES)
    images = _inputs(dict(disc=disc, toc=toc, **(dict(libchdr=libchdr) if libchdr is not None else {})))
    derived, _, _, _, _, _ = (_derive(snapshot.value, images, store) if analysis is None else
                              _derive(snapshot.value, images, store, analysis) if resident is None else
                              _derive(snapshot.value, images, store, analysis, resident))
    document = dict(format=FORMAT, schema=1, kind='declared', execution_evidence=False,
        map=dict(path=MAP_NAME, sha256=snapshot.sha256, size_bytes=snapshot.size_bytes), **derived)
    if analysis is not None:
        document['analysis'] = analysis
    if resident is not None:
        document['resident'] = resident.document
    # The original bounded JSON snapshot already retains the exact admitted
    # bytes. Do not reopen with an unbounded read after an earlier size check.
    raw = snapshot.raw
    encoded = (json.dumps(document, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if len(encoded) + len(raw) + _resident_bytes(resident) > MAX_DECLARATION_BYTES:
        raise ValueError('CD load numeric graph exceeds its byte bound')
    store.revalidate()
    if resident is not None:
        resident.revalidate()
    output.mkdir()
    if resident is not None:
        from .resident_sources import copy_resident
        copy_resident(resident, output / 'resident')
    with (output / MAP_NAME).open('xb') as stream:
        stream.write(raw)
    with (output / 'roots.json').open('xb') as stream:
        stream.write(encoded)
    admitted = load(output / 'roots.json', images)
    store.revalidate()
    if resident is not None:
        resident.revalidate()
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
    if admitted._resident is not None and output.is_relative_to(admitted._resident.path.parent):
        raise ValueError('CD declarations copy cannot modify its resident source namespace')
    _directory(output.parent)
    output.mkdir()
    if admitted._resident is not None:
        from .resident_sources import copy_resident
        copy_resident(admitted._resident, output / 'resident')
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
