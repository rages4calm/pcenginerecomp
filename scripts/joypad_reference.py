"""Authored controller-port sequences for an isolated Geargrafx process.

The emulator supplies every expected CPU state and final RAM image. Host
buttons are held through MCP, without frame macros or presentation input.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tests'))
from generate_joypad_fixture import make_fixture

BUTTONS = ('I', 'II', 'select', 'run', 'up', 'right', 'down', 'left',
           'III', 'IV', 'V', 'VI')


def plans():
    _, cases = make_fixture()
    sites = {(op, address): pc for pc, op, address in cases}
    addresses = (0x1000, 0x1001, 0x107F, 0x1100, 0x13FF,
                 0xB000, 0xB001, 0xB07F, 0xB100, 0xB3FF)
    result = []

    def access(value=-1, alias=0, op=None):
        return sites[(op if op is not None else 0xAD if value < 0 else 0x8D), addresses[alias]], value

    def append(name, operations, types=(2,) * 5, pressed=(0,) * 5, tap=False):
        i = len(result)
        result.append({'id': name, 'seed': i, 'a': (i * 43 + 0x80) & 255,
                       'x': i * 37 & 255, 'y': i * 67 & 255,
                       'sp': (0, 1, 254, 255)[i % 4], 'p': (4, 255, 0x55, 0xAE)[i % 4],
                       'types': list(types), 'pressed': list(pressed), 'tap': tap, 'steps': operations})

    # Cold reads after host button injection remain latched until a write.
    # Each button has its own plan, preserving the independently observed
    # direction/button ordering rather than folding these into masks only.
    for bit, button in enumerate(BUTTONS):
        operations = [access(), access(0), access(), access(1), access(),
                      access(3), access(), access(2), access(), access(0), access(),
                      access(1), access(), access(3), access(), access(0), access(), access(1), access()]
        append('button-' + button, operations, types=(6 if bit >= 8 else 2,) * 5,
               pressed=(1 << bit, 0, 0, 0, 0))

    for kind in (2, 6):
        for mask in (0, 0xFFF, 0xA55, 0x5AA):
            operations = [access()]
            for i, value in enumerate((3, 3, 0, 0, 1, 1, 2, 3, 2, 0, 1, 3, 0, 1, 3, 0, 1)):
                operations += [access(value, i % 10), access(alias=(i + 3) % 10)]
            append(f'pad-{kind}-mask-{mask:03x}', operations,
                   types=(kind,) * 5, pressed=(mask,) * 5)

    # Exhaust all output byte values through every address alias. Non-control
    # high bits must not alter the two control lines, including held levels.
    for start in range(0, 256, 64):
        operations = [access()]
        for value in range(start, start + 64):
            operations += [access(value, value % 10), access(alias=(value + 5) % 10)]
        append(f'output-bytes-{start:02x}', operations,
               types=(6,) * 5, pressed=(0xA95,) * 5)

    # Five distinct pads, mixed controller types, repeat levels, saturation
    # beyond player five, CLR-with-SEL-low and canonical SEL-high reset.
    for tap in (False, True):
        operations = [access(), access(3), access(), access(0), access()]
        for index in range(8):
            operations += [access(1, index % 10), access(), access(1), access(), access(0), access()]
        operations += [access(2), access(), access(0), access(), access(3), access(), access(0), access()]
        for index in range(6):
            operations += [access(1), access(), access(0), access()]
        append(f'mixed-five-tap-{int(tap)}', operations,
               types=(2, 6, 2, 6, 6), pressed=(0x001, 0x212, 0x044, 0x888, 0xF20), tap=tap)

    for op in (0x0C, 0x1C):
        operations = [access(3), access(0), access()]
        for value in (0, 1, 2, 3, 0x7F, 0x80, 0xFF):
            operations += [(sites[op, 0x1000], value), access(), (sites[op, 0xB3FF], value), access()]
        append(f'rmw-{op:02x}', operations, types=(6,) * 5, pressed=(0x55A,) * 5)
    return result


def write_plan(path, plan, japanese, cd):
    header = [plan[k] for k in ('seed', 'a', 'x', 'y', 'sp', 'p')]
    header += [int(japanese), int(cd), int(plan['tap']), *plan['types'], *plan['pressed'], len(plan['steps'])]
    path.write_text(' '.join(map(str, header)) + '\n' + ''.join(f'{pc} {value}\n' for pc, value in plan['steps']), encoding='ascii')


def run_joypad_matrix(client, areas, args, started, info):
    from scripts.reference_geargrafx import state
    snapshot, _ = make_fixture()
    ram_area = next(a['id'] for a in areas if a['name'] == 'SYSTEM RAM' and a['byte_size'] == 8192)
    media = client.call('get_media_info')
    cd = args.suite == 'joypad-cd'
    if bool(media['is_cdrom']) != cd or bool(media['is_cdrom_hardware_enabled']) != cd:
        raise RuntimeError('Authored media hardware profile differs')
    # In Geargrafx's pinned core, the input region line is high only when
    # GetConsoleType() is explicitly PCE/SGX. Headless Auto remains Auto and
    # drives the US line. Do not infer region from the guest port value.
    if media['console_type'] != 'Auto':
        raise RuntimeError('Expected isolated headless Auto console configuration')
    japanese = False
    selected = plans()[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError('Empty joypad shard')
    counts = {tier: {'states': 0, 'ram': 0, 'native_steps': 0, 'interpreter_steps': 0}
              for tier in ('native', 'interpreter')}

    def check_budget():
        if time.monotonic() - started > 180 or (args.out / 'process.log').stat().st_size > 256 * 1024:
            raise RuntimeError('Joypad reference exceeded its time or diagnostic budget')

    for plan in selected:
        check_budget()
        held = client.call('get_input_state')
        for row in held['players']:
            for button in row['pressed']:
                client.call('controller_button', player=row['player'], button=button, action='release')
        for player, kind in enumerate(plan['types'], 1):
            client.call('controller_set_type', player=player, type='standard' if kind == 2 else 'avenue_pad_6')
        client.call('controller_set_turbo_tap', enabled=plan['tap'])
        client.call('debug_reset')
        client.call('debug_pause')
        # Authored ROM bootstrap establishes SEI, CSH and the initial map.
        client.call('write_huc6280_register', name='PC', value='E000')
        for _ in range(17):
            client.call('debug_step_into')
        for player, mask in enumerate(plan['pressed'], 1):
            for bit, button in enumerate(BUTTONS):
                if mask & (1 << bit):
                    client.call('controller_button', player=player, button=button, action='press')
        observed = client.call('get_input_state')
        expected_pressed = {player: {button for bit, button in enumerate(BUTTONS) if mask & (1 << bit)}
                            for player, mask in enumerate(plan['pressed'], 1)}
        if observed['pending_releases'] or {row['player']: set(row['pressed']) for row in observed['players']} != expected_pressed:
            raise RuntimeError('Reference held controller input differs')
        ram = bytearray((i * 37 + plan['seed'] * 17) & 255 for i in range(8192))
        for pa, value in snapshot.memory.items():
            ram[pa - 0x1F0000] = value
        client.call('write_memory', area=ram_area, offset='0000', bytes=ram.hex(' '))
        client.call('write_huc6280_register', name='PC', value='2700')
        for _ in range(16):
            client.call('debug_step_into')
        for name, key in (('A', 'a'), ('X', 'x'), ('Y', 'y'), ('S', 'sp'), ('P', 'p')):
            client.call('write_huc6280_register', name=name, value=f'{plan[key]:X}')
        before = client.call('get_huc6280_status')
        if state(before)['mpr'] != list(snapshot.mpr) or before['SPEED'] != '7.16 MHz' or before['TIMER']:
            raise RuntimeError('Reference controller CPU profile differs')
        expected = []
        for pc, value in plan['steps']:
            check_budget()
            client.call('write_huc6280_register', name='PC', value=f'{pc:X}')
            if value >= 0:
                client.call('write_huc6280_register', name='A', value=f'{value:X}')
            client.call('debug_step_into')
            expected.append({'cpu': state(client.call('get_huc6280_status'))})
        wanted_ram = bytes.fromhex(client.call('read_memory', area=ram_area, offset='0000', size=8192)['data']).hex()
        plan_path = args.out / 'sequence.txt'
        write_plan(plan_path, plan, japanese, cd)
        for tier in counts:
            process = subprocess.run([str(args.probe.resolve()), '--probe', str(plan_path.resolve()), tier],
                                     capture_output=True, text=True, check=True, timeout=5)
            actual = json.loads(process.stdout)
            got = [{'cpu': item['cpu']} for item in actual['states']]
            mismatch = {}
            if got != expected:
                mismatch['states'] = {'actual': got, 'expected': expected}
            if actual['ram'] != wanted_ram:
                mismatch['ram'] = {'actual': actual['ram'], 'expected': wanted_ram}
            steps = len(plan['steps'])
            n, i = actual['native_steps'], actual['interpreter_steps']
            if (n, i) != ((steps, 0) if tier == 'native' else (0, steps)):
                mismatch['counters'] = {'native': n, 'interpreter': i, 'expected': steps}
            if mismatch:
                (args.out / 'failure.json').write_text(json.dumps({'plan': plan['id'], 'tier': tier, 'mismatch': mismatch}, indent=2) + '\n')
                raise RuntimeError(f"Reference joypad mismatch: {plan['id']}, {tier}")
            counts[tier]['states'] += steps
            counts[tier]['ram'] += 1
            counts[tier]['native_steps'] += n
            counts[tier]['interpreter_steps'] += i
    report = {'schema': 1, 'result': 'pass', 'suite': args.suite, 'oracle': info['serverInfo'],
              'oracle_exe_sha256': hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              'probe_sha256': hashlib.sha256(args.probe.read_bytes()).hexdigest(),
              'shard': {'index': args.shard_index, 'count': args.shard_count},
              'checked_sequences': [p['id'] for p in selected], 'comparisons': counts,
              'profile': {'japanese': japanese, 'cd': cd},
              'inputs': 'Authored bootstrap and work RAM; held MCP controller input; authored blank CD when requested',
              'scope': 'CPU/register/flag/MPR checkpoints and full work RAM; 2/6 buttons, five pads, multitap edges/saturation, aliases, all output bytes and RMW',
              'not_checked': ['Other console region settings', 'host events during a guest sequence', 'mouse/Avenue Pad 3/TurboLink/MB128/turbo', 'IRQ delivery', 'hardware qualification', 'gameplay']}
    (args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
