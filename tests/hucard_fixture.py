"""Authored HuCard images and independently declared finite reference plans.

No game/firmware bytes are used. The selected 512 KiB layout is the documented
Gear/Mesen compatibility map, not a unique physical cartridge-board decode.
"""
import hashlib

BANK_COUNTS = (1, 3, 16, 32, 48, 64, 96, 128)
CPU_FIELDS = ('pc', 'a', 'x', 'y', 'sp', 'p', 'divisor', 'ticks',
              *(f'mpr{i}' for i in range(8)), 'mpr_latch', 'io_latch',
              'timer_enabled', 'timer_reload', 'timer_counter', 'irq_mask', 'irq_request')
DEVICE_FIELDS = ('vdc_selected', 'vdc_status', 'vdc_read_buffer',
                 *(f'vdc_reg{i}' for i in range(20)), 'vce_control', 'vce_address',
                 'palette_hash', 'joypad_latch', 'psg_selected', 'psg_main_volume',
                 'psg_lfo_frequency', 'psg_lfo_control',
                 *(f'psg_ch{i}_{field}' for i in range(6)
                   for field in ('frequency', 'control', 'balance', 'index', 'noise', 'dda', 'noise_seed', 'wave_hash')),
                 'wram_hash', 'vram_hash', 'sat_hash')


def backing_bank(count, bank):
    if not 1 <= count <= 128 or not 0 <= bank < 128:
        raise ValueError('Authored bank range')
    if count == 48:
        return bank & 31 if bank < 64 else 32 + (bank & 15)
    if count == 64:
        return bank & 63 if bank < 64 else 32 + (bank & 31)
    if count == 96:
        return bank & 63 if bank < 64 else 64 + (bank & 31)
    return bank % count


def authored_program():
    # Only low-speed instructions: no projection of the known CSH transition.
    # Identical authored code at +$100 in each file bank permits a genuine TAM
    # fetch into physical bank40 even for boards where that is not a bank00 alias.
    return bytes.fromhex(
        '78 D8 A9 FF 53 01 A9 F8 53 02 A9 40 53 80 '
        'AD 34 F2 8D 00 20 A9 20 53 04 AD 34 42 8D 01 20 '
        'A9 F9 53 08 A9 A5 8D 02 60 AD 02 20 8D 03 20 '
        'AD 00 18 8D 04 20 AD 00 1C 8D 05 20 AD 00 10 8D 06 20 '
        'A9 7E 8D 07 18 AD 07 18 8D 07 20 '
        'A9 12 8D 00 08 8D 00 18 AD 00 18 AD 00 08 8D 08 20 80 FE')


def authored_rom(count):
    if count not in BANK_COUNTS:
        raise ValueError('Select a declared authored ROM size')
    image = bytearray((bank*31 + offset*17 + 29) & 255
                      for bank in range(count) for offset in range(8192))
    code = authored_program()
    for bank in range(count):
        image[bank*8192+256:bank*8192+256+len(code)] = code
    image[8190:8192] = b'\0\xe1'
    return bytes(image)


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte)*1099511628211) & ((1 << 64)-1)
    return value


def plans(count):
    result = []
    operations = [('r', 0, 0, 0, 0), ('s',), ('d',)]
    for bank in range(128):
        for offset in (0, 1, 0x234, 0x1234, 8190, 8191):
            operations += [('q', bank, offset), ('p', bank, offset)]
        operations += [('w', bank, 0x234, 0xDE), ('q', bank, 0x234)]
    for bank in (*range(0x80, 0xF8), 0xFC, 0xFD, 0xFE):
        for offset in (0, 4095, 8191):
            operations += [('q', bank, offset), ('w', bank, offset, 0x19), ('q', bank, offset)]
    for bank in range(0xF8, 0xFC):
        operations += [('w', bank, 13, (bank*23+7) & 255)]
        operations += [('q', alias, 13) for alias in range(0xF8, 0xFC)]
    operations += [('w', 255, 0x800, 0x55), ('q', 255, 0x800)]
    for offset in (0x1800, 0x1801, 0x1807, 0x18C0, 0x1BFF, 0x1C00, 0x1FFF):
        operations += [('q', 255, offset), ('w', 255, offset, 0xA5),
                       ('q', 255, offset), ('q', 255, 0x800)]
    operations += [('q', 255, 0x1000), ('s',)]
    result.append(dict(id=f'memory-{count}', operations=operations))
    for region in (0, 1):
        for fill in (0, 255, 165):
            result.append(dict(id=f'trace-{count}-{region}-{fill}', operations=[
                ('r', region, fill, fill, fill), ('s',), ('d',), ('i', 64),
                *[('q', 0xF8, i) for i in range(9)], ('s',)]))
    return result


def serialize(cases):
    lines, spans, total = [], [], 0
    for case in cases:
        before = total
        for operation in case['operations']:
            lines.append(' '.join(map(str, operation)))
            total += operation[1] if operation[0] == 'i' else int(operation[0] in ('s', 'd', 'q', 'p'))
        spans.append(dict(id=case['id'], start=before, records=total-before))
    return '\n'.join(lines)+'\n', spans


def independent_expectations(records, cases, count, image):
    """Check literal memory/presence/reset values without a production parser."""
    index = checks = 0
    for case in cases:
        ram = bytearray(8192)
        region = fill = 0
        latch = 255
        for operation in case['operations']:
            op = operation[0]
            if op == 'r':
                region, registers, mpr, fill = operation[1:]
                ram[:] = bytes([fill])*8192
                latch = 255
            elif op == 'w':
                bank, offset, value = operation[1:]
                if 0xF8 <= bank <= 0xFB:
                    ram[offset] = value
                elif bank == 255 and offset == 0x800:
                    latch = value
            elif op in ('q', 'p'):
                bank, offset = operation[1:]
                if bank < 128:
                    value = image[backing_bank(count, bank)*8192+offset]
                elif 0xF8 <= bank <= 0xFB:
                    value = ram[offset]
                elif bank == 255 and offset == 0x800:
                    value = latch
                elif bank == 255 and offset == 0x1000:
                    value = 0xF0 if region == 0 else 0xB0
                    latch = value
                else:
                    value = 255
                if records[index] != dict(kind='peek' if op == 'p' else 'memory', values=[bank, offset, value]):
                    raise ValueError(f'Independent {case["id"]} memory mismatch at {operation}: {records[index]}')
                index += 1
                checks += 1
            elif op == 's':
                values = records[index]['values']
                if index == next(s['start'] for s in serialize(cases)[1] if s['id'] == case['id']):
                    expected = [0xE100, registers, registers, registers, registers,
                                (registers & ~(32|8|16)) | 4, 12, 0, *([mpr]*7), 0, 0, 255, 0, 0, 0, 0, 0]
                    if values != expected:
                        raise ValueError(f'Independent {case["id"]} initial CPU mismatch: {values} != {expected}')
                    checks += len(values)
                index += 1
            elif op == 'd':
                values = records[index]['values']
                if values[:3] != [0, 0, 65535] or values[26] != (0xF0 if region == 0 else 0xB0):
                    raise ValueError('Independent initial VDC/presence mismatch')
                if values[-3:] != [fnv(bytes([fill])*8192), fnv(bytes(65536)), fnv(bytes(512))]:
                    raise ValueError('Independent initial memory hashes mismatch')
                checks += 7
                index += 1
            elif op == 'i':
                file0, file1 = backing_bank(count, 0x40), backing_bank(count, 0x20)
                expected = [image[file0*8192+0x1234], image[file1*8192+0x234], 0xA5, 0xA5,
                            0xFF, 0xFF, 0xF0 if region == 0 else 0xB0, 0xFF, 0x12]
                ram[:9] = bytes(expected)
                latch = 0x12
                index += operation[1]
    if index != len(records):
        raise ValueError('Independent authored record accounting differs')
    return checks
