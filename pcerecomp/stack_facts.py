"""Bounded, relative HuC6280 stack facts for discovery, never runtime state.

Cells are (known-bit mask, value), bottom first. No initial SP or memory is
invented. The caller proves the canonical WRAM mapping, capacity and frame
boundaries before applying a transfer. Bit masks preserve partial PHP facts
without treating an unknown status bit as zero.
"""

FLAGS = ('c', 'd', 't', 'n', 'z', 'v', 'i')
BITS = (0, 3, 5, 7, 1, 6, 2)
PUSHES = ('PHA', 'PHP', 'PHX', 'PHY')
POPS = ('PLA', 'PLP', 'PLX', 'PLY')


def join(left, right):
    """Intersect facts; equal relative depths are part of the discovery key."""
    if len(left[10]) != len(right[10]):
        raise ValueError('Stack fact depth disagrees with discovery state')
    cells = []
    for (lm, lv), (rm, rv) in zip(left[10], right[10]):
        mask = lm & rm & ~(lv ^ rv) & 255
        cells.append((mask, lv & mask))
    return tuple(a if a == b else None for a, b in zip(left[:10], right[:10])) + (tuple(cells),)


def transfer(ins, incoming, outgoing, *, admitted=True, software_interrupts=False):
    """Apply an admitted stack operation to ten scalar facts and saved cells."""
    name = ins.mnemonic
    values = list(outgoing)
    # Ordinary instructions preserve I; only these controls change it here.
    values.append(0 if name == 'CLI' else 1 if name in ('SEI', 'BRK') else
                  None if name in ('RTI', 'PLP', 'ILL') else incoming[9])
    cells = list(incoming[10])
    before = len(cells)
    pushed, popped = [], []
    if not admitted:
        return tuple(values) + (tuple(cells),), None
    if name in PUSHES:
        if name == 'PHP':
            mask, value = 0x30, 0x10  # Stored B=1, T=0, even after SET.
            for flag, bit in zip(incoming[3:10], BITS):
                if bit != 5 and flag is not None:
                    mask |= 1 << bit
                    value |= flag << bit
            cell = mask, value
        else:
            register = incoming[('PHA', 'PHX', 'PHY').index(name)]
            cell = (0, 0) if register is None else (255, register)
        pushed.append(cell)
        cells.append(cell)
    elif name in POPS:
        cell = cells.pop()
        popped.append(cell)
        mask, value = cell
        if name == 'PLP':
            for index, bit in enumerate(BITS, 3):
                values[index] = (value >> bit) & 1 if mask & (1 << bit) else None
        else:
            values[('PLA', 'PLX', 'PLY').index(name)] = value if mask == 255 else None
            values[6] = (value >> 7) & 1 if mask & 128 else None
            values[7] = 0 if value else 1 if mask == 255 else None
    elif name in ('JSR', 'BSR'):
        word = (ins.next_pc - 1) & 65535
        pushed = [(255, word >> 8), (255, word & 255)]
        cells.extend(pushed)
    elif name == 'RTS':
        popped = [cells.pop(), cells.pop()]
    elif software_interrupts and name == 'BRK':
        word = ins.next_pc
        mask, value = 0x30, 0x10  # BRK stores B=1/T=0; other status is saved.
        for flag, bit in zip(incoming[3:10], BITS):
            if bit != 5 and flag is not None:
                mask |= 1 << bit
                value |= flag << bit
        pushed = [(255, word >> 8), (255, word & 255), (mask, value)]
        cells.extend(pushed)
    elif software_interrupts and name == 'RTI':
        popped = [cells.pop(), cells.pop(), cells.pop()]
        mask, value = popped[0]
        for index, bit in enumerate(BITS, 3):
            values[index] = (value >> bit) & 1 if mask & (1 << bit) else None
    event = None
    if pushed or popped or name == 'TXS':
        as_dict = lambda cell: dict(known_mask=cell[0], value=cell[1])
        event = dict(operation=name, before_bytes=before, after_bytes=len(cells),
                     pushed=[as_dict(c) for c in pushed], popped=[as_dict(c) for c in popped])
    return tuple(values) + (tuple(cells),), event
