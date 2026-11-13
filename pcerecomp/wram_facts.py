"""Opt-in bounded WRAM facts, not execution or a general memory emulator.

Only explicitly authorized canonical base-WRAM bytes are tracked. Initial bytes
are unknown; joins retain equal full-byte values only. Unknown destinations and
block writes invalidate facts. Stack-page bytes are excluded by admission.
"""
from .isa import physical
from .register_eval import evaluate
from .branch_facts import extend_status

MAX_BYTES = 256
STORES = ('STA', 'STX', 'STY', 'STZ')
SHIFTS = ('ASL', 'LSR', 'ROL', 'ROR')
RMW = (*SHIFTS, 'INC', 'DEC', 'TSB', 'TRB')
BLOCKS = ('TII', 'TIA', 'TAI', 'TIN', 'TDD')
ROUTED = ('ADC', 'AND', 'ORA', 'EOR')


class Unknown(ValueError):
    def __init__(self, reason, **detail):
        self.reason, self.detail = reason, detail
        super().__init__(reason)


def canonical(address):
    return address & 8191 if 0xF8 <= address >> 13 <= 0xFB else None


def address(ins, facts, read):
    """Resolve an effective address without reading I/O or unpermitted memory."""
    def index(register):
        value = facts[register]
        if value is None:
            raise Unknown('data_index_unknown', register='x' if register == 1 else 'y')
        return value

    mode, data = ins.mode, ins.data
    if mode in ('zpg', 'zpx', 'zpy'):
        return 0x2000 + ((data[1] + (index(1 if mode == 'zpx' else 2) if mode != 'zpg' else 0)) & 255)
    if mode in ('abs', 'abx', 'aby'):
        return ((data[1] | data[2] << 8) + (index(1 if mode == 'abx' else 2) if mode != 'abs' else 0)) & 65535
    if mode in ('idx', 'idy', 'zpi'):
        pointer = (data[1] + (index(1) if mode == 'idx' else 0)) & 255
        low = read(0x2000 + pointer, 'pointer-low')
        high = read(0x2000 + ((pointer + 1) & 255), 'pointer-high')
        return ((low | high << 8) + (index(2) if mode == 'idy' else 0)) & 65535
    if mode in ('imz', 'izx'):
        return 0x2000 + ((data[2] + (index(1) if mode == 'izx' else 0)) & 255)
    if mode in ('ima', 'imx'):
        return ((data[2] | data[3] << 8) + (index(1) if mode == 'imx' else 0)) & 65535
    raise Unknown('unsupported_data_mode')


def effects(ins, incoming, outgoing, mpr, slots, read, operand=None):
    """Return nine scalar facts, permitted byte facts and an optional witness.

    `read` is a source/permission-checked abstract read supplied by discovery.
    The result never feeds generated operations or guest state.
    """
    name, mode = ins.mnemonic, ins.mode
    memory = list(incoming[11])
    values = list(outgoing)
    event = dict(operation=name, writes=[])

    def write(logical, value):
        offset = canonical(physical(logical, mpr))
        event['logical_address'] = logical
        event['physical'] = physical(logical, mpr)
        if offset not in slots:
            event['status'] = 'outside_tracked_wram'
            return
        pos = slots[offset]
        event.update(status='tracked', writes=[dict(offset=offset, before=memory[pos], value=value)])
        memory[pos] = value

    def invalidate(reason, detail=None):
        event.update(status='invalidated', reason=reason, detail=detail or {},
                     invalidated_offsets=list(slots))
        memory[:] = [None] * len(memory)

    def get(logical, role='value'):
        try:
            return read(logical, role)
        except Unknown as error:
            event.update(read_reason=error.reason, read_detail=error.detail)
            return None

    if name in BLOCKS:
        invalidate('block_write_untracked')
    elif name in ROUTED and incoming[5] != 0:
        # A possible T destination is always logical $20xx. ROM/I/O mappings
        # cannot alias our tracked WRAM; no device values are inferred.
        event['transfer'] = incoming[5]
        if incoming[1] is None:
            if canonical(physical(0x2000, mpr)) is not None:
                invalidate('transfer_index_unknown')
            else:
                event['status'] = 'outside_tracked_wram'
        else:
            logical = 0x2000 + incoming[1]
            left = get(logical, 'transfer-left')
            if incoming[5] is None:
                write(logical, None)
                event['reason'] = 'unknown_transfer'
            else:
                ghost = (left, *incoming[1:5], 0, *incoming[6:9])
                result, reason = evaluate(ins, ghost[:6], mpr, operand)
                result = extend_status(ins, ghost, result, operand)
                values[3:9] = result[3:9]
                write(logical, result[0])
                event['reason'] = reason
    elif name in STORES or name in RMW and mode != 'acc' or name.startswith(('RMB', 'SMB')):
        try:
            logical = address(ins, incoming, read)
        except Unknown as error:
            invalidate(error.reason, error.detail)
        else:
            if name in STORES:
                result = 0 if name == 'STZ' else incoming[STORES.index(name)]
            else:
                old = get(logical)
                result = None
                if name in SHIFTS or name in ('INC', 'DEC'):
                    if old is not None:
                        if name in SHIFTS:
                            values[3] = (old >> 7) if name in ('ASL', 'ROL') else old & 1
                        if name in ('ROL', 'ROR') and incoming[3] is None:
                            pass
                        elif name == 'ASL': result = (old * 2) & 255
                        elif name == 'LSR': result = old // 2
                        elif name == 'ROL': result = (old * 2 + incoming[3]) & 255
                        elif name == 'ROR': result = old // 2 + incoming[3] * 128
                        else: result = (old + (1 if name == 'INC' else -1)) & 255
                    values[6] = None if result is None else int(result >= 128)
                    values[7] = None if result is None else int(result == 0)
                elif name in ('TSB', 'TRB'):
                    if old is not None and incoming[0] is not None:
                        result = old | incoming[0] if name == 'TSB' else old & ~incoming[0]
                    values[6] = None if old is None else old >> 7
                    values[8] = None if old is None else (old >> 6) & 1
                    values[7] = None if result is None else int(result == 0)
                elif old is not None:
                    bit = 1 << int(name[-1])
                    result = old | bit if name.startswith('SMB') else old & ~bit
            write(logical, result)
    elif name in ('BIT', 'TST'):
        if mode == 'imm': old = ins.data[1]
        else:
            try:
                logical = address(ins, incoming, read)
            except Unknown as error:
                event.update(read_reason=error.reason, read_detail=error.detail)
                old = None
            else:
                old = get(logical)
        mask = ins.data[1] if name == 'TST' else incoming[0]
        values[6] = None if old is None else old >> 7
        values[8] = None if old is None else (old >> 6) & 1
        values[7] = None if old is None or mask is None else int(old & mask == 0)
        event['status'] = 'test_only'
    else:
        return outgoing, tuple(memory), None
    return tuple(values), tuple(memory), event
