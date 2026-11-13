"""Bounded abstract copy effects and write hazards, never guest execution.

HuC6280 block operations save Y/A/X on the real stack before reading their
operands. ROM-only fetch admission makes those operand bytes immutable. We
preserve registers only after proving every destination disjoint from all base
WRAM stack aliases, and check mapper hazards before inferring any copied value. Explicit mapper
mode follows the address-selected SF2 window after each ordered write.
"""
from .isa import physical
from .wram_facts import Unknown, canonical

MAX_BLOCK_BYTES = 65536
MAX_TABLE_STATES = 256


def mapper_address(address):
    return address >> 13 == 0 and address & 8191 >= 0x1FF0


def block_addresses(name, source, destination, length):
    """Ordered 16-bit address pairs, including alternating and fixed endpoints."""
    for i in range(length):
        yield source, destination
        if name == 'TDD':
            source, destination = (source-1)&65535, (destination-1)&65535
        elif name == 'TIN':
            source = (source+1)&65535
        elif name == 'TIA':
            source = (source+1)&65535
            destination = (destination + (-1 if i&1 else 1))&65535
        elif name == 'TAI':
            source = (source + (-1 if i&1 else 1))&65535
            destination = (destination+1)&65535
        else:
            source, destination = (source+1)&65535, (destination+1)&65535


def plan_block(ins, mpr, depth, profile, byte_limit, *, allow_mapper=False):
    source, destination, encoded = (ins.data[n] | ins.data[n+1] << 8 for n in (1,3,5))
    length = encoded or 65536
    result = dict(operation=ins.mnemonic, source=source, destination=destination,
        encoded_length=encoded, length=length, status='blocked')
    if length > byte_limit:
        result['reason'] = 'block_transfer_limit'
    elif not 0xF8 <= mpr[1] <= 0xFB:
        result['reason'] = 'unsupported_block_stack_mapping'
    elif depth+3 > 256:
        result['reason'] = 'stack_capacity'
    else:
        pairs = list(block_addresses(ins.mnemonic, source, destination, length))
        destinations = [physical(d,mpr) for _,d in pairs]
        if profile == 'sf2' and not allow_mapper and any(mapper_address(d) for d in destinations):
            result['reason'] = 'mapper_write_barrier'
        elif any((offset := canonical(d)) is not None and 256 <= offset < 512 for d in destinations):
            result['reason'] = 'stack_write_barrier'
        else:
            result.update(status='eligible', temporary_stack_bytes=3,
                maximum_stack_depth=depth+3, registers_preserved=True)
            return result, pairs
    return result, None


def propagate_block(plan, pairs, incoming, outgoing, mpr, slots, read, *, mapper_selector=None):
    """Sequential byte transfer: an overlapping source sees preceding writes."""
    memory = list(incoming[11])
    steps, known = [], 0
    selector = mapper_selector
    for index,(source,destination) in enumerate(pairs):
        row = dict(index=index, source=source, destination=destination,
            source_physical=physical(source,mpr), destination_physical=physical(destination,mpr))
        try:
            value = (read(source, 'block-source', memory) if selector is None else
                     read(source, 'block-source', memory, selector))
        except Unknown as error:
            value = None
            row.update(read_reason=error.reason, read_detail=error.detail)
        else:
            known += 1
        row['value'] = value
        if selector is not None:
            # The source byte is read under the old window. The write address,
            # regardless of the byte value, selects the window for later reads.
            row['selector_before'] = selector
            row['mapper_write'] = mapper_address(row['destination_physical'])
            if row['mapper_write']:
                selector = row['destination_physical'] & 15
            row['selector_after'] = selector
        offset = canonical(row['destination_physical'])
        if offset in slots:
            row['wram_offset'] = offset
            row['before'] = memory[slots[offset]]
            memory[slots[offset]] = value
        steps.append(row)
    event = dict(plan, status='analyzed', transfers=steps,
        known_reads=known, unknown_reads=len(steps)-known)
    if selector is not None:
        event.update(selector_before=mapper_selector, selector_after=selector,
            mapper_writes=sum(row['mapper_write'] for row in steps))
    # Copying was proved disjoint from every possible temporary save address.
    return (*incoming[:3], *outgoing[3:]), tuple(memory), event
