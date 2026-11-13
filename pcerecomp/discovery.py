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
from .register_eval import ALU, evaluate
from .branch_facts import FLAGS, extend_status, flag_decision, refine
from . import stack_facts as stack_values
from . import wram_facts as wram_values
from . import memory_flow as flow
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
VECTOR_POLICY = 'bounded-source-qualified-rom-vectors-v1'
CALL_POLICY = 'bounded-source-qualified-rom-calls-v1'
TABLE_POLICY = 'bounded-source-qualified-rom-tables-v1'
TABLE_CALL_POLICY = 'bounded-source-qualified-rom-table-calls-v1'
DATA_POLICY = 'bounded-source-qualified-rom-data-v1'
EVAL_POLICY = 'bounded-source-qualified-register-eval-v1'
BRANCH_POLICY = 'bounded-source-qualified-branches-v1'
STACK_POLICY = 'bounded-source-qualified-stack-values-v1'
WRAM_POLICY = 'bounded-source-qualified-wram-values-v1'
FLOW_POLICY = 'bounded-source-qualified-memory-flow-v1'
MAPPER_POLICY = 'bounded-source-qualified-mapper-flow-v1'
SOFTWARE_POLICY = 'bounded-source-qualified-software-interrupts-v1'
MAX_CALL_DEPTH = 64
MAX_ROM_TABLE_SITES = 256
# Calling frames can revisit one source view; bound expanded table witnesses
# separately, to at most 65,536 index decisions before serialization.
MAX_ROM_TABLE_STATES = 256
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
    selector, mpr, pc = key[:3]
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


class _Boundary(wram_values.Unknown):
    pass


def _wram_ranges(values):
    ranges = _ranges(values, 8192)
    if sum(end-start for start,end in ranges) > wram_values.MAX_BYTES:
        raise ValueError('WRAM facts allow at most 256 explicitly permitted bytes')
    if any(start < 512 and end > 256 for start,end in ranges):
        raise ValueError('WRAM facts exclude the stack page $0100-$01FF')
    return ranges


def _stack_write_barrier(ins, mpr, facts):
    """Unknown SP protects the entire canonical WRAM stack page, including aliases.

    SP and general memory contents are not tracked. Even the saved-value policy
    consequently treats indirect/unknown-index and block writes as frontiers.
    """
    if ins.mnemonic not in _WRITERS and not ins.mnemonic.startswith(('RMB', 'SMB')):
        return False
    if ins.mode in ('acc', 'zpg', 'zpx', 'zpy'):
        return False
    if ins.mode not in ('abs', 'abx', 'aby'):
        return True
    index = 0 if ins.mode == 'abs' else facts[1 if ins.mode == 'abx' else 2]
    if index is None:
        return True
    address = physical(((ins.data[1] | ins.data[2] << 8) + index) & 65535, mpr)
    return 0xF8 <= address >> 13 <= 0xFB and 0x100 <= address & 8191 <= 0x1FF


def _derive(seeds, rom, ranges, instruction_limit, context_limit, vector_ranges=None,
            call_depth_limit=None, rom_table_limit=None, data_ranges=None, alu_facts=False, branch_facts=False, stack_facts=False, wram_facts=False, wram_ranges=None, memory_flow=False, block_transfer_limit=None, wram_table_limit=None, mapper_facts=False, software_interrupts=False):
    if type(alu_facts) is not bool:
        raise ValueError('Register evaluation requires a boolean alu_facts option')
    if type(branch_facts) is not bool or branch_facts and not alu_facts:
        raise ValueError('Branch facts require a boolean option and alu_facts=True')
    if type(stack_facts) is not bool or stack_facts and (not branch_facts or call_depth_limit is None):
        raise ValueError('Stack facts require a boolean option, branch_facts=True and a call depth limit')
    if (type(wram_facts) is not bool or wram_facts and (not stack_facts or wram_ranges is None)
            or not wram_facts and wram_ranges is not None):
        raise ValueError('WRAM facts require a boolean option, stack_facts=True and explicit WRAM ranges')
    if (type(memory_flow) is not bool or memory_flow and (not wram_facts or block_transfer_limit is None)
            or not memory_flow and (block_transfer_limit is not None or wram_table_limit is not None)):
        raise ValueError('Memory flow requires a boolean option, WRAM facts and an explicit block transfer limit')
    if memory_flow:
        integer(block_transfer_limit, flow.MAX_BLOCK_BYTES, 'block transfer limit', 1)
        if wram_table_limit is not None:
            integer(wram_table_limit, flow.MAX_TABLE_STATES, 'WRAM table state limit', 1)
    if type(mapper_facts) is not bool or mapper_facts and (not memory_flow or seeds.source_metadata['profile'] != 'sf2'):
        raise ValueError('Mapper facts require memory_flow=True and the explicit SF2 profile')
    if type(software_interrupts) is not bool or software_interrupts and not memory_flow:
        raise ValueError('Software interrupts require memory_flow=True and a boolean option')
    slots = {offset: pos for pos,offset in enumerate(
        offset for start,end in (wram_ranges or ()) for offset in range(start,end))}
    integer(instruction_limit, MAX_INSTRUCTIONS, 'discovery instruction limit', 1)
    integer(context_limit, MAX_CONTEXTS, 'discovery context limit', 1)
    calls = call_depth_limit is not None
    if calls:
        integer(call_depth_limit, MAX_CALL_DEPTH, 'discovery call depth', 1)
    if rom_table_limit is not None:
        integer(rom_table_limit, MAX_ROM_TABLE_SITES, 'ROM table site limit', 1)
        if vector_ranges is None:
            raise ValueError('ROM table enumeration requires explicit ROM vector ranges')
    seed_rows = seeds.roots
    seed_keys = sorted({_root_key(root) for root in seed_rows})
    if calls:
        seed_keys = [key + (((), 0),) for key in seed_keys]
    if len(seed_keys) > instruction_limit:
        raise ValueError('Seed instructions exceed the discovery instruction limit')
    if len({key[:2] for key in seed_keys}) > context_limit:
        raise ValueError('Seed contexts exceed the discovery context limit')
    starts = [start for start, _ in ranges]
    vector_starts = [start for start, _ in vector_ranges] if vector_ranges is not None else []
    data_starts = [start for start, _ in data_ranges] if data_ranges is not None else []
    maps, decoded = {}, {}
    profile = seeds.source_metadata['profile']

    def offset(key, logical, *, vector=False, data=False):
        selector, mpr, _ = key[:3]
        if selector not in maps:
            maps[selector] = bank_map(len(rom), profile, selector)
        address = physical(logical, mpr)
        bank = address >> 13
        if bank >= 128 or maps[selector][bank] is None:
            if data:
                raise _Boundary('non_rom_data', logical_address=logical, physical=address)
            if vector:
                raise _Boundary('non_rom_vector', logical_address=logical, physical=address)
            raise _Boundary('non_rom_fetch', logical_pc=logical & 65535, physical=address)
        value = maps[selector][bank] * 8192 + (address & 8191)
        allowed, beginning = (vector_ranges, vector_starts) if vector else (ranges, starts)
        if data:
            allowed, beginning = data_ranges, data_starts
        if allowed is None:
            raise _Boundary('missing_rom_data_permission' if data else 'missing_vector_permission', logical_address=logical)
        index = bisect_right(beginning, value) - 1
        if index < 0 or value >= allowed[index][1]:
            if data:
                raise _Boundary('allowed_data_boundary', logical_address=logical,
                                physical=address, rom_offset=value)
            if vector:
                raise _Boundary('allowed_vector_boundary', logical_address=logical,
                                physical=address, rom_offset=value)
            raise _Boundary('allowed_rom_boundary', logical_pc=logical & 65535,
                            physical=address, rom_offset=value)
        return value

    def instruction(key):
        key = key[:3]  # Decode once per code view, not once per calling context.
        if key not in decoded:
            ins = decode(lambda logical: rom[offset(key, logical)], key[2], key[1])
            offsets = [offset(key, (key[2] + index) & 65535) for index in range(len(ins.data))]
            decoded[key] = (ins, offsets)
        return decoded[key]

    def value_read(key, incoming, logical, role, reads, *, vector=False, memory=None, selector=None):
        if selector is not None:
            key = (selector, *key[1:])
        address = physical(logical, key[1])
        canonical = wram_values.canonical(address)
        if canonical is not None:
            if canonical not in slots:
                raise _Boundary('allowed_wram_data_boundary', logical_address=logical, physical=address, wram_offset=canonical)
            value = (incoming[11] if memory is None else memory)[slots[canonical]]
            if value is None:
                raise _Boundary('wram_value_unknown', logical_address=logical, physical=address, wram_offset=canonical)
            reads.append(dict(role=role, storage='wram', logical_address=logical, physical=address, wram_offset=canonical, value=value))
        else:
            source = offset(key, logical, data=not vector, vector=vector)
            value = rom[source]
            reads.append(dict(role=role, storage='rom', logical_address=logical, physical=address, rom_offset=source, value=value))
        return value

    def data_fact(key, ins, incoming):
        """Evidence for a load only; generated operations never use these values.

        Unknown/denied reads leave the destination unknown and preserve the old
        control-flow rules. Pointer bytes have their own data permissions.
        """
        reads = []
        register = ins.mnemonic[-1].lower() if ins.mnemonic in ('LDA', 'LDX', 'LDY', 'CPX', 'CPY') else 'a'
        record = dict(register=register, mode=ins.mode, reads=reads)

        def index(register):
            value = incoming[1 if register == 'x' else 2]
            if value is None:
                raise _Boundary('data_index_unknown', register=register)
            return value

        def read(logical, role):
            if wram_facts:
                return value_read(key, incoming, logical, role, reads)
            source = offset(key, logical, data=True)
            value = rom[source]
            reads.append(dict(role=role, logical_address=logical,
                physical=physical(logical, key[1]), rom_offset=source, value=value))
            return value

        try:
            mode = ins.mode
            if mode in ('zpg', 'zpx', 'zpy'):
                added = index('x' if mode == 'zpx' else 'y') if mode != 'zpg' else 0
                logical = 0x2000 + ((ins.data[1] + added) & 255)
            elif mode in ('abs', 'abx', 'aby'):
                added = index('x' if mode == 'abx' else 'y') if mode != 'abs' else 0
                logical = ((ins.data[1] | ins.data[2] << 8) + added) & 65535
            elif mode in ('idx', 'idy', 'zpi'):
                pointer = (ins.data[1] + (index('x') if mode == 'idx' else 0)) & 255
                low = read(0x2000 + pointer, 'pointer-low')
                high = read(0x2000 + ((pointer + 1) & 255), 'pointer-high')
                logical = ((low | high << 8) + (index('y') if mode == 'idy' else 0)) & 65535
            else:
                raise _Boundary('unsupported_data_mode')
            record.update(status='resolved', value=read(logical, 'value'))
        except _Boundary as error:
            record.update(status='unknown', reason=error.reason, detail=error.detail)
        return record

    # Every seed must be wholly inside explicit code ranges. A later traversal
    # boundary is a reported frontier, not a reason to remove an original seed.
    for key in seed_keys:
        try:
            instruction(key)
        except _Boundary as error:
            raise ValueError('An original seed fetch is outside the allowed ROM view: ' + error.reason) from error
    unknown = (None,) * (9 if branch_facts else 6 if alu_facts else 3)
    if stack_facts:
        unknown += (None, ())
    if wram_facts:
        unknown += ((None,) * len(slots),)
    pending, queued = deque(), set()
    facts, contexts, successors, problems, vectors = {}, set(), {}, {}, {}
    tables, table_cache, table_states = {}, {}, set()
    callsites, returns, loads = {}, {}, {}
    evaluations, operands = {}, {}
    conditions, stack_events = {}, {}
    wram_events, wram_vectors = {}, {}
    block_events, block_states, wram_tables, wram_table_states = {}, {}, {}, set()
    block_bytes = 0
    mapper_events = {}
    interrupt_sites, interrupt_entries, interrupt_returns = {}, {}, {}

    def interrupt_frame(frame):
        return software_interrupts and instruction(frame[0])[0].mnemonic == 'BRK'

    def frame_bytes(frame):
        return 3 if interrupt_frame(frame) else 2

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
            merged = (stack_values.join(facts[key], incoming) if stack_facts else
                      tuple(left if left == right else None for left, right in zip(facts[key], incoming)))
            if wram_facts:
                merged += (tuple(a if a == b else None for a,b in zip(facts[key][11], incoming[11])),)
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
        selector, mpr, pc = key[:3]
        next_selector = selector
        mapper_events.pop(key, None)
        interrupt_sites.pop(key, None)
        interrupt_entries.pop(key, None)
        interrupt_returns.pop(key, None)
        frames, depth = key[3] if calls else ((), 0)
        next_stack = (frames, depth)
        ins, _ = instruction(key)
        successors[key], problems[key] = [], []
        vectors.pop(key, None)
        tables.pop(key, None)
        callsites.pop(key, None)
        returns.pop(key, None)
        loads.pop(key, None)
        operands.pop(key, None)
        conditions.pop(key, None)
        stack_events.pop(key, None)
        wram_events.pop(key, None)
        wram_vectors.pop(key, None)
        block_events.pop(key, None)
        wram_tables.pop(key, None)
        operand = None
        if alu_facts and (data_ranges is not None or wram_facts) and ins.mnemonic in ALU and ins.mode != 'imm':
            record = data_fact(key, ins, facts[key])
            operands[key] = record
            if record['status'] == 'resolved':
                operand = record['value']
        if alu_facts:
            outgoing, reason = evaluate(ins, facts[key][:6], mpr, operand)
            evaluations[key] = reason
        else:
            outgoing = _register_facts(ins, facts[key], mpr)
        name = ins.mnemonic
        if (data_ranges is not None or wram_facts) and name in ('LDA', 'LDX', 'LDY') and ins.mode != 'imm':
            record = data_fact(key, ins, facts[key])
            loads[key] = record
            if record['status'] == 'resolved':
                values = list(outgoing)
                values[('a', 'x', 'y').index(record['register'])] = record['value']
                outgoing = tuple(values)
        if branch_facts:
            outgoing = extend_status(ins, facts[key][:9], outgoing, operand)
        memory = None
        block_refusal = None
        if wram_facts:
            reads = []
            read = lambda logical,role,memory=None,selector=None: value_read(key, facts[key], logical, role, reads, memory=memory, selector=selector)
            if memory_flow and name in wram_values.BLOCKS:
                plan, pairs = flow.plan_block(ins, mpr, depth, profile, block_transfer_limit, allow_mapper=mapper_facts)
                if pairs is not None and key not in block_states and block_bytes+plan['length'] > flow.MAX_BLOCK_BYTES:
                    plan.update(status='blocked', reason='block_state_limit')
                    pairs = None
                if pairs is None:
                    block_refusal = plan['reason']
                    memory = facts[key][11]
                    effect = plan
                else:
                    if key not in block_states:
                        block_bytes += plan['length']
                    block_states[key] = plan['length']
                    outgoing, memory, effect = flow.propagate_block(plan, pairs, facts[key], outgoing, mpr, slots, read, mapper_selector=selector if mapper_facts else None)
                    if mapper_facts:
                        next_selector = effect['selector_after']
                        mapper_events[key] = dict(operation=name, selector_before=selector, selector_after=next_selector, writes=effect['mapper_writes'],
                            transitions=sum(r['selector_before'] != r['selector_after'] for r in effect['transfers']),
                            window_changes=sum(r['selector_before']%4 != r['selector_after']%4 for r in effect['transfers']))
                effect['reads'] = reads
                block_events[key] = effect
            else:
                outgoing, memory, effect = wram_values.effects(ins, facts[key], outgoing, mpr, slots, read, operand)
                if effect is not None:
                    effect['reads'] = reads
                    wram_events[key] = effect
        if alu_facts:
            evaluations[key] = dict(registers=dict(zip(('a', 'x', 'y'), outgoing[:3])),
                flags=dict(zip(FLAGS if branch_facts else ('c', 'd', 't'), outgoing[3:])), reason=evaluations[key])
        stack_write_barrier = _stack_write_barrier(ins, mpr, facts[key])
        if wram_facts and stack_write_barrier and 'logical_address' in wram_events.get(key, {}):
            canonical = wram_values.canonical(wram_events[key]['physical'])
            stack_write_barrier = canonical is not None and 256 <= canonical < 512
        mapper_barrier = _mapper_barrier(ins, mpr, profile)
        if memory_flow and mapper_barrier and 'logical_address' in wram_events.get(key, {}):
            mapper_barrier = flow.mapper_address(wram_events[key]['physical'])
        if mapper_facts and mapper_barrier and 'logical_address' in wram_events.get(key, {}):
            effect = wram_events[key]
            next_selector = effect['physical'] & 15
            mapper_events[key] = dict(operation=name, logical_address=effect['logical_address'],
                physical=effect['physical'], selector_before=selector, selector_after=next_selector,
                writes=1, transitions=int(selector != next_selector),
                window_changes=int(selector%4 != next_selector%4), selection_source='write_address')
            mapper_barrier = False
        if memory_flow and name in wram_values.BLOCKS and block_refusal is None:
            mapper_barrier = stack_write_barrier = False
        targets = []
        if block_refusal is not None:
            problems[key].append(dict(reason=block_refusal, resume_pc=ins.next_pc))
        elif mapper_barrier:
            problems[key].append(dict(reason='mapper_write_barrier', resume_pc=ins.next_pc))
        elif (frames or stack_facts and depth) and stack_write_barrier:
            problems[key].append(dict(reason='stack_write_barrier', resume_pc=ins.next_pc))
        elif (frames or stack_facts and depth) and name == 'TXS':
            problems[key].append(dict(reason='stack_pointer_change', resume_pc=ins.next_pc))
        elif (frames or stack_facts) and name in stack_values.PUSHES:
            if stack_facts and not 0xF8 <= mpr[1] <= 0xFB:
                problems[key].append(dict(reason='unsupported_stack_mapping', resume_pc=ins.next_pc))
            elif depth == 256:
                problems[key].append(dict(reason='stack_capacity'))
            else:
                next_stack = frames, depth + 1
                targets = [(mpr, ins.next_pc, 'fallthrough')]
        elif (frames or stack_facts) and name in stack_values.POPS:
            if stack_facts and not 0xF8 <= mpr[1] <= 0xFB:
                problems[key].append(dict(reason='unsupported_stack_mapping', resume_pc=ins.next_pc))
            elif not depth:
                problems[key].append(dict(reason='stack_underflow'))
            elif frames and depth <= frames[-1][2] + frame_bytes(frames[-1]):
                problems[key].append(dict(reason='stack_frame_pop'))
            else:
                next_stack = frames, depth - 1
                targets = [(mpr, ins.next_pc, 'fallthrough')]
        elif name in BRANCHES or ins.mode == 'zrl':
            targets = [(mpr, ins.target, 'taken'), (mpr, ins.next_pc, 'fallthrough')]
            if branch_facts:
                if name in BRANCHES:
                    condition = flag_decision(name, facts[key])
                else:
                    bit = int(name[-1]); expected = int(name.startswith('BBS'))
                    condition = dict(bit=bit, expected=expected, decision='both', reads=[])
                    logical = 0x2000 + ins.data[1]
                    if wram_facts:
                        try:
                            value = value_read(key, facts[key], logical, 'bit-value', condition['reads'])
                        except _Boundary as error:
                            condition.update(reason=error.reason, detail=error.detail)
                        else:
                            condition.update(value=value, decision='taken' if ((value >> bit) & 1) == expected else 'fallthrough')
                    elif data_ranges is None:
                        condition.update(reason='missing_data_permission')
                    else:
                        try:
                            source = offset(key, logical, data=True)
                        except _Boundary as error:
                            condition.update(reason=error.reason, detail=error.detail)
                        else:
                            value = rom[source]
                            condition.update(value=value, reads=[dict(logical_address=logical,
                                physical=physical(logical,mpr), rom_offset=source, value=value)],
                                decision='taken' if ((value >> bit) & 1) == expected else 'fallthrough')
                conditions[key] = condition
                if condition['decision'] != 'both':
                    targets = [target for target in targets if target[2] == condition['decision']]
        elif software_interrupts and name == 'BRK':
            entry = dict(vector_address=0xFFF6, resume_pc=ins.next_pc, frame_bytes=3, reads=[], status='blocked')
            interrupt_entries[key] = entry
            if not 0xF8 <= mpr[1] <= 0xFB:
                entry['reason'] = 'unsupported_stack_mapping'
            elif len(frames) == call_depth_limit:
                entry['reason'] = 'call_depth_limit'
            elif depth+3 > 256:
                entry['reason'] = 'stack_capacity'
            else:
                try:
                    pair = [value_read(key, facts[key], address, role, entry['reads'], vector=True)
                        for address,role in ((0xFFF6,'interrupt-vector-low'),(0xFFF7,'interrupt-vector-high'))]
                except _Boundary as error:
                    entry.update(reason=error.reason, detail=error.detail)
                else:
                    target = pair[0] | pair[1] << 8
                    entry.update(status='resolved', target=target)
                    next_stack = frames + ((key[:3],ins.next_pc,depth),), depth+3
                    targets = [(mpr,target,'software_interrupt')]
                    interrupt_sites[key] = ins.next_pc
            if entry['status'] == 'blocked':
                problems[key].append(dict(reason=entry['reason'], **entry.get('detail',{})))
        elif software_interrupts and name == 'RTI':
            if not frames or not interrupt_frame(frames[-1]):
                problems[key].append(dict(reason='unmatched_interrupt_return'))
            else:
                caller,resume,saved_depth = frames[-1]
                if depth != saved_depth+3:
                    problems[key].append(dict(reason='unbalanced_interrupt_return'))
                elif facts[key][10][-3:-1] != ((255,resume>>8),(255,resume&255)):
                    problems[key].append(dict(reason='unproven_interrupt_return_word'))
                else:
                    next_stack = frames[:-1], saved_depth
                    targets = [(mpr,resume,'interrupt_return')]
                    interrupt_returns[key] = caller + (next_stack,)
        elif name in ('JSR', 'BSR'):
            if not calls:
                targets = [(mpr, ins.target, 'call')]
                problems[key].append(dict(reason='dynamic_return_site', resume_pc=ins.next_pc))
            elif not 0xF8 <= mpr[1] <= 0xFB:
                problems[key].append(dict(reason='unsupported_stack_mapping', resume_pc=ins.next_pc))
            elif len(frames) == call_depth_limit:
                problems[key].append(dict(reason='call_depth_limit', resume_pc=ins.next_pc))
            elif depth + 2 > 256:
                problems[key].append(dict(reason='stack_capacity', resume_pc=ins.next_pc))
            else:
                frame = key[:3], ins.next_pc, depth
                next_stack = frames + (frame,), depth + 2
                targets = [(mpr, ins.target, 'call')]
                callsites[key] = ins.next_pc
        elif name == 'RTS' and frames:
            caller, resume, saved_depth = frames[-1]
            if interrupt_frame(frames[-1]):
                problems[key].append(dict(reason='wrong_return_frame_kind'))
            elif depth != saved_depth + 2:
                problems[key].append(dict(reason='unbalanced_return'))
            elif stack_facts and facts[key][10][-2:] != (
                    (255, ((resume - 1) & 65535) >> 8), (255, (resume - 1) & 255)):
                problems[key].append(dict(reason='unproven_return_word'))
            else:
                next_stack = frames[:-1], saved_depth
                targets = [(mpr, resume, 'return')]
                returns[key] = caller + (next_stack,)
        elif name in ('JMP', 'BRA') and ins.target is not None:
            targets = [(mpr, ins.target, 'jump')]
        elif name == 'JMP' and (vector_ranges is not None or wram_facts):
            # Only caller-authorized immutable ROM bytes, never RAM guesses.
            # The default requires known X; opt-in tables enumerate its domain.
            # Both pointer reads use their own MPR page and full 16-bit wrap.
            index = facts[key][1] if ins.mode == 'iax' else 0
            base = ins.data[1] | ins.data[2] << 8
            mutable = wram_facts and any(wram_values.canonical(physical((base+i)&65535,mpr)) is not None
                for i in (range(257) if index is None else (index,index+1)))
            if mutable:
                if index is None and memory_flow and wram_table_limit is not None:
                    if key not in wram_table_states and len(wram_table_states)==wram_table_limit:
                        problems[key].append(dict(reason='wram_table_limit'))
                    else:
                        wram_table_states.add(key)
                        entries, blocked = [], []
                        for candidate in range(256):
                            logical = [(base+candidate)&65535, (base+candidate+1)&65535]
                            record = dict(index=candidate, logical_addresses=logical, reads=[])
                            try:
                                pair = [value_read(key, facts[key], address, role, record['reads'], vector=True)
                                    for address,role in zip(logical,('pointer-low','pointer-high'))]
                            except _Boundary as error:
                                record.update(reason=error.reason, detail=error.detail)
                                blocked.append(record)
                                problems[key].append(dict(reason=error.reason, vector_index=candidate, **error.detail))
                            else:
                                record['target'] = pair[0] | pair[1] << 8
                                entries.append(record)
                        wram_tables[key] = dict(base=base, index_domain=[0,255], source_complete=not blocked,
                            entries=entries, blocked=blocked)
                        targets = [(mpr,e['target'],'wram_vector',e['index']) for e in entries]
                else:
                    record = dict(base=base, index=index, reads=[], status='unknown')
                    wram_vectors[key] = record
                    if index is None:
                        record['reason'] = 'wram_vector_index_unknown'
                        problems[key].append(dict(reason=record['reason']))
                    else:
                        logical = [(base+index)&65535, (base+index+1)&65535]
                        record['logical_addresses'] = logical
                        try:
                            pair = [value_read(key, facts[key], address, role, record['reads'], vector=True)
                                for address,role in zip(logical,('pointer-low','pointer-high'))]
                        except _Boundary as error:
                            record.update(reason=error.reason, detail=error.detail)
                            problems[key].append(dict(reason=error.reason, **error.detail))
                        else:
                            target = pair[0] | pair[1] << 8
                            record.update(status='resolved', target=target)
                            targets = [(mpr, target, 'wram_vector')]
            elif index is None and rom_table_limit is not None:
                # X is an eight-bit register: enumerate its complete domain,
                # not guessed aligned entries or an arbitrary numeric prefix.
                # Cache immutable pointer evidence per full source view, not
                # per calling frame. Reprocessing cannot consume its site twice.
                view = key[:3]
                if view not in table_cache and len(table_cache) == rom_table_limit:
                    problems[key].append(dict(reason='rom_table_limit'))
                elif key not in table_states and len(table_states) == MAX_ROM_TABLE_STATES:
                    problems[key].append(dict(reason='rom_table_state_limit'))
                else:
                    table_states.add(key)
                    if view not in table_cache:
                        base = ins.data[1] | ins.data[2] << 8
                        entries, blocked = [], []
                        for candidate in range(256):
                            logical = [(base + candidate) & 65535, (base + candidate + 1) & 65535]
                            try:
                                offsets = [offset(key, address, vector=True) for address in logical]
                            except _Boundary as error:
                                blocked.append(dict(reason=error.reason, vector_index=candidate, **error.detail))
                            else:
                                entries.append(dict(index=candidate, logical_addresses=logical,
                                    rom_offsets=offsets, target=rom[offsets[0]] | rom[offsets[1]] << 8))
                        table_cache[view] = (dict(base=base, index_domain=[0, 255],
                            source_complete=not blocked, entries=entries), blocked)
                    table, blocked = table_cache[view]
                    tables[key] = table
                    problems[key].extend(blocked)
                    targets = [(mpr, entry['target'], 'rom_vector', entry['index'])
                               for entry in table['entries']]
            elif index is None:
                problems[key].append(dict(reason='indirect_index_unknown'))
            else:
                base = ins.data[1] | ins.data[2] << 8
                logical = [(base + index) & 65535, (base + index + 1) & 65535]
                try:
                    offsets = [offset(key, address, vector=True) for address in logical]
                except _Boundary as error:
                    problems[key].append(dict(reason=error.reason, **error.detail))
                else:
                    target = rom[offsets[0]] | rom[offsets[1]] << 8
                    vectors[key] = dict(base=base, index=index, logical_addresses=logical,
                                        rom_offsets=offsets, target=target)
                    targets = [(mpr, target, 'rom_vector')]
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
                if (frames or stack_facts and depth) and not 0xF8 <= mapped[1] <= 0xFB:
                    problems[key].append(dict(reason='stack_mapping_change', resume_pc=ins.next_pc))
                else:
                    targets = [(mapped, ins.next_pc, 'mapping_change' if mask else 'fallthrough')]
        else:
            targets = [(mpr, ins.next_pc, 'fallthrough')]
        if stack_facts:
            outgoing, event = stack_values.transfer(ins, facts[key], outgoing, admitted=bool(targets), software_interrupts=software_interrupts)
            if targets and len(outgoing[10]) != next_stack[1]:
                raise ValueError('Stack transfer disagrees with bounded depth')
            if event is not None:
                stack_events[key] = event
            evaluations[key] = dict(registers=dict(zip(('a', 'x', 'y'), outgoing[:3])),
                flags=dict(zip(stack_values.FLAGS, outgoing[3:10])),
                reason='saved_stack_bits' if name in stack_values.POPS and targets else evaluations[key]['reason'])
        if wram_facts:
            outgoing += (memory,)
        for target_spec in targets:
            mapped, target_pc, kind = target_spec[:3]
            vector_index = target_spec[3] if len(target_spec) == 4 else None
            incoming = outgoing if vector_index is None else (outgoing[0], vector_index, *outgoing[2:])
            if key in conditions:
                incoming = refine(incoming, conditions[key], kind)
            target = next_selector, mapped, target_pc
            if calls:
                target += (next_stack,)
            refused = offer(target, incoming)
            if refused:
                problem = dict(refused, target=_address(target), kind=kind)
                if vector_index is not None:
                    problem['vector_index'] = vector_index
                problems[key].append(problem)
            else:
                successors[key].append((target, kind, vector_index))

    # Monotone joins can invalidate an earlier constant-A TAM edge. Retain only
    # states connected to the current seed graph, not stale optimistic branches.
    reachable, todo = set(), deque(seed_keys)
    while todo:
        key = todo.popleft()
        if key in reachable:
            continue
        reachable.add(key)
        todo.extend(edge[0] for edge in successors.get(key, ()))
    ordered = sorted(reachable, key=lambda key: (key[1], key[2], key[0], key[3:]))
    node_ids = {key: index for index, key in enumerate(ordered)}
    roots, nodes, edges, unresolved = [], [], [], []
    source_keys, occupied, overlap_bytes = set(), {}, {}
    root_views = set()
    returned_calls = {returns[key] for key in reachable if key in returns}
    returned_interrupts = {interrupt_returns[key] for key in reachable if key in interrupt_returns}
    for key in ordered:
        ins, offsets = instruction(key)
        node_id = node_ids[key]
        root = _address(key) | dict(rom_offsets=list(offsets))
        new_root = key[:3] not in root_views
        if new_root:
            roots.append(root)
            root_views.add(key[:3])
        nodes.append(root | dict(node_id=node_id, mnemonic=ins.mnemonic, mode=ins.mode,
            target=ins.target, register_facts=dict(zip(('a', 'x', 'y'), facts[key]))))
        if key in vectors:
            nodes[-1]['rom_vector'] = vectors[key]
        if key in tables:
            nodes[-1]['rom_vector_table'] = tables[key]
        if key in loads:
            nodes[-1]['data_load' if wram_facts else 'rom_data_load'] = loads[key]
        if alu_facts:
            names = stack_values.FLAGS if stack_facts else FLAGS if branch_facts else ('c', 'd', 't')
            nodes[-1]['flag_facts'] = dict(zip(names, facts[key][3:10] if stack_facts else facts[key][3:]))
            nodes[-1]['register_evaluation'] = evaluations[key]
            if key in operands:
                nodes[-1]['alu_operand' if wram_facts else 'rom_alu_operand'] = operands[key]
        if wram_facts:
            nodes[-1]['wram_facts'] = [dict(offset=offset, value=facts[key][11][pos]) for offset,pos in slots.items()]
            if key in wram_events:
                nodes[-1]['wram_effect'] = wram_events[key]
            if key in wram_vectors:
                nodes[-1]['wram_vector'] = wram_vectors[key]
        if memory_flow:
            if key in block_events:
                nodes[-1]['block_effect'] = block_events[key]
            if key in wram_tables:
                nodes[-1]['wram_vector_table'] = wram_tables[key]
        if mapper_facts and key in mapper_events:
            nodes[-1]['mapper_effect'] = mapper_events[key]
        if key in conditions:
            nodes[-1]['conditional'] = conditions[key]
        if stack_facts:
            nodes[-1]['stack_facts'] = [dict(known_mask=mask, value=value) for mask,value in facts[key][10]]
            if key in stack_events:
                nodes[-1]['stack_event'] = stack_events[key]
        if calls:
            frames, depth = key[3]
            nodes[-1]['stack_bytes'] = depth
            nodes[-1]['call_stack'] = [dict(caller=_address(caller) | dict(
                rom_offsets=list(instruction(caller)[1])), resume_pc=resume,
                stored_return_word=resume if interrupt_frame((caller,resume,saved)) else (resume - 1) & 65535, depth_before=saved,
                **(dict(kind='software_interrupt', frame_bytes=3) if interrupt_frame((caller,resume,saved)) else {}))
                for caller, resume, saved in frames]
            if key in callsites:
                nodes[-1]['return_site'] = dict(resume_pc=callsites[key],
                                               candidate_return=key in returned_calls)
                if key not in returned_calls:
                    unresolved.append(_address(key) | dict(node_id=node_id,
                        reason='unresolved_call_return', resume_pc=callsites[key]))
        if software_interrupts:
            if key in interrupt_entries:
                nodes[-1]['software_interrupt'] = interrupt_entries[key]
            if key in interrupt_sites:
                nodes[-1]['interrupt_return_site'] = dict(resume_pc=interrupt_sites[key], candidate_return=key in returned_interrupts)
                if key not in returned_interrupts:
                    unresolved.append(_address(key) | dict(node_id=node_id, reason='unresolved_software_return', resume_pc=interrupt_sites[key]))
            if key in interrupt_returns:
                nodes[-1]['interrupt_return'] = dict(caller=_address(interrupt_returns[key]), resume_pc=key[3][0][-1][1])
        source_keys.add(instruction_key(ins.report() | {'mpr': key[1]}))
        for target, kind, vector_index in successors.get(key, ()):
            edge = dict(from_id=node_id, to_id=node_ids[target], kind=kind)
            if vector_index is not None:
                edge['vector_index'] = vector_index
            edges.append(edge)
        for problem in problems.get(key, ()):
            unresolved.append(_address(key) | dict(node_id=node_id) | problem)
        for index, rom_offset in enumerate(offsets if new_root else ()):
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
            overlaps=len(overlaps), native_supported=sum(
                    instruction(key)[0].native for key in {key[:3] for key in ordered}),
            limit_reached=any(item['reason'] in ('instruction_limit', 'context_limit',
                'call_depth_limit', 'stack_capacity', 'rom_table_limit', 'rom_table_state_limit',
                'block_transfer_limit','block_state_limit','wram_table_limit') for item in unresolved),
            execution_evidence=False))
    if vector_ranges is not None:
        report['summary']['resolved_vectors'] = sum(key in vectors or bool(tables.get(key, {}).get('entries')) for key in ordered)
    if rom_table_limit is not None:
        report['summary'].update(enumerated_vector_sites=sum(key in tables for key in ordered),
            explored_vector_tables=len(table_cache),
            explored_vector_table_states=len(table_states),
            resolved_vector_entries=sum(len(tables[key]['entries']) if key in tables else int(key in vectors)
                                        for key in ordered))
    if calls:
        report['summary'].update(call_states=len(nodes), resolved_returns=sum(key in returns for key in ordered),
            calls_with_candidate_returns=sum(key in returned_calls for key in callsites if key in reachable),
            calls_without_candidate_returns=sum(key not in returned_calls for key in callsites if key in reachable))
    if data_ranges is not None and not wram_facts:
        report['summary'].update(resolved_rom_data_loads=sum(key in loads and loads[key]['status'] == 'resolved' for key in ordered),
            unknown_rom_data_loads=sum(key in loads and loads[key]['status'] == 'unknown' for key in ordered))
    if alu_facts:
        report['summary'].update(register_evaluations=len(nodes),
            **{('resolved_alu_operands' if wram_facts else 'resolved_rom_alu_operands'):sum(key in operands and operands[key]['status'] == 'resolved' for key in ordered),
            ('unknown_alu_operands' if wram_facts else 'unknown_rom_alu_operands'):sum(key in operands and operands[key]['status'] == 'unknown' for key in ordered)})
    if branch_facts:
        decided = sum(key in conditions and conditions[key]['decision'] != 'both' for key in ordered)
        report['summary'].update(conditional_states=sum(key in conditions for key in ordered),
            decided_conditionals=decided, pruned_conditional_edges=decided,
            unknown_conditionals=sum(key in conditions and conditions[key]['decision'] == 'both' for key in ordered))
    if stack_facts:
        report['summary'].update(stack_transfers=sum(key in stack_events for key in ordered),
            stack_pops=sum(key in stack_events and instruction(key)[0].mnemonic in stack_values.POPS for key in ordered),
            peak_stack_bytes=max(key[3][1] for key in ordered))
    if wram_facts:
        report['summary'].update(tracked_wram_bytes=len(slots),
            resolved_data_loads=sum(key in loads and loads[key]['status']=='resolved' for key in ordered),
            unknown_data_loads=sum(key in loads and loads[key]['status']=='unknown' for key in ordered),
            wram_effects=sum(key in wram_events for key in ordered),
            wram_invalidations=sum(key in wram_events and wram_events[key]['status']=='invalidated' for key in ordered),
            resolved_wram_vectors=sum(key in wram_vectors and wram_vectors[key]['status']=='resolved' for key in ordered))
    if memory_flow:
        report['summary'].update(explored_block_states=len(block_states), explored_block_bytes=block_bytes,
            analyzed_block_states=sum(key in block_events and block_events[key]['status']=='analyzed' for key in ordered),
            known_block_reads=sum(block_events[key].get('known_reads',0) for key in ordered if key in block_events),
            unknown_block_reads=sum(block_events[key].get('unknown_reads',0) for key in ordered if key in block_events),
            maximum_temporary_stack_depth=max([block_events[key].get('maximum_stack_depth',0) for key in ordered if key in block_events] or [0]),
            explored_wram_table_states=len(wram_table_states),
            resolved_wram_table_entries=sum(len(wram_tables[key]['entries']) for key in ordered if key in wram_tables))
    if mapper_facts:
        report['summary'].update(mapper_effects=sum(key in mapper_events for key in ordered),
            mapper_writes=sum(mapper_events[key]['writes'] for key in ordered if key in mapper_events),
            mapper_transitions=sum(mapper_events[key]['transitions'] for key in ordered if key in mapper_events),
            mapper_window_changes=sum(mapper_events[key]['window_changes'] for key in ordered if key in mapper_events))
    if software_interrupts:
        report['summary'].update(software_interrupt_entries=sum(key in interrupt_sites for key in ordered),
            software_interrupt_returns=sum(key in interrupt_returns for key in ordered),
            interrupts_with_candidate_returns=sum(key in returned_interrupts for key in interrupt_sites if key in reachable),
            interrupts_without_candidate_returns=sum(key not in returned_interrupts for key in interrupt_sites if key in reachable))
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


def _report(seeds, seed_raw, roots_raw, partial, ranges, instruction_limit, context_limit,
            vector_ranges=None, call_depth_limit=None, rom_table_limit=None, data_ranges=None, alu_facts=False, branch_facts=False, stack_facts=False, wram_facts=False, wram_ranges=None, memory_flow=False, block_transfer_limit=None, wram_table_limit=None, mapper_facts=False, software_interrupts=False):
    result = dict(format=FORMAT, schema=SCHEMA, execution_evidence=False, kind='static_candidates',
        analysis_policy=CALL_POLICY if call_depth_limit is not None else (
            POLICY if vector_ranges is None else VECTOR_POLICY),
        static_reachability='candidates_only', routine_closure=False,
        source=seeds.source_metadata,
        options=dict(rom_ranges=[dict(start=start, length=end - start) for start, end in ranges],
                     instruction_limit=instruction_limit, context_limit=context_limit),
        artifacts={SEEDS_NAME: dict(sha256=hashlib.sha256(seed_raw).hexdigest(), size_bytes=len(seed_raw)),
                   ROOTS_NAME: dict(sha256=hashlib.sha256(roots_raw).hexdigest(), size_bytes=len(roots_raw))},
        **partial)
    if vector_ranges is not None:
        result['options']['rom_vector_ranges'] = [dict(start=start, length=end - start)
                                                for start, end in vector_ranges]
    if call_depth_limit is not None:
        result['options']['call_depth_limit'] = call_depth_limit
    if rom_table_limit is not None:
        result['options']['rom_table_limit'] = rom_table_limit
        result['analysis_policy'] = TABLE_CALL_POLICY if call_depth_limit is not None else TABLE_POLICY
    if data_ranges is not None:
        result['options']['rom_data_ranges'] = [dict(start=start, length=end-start) for start, end in data_ranges]
        result['analysis_policy'] = DATA_POLICY
    if alu_facts:
        result['options']['alu_facts'] = True
        result['analysis_policy'] = EVAL_POLICY
    if branch_facts:
        result['options']['branch_facts'] = True
        result['analysis_policy'] = BRANCH_POLICY
    if stack_facts:
        result['options']['stack_facts'] = True
        result['analysis_policy'] = STACK_POLICY
    if wram_facts:
        result['options']['wram_facts'] = True
        result['options']['wram_data_ranges'] = [dict(start=start, length=end-start) for start,end in wram_ranges]
        result['analysis_policy'] = WRAM_POLICY
    if memory_flow:
        result['options'].update(memory_flow=True, block_transfer_limit=block_transfer_limit)
        if wram_table_limit is not None:
            result['options']['wram_table_limit'] = wram_table_limit
        result['analysis_policy'] = FLOW_POLICY
    if mapper_facts:
        result['options']['mapper_facts'] = True
        result['analysis_policy'] = MAPPER_POLICY
    if software_interrupts:
        result['options']['software_interrupts'] = True
        result['analysis_policy'] = SOFTWARE_POLICY
    return result


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
                   instruction_limit=10000, context_limit=256, rom_vector_ranges=None,
                   call_depth_limit=None, rom_table_limit=None, rom_data_ranges=None, alu_facts=False, branch_facts=False, stack_facts=False, wram_facts=False, wram_data_ranges=None, memory_flow=False, block_transfer_limit=None, wram_table_limit=None, mapper_facts=False, software_interrupts=False):
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
    vectors = None if rom_vector_ranges is None else _ranges(rom_vector_ranges, len(rom))
    data = None if rom_data_ranges is None else _ranges(rom_data_ranges, len(rom))
    wram = None if wram_data_ranges is None else _wram_ranges(wram_data_ranges)
    document, partial = _derive(seeds, rom, ranges, instruction_limit, context_limit, vectors, call_depth_limit, rom_table_limit, data, alu_facts, branch_facts, stack_facts, wram_facts, wram, memory_flow, block_transfer_limit, wram_table_limit, mapper_facts, software_interrupts)
    roots_raw = _canonical(document, MAX_DECLARATION_BYTES)
    report = _report(seeds, seed.raw, roots_raw, partial, ranges, instruction_limit, context_limit,
                     vectors, call_depth_limit, rom_table_limit, data, alu_facts, branch_facts, stack_facts, wram_facts, wram, memory_flow, block_transfer_limit, wram_table_limit, mapper_facts, software_interrupts)
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
            or report['analysis_policy'] not in (POLICY, VECTOR_POLICY, CALL_POLICY, TABLE_POLICY, TABLE_CALL_POLICY, DATA_POLICY, EVAL_POLICY, BRANCH_POLICY, STACK_POLICY, WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY)
            or report['static_reachability'] != 'candidates_only'
            or report['routine_closure'] is not False):
        raise ValueError('Unsupported discovery report contract')
    options = report['options']
    option_fields = {'rom_ranges', 'instruction_limit', 'context_limit'}
    if report['analysis_policy'] in (EVAL_POLICY, BRANCH_POLICY, STACK_POLICY, WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY):
        option_fields.add('alu_facts')
        if report['analysis_policy'] in (BRANCH_POLICY, STACK_POLICY, WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY):
            option_fields.add('branch_facts')
        if report['analysis_policy'] in (STACK_POLICY, WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY):
            option_fields.update(('stack_facts', 'call_depth_limit'))
        if report['analysis_policy'] in (WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY):
            option_fields.update(('wram_facts','wram_data_ranges'))
        if report['analysis_policy'] in (FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY):
            option_fields.update(('memory_flow','block_transfer_limit'))
            if report['analysis_policy'] == MAPPER_POLICY:
                option_fields.add('mapper_facts')
            if report['analysis_policy'] == SOFTWARE_POLICY:
                option_fields.add('software_interrupts')
                if type(options) is dict and 'mapper_facts' in options:
                    option_fields.add('mapper_facts')
            if type(options) is dict and 'wram_table_limit' in options:
                option_fields.add('wram_table_limit')
        if type(options) is dict:
            option_fields.update(set(options) & {'rom_vector_ranges', 'rom_table_limit', 'call_depth_limit', 'rom_data_ranges'})
    if report['analysis_policy'] == DATA_POLICY:
        option_fields.add('rom_data_ranges')
        if type(options) is dict:
            option_fields.update(set(options) & {'rom_vector_ranges', 'rom_table_limit', 'call_depth_limit'})
    if report['analysis_policy'] in (CALL_POLICY, TABLE_CALL_POLICY):
        option_fields.add('call_depth_limit')
    if report['analysis_policy'] in (TABLE_POLICY, TABLE_CALL_POLICY):
        option_fields.update(('rom_table_limit', 'rom_vector_ranges'))
    if (report['analysis_policy'] == VECTOR_POLICY or
            report['analysis_policy'] == CALL_POLICY and type(options) is dict and 'rom_vector_ranges' in options):
        option_fields.add('rom_vector_ranges')
    if type(options) is not dict or set(options) != option_fields:
        raise ValueError('Invalid discovery options')
    alu_facts = report['analysis_policy'] in (EVAL_POLICY, BRANCH_POLICY, STACK_POLICY, WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY)
    branch_facts = report['analysis_policy'] in (BRANCH_POLICY, STACK_POLICY, WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY)
    stack_facts = report['analysis_policy'] in (STACK_POLICY, WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY)
    wram_facts = report['analysis_policy'] in (WRAM_POLICY, FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY)
    memory_flow = report['analysis_policy'] in (FLOW_POLICY, MAPPER_POLICY, SOFTWARE_POLICY)
    software_interrupts = report['analysis_policy'] == SOFTWARE_POLICY
    if software_interrupts and options['software_interrupts'] is not True:
        raise ValueError('Software interrupt policy requires literal true')
    mapper_facts = report['analysis_policy'] == MAPPER_POLICY or software_interrupts and options.get('mapper_facts',False)
    if mapper_facts and options['mapper_facts'] is not True:
        raise ValueError('Mapper policy requires literal true')
    block_transfer_limit = options.get('block_transfer_limit')
    wram_table_limit = options.get('wram_table_limit')
    if memory_flow and options['memory_flow'] is not True:
        raise ValueError('Memory-flow policy requires literal true')
    if wram_facts and options['wram_facts'] is not True:
        raise ValueError('WRAM policy requires literal true')
    if stack_facts and options['stack_facts'] is not True:
        raise ValueError('Stack policy requires literal true')
    if alu_facts and options['alu_facts'] is not True:
        raise ValueError('Register evaluation policy requires literal true')
    if branch_facts and options['branch_facts'] is not True:
        raise ValueError('Branch policy requires literal true')
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
    vectors = None
    if 'rom_vector_ranges' in option_fields:
        recorded_vectors = options['rom_vector_ranges']
        if type(recorded_vectors) is not list or not 1 <= len(recorded_vectors) <= MAX_RANGES:
            raise ValueError('Invalid discovery ROM vector range list')
        for entry in recorded_vectors:
            if type(entry) is not dict or set(entry) != {'start', 'length'}:
                raise ValueError('Invalid discovery ROM vector range fields')
        vectors = _ranges([(entry['start'], entry['length']) for entry in recorded_vectors], len(rom))
    call_depth = options.get('call_depth_limit')
    if 'call_depth_limit' in option_fields:
        integer(call_depth, MAX_CALL_DEPTH, 'discovery call depth', 1)
    table_limit = options.get('rom_table_limit')
    if 'rom_table_limit' in option_fields:
        integer(table_limit, MAX_ROM_TABLE_SITES, 'ROM table site limit', 1)
    data = None
    if 'rom_data_ranges' in option_fields:
        recorded_data = options['rom_data_ranges']
        if type(recorded_data) is not list or not 1 <= len(recorded_data) <= MAX_RANGES:
            raise ValueError('Invalid discovery ROM data range list')
        for entry in recorded_data:
            if type(entry) is not dict or set(entry) != {'start', 'length'}:
                raise ValueError('Invalid discovery ROM data range fields')
        data = _ranges([(entry['start'], entry['length']) for entry in recorded_data], len(rom))
    wram = None
    if wram_facts:
        entries = options['wram_data_ranges']
        if (type(entries) is not list or not 1 <= len(entries) <= MAX_RANGES
                or any(type(e) is not dict or set(e) != {'start','length'} for e in entries)):
            raise ValueError('Invalid WRAM data range fields')
        wram = _wram_ranges([(e['start'], e['length']) for e in entries])
    document, partial = _derive(seeds, rom, ranges, options['instruction_limit'], options['context_limit'],
                                vectors, call_depth, table_limit, data, alu_facts, branch_facts, stack_facts, wram_facts, wram, memory_flow, block_transfer_limit, wram_table_limit, mapper_facts, software_interrupts)
    roots_raw = _canonical(document, MAX_DECLARATION_BYTES)
    if snapshots[ROOTS_NAME].raw != roots_raw:
        raise ValueError('Expanded numeric roots disagree with source-qualified derivation')
    expected = _report(seeds, snapshots[SEEDS_NAME].raw, roots_raw, partial, ranges,
                       options['instruction_limit'], options['context_limit'], vectors, call_depth, table_limit, data, alu_facts, branch_facts, stack_facts, wram_facts, wram, memory_flow, block_transfer_limit, wram_table_limit, mapper_facts, software_interrupts)
    if report_snapshot.raw != _canonical(expected, MAX_REPORT_BYTES):
        raise ValueError('Discovery report differs from recomputed derivation or canonical encoding')
    declarations = load_declarations(root / ROOTS_NAME, image_path)
    bindings = {name: dict(path=snapshot.path, sha256=snapshot.sha256, size_bytes=snapshot.size_bytes)
                for name, snapshot in {REPORT_NAME: report_snapshot, **snapshots,
                                       'source_image': image_snapshot}.items()}
    admitted = AdmittedDiscovery(path, report_snapshot.sha256, declarations, expected, bindings, store)
    admitted.revalidate()
    return admitted


def copy_discovery(path, image_path, output):
    """Copy an admitted three-file derivation without media or rewritten evidence.

    Output must be a new, separate directory. Recompute both graphs and retain
    exact original bytes; a partial copy is diagnostic output, never admission.
    """
    source = load_discovery(path, image_path)
    output = _path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Discovery copy requires a new directory')
    if output.is_relative_to(source.report_path.parent):
        raise ValueError('Discovery copy cannot modify its original closed graph')
    _directory(output.parent)
    if output.parent.samefile(source.report_path.parent):
        raise ValueError('Discovery copy cannot modify its original closed graph')
    source.revalidate()
    output.mkdir(exist_ok=False)
    for name in (SEEDS_NAME, ROOTS_NAME, REPORT_NAME):
        binding = source.artifact_bindings[name]
        snapshot = source._store.read_json(binding['path'], expected_sha256=binding['sha256'],
            max_bytes=MAX_REPORT_BYTES if name == REPORT_NAME else MAX_DECLARATION_BYTES)
        if snapshot.size_bytes != binding['size_bytes']:
            raise ValueError('Original discovery artifact size changed')
        source.revalidate()
        _write_new(output / name, snapshot.raw)  # The report is published last.
    copied = load_discovery(output, image_path)
    source.revalidate()
    if copied.sha256 != source.sha256:
        raise ValueError('Copied discovery differs from its original derivation')
    return copied
