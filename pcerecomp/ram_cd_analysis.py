"""Bounded candidate traversal of authenticated, mutable RAM/CD source bytes.

Adapters own source authentication and effective code/data permissions. Nothing
here makes snapshot RAM immutable or establishes execution or routine closure.
"""
from collections import deque

from .analysis import _register_facts
from .capture import integer
from .declarations import instruction_key, _sort_key
from .isa import BRANCHES, physical

MAX_STATES = 100000
MAX_CONTEXTS = 4096
MAX_CALL_DEPTH = 64
ANALYSIS_POLICY = 'bounded-ram-cd-candidates-v1'
_WRITERS = {'STA', 'STX', 'STY', 'STZ', 'ASL', 'LSR', 'ROL', 'ROR',
            'INC', 'DEC', 'TSB', 'TRB'}
_PUSH = {'PHA', 'PHP', 'PHX', 'PHY'}
_POP = {'PLA', 'PLP', 'PLX', 'PLY'}


def derive(entries, mapping, *, fetch, is_code, is_ram, canonical,
           instruction_limit, context_limit, call_depth_limit=None):
    """Return a deterministic graph, declarations and source-provenance roots.

    Relative stack depth is symbolic: the source SP is deliberately unknown.
    Frames prove balanced return words only; popped register values are unknown.
    """
    integer(instruction_limit, MAX_STATES, 'RAM/CD state limit', 1)
    integer(context_limit, MAX_CONTEXTS, 'RAM/CD context limit', 1)
    if call_depth_limit is not None:
        integer(call_depth_limit, MAX_CALL_DEPTH, 'RAM/CD call depth', 1)
    if type(entries) is not list or not 1 <= len(entries) <= 256:
        raise ValueError('RAM/CD entries require one to 256 sorted unique logical PCs')
    for pc in entries:
        integer(pc, 65535, 'RAM/CD entry')
    if entries != sorted(set(entries)):
        raise ValueError('RAM/CD entries require sorted unique logical PCs')
    if type(mapping) not in (list, tuple) or len(mapping) != 8:
        raise ValueError('RAM/CD mapping requires eight byte values')
    for bank in mapping:
        integer(bank, 255, 'RAM/CD mapping bank')
    mapping = tuple(mapping)
    if len(entries) > instruction_limit:
        raise ValueError('RAM/CD seeds exceed state limit')

    def state_json(state):
        pc, mpr, facts, transfer, frames, depth = state
        return dict(pc=pc, mpr=list(mpr), registers=list(facts), transfer=transfer,
                    frames=[dict(pc=f[0], mpr=list(f[1]), continuation=f[2],
                                 depth=f[3]) for f in frames], stack_depth=depth)

    def write_barrier(ins, mpr, facts, transfer, frames):
        name, mode = ins.mnemonic, ins.mode
        if mode == 'blk':
            return 'block_transfer_changes_memory'
        if name in ('ST0', 'ST1', 'ST2'):
            return 'opaque_device_write'
        targets = []
        implicit_stack = name in _PUSH or name in ('JSR', 'BSR')
        if implicit_stack:
            targets = range(0x2100, 0x2200)
        elif name in ('ADC', 'AND', 'EOR', 'ORA') and transfer != 0:
            targets = (0x2000 + x for x in
                       (range(256) if facts[1] is None else (facts[1],)))
        elif (name in _WRITERS or name.startswith(('RMB', 'SMB'))) and mode != 'acc':
            if mode in ('zpg', 'zpx', 'zpy'):
                index = None if mode == 'zpg' else facts[1 if mode == 'zpx' else 2]
                offsets = (0,) if mode == 'zpg' else range(256) if index is None else (index,)
                targets = (0x2000 + ((ins.data[1] + i) & 255) for i in offsets)
            elif mode in ('abs', 'abx', 'aby'):
                base = ins.data[1] | ins.data[2] << 8
                index = None if mode == 'abs' else facts[1 if mode == 'abx' else 2]
                offsets = (0,) if mode == 'abs' else range(256) if index is None else (index,)
                targets = ((base + i) & 65535 for i in offsets)
            else:
                return 'unknown_write_target'
        for logical in targets:
            pa = canonical(physical(logical, mpr))
            # Physical aliases matter too: another logical page can map WRAM.
            if frames and not implicit_stack and 0x1F0100 <= pa < 0x1F0200:
                return 'stack_write_barrier'
            if not is_ram(pa):
                return 'write_not_proven_ram'
            if is_code(pa):
                return 'possible_code_write'
        return None

    initial = [(pc, mapping, (None, None, None), None, (), 0) for pc in entries]
    for state in initial:
        try:
            fetch(state[0], state[1])
        except ValueError as error:
            raise ValueError('RAM/CD seed is not wholly in authenticated allowed code: ' + str(error)) from error
    queue, scheduled = deque(initial), set(initial)
    nodes, edges, frontiers, overlaps = [], [], [], []
    contexts, union, roots, occupied = {mapping}, {}, {}, {}
    while queue:
        if len(nodes) >= instruction_limit:
            frontiers.append(dict(reason='state_limit', pending_states=len(queue)))
            break
        state = queue.popleft()
        pc, mpr, facts, transfer, frames, depth = state
        try:
            ins, locations = fetch(pc, mpr)
        except ValueError as error:
            frontiers.append(dict(state=state_json(state), reason=str(error)))
            continue
        declaration = ins.report() | dict(mpr=mpr)
        key = instruction_key(declaration)
        union[key] = declaration
        roots[key] = dict(pc=pc, mpr=list(mpr), fetch=locations)
        index = len(nodes)
        nodes.append(dict(id=index, **state_json(state), fetch=locations,
                          mnemonic=ins.mnemonic, mode=ins.mode))
        for address in ins.physical:
            address = canonical(address)
            if address in occupied and occupied[address] != pc:
                overlaps.append(dict(physical=address, pc=pc, other=occupied[address]))
            occupied[address] = pc

        def stop(reason, **detail):
            frontiers.append(dict(node=index, reason=reason, **detail))

        barrier = write_barrier(ins, mpr, facts, transfer, frames)
        if barrier:
            stop(barrier)
            continue
        if not ins.native:
            stop('unsupported_instruction')
            continue
        name = ins.mnemonic
        if name in ('RTI', 'BRK'):
            stop('interrupt_return' if name == 'RTI' else 'interrupt_vector')
            continue
        if name == 'JMP' and ins.target is None:
            stop('indirect_jump')
            continue
        updated = tuple(_register_facts(ins, facts, mpr))
        next_mpr = mpr
        if name == 'TAM' and ins.data[1]:
            if facts[0] is None:
                stop('unknown_mapping_value')
                continue
            next_mpr = tuple(facts[0] if ins.data[1] & (1 << i) else bank
                             for i, bank in enumerate(mpr))
        next_t = 1 if name == 'SET' else None if name == 'PLP' else 0
        next_frames, next_depth = frames, depth
        if call_depth_limit is not None:
            if (frames or depth or name in _PUSH or name in ('JSR', 'BSR')) and not 0xF8 <= next_mpr[1] <= 0xFB:
                stop('unsupported_stack_mapping')
                continue
            if name == 'TXS':
                if frames or depth:
                    stop('stack_pointer_write_barrier')
                    continue
                next_depth = 0
            elif name in _PUSH:
                if depth >= 256:
                    stop('stack_depth_limit')
                    continue
                next_depth += 1
            elif name in _POP:
                floor = frames[-1][3] + 2 if frames else 0
                if depth <= floor:
                    stop('stack_return_word_pop' if frames else 'unproven_stack_pop')
                    continue
                next_depth -= 1
            elif name in ('JSR', 'BSR'):
                if len(frames) >= call_depth_limit:
                    stop('call_depth_limit', continuation=ins.next_pc)
                    continue
                if depth > 254:
                    stop('stack_depth_limit')
                    continue
                next_frames = frames + ((pc, mpr, ins.next_pc, depth),)
                next_depth = depth + 2
            elif name == 'RTS':
                if not frames:
                    stop('dynamic_return')
                    continue
                frame = frames[-1]
                if depth != frame[3] + 2:
                    stop('unbalanced_return_stack')
                    continue
                next_frames, next_depth = frames[:-1], frame[3]
        elif name == 'RTS':
            stop('dynamic_return')
            continue

        if name in BRANCHES or ins.mode == 'zrl':
            successors = [(ins.target, 'taken'), (ins.next_pc, 'fallthrough')]
        elif name in ('JSR', 'BSR'):
            successors = [(ins.target, 'call')]
            if call_depth_limit is None:
                stop('return_continuation_unproven', continuation=ins.next_pc)
        elif name == 'RTS':
            successors = [(frames[-1][2], 'return')]
        elif name in ('JMP', 'BRA'):
            successors = [(ins.target, 'jump')]
        else:
            successors = [(ins.next_pc, 'fallthrough')]
        for target, kind in successors:
            successor = (target, next_mpr, updated, next_t, next_frames, next_depth)
            if next_mpr not in contexts and len(contexts) >= context_limit:
                stop('context_limit', target=state_json(successor))
                continue
            contexts.add(next_mpr)
            edges.append(dict(source=index, target=state_json(successor), kind=kind))
            if successor not in scheduled:
                scheduled.add(successor)
                queue.append(successor)
    graph = dict(nodes=nodes, edges=edges, unresolved=frontiers, overlaps=overlaps,
                 summary=dict(states=len(nodes), identities=len(union),
                              contexts=len({tuple(n['mpr']) for n in nodes}),
                              unresolved=len(frontiers)))
    return graph, sorted(union.values(), key=_sort_key), list(roots.values())
