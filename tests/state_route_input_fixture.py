"""Authored eight-poll guest; only host held input is injected between opcodes."""
from collections import Counter

MPR = (255, 248, 128, 129, 130, 131, 132, 0)
ENTRY = 0x2800
DELAYS = (0, 3, 11)
PHASES = ('before-load', 'before-write', 'after-write', 'after-read')


def program(delay):
    if delay not in DELAYS:
        raise ValueError('Unknown authored NOP delay')
    rows, marks, pc = [], [], ENTRY

    def emit(data, cycles):
        nonlocal pc
        rows.append(dict(pc=pc, data=list(data), cycles=cycles))
        pc += len(data)

    for poll in range(8):
        emit((0xA9, poll+1), 2)
        emit((0x8D, 0, 0x24), 5)
        emit((0xAD, 0, 0x10), 5)  # Deliberate stale latch read.
        emit((0x8D, 0x10+poll, 0x24), 5)
        emit((0xA9, 0), 2)
        write = len(rows)
        emit((0x8D, 0, 0x10), 5)
        for _ in range(delay):
            emit((0xEA,), 2)
        read = len(rows)
        emit((0xAD, 0, 0x10), 5)
        emit((0x8D, 0x20+poll, 0x24), 5)
        emit((0xA9, 1), 2)
        emit((0x8D, 0, 0x10), 5)
        for _ in range(delay):
            emit((0xEA,), 2)
        emit((0xAD, 0, 0x10), 5)
        emit((0x8D, 0x30+poll, 0x24), 5)
        marks.append((write-1, write, write+1, read+1))
    return rows, marks


def plans():
    cases = []
    for divisor in (3, 12):
        for delay in DELAYS:
            rows, marks = program(delay)
            for phase, name in enumerate(PHASES):
                # I+Right, then Up, then release: three changes, each around
                # an actual guest write/read at poll indices 2, 4 and 6.
                injections = [[marks[poll][phase], mask]
                              for poll, mask in ((2, 0x21), (4, 0x10), (6, 0))]
                cases.append(dict(id=f'div{divisor}-nop{delay}-{name}', divisor=divisor,
                                  delay=delay, phase=name, injections=injections,
                                  instructions=len(rows), ticks=sum(r['cycles'] for r in rows)*divisor))
    return cases


def serialize(case):
    return ' '.join(map(str, (case['divisor'], case['instructions'], len(case['injections']))))+'\n'+''.join(
        f'{index} {mask}\n' for index, mask in case['injections'])


def source_identity(row):
    physical = [(MPR[(row['pc']+i) >> 13] << 13) | ((row['pc']+i) & 8191)
                for i in range(len(row['data']))]
    return row['pc'], MPR, tuple(physical), tuple(row['data'])


def expected(case):
    """Literal CPU-cycle and two-nibble electrical profile, no runtime imports."""
    rows, _ = program(case['delay'])
    injections = dict(case['injections'])
    a, p, ticks, latch, held = 0, 4, 0, 0xF0, 0
    ram, events = bytearray(64), []
    for index, row in enumerate(rows):
        held = injections.get(index, held)
        pc, data = row['pc'], row['data']
        # Fixed-width raw observer record: index, full fetched identity,
        # before(A,P,ticks,latch,held), after(PC,A,P,ticks,latch,sequence).
        identity = source_identity(row)
        event = [index, pc, *MPR, len(data), *identity[2], *([0]*(3-len(data))),
                 *data, *([0]*(3-len(data))), a, p, ticks, latch, held]
        if data[0] == 0xA9:
            a = data[1]
        elif data[0] == 0xAD:
            a = latch
        elif data[0] == 0x8D:
            address = data[1] | data[2] << 8
            if address == 0x1000:
                # Both supported banks have active-low I/II/Select/Run or
                # Up/Right/Down/Left in the low nibble. CLR is always zero.
                latch = 0xF0 | (15 ^ ((held >> (4 if a == 1 else 0)) & 15))
            else:
                ram[address-0x2400] = a
        if data[0] in (0xA9, 0xAD):
            p = (p & ~130) | (a & 128) | (2 if a == 0 else 0)
        ticks += row['cycles']*case['divisor']
        event.extend((pc+len(data), a, p, ticks, latch, ram[0]))
        events.append(dict(kind='instruction', values=event))
    events.append(dict(kind='ram', values=list(ram)))
    return events


def expected_hits(case):
    return Counter(source_identity(row) for row in program(case['delay'])[0])


def validate_events(actual, case):
    wanted = expected(case)
    if not isinstance(actual, list) or len(actual) != len(wanted):
        raise ValueError('Input instruction/endpoint observation count differs')
    for index, (got, want) in enumerate(zip(actual, wanted)):
        if (not isinstance(got, dict) or set(got) != {'kind', 'values'} or
                not isinstance(got['values'], list) or
                any(type(v) is not int or v < 0 for v in got['values']) or got != want):
            raise ValueError(f'Input literal expectation differs: {case["id"]} record {index}: {got}, expected {want}')
    return sum(len(row['values']) for row in wanted)
