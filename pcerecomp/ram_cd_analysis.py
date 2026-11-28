"""Bounded candidate traversal of authenticated, mutable RAM/CD source bytes.

Adapters own source authentication and effective code/data permissions. Nothing
here makes snapshot RAM immutable or establishes execution or routine closure.
Opt-in vector reads authenticate candidate targets; translated JMP stays dynamic.
"""
from collections import deque

from .analysis import _register_facts
from .capture import integer
from .declarations import instruction_key, _sort_key
from .isa import BRANCHES, physical

MAX_STATES = 100000
MAX_CONTEXTS = 4096
MAX_CALL_DEPTH = 64
# Bounds retained symbolic cells and their serialized node/edge copies. This is
# a parser resource bound for the new policy, independent of instruction count.
MAX_STACK_PROOF_CELLS = 262144
ANALYSIS_POLICY = 'bounded-ram-cd-candidates-v1'
FAR_CALL_POLICY = 'bounded-ram-cd-stack-values-v1'
VECTOR_POLICY = 'bounded-ram-cd-vectors-v1'
_WRITERS = {'STA', 'STX', 'STY', 'STZ', 'ASL', 'LSR', 'ROL', 'ROR',
            'INC', 'DEC', 'TSB', 'TRB'}
_PUSH = {'PHA', 'PHP', 'PHX', 'PHY'}
_POP = {'PLA', 'PLP', 'PLX', 'PLY'}


def derive(entries, mapping, *, fetch, is_code, is_ram, canonical,
           instruction_limit, context_limit, call_depth_limit=None, far_calls=False,
           vector_jumps=False, read_vector_byte=None, is_vector=None):
    """Select a versioned analysis without changing the original graph shape."""
    if type(far_calls) is not bool:
        raise ValueError('RAM/CD far-call selection requires a boolean')
    if type(vector_jumps) is not bool:
        raise ValueError('RAM/CD vector-jump selection requires a boolean')
    if vector_jumps:
        if not callable(read_vector_byte) or not callable(is_vector):
            raise ValueError('RAM/CD vector analysis requires authenticated reads and protected ranges')
    elif read_vector_byte is not None or is_vector is not None:
        raise ValueError('RAM/CD vector callbacks require explicit vector analysis')
    if far_calls or vector_jumps:
        return _derive_stack(entries, mapping, fetch=fetch, is_code=is_code,
            is_ram=is_ram, canonical=canonical, instruction_limit=instruction_limit,
            context_limit=context_limit, call_depth_limit=call_depth_limit,
            vector_jumps=vector_jumps, read_vector_byte=read_vector_byte, is_vector=is_vector)
    return _derive_plain(entries, mapping, fetch=fetch, is_code=is_code,
        is_ram=is_ram, canonical=canonical, instruction_limit=instruction_limit,
        context_limit=context_limit, call_depth_limit=call_depth_limit)


def _derive_plain(entries, mapping, *, fetch, is_code, is_ram, canonical,
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


def _derive_stack(entries, mapping, *, fetch, is_code, is_ram, canonical,
                  instruction_limit, context_limit, call_depth_limit, vector_jumps=False,
                  read_vector_byte=None, is_vector=None):
    """Track only stack bytes produced by analyzed instructions.

    This is an abstract byte stack, never a read of snapshot stack contents.
    Reconstructed RTS edges describe actual known pushed words, not an inferred
    calling convention or a caller-supplied summary of skipped instructions.
    """
    integer(instruction_limit, MAX_STATES, 'RAM/CD state limit', 1)
    integer(context_limit, MAX_CONTEXTS, 'RAM/CD context limit', 1)
    integer(call_depth_limit, MAX_CALL_DEPTH, 'RAM/CD call depth', 1)
    if type(entries) is not list or not 1 <= len(entries) <= 256:
        raise ValueError('RAM/CD entries require one to 256 sorted unique logical PCs')
    for pc in entries:integer(pc, 65535, 'RAM/CD entry')
    if entries != sorted(set(entries)) or len(entries) > instruction_limit:
        raise ValueError('RAM/CD entries must be sorted unique and fit the state limit')
    if type(mapping) not in (list, tuple) or len(mapping) != 8:
        raise ValueError('RAM/CD mapping requires eight byte values')
    for bank in mapping:integer(bank, 255, 'RAM/CD mapping bank')
    mapping = tuple(mapping)

    def origin(ins, mpr, kind):
        return kind, ins.pc, tuple(mpr), tuple(ins.physical), tuple(ins.data)

    def origin_json(value):
        if value is None:return None
        kind, pc, mpr, addresses, data = value
        return dict(kind=kind, pc=pc, mpr=list(mpr), physical=list(addresses), data=list(data))

    def state_json(state):
        pc, mpr, facts, transfer, frames, cells, origins, sp = state
        return dict(pc=pc, mpr=list(mpr), registers=list(facts), transfer=transfer,
            frames=[dict(pc=f[0], mpr=list(f[1]), continuation=f[2], depth=f[3]) for f in frames],
            stack_depth=len(cells), stack_pointer=sp,
            stack_values=[dict(value=value, origin=origin_json(source)) for value, source in cells],
            register_origins=[origin_json(source) for source in origins])

    def write_barrier(ins, mpr, facts, transfer, frames, cells):
        name, mode = ins.mnemonic, ins.mode
        if mode == 'blk':return 'block_transfer_changes_memory'
        if name in ('ST0', 'ST1', 'ST2'):return 'opaque_device_write'
        targets = []
        implicit = name in _PUSH or name in ('JSR', 'BSR')
        if implicit:targets = range(0x2100, 0x2200)
        elif name in ('ADC', 'AND', 'EOR', 'ORA') and transfer != 0:
            targets = (0x2000+x for x in (range(256) if facts[1] is None else (facts[1],)))
        elif (name in _WRITERS or name.startswith(('RMB', 'SMB'))) and mode != 'acc':
            if mode in ('zpg', 'zpx', 'zpy'):
                index = None if mode == 'zpg' else facts[1 if mode == 'zpx' else 2]
                offsets = (0,) if mode == 'zpg' else range(256) if index is None else (index,)
                targets = (0x2000+((ins.data[1]+i)&255) for i in offsets)
            elif mode in ('abs', 'abx', 'aby'):
                base = ins.data[1] | ins.data[2] << 8
                index = None if mode == 'abs' else facts[1 if mode == 'abx' else 2]
                offsets = (0,) if mode == 'abs' else range(256) if index is None else (index,)
                targets = ((base+i)&65535 for i in offsets)
            else:return 'unknown_write_target'
        for logical in targets:
            address = canonical(physical(logical, mpr))
            if vector_jumps and is_vector(address):return 'possible_vector_write'
            if (frames or cells) and not implicit and 0x1F0100 <= address < 0x1F0200:
                return 'stack_write_barrier'
            if not is_ram(address):return 'write_not_proven_ram'
            if is_code(address):return 'possible_code_write'
        return None

    def stack_read(ins, mpr, facts, cells, sp):
        # An absolute SP established by a real TXS is required. TSX alone does
        # not establish one: absolute indexed addressing may leave page $21xx.
        if sp is None or ins.mode not in ('abs', 'abx', 'aby'):return None
        index = 0 if ins.mode == 'abs' else facts[1 if ins.mode == 'abx' else 2]
        if index is None:return None
        logical = ((ins.data[1] | ins.data[2]<<8)+index)&65535
        address = canonical(physical(logical, mpr))
        if not 0x1F0100 <= address < 0x1F0200:return None
        offset = ((address&255)-sp-1)&255
        return cells[-1-offset] if offset < len(cells) else None

    initial = [(pc, mapping, (None, None, None), None, (), (), (None, None, None), None) for pc in entries]
    for state in initial:
        try:fetch(state[0], state[1])
        except ValueError as error:
            raise ValueError('RAM/CD seed is not wholly in authenticated allowed code: '+str(error)) from error
    queue, scheduled = deque(initial), set(initial)
    nodes, edges, frontiers, overlaps = [], [], [], []
    contexts, union, roots, occupied = {mapping}, {}, {}, {}
    cell_cost = 0
    while queue:
        if len(nodes) >= instruction_limit:
            frontiers.append(dict(reason='state_limit', pending_states=len(queue)));break
        state = queue.popleft()
        pc, mpr, facts, transfer, frames, cells, origins, sp = state
        if cell_cost+len(cells)>MAX_STACK_PROOF_CELLS:
            frontiers.append(dict(reason='stack_fact_limit',pending_states=len(queue)+1));break
        # Charge either the node state or a failed-fetch frontier state. The
        # scheduled tuple was charged when enqueued and remains retained.
        cell_cost += len(cells)
        try:ins, locations = fetch(pc, mpr)
        except ValueError as error:
            frontiers.append(dict(state=state_json(state), reason=str(error)));continue
        row = ins.report() | dict(mpr=mpr);key = instruction_key(row)
        union[key] = row;roots[key] = dict(pc=pc, mpr=list(mpr), fetch=locations)
        number = len(nodes)
        nodes.append(dict(id=number, **state_json(state), fetch=locations, mnemonic=ins.mnemonic, mode=ins.mode))
        for address in ins.physical:
            address = canonical(address)
            if address in occupied and occupied[address] != pc:
                overlaps.append(dict(physical=address, pc=pc, other=occupied[address]))
            occupied[address] = pc
        def stop(reason, **detail):frontiers.append(dict(node=number, reason=reason, **detail))
        barrier = write_barrier(ins, mpr, facts, transfer, frames, cells)
        if barrier:stop(barrier);continue
        if not ins.native:stop('unsupported_instruction');continue
        name = ins.mnemonic
        if name in ('RTI', 'BRK'):
            stop('interrupt_return' if name == 'RTI' else 'interrupt_vector');continue
        vector_word = None
        if name == 'JMP' and ins.target is None:
            if not vector_jumps:stop('indirect_jump');continue
            if ins.mode not in ('ind','iax'):stop('unsupported_indirect_jump');continue
            if ins.mode == 'iax' and facts[1] is None:
                stop('unknown_vector_index');continue
            base = ins.data[1] | ins.data[2]<<8
            index = facts[1] if ins.mode == 'iax' else None
            pointer = (base+(index if index is not None else 0))&65535
            vector_word = dict(pc=pc,mpr=list(mpr),mode=ins.mode,base=base,index=index,pointer=pointer)
            reads = []
            try:
                for logical in (pointer,(pointer+1)&65535):
                    address = physical(logical,mpr)
                    normalized = canonical(address)
                    if not is_vector(normalized):
                        raise ValueError('vector_byte_outside_authenticated_range')
                    value, provenance = read_vector_byte(logical,mpr)
                    integer(value,255,'RAM/CD vector byte')
                    if type(provenance) is not dict or not provenance:
                        raise ValueError('vector_byte_missing_provenance')
                    reads.append(dict(logical=logical,physical=address,canonical_physical=normalized,
                                      value=value,provenance=provenance))
            except ValueError as error:
                stop('vector_read_unproven',detail=str(error),vector_word=vector_word,reads=reads)
                continue
            vector_word.update(low=reads[0],high=reads[1],target=reads[0]['value']|reads[1]['value']<<8)
        updated = list(_register_facts(ins, facts, mpr));new_origins = list(origins)
        for i, value in enumerate(updated):
            if value is None:new_origins[i] = None
            elif value != facts[i]:new_origins[i] = origin(ins, mpr, 'register')
        if name in ('CLA','CLX','CLY'):
            new_origins['axy'.index(name[-1].lower())] = origin(ins,mpr,'clear')
        elif name == 'TMA' and updated[0] is not None:
            new_origins[0] = origin(ins,mpr,'mapping-read')
        if name in ('LDA', 'LDX', 'LDY'):
            i = ('LDA', 'LDX', 'LDY').index(name)
            cell = stack_read(ins, mpr, facts, cells, sp)
            if cell is not None:updated[i], new_origins[i] = cell
            elif ins.mode == 'imm':new_origins[i] = origin(ins, mpr, 'immediate')
        elif name in ('TAX', 'TAY', 'TXA', 'TYA'):
            new_origins['axy'.index(name[-1].lower())] = origins['axy'.index(name[1].lower())]
        elif name in ('SAX', 'SAY', 'SXY'):
            i,j = ('axy'.index(n.lower()) for n in name[1:]);new_origins[i],new_origins[j] = origins[j],origins[i]
        next_t = 1 if name == 'SET' else None if name == 'PLP' else 0
        next_mpr = mpr
        if name == 'TAM' and ins.data[1]:
            if facts[0] is None:stop('unknown_mapping_value');continue
            next_mpr = tuple(facts[0] if ins.data[1]&(1<<i) else bank for i,bank in enumerate(mpr))
        if (frames or cells or name in _PUSH or name in _POP or name in ('JSR','BSR','RTS')) and not 0xF8 <= next_mpr[1] <= 0xFB:
            stop('unsupported_stack_mapping');continue
        next_cells, next_frames, next_sp = cells, frames, sp
        returned = None
        if name == 'TXS':
            if cells or frames:stop('stack_pointer_write_barrier');continue
            next_sp = facts[1]
        elif name == 'TSX':
            updated[1] = sp;new_origins[1] = None if sp is None else origin(ins,mpr,'stack-pointer')
        elif name in _PUSH:
            if len(cells) >= 256:stop('stack_depth_limit');continue
            if name == 'PHP':cell = (None, origin(ins,mpr,'status'))
            else:
                i = ('PHA','PHX','PHY').index(name);cell = (facts[i], origins[i])
            next_cells = cells+(cell,);next_sp = None if sp is None else (sp-1)&255
        elif name in _POP:
            if not cells:stop('unproven_stack_pop');continue
            cell = cells[-1];next_cells = cells[:-1];next_sp = None if sp is None else (sp+1)&255
            if name != 'PLP':
                i = ('PLA','PLX','PLY').index(name);updated[i],new_origins[i] = cell
            else:next_t = None
        elif name in ('JSR','BSR'):
            if len(frames) >= call_depth_limit:stop('call_depth_limit', continuation=ins.next_pc);continue
            if len(cells) > 254:stop('stack_depth_limit');continue
            word = (ins.next_pc-1)&65535
            next_cells = cells+((word>>8,origin(ins,mpr,'return-high')),(word&255,origin(ins,mpr,'return-low')))
            next_frames = frames+((pc,mpr,ins.next_pc,len(cells)),)
            next_sp = None if sp is None else (sp-2)&255
        elif name == 'RTS':
            if len(cells)<2:stop('unproven_return_word');continue
            low, high = cells[-1], cells[-2]
            if low[0] is None or high[0] is None:stop('unknown_return_word');continue
            target = ((low[0]|high[0]<<8)+1)&65535
            next_cells = cells[:-2];next_sp = None if sp is None else (sp+2)&255
            matched = bool(frames and len(next_cells)==frames[-1][3] and target==frames[-1][2]
                and low[1] is not None and high[1] is not None
                and low[1][:3]==('return-low',frames[-1][0],frames[-1][1])
                and high[1][:3]==('return-high',frames[-1][0],frames[-1][1]))
            # Any consumed call-frame words are retired as bookkeeping, never
            # used to invent a destination or restore an earlier mapping.
            next_frames = tuple(frame for frame in frames if frame[3] < len(next_cells))
            returned = (target, 'return' if matched else 'reconstructed_return',
                dict(low=dict(value=low[0],origin=origin_json(low[1])), high=dict(value=high[0],origin=origin_json(high[1])), matched_call=matched))
        if vector_word is not None:successors=[(vector_word['target'],'vector_jump')]
        elif returned is not None:successors=[returned[:2]]
        elif name in BRANCHES or ins.mode=='zrl':successors=[(ins.target,'taken'),(ins.next_pc,'fallthrough')]
        elif name in ('JSR','BSR'):successors=[(ins.target,'call')]
        elif name in ('JMP','BRA'):successors=[(ins.target,'jump')]
        else:successors=[(ins.next_pc,'fallthrough')]
        for target,kind in successors:
            successor=(target,next_mpr,tuple(updated),next_t,next_frames,next_cells,tuple(new_origins),next_sp)
            if next_mpr not in contexts and len(contexts)>=context_limit:
                if cell_cost+len(next_cells)>MAX_STACK_PROOF_CELLS:
                    stop('stack_fact_limit',target_pc=target,target_mpr=list(next_mpr));continue
                cell_cost += len(next_cells)
                stop('context_limit',target=state_json(successor));continue
            cost = len(next_cells)*(1+int(successor not in scheduled))
            if cell_cost+cost>MAX_STACK_PROOF_CELLS:
                stop('stack_fact_limit',target_pc=target,target_mpr=list(next_mpr));continue
            cell_cost += cost
            contexts.add(next_mpr)
            edge=dict(source=number,target=state_json(successor),kind=kind)
            if returned is not None:edge['return_word']=returned[2]
            if vector_word is not None:edge['vector_word']=vector_word
            edges.append(edge)
            if successor not in scheduled:scheduled.add(successor);queue.append(successor)
    graph=dict(nodes=nodes,edges=edges,unresolved=frontiers,overlaps=overlaps,
        summary=dict(states=len(nodes),identities=len(union),contexts=len({tuple(n['mpr']) for n in nodes}),unresolved=len(frontiers)))
    return graph, sorted(union.values(),key=_sort_key),list(roots.values())
