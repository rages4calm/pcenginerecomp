"""Explicit unexecuted ROM instruction entries, separate from execution evidence.

Each numeric root declares one decoded instruction under an exact MPR and board
selector. No routine traversal, speculative bytes, hit counters or execution
origins are manufactured. Complete source identities remain the compiler key.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from .cartridge import ENCODINGS, HEADERS, MAX_ROM_BYTES, PROFILES, bank_map, decode as decode_rom
from .capture import integer
from .isa import NATIVE, decode, physical
from .snapshots import SnapshotStore

FORMAT = 'pce-declared-roots-1'
SCHEMA = 1
MAX_DECLARATION_BYTES = 64 * 1024 * 1024
MAX_ROOTS = 1048576
MAX_COMPILATION_IDENTITIES = 1048576
MAX_IMAGE_BYTES = MAX_ROM_BYTES + 512
STATIC_REACHABILITY = 'not_inferred'


def instruction_key(instruction):
    """Full decoded fetch identity, without provenance or invented hit fields."""
    return (instruction['pc'], tuple(instruction['mpr']),
            tuple(instruction['physical']), tuple(instruction['data']))


def _sort_key(instruction):
    return (instruction['mpr'], instruction['pc'], instruction['data'], instruction['physical'])


def _path(value):
    try:
        return Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as error:
        raise ValueError('Declaration input requires a valid file path') from error


def _ordinary(path, maximum, minimum=1):
    """SnapshotStore supports aliases; this narrower format explicitly does not."""
    try:
        for candidate in (*reversed(path.parents), path):
            info = candidate.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                raise ValueError('Declaration inputs do not support links or reparse points')
            if candidate != path and not stat.S_ISDIR(info.st_mode):
                raise ValueError('Declaration input parents must be ordinary directories')
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Declaration inputs require ordinary single-link regular files')
        if not minimum <= info.st_size <= maximum:
            raise ValueError('Declaration input exceeds its supported byte bounds')
    except OSError as error:
        raise ValueError('Declaration input is missing or unreadable') from error


def _fields(value, expected, label):
    if type(value) is not dict or set(value) != expected:
        raise ValueError('Invalid ' + label + ' fields')


def _choice(value, choices, label):
    if type(value) is not str or value not in choices:
        raise ValueError('Invalid declaration ' + label)


def _digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Declaration image requires a lowercase SHA256')


def _binding(snapshot):
    return dict(path=snapshot.path, sha256=snapshot.sha256, size_bytes=snapshot.size_bytes)


def _root_order(root):
    return (root['mpr'], root['pc'], root['selector'], root['rom_offsets'])


def _diagnostics(root, instruction, profile):
    reasons = []
    mnemonic, mode = instruction['mnemonic'], instruction['mode']
    if mnemonic == 'TAM' and instruction['data'][1]:
        reasons.append('dynamic_mpr_mapping')
    if mnemonic in ('RTS', 'RTI'):
        reasons.append('dynamic_return_target')
    elif mnemonic == 'JMP' and mode in ('ind', 'iax'):
        reasons.append('indirect_control_target')
    elif mnemonic in ('JSR', 'BSR'):
        reasons.append('call_target_and_return_continuation_not_traversed')
    elif mnemonic == 'BRK':
        reasons.append('interrupt_vector_not_traversed')
    elif instruction['target'] is not None:
        reasons.append('control_successors_not_traversed')
    if profile == 'sf2' and mnemonic in ('STA', 'STX', 'STY', 'STZ', 'TII', 'TIA', 'TAI', 'TIN', 'TDD'):
        reasons.append('write_target_may_change_board_selector')
    if not instruction['native_supported']:
        reasons.append('unsupported_instruction')
    return [dict(pc=root['pc'], mpr=list(root['mpr']), selector=root['selector'],
                 reason=reason, static_reachability=STATIC_REACHABILITY) for reason in reasons]


@dataclass(frozen=True)
class AdmittedDeclarations:
    path: Path
    image_path: Path
    sha256: str
    _instructions: list
    _roots: list
    _source_metadata: dict
    _artifact_bindings: dict
    _diagnostics: list
    _store: SnapshotStore
    format: str = FORMAT
    _minimum_image_bytes: int = 8192

    @property
    def instructions(self):
        return deepcopy(self._instructions)

    @property
    def roots(self):
        return deepcopy(self._roots)

    @property
    def source_metadata(self):
        return deepcopy(self._source_metadata)

    @property
    def artifact_bindings(self):
        return deepcopy(self._artifact_bindings)

    @property
    def diagnostics(self):
        return deepcopy(self._diagnostics)

    @property
    def static_reachability(self):
        return STATIC_REACHABILITY

    def revalidate(self):
        _ordinary(self.path, MAX_DECLARATION_BYTES)
        _ordinary(self.image_path, MAX_IMAGE_BYTES, self._minimum_image_bytes)
        self._store.revalidate()
        _ordinary(self.path, MAX_DECLARATION_BYTES)
        _ordinary(self.image_path, MAX_IMAGE_BYTES, self._minimum_image_bytes)


def load_declarations(path, image_path):
    """Bind exact numeric declarations and derive each entry from a supplied ROM."""
    path, image_path = _path(path), _path(image_path)
    _ordinary(path, MAX_DECLARATION_BYTES)
    _ordinary(image_path, MAX_IMAGE_BYTES)
    store = SnapshotStore()
    snapshot = store.read_json(path, max_bytes=MAX_DECLARATION_BYTES)
    document = snapshot.value
    _fields(document, {'format', 'schema', 'execution_evidence', 'kind', 'image', 'roots'}, 'declaration')
    from . import boot_sources
    if document['format'] == boot_sources.FORMAT:
        return boot_sources.admit(path,image_path,store,snapshot)
    _ordinary(image_path, MAX_IMAGE_BYTES, 8192)
    if (document['format'] != FORMAT or type(document['schema']) is not int
            or document['schema'] != SCHEMA or document['execution_evidence'] is not False
            or document['kind'] != 'declared'):
        raise ValueError('Unsupported declaration format/schema/kind/evidence')
    image = document['image']
    _fields(image, {'sha256', 'profile', 'header', 'encoding'}, 'declaration image')
    _digest(image['sha256'])
    for key, values in (('profile', PROFILES), ('header', HEADERS), ('encoding', ENCODINGS)):
        _choice(image[key], values, key)
    image_snapshot = store.bind(image_path, expected_sha256=image['sha256'])
    # Binary snapshots stream; this separate bounded byte buffer is checked
    # against the same admitted digest before deriving any source instruction.
    with image_path.open('rb') as stream:
        raw = stream.read(MAX_IMAGE_BYTES + 1)
    if len(raw) != image_snapshot.size_bytes or hashlib.sha256(raw).hexdigest() != image_snapshot.sha256:
        raise ValueError('Declaration image changed during decoding')
    rom = decode_rom(raw, image['header'], image['encoding'], image['profile'])
    source = dict(image_sha256=image_snapshot.sha256,
        decoded_rom_sha256=hashlib.sha256(rom).hexdigest(), profile=image['profile'],
        header=image['header'], encoding=image['encoding'],
        file_bytes=image_snapshot.size_bytes, rom_bytes=len(rom))
    roots = document['roots']
    if type(roots) is not list or not 1 <= len(roots) <= MAX_ROOTS:
        raise ValueError('Declarations require a bounded nonempty root list')
    seen, union, diagnostics = set(), {}, []
    maps = {}
    for root in roots:
        _fields(root, {'pc', 'mpr', 'selector', 'rom_offsets'}, 'declaration root')
        pc = integer(root['pc'], 65535, 'declared logical PC')
        if type(root['mpr']) is not list or len(root['mpr']) != 8:
            raise ValueError('Declared roots require all eight MPR bytes')
        mpr = tuple(integer(item, 255, 'declared MPR') for item in root['mpr'])
        selector = integer(root['selector'], 15, 'declared selector')
        if image['profile'] != 'sf2' and selector:
            raise ValueError('Only SF2 declarations permit a nonzero selector')
        offsets = root['rom_offsets']
        if type(offsets) is not list or not 1 <= len(offsets) <= 7:
            raise ValueError('Declared ROM offsets require one to seven bytes')
        for offset in offsets:
            integer(offset, len(rom) - 1, 'declared ROM offset')
        identity = (pc, mpr, selector, tuple(offsets))
        if identity in seen:
            raise ValueError('Duplicate identical declared root')
        seen.add(identity)
        if selector not in maps:
            maps[selector] = bank_map(len(rom), image['profile'], selector)
        banks = maps[selector]

        def rom_offset(address):
            address = physical(address, mpr)
            bank = address >> 13
            if bank >= 128 or banks[bank] is None:
                raise ValueError('Declared instruction fetch is not driven cartridge ROM')
            return banks[bank] * 8192 + (address & 8191)

        instruction = decode(lambda address: rom[rom_offset(address)], pc, mpr)
        derived = [rom_offset((pc + index) & 65535) for index in range(len(instruction.data))]
        if offsets != derived:
            raise ValueError('Declared ROM offsets disagree with decoded instruction length or mapping')
        report = instruction.report() | {'mpr': mpr}
        union[instruction_key(report)] = report
        diagnostics.extend(_diagnostics(root, report, image['profile']))
    admitted = AdmittedDeclarations(path, image_path, snapshot.sha256,
        sorted(union.values(), key=_sort_key), sorted(roots, key=_root_order), source,
        dict(declarations=_binding(snapshot), source_image=_binding(image_snapshot)), diagnostics, store)
    admitted.revalidate()
    return admitted


def _exclusions(ranges):
    if not isinstance(ranges, (list, tuple)) or len(ranges) > 256:
        raise ValueError('Emission exclusions require at most 256 physical ranges')
    result = set()
    for span in ranges:
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ValueError('Emission exclusion must be (physical start, length)')
        start = integer(span[0], 0x1FFFFF, 'excluded physical start')
        length = integer(span[1], 0x200000 - start, 'excluded physical length', 1)
        result.add((start, length))
    return sorted(result)


@dataclass(frozen=True)
class AdmittedCompilation:
    declarations: AdmittedDeclarations
    history: object
    _instructions: list
    observed_keys: frozenset
    declared_keys: frozenset

    @property
    def instructions(self):
        return deepcopy(self._instructions)

    @property
    def accounting(self):
        return self.history.accounting if self.history is not None else {}

    @property
    def provenance(self):
        value = dict(declared_roots_sha256=self.declarations.sha256,
            declared_roots_format=self.declarations.format, declared_roots_schema=SCHEMA,
            declared_roots_source=self.declarations.source_metadata)
        if self.history is not None:
            index = self.history.index
            value.update(observation_history_sha256=self.history.index_sha256,
                observation_history_format=index['format'], observation_history_schema=index['schema'],
                observation_inputs=self.history.input_metadata)
        return value

    @property
    def static_reachability(self):
        return STATIC_REACHABILITY

    @property
    def diagnostics(self):
        return self.declarations.diagnostics

    def revalidate(self):
        self.declarations.revalidate()
        if self.history is not None:
            self.history.revalidate()

    def _selection(self, exclude_ranges, *, include_instructions):
        ranges = _exclusions(exclude_ranges)
        selected, removed = [], []
        for instruction in self._instructions:
            excluded = any(start <= address < start + length
                           for address in instruction['physical'] for start, length in ranges)
            (removed if excluded else selected).append(instruction)
        removed_keys = {instruction_key(item) for item in removed}
        unsupported = {instruction_key(item) for item in selected if item['data'][0] not in NATIVE}
        observed, declared = self.observed_keys, self.declared_keys
        counts = dict(observed_instructions=len(observed), declared_instructions=len(declared),
            declared_roots_count=len(self.declarations._roots), source_identity_count=len(self._instructions),
            declared_only=len(declared - observed), observed_only=len(observed - declared),
            declared_observed_overlap=len(observed & declared),
            emitted_instructions=len(selected) - len(unsupported),
            excluded_observations=len(removed_keys & observed),
            excluded_declarations=len(removed_keys & declared),
            excluded_retired_hits=sum(item['native_hits'] + item['interpreted_hits']
                                      for item in removed if instruction_key(item) in observed),
            unsupported_observations=len(unsupported & observed),
            unsupported_declarations=len(unsupported & declared))
        result = dict(counts=counts,
                      exclusions=[dict(start=start, length=length) for start, length in ranges])
        if include_instructions:
            result['instructions'] = deepcopy(selected)
        return result

    def selection(self, exclude_ranges=()):
        return self._selection(exclude_ranges, include_instructions=True)

    def counts(self, exclude_ranges=()):
        return self._selection(exclude_ranges, include_instructions=False)['counts']


def load_compilation(declarations_path, image_path, *, observation_history=None):
    """Union independently declared entries with authentic observed identities.

    Declarations supply no hits. If an identity is observed as well, its exact
    historical tier fields are retained; independent evidence classes overlap.
    """
    from .history import AdmittedHistory, load_history

    declarations = load_declarations(declarations_path, image_path)
    history = (None if observation_history is None else observation_history
               if isinstance(observation_history, AdmittedHistory) else load_history(observation_history))
    if history is not None:
        history.revalidate()
    declared_rows = declarations.instructions
    observed_rows = [] if history is None else history.instructions
    declared = frozenset(instruction_key(item) for item in declared_rows)
    observed = frozenset(instruction_key(item) for item in observed_rows)
    if len(declared | observed) > MAX_COMPILATION_IDENTITIES:
        raise ValueError('Compilation source identity union exceeds its bound; no identities dropped')
    union = {instruction_key(item): item for item in declared_rows}
    union.update((instruction_key(item), item) for item in observed_rows)
    admitted = AdmittedCompilation(declarations, history, sorted(union.values(), key=_sort_key), observed, declared)
    admitted.revalidate()
    return admitted
