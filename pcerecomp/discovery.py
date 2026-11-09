"""Bounded ROM control-flow candidates, never observations or routine closure.

The input and output are ordinary numeric declared-roots catalogues. Separate
derivation evidence binds the copied seeds, explicit source ranges and board
view. No return mapping, data reference, execution hit or reachability is guessed.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat

from .analysis import _register_facts
from .cartridge import bank_map, decode as decode_rom
from .capture import integer
from .declarations import (FORMAT as ROOTS_FORMAT, SCHEMA as ROOTS_SCHEMA,
    MAX_DECLARATION_BYTES, MAX_IMAGE_BYTES, MAX_ROOTS, _ordinary,
    instruction_key, load_declarations)
from .isa import BRANCHES, decode, physical
from .snapshots import SnapshotStore

FORMAT = 'pce-static-discovery-1'
SCHEMA = 1
POLICY = 'bounded-source-qualified-rom-v1'
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_INSTRUCTIONS = MAX_ROOTS
MAX_CONTEXTS = 4096
MAX_RANGES = 256
REPORT_NAME = 'discovery.json'
ROOTS_NAME = 'roots.json'
SEEDS_NAME = 'seed-roots.json'
_FILES = {REPORT_NAME, ROOTS_NAME, SEEDS_NAME}
_REPORT_FIELDS = {'format', 'schema', 'execution_evidence', 'kind', 'analysis_policy',
    'static_reachability', 'routine_closure', 'source', 'options', 'artifacts',
    'seed_node_ids', 'nodes', 'edges', 'unresolved', 'overlaps', 'summary'}
_WRITERS = {'STA', 'STX', 'STY', 'STZ', 'ASL', 'LSR', 'ROL', 'ROR', 'INC', 'DEC',
            'TSB', 'TRB', 'TII', 'TIA', 'TAI', 'TIN', 'TDD'}


def _path(value):
    try:
        return Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as error:
        raise ValueError('Discovery requires valid text paths') from error


def _directory(path):
    try:
        for candidate in (*reversed(path.parents), path):
            info = candidate.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                raise ValueError('Discovery requires ordinary unlinked directories')
    except OSError as error:
        raise ValueError('Discovery directory is missing or unreadable') from error


def _closed_graph(root):
    _directory(root)
    try:
        names = {path.name for path in root.iterdir()}
    except OSError as error:
        raise ValueError('Discovery graph cannot be inspected') from error
    if names != _FILES:
        raise ValueError('Discovery graph contains missing or unlisted content')
    for name in sorted(_FILES):
        _ordinary(root / name, MAX_REPORT_BYTES if name == REPORT_NAME else MAX_DECLARATION_BYTES)


def _canonical(value, maximum):
    # Encode incrementally so an oversized graph never allocates an unbounded
    # serialized buffer or creates a partially published output directory.
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    data = bytearray()
    try:
        for token in encoder.iterencode(value):
            encoded = token.encode('utf-8')
            if len(data) + len(encoded) + 1 > maximum:
                raise ValueError('Discovery JSON exceeds its serialized byte bound')
            data.extend(encoded)
    except (TypeError, RecursionError) as error:
        raise ValueError('Invalid discovery JSON value') from error
    data.extend(b'\n')
    return bytes(data)


def _ranges(values, rom_bytes):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_RANGES:
        raise ValueError('Discovery requires one to 256 explicit decoded-ROM ranges')
    intervals = []
    for value in values:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError('ROM ranges require (decoded start, byte length) pairs')
        start = integer(value[0], rom_bytes - 1, 'ROM range start')
        length = integer(value[1], rom_bytes - start, 'ROM range length', 1)
        intervals.append((start, start + length))
    merged = []
    for start, end in sorted(set(intervals)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _address(key):
    selector, mpr, pc = key
    return dict(pc=pc, mpr=list(mpr), selector=selector)


def _root_key(root):
    return root['selector'], tuple(root['mpr']), root['pc']


def _root_order(root):
    return root['mpr'], root['pc'], root['selector'], root['rom_offsets']


def _mapper_barrier(instruction, mpr, profile):
    if profile != 'sf2':
        return False
    name, mode = instruction.mnemonic, instruction.mode
    writer = name in _WRITERS or name.startswith(('RMB', 'SMB'))
    if not writer or mode == 'acc':
        return False
    # Zero-page writes are at logical $20xx, including indexed wrap. Stack
    # writes are $21xx; dedicated ST0/ST1/ST2 are VDC ports, not mapper writes.
    if mode in ('zpg', 'zpx', 'zpy'):
        return False
    if mode == 'abs':
        address = physical(instruction.data[1] | instruction.data[2] << 8, mpr)
        return address >> 13 == 0 and (address & 8191) >= 0x1FF0
    # Indexed/indirect writes and block destinations are not guessed. This
    # deliberately stops even when a stronger address analysis could prove safe.
    return True


class _Boundary(ValueError):
    def __init__(self, reason, **detail):
        self.reason, self.detail = reason, detail
        super().__init__(reason)


def _derive(seeds, rom, ranges, instruction_limit, context_limit):
    integer(instruction_limit, MAX_INSTRUCTIONS, 'discovery instruction limit', 1)
    integer(context_limit, MAX_CONTEXTS, 'discovery context limit', 1)
    seed_rows = seeds.roots
    seed_keys = sorted({_root_key(root) for root in seed_rows})
    if len(seed_keys) > instruction_limit:
        raise ValueError('Seed instructions exceed the discovery instruction limit')
    if len({key[:2] for key in seed_keys}) > context_limit:
        raise ValueError('Seed contexts exceed the discovery context limit')
    starts = [start for start, _ in ranges]
    maps, decoded = {}, {}
    profile = seeds.source_metadata['profile']

    def offset(key, logical):
        selector, mpr, _ = key
        if selector not in maps:
            maps[selector] = bank_map(len(rom), profile, selector)
        address = physical(logical, mpr)
        bank = address >> 13
        if bank >= 128 or maps[selector][bank] is None:
            raise _Boundary('non_rom_fetch', logical_pc=logical & 65535, physical=address)
        value = maps[selector][bank] * 8192 + (address & 8191)
        index = bisect_right(starts, value) - 1
        if index < 0 or value >= ranges[index][1]:
            raise _Boundary('allowed_rom_boundary', logical_pc=logical & 65535,
                            physical=address, rom_offset=value)
        return value

    def instruction(key):
        if key not in decoded:
            ins = decode(lambda logical: rom[offset(key, logical)], key[2], key[1])
            offsets = [offset(key, (key[2] + index) & 65535) for index in range(len(ins.data))]
            decoded[key] = (ins, offsets)
        return decoded[key]

    # Every seed must be wholly inside explicit code ranges. A later traversal
    # boundary is a reported frontier, not a reason to remove an original seed.
    for key in seed_keys:
        try:
            instruction(key)
        except _Boundary as error:
            raise ValueError('An original seed fetch is outside the allowed ROM view: ' + error.reason) from error
    unknown = (None, None, None)
    pending, queued = deque(), set()
    facts, contexts, successors, problems = {}, set(), {}, {}

    def offer(key, incoming):
        if key not in facts:
            if key[:2] not in contexts and len(contexts) == context_limit:
                return dict(reason='context_limit')
            if len(facts) == instruction_limit:
                return dict(reason='instruction_limit')
        try:
            instruction(key)
        except _Boundary as error:
            return dict(reason=error.reason, **error.detail)
        if key not in facts:
            contexts.add(key[:2])
            facts[key] = incoming
        else:
            merged = tuple(left if left == right else None for left, right in zip(facts[key], incoming))
            if merged == facts[key]:
                return None
            facts[key] = merged
        if key not in queued:
            pending.append(key)
            queued.add(key)
        return None

    for key in seed_keys:
        refused = offer(key, unknown)
        if refused is not None:
            raise ValueError('An original seed could not be admitted: ' + refused['reason'])
    while pending:
        key = pending.popleft()
        queued.remove(key)
        selector, mpr, pc = key
        ins, _ = instruction(key)
        successors[key], problems[key] = [], []
        outgoing = _register_facts(ins, facts[key], mpr)
        name = ins.mnemonic
        targets = []
        if _mapper_barrier(ins, mpr, profile):
            problems[key].append(dict(reason='mapper_write_barrier', resume_pc=ins.next_pc))
        elif name in BRANCHES or ins.mode == 'zrl':
            targets = [(mpr, ins.target, 'taken'), (mpr, ins.next_pc, 'fallthrough')]
        elif name in ('JSR', 'BSR'):
            targets = [(mpr, ins.target, 'call')]
            problems[key].append(dict(reason='dynamic_return_site', resume_pc=ins.next_pc))
        elif name in ('JMP', 'BRA') and ins.target is not None:
            targets = [(mpr, ins.target, 'jump')]
        elif name in ('RTS', 'RTI', 'BRK', 'ILL') or name == 'JMP':
            reason = {'RTS': 'dynamic_return', 'RTI': 'interrupt_return',
                      'BRK': 'interrupt_vector', 'ILL': 'unassigned_opcode'}.get(name, 'indirect_jump')
            problems[key].append(dict(reason=reason))
        elif name == 'TAM':
            mask = ins.data[1]
            if mask and facts[key][0] is None:
                problems[key].append(dict(reason='mapping_change', resume_pc=ins.next_pc, mask=mask))
            else:
                mapped = tuple(facts[key][0] if mask & (1 << index) else bank
                               for index, bank in enumerate(mpr))
                targets = [(mapped, ins.next_pc, 'mapping_change' if mask else 'fallthrough')]
        else:
            targets = [(mpr, ins.next_pc, 'fallthrough')]
        for mapped, target_pc, kind in targets:
            target = selector, mapped, target_pc
            refused = offer(target, outgoing)
            if refused:
                problems[key].append(dict(refused, target=_address(target), kind=kind))
            else:
                successors[key].append((target, kind))

    # Monotone joins can invalidate an earlier constant-A TAM edge. Retain only
    # states connected to the current seed graph, not stale optimistic branches.
    reachable, todo = set(), deque(seed_keys)
    while todo:
        key = todo.popleft()
        if key in reachable:
            continue
        reachable.add(key)
        todo.extend(target for target, _ in successors.get(key, ()))
    ordered = sorted(reachable, key=lambda key: (key[1], key[2], key[0]))
    node_ids = {key: index for index, key in enumerate(ordered)}
    roots, nodes, edges, unresolved = [], [], [], []
    source_keys, occupied, overlap_bytes = set(), {}, {}
    for key in ordered:
        ins, offsets = instruction(key)
        node_id = node_ids[key]
        root = _address(key) | dict(rom_offsets=list(offsets))
        roots.append(root)
        nodes.append(root | dict(node_id=node_id, mnemonic=ins.mnemonic, mode=ins.mode,
            target=ins.target, register_facts=dict(zip(('a', 'x', 'y'), facts[key]))))
        source_keys.add(instruction_key(ins.report() | {'mpr': key[1]}))
        for target, kind in successors.get(key, ()):
            edges.append(dict(from_id=node_id, to_id=node_ids[target], kind=kind))
        for problem in problems.get(key, ()):
            unresolved.append(_address(key) | dict(node_id=node_id) | problem)
        for index, rom_offset in enumerate(offsets):
            logical = (key[2] + index) & 65535
            # Different logical aliases/MPRs/selectors are distinct code views.
            # Only competing starts in this exact view overlap one another.
            byte_key = key[0], key[1], logical, rom_offset
            previous_starts = occupied.setdefault(byte_key, [])
            for previous in previous_starts:
                pair = tuple(sorted((node_ids[previous], node_id)))
                overlap_bytes.setdefault(pair, set()).add((logical, rom_offset))
            previous_starts.append(key)
    roots.sort(key=_root_order)
    overlaps = [dict(left_id=pair[0], right_id=pair[1],
                     logical_addresses=[logical for logical, _ in sorted(values)],
                     rom_offsets=[offset for _, offset in sorted(values)])
                for pair, values in sorted(overlap_bytes.items())]
    unique = lambda values: [json.loads(value) for value in sorted({
        json.dumps(value, sort_keys=True, separators=(',', ':')) for value in values})]
    unresolved = unique(unresolved)
    report = dict(seed_node_ids=[node_ids[key] for key in seed_keys], nodes=nodes,
        edges=unique(edges), unresolved=unresolved, overlaps=overlaps,
        summary=dict(seed_roots=len(seed_rows), candidate_roots=len(roots),
            source_identities=len(source_keys), contexts=len({key[:2] for key in reachable}),
            explored_states=len(facts), explored_contexts=len(contexts), unresolved=len(unresolved),
            overlaps=len(overlaps), native_supported=sum(instruction(key)[0].native for key in ordered),
            limit_reached=any(item['reason'] in ('instruction_limit', 'context_limit') for item in unresolved),
            execution_evidence=False))
    document = dict(format=ROOTS_FORMAT, schema=ROOTS_SCHEMA, execution_evidence=False, kind='declared',
        image=dict(sha256=seeds.source_metadata['image_sha256'],
                   **{name: seeds.source_metadata[name] for name in ('profile', 'header', 'encoding')}), roots=roots)
    return document, report


def _rom(seeds):
    binding = seeds.artifact_bindings['source_image']
    with binding['path'].open('rb') as stream:
        raw = stream.read(MAX_IMAGE_BYTES + 1)
    if len(raw) != binding['size_bytes'] or hashlib.sha256(raw).hexdigest() != binding['sha256']:
        raise ValueError('Discovery source image changed during decoding')
    metadata = seeds.source_metadata
    rom = decode_rom(raw, metadata['header'], metadata['encoding'], metadata['profile'])
    if hashlib.sha256(rom).hexdigest() != metadata['decoded_rom_sha256']:
        raise ValueError('Discovery decoded image identity differs')
    seeds.revalidate()
    return rom


def _report(seeds, seed_raw, roots_raw, partial, ranges, instruction_limit, context_limit):
    return dict(format=FORMAT, schema=SCHEMA, execution_evidence=False, kind='static_candidates',
        analysis_policy=POLICY, static_reachability='candidates_only', routine_closure=False,
        source=seeds.source_metadata,
        options=dict(rom_ranges=[dict(start=start, length=end - start) for start, end in ranges],
                     instruction_limit=instruction_limit, context_limit=context_limit),
        artifacts={SEEDS_NAME: dict(sha256=hashlib.sha256(seed_raw).hexdigest(), size_bytes=len(seed_raw)),
                   ROOTS_NAME: dict(sha256=hashlib.sha256(roots_raw).hexdigest(), size_bytes=len(roots_raw))},
        **partial)


def _write_new(path, data):
    _directory(path.parent)
    with path.open('xb') as stream:
        stream.write(data)


@dataclass(frozen=True)
class AdmittedDiscovery:
    report_path: Path
    sha256: str
    declarations: object
    _report: dict
    _bindings: dict
    _store: SnapshotStore

    @property
    def report(self):
        return deepcopy(self._report)

    @property
    def roots_path(self):
        return self.declarations.path

    @property
    def artifact_bindings(self):
        return deepcopy(self._bindings)

    def revalidate(self):
        _closed_graph(self.report_path.parent)
        _ordinary(self.declarations.image_path, MAX_IMAGE_BYTES, 8192)
        self._store.revalidate()
        self.declarations.revalidate()
        _closed_graph(self.report_path.parent)


def discover_roots(seed_path, image_path, output, *, rom_ranges,
                   instruction_limit=10000, context_limit=256):
    """Write a new source-qualified candidate catalogue and derivation closure."""
    output = _path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Discovery output must be a new directory')
    _directory(output.parent)
    seeds = load_declarations(seed_path, image_path)
    store = SnapshotStore()
    seed = store.read_json(seeds.path, expected_sha256=seeds.sha256, max_bytes=MAX_DECLARATION_BYTES)
    rom = _rom(seeds)
    ranges = _ranges(rom_ranges, len(rom))
    document, partial = _derive(seeds, rom, ranges, instruction_limit, context_limit)
    roots_raw = _canonical(document, MAX_DECLARATION_BYTES)
    report = _report(seeds, seed.raw, roots_raw, partial, ranges, instruction_limit, context_limit)
    report_raw = _canonical(report, MAX_REPORT_BYTES)
    seeds.revalidate()
    store.revalidate()
    output.mkdir(exist_ok=False)
    _write_new(output / SEEDS_NAME, seed.raw)
    _write_new(output / ROOTS_NAME, roots_raw)
    seeds.revalidate()
    store.revalidate()
    _write_new(output / REPORT_NAME, report_raw)  # Last: partial graphs never admit.
    admitted = load_discovery(output, image_path)
    seeds.revalidate()
    store.revalidate()
    return admitted


def load_discovery(path, image_path):
    """Recompute a separate discovery report; hashes alone do not establish CFG facts."""
    path = _path(path)
    if path.is_dir() and not path.is_symlink():
        path /= REPORT_NAME
    if path.name != REPORT_NAME:
        raise ValueError('Discovery report must be named discovery.json')
    root = path.parent
    _closed_graph(root)
    store = SnapshotStore()
    report_snapshot = store.read_json(path, max_bytes=MAX_REPORT_BYTES)
    report = report_snapshot.value
    if type(report) is not dict or set(report) != _REPORT_FIELDS:
        raise ValueError('Invalid discovery report fields')
    if (report['format'] != FORMAT or type(report['schema']) is not int or report['schema'] != SCHEMA
            or report['execution_evidence'] is not False or report['kind'] != 'static_candidates'
            or report['analysis_policy'] != POLICY or report['static_reachability'] != 'candidates_only'
            or report['routine_closure'] is not False):
        raise ValueError('Unsupported discovery report contract')
    options = report['options']
    if type(options) is not dict or set(options) != {'rom_ranges', 'instruction_limit', 'context_limit'}:
        raise ValueError('Invalid discovery options')
    references = report['artifacts']
    if type(references) is not dict or set(references) != {SEEDS_NAME, ROOTS_NAME}:
        raise ValueError('Invalid discovery artifact references')
    snapshots = {}
    for name in (SEEDS_NAME, ROOTS_NAME):
        reference = references[name]
        if type(reference) is not dict or set(reference) != {'sha256', 'size_bytes'}:
            raise ValueError('Invalid discovery artifact fields')
        integer(reference['size_bytes'], MAX_DECLARATION_BYTES, 'discovery artifact bytes', 1)
        snapshots[name] = store.read_json(root / name, expected_sha256=reference['sha256'],
                                          max_bytes=MAX_DECLARATION_BYTES)
        if snapshots[name].size_bytes != reference['size_bytes']:
            raise ValueError('Discovery artifact size differs')
    seeds = load_declarations(root / SEEDS_NAME, image_path)
    source = seeds.artifact_bindings['source_image']
    image_snapshot = store.bind(source['path'], expected_sha256=source['sha256'])
    rom = _rom(seeds)
    recorded_ranges = options['rom_ranges']
    if type(recorded_ranges) is not list or not 1 <= len(recorded_ranges) <= MAX_RANGES:
        raise ValueError('Invalid discovery ROM range list')
    for entry in recorded_ranges:
        if type(entry) is not dict or set(entry) != {'start', 'length'}:
            raise ValueError('Invalid discovery ROM range fields')
    ranges = _ranges([(entry['start'], entry['length']) for entry in recorded_ranges], len(rom))
    document, partial = _derive(seeds, rom, ranges, options['instruction_limit'], options['context_limit'])
    roots_raw = _canonical(document, MAX_DECLARATION_BYTES)
    if snapshots[ROOTS_NAME].raw != roots_raw:
        raise ValueError('Expanded numeric roots disagree with source-qualified derivation')
    expected = _report(seeds, snapshots[SEEDS_NAME].raw, roots_raw, partial, ranges,
                       options['instruction_limit'], options['context_limit'])
    if report_snapshot.raw != _canonical(expected, MAX_REPORT_BYTES):
        raise ValueError('Discovery report differs from recomputed derivation or canonical encoding')
    declarations = load_declarations(root / ROOTS_NAME, image_path)
    bindings = {name: dict(path=snapshot.path, sha256=snapshot.sha256, size_bytes=snapshot.size_bytes)
                for name, snapshot in {REPORT_NAME: report_snapshot, **snapshots,
                                       'source_image': image_snapshot}.items()}
    admitted = AdmittedDiscovery(path, report_snapshot.sha256, declarations, expected, bindings, store)
    admitted.revalidate()
    return admitted
