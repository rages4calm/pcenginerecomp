"""Bounded whole-instruction block-transfer checks against isolated Geargrafx.

Only authored code and RAM enter either process. Full RAM includes stack save /
restore effects; entry timestamps compare complete-instruction clock deltas.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from generate_block_fixture import make_fixture
from scripts.reference_geargrafx import Mcp, state

FLAGS = (0, 255, 0x55, 0xAA)


def plans():
    _, cases = make_fixture()
    result = []
    for index, (pc, op, source, destination, length) in enumerate(cases):
        for divisor in (3, 12):
            for variant, flags in enumerate(FLAGS):
                seed = (index * 7 + variant * 13 + divisor) & 255
                # Geargrafx re-fetches the opcode on each transfer byte.
                # Preserve F3 in the opcode cell during the zero-length TAI
                # case rather than silently qualifying self-overwrite behavior.
                patches = [(0x300, 0xF3), (0x301, 0xF3)] if op == 0xF3 and length == 0 else []
                result.append({'id': f'{index:03d}-{op:02x}-{divisor}-{variant}',
                               'index': index, 'pc': pc, 'op': op,
                               'source': source, 'destination': destination, 'length': length,
                               'seed': seed, 'a': (0x83 + index * 29 + variant) & 255,
                               'x': (0x39 + index * 11 + variant) & 255,
                               'y': (0xA7 + index * 17 + variant) & 255,
                               'sp': (0, 1, 254, 255)[variant], 'p': flags,
                               'divisor': divisor, 'patches': patches,
                               'effective_length': length,
                               'timing': True})
        if 0x2100 <= pc < 0x2200:
            # Y/A/X overwrite length-low/destination-high/destination-low
            # before the instruction fetches them. The surviving opcode is
            # untouched, allowing an independent live check of this ordering.
            for divisor in (3, 12):
                result.append({'id': f'{index:03d}-{op:02x}-{divisor}-operand-stack-alias',
                               'index': index, 'pc': pc, 'op': op,
                               'source': source, 'destination': destination, 'length': length,
                               'effective_length': 3, 'seed': index & 255,
                               'a': 0x24, 'x': 0, 'y': 3, 'sp': (pc + 5) & 255,
                               'p': 255, 'divisor': divisor, 'patches': [], 'timing': True})
    return result


def initial_ram(snapshot, plan):
    ram = bytearray((i * 37 + plan['seed'] * 17) & 255 for i in range(8192))
    for physical, value in snapshot.memory.items():
        ram[physical - 0x1F0000] = value
    for offset, value in plan['patches']:
        ram[offset] = value
    return ram


def write_plan(path, plan):
    header = [plan[key] for key in ('index', 'seed', 'a', 'x', 'y', 'sp', 'p', 'divisor')]
    path.write_text(' '.join(map(str, header + [len(plan['patches'])])) + '\n' +
                    ''.join(f'{offset} {value}\n' for offset, value in plan['patches']), encoding='ascii')


def measured_ticks(trace, pc, sentinel):
    """Geargrafx emits one block-entry trace record plus one sentinel."""
    count = 2
    if trace.get('overrun') or trace.get('count') != count or len(trace.get('lines', [])) != count:
        raise RuntimeError('Missing, extra or overwritten block trace entries')
    entries = []
    for index, line in enumerate(trace['lines']):
        match = re.match(r'^@(\d+)\s+.*?\b([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s', line)
        expected_pc = sentinel if index == count - 1 else pc
        if not match or int(match[2], 16) != 0xF8 or int(match[3], 16) != expected_pc:
            raise RuntimeError('Unexpected block trace bank/PC')
        entries.append(int(match[1]))
    if any(b <= a for a, b in zip(entries, entries[1:])):
        raise RuntimeError('Non-monotonic block trace clocks')
    return entries[-1] - entries[0]


def run(args):
    exe, probe, out = args.exe.resolve(), args.probe.resolve(), args.out.resolve()
    if not exe.is_relative_to(ROOT / '.deps') or not exe.is_file() or not probe.is_file():
        raise ValueError('Use existing project-local .deps Geargrafx and compiled block probe')
    if not 1 <= args.shard_count <= 32 or not 0 <= args.shard_index < args.shard_count:
        raise ValueError('Invalid shard bounds')
    selected = plans()[args.shard_index::args.shard_count]
    if not selected:
        raise ValueError('Empty block shard')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').write_text('{"result":"incomplete"}\n')
    setup = bytes.fromhex('78 D4 A9 FF 53 01 A9 F8 53 02 A9 80 53 04 A9 81 53 08 A9 82 53 10 A9 83 53 20 A9 84 53 40 80 FE')
    rom = bytearray([0xEA] * 8192)
    rom[:len(setup)] = setup
    rom[-2:] = bytes((0, 0xE0))
    image = out / 'synthetic.pce'
    image.write_bytes(rom)
    (exe.parent / 'portable.ini').touch(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    started = time.monotonic()
    snapshot, _ = make_fixture()
    counts = {tier: {'states': 0, 'ram': 0, 'matching_tick_deltas': 0,
                     'native_steps': 0, 'interpreter_steps': 0} for tier in ('native', 'interpreter')}
    with (out / 'process.log').open('wb') as log:
        process = subprocess.Popen([str(exe), '--headless', '--portable', '--mcp-http', '--mcp-http-port', str(port)],
            cwd=exe.parent, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        client = Mcp(port)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Isolated block reference exited')
                try:
                    info = client.rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                        'clientInfo': {'name': 'pcenginerecomp-block-reference', 'version': '0.1'}})
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError('Reference startup exceeded budget')
            client.headers['MCP-Protocol-Version'] = info['protocolVersion']
            client.rpc('notifications/initialized')
            client.call('load_media', file_path=str(image))
            client.call('debug_pause')
            client.call('write_huc6280_register', name='PC', value='E000')
            for _ in range(17):
                client.call('debug_step_into')
            areas = client.call('list_memory_areas')['areas']
            area = next(a['id'] for a in areas if a['name'] == 'SYSTEM RAM' and a['byte_size'] == 8192)
            for plan in selected:
                if time.monotonic() - started > 180 or (out / 'process.log').stat().st_size > 256 * 1024:
                    raise RuntimeError('Block reference exceeded time or diagnostic budget')
                ram = initial_ram(snapshot, plan)
                client.call('write_memory', area=area, offset='0000', bytes=ram.hex(' '))
                # Map every logical page to work RAM, including wrap at FFFF.
                # Bootstrap bytes are transient and restored before observation.
                boot = bytes((0xA9, 0xF8, 0x53, 0xFF, 0xD4 if plan['divisor'] == 3 else 0x54))
                client.call('write_memory', area=area, offset='0700', bytes=boot.hex(' '))
                client.call('write_huc6280_register', name='PC', value='2700')
                for _ in range(3):
                    client.call('debug_step_into')
                client.call('write_memory', area=area, offset='0700', bytes=ram[0x700:0x705].hex(' '))
                for name, key in (('PC', 'pc'), ('A', 'a'), ('X', 'x'), ('Y', 'y'), ('S', 'sp'), ('P', 'p')):
                    client.call('write_huc6280_register', name=name, value=f'{plan[key]:X}')
                before = client.call('get_huc6280_status')
                expected_before = {key: plan[key] for key in ('pc', 'a', 'x', 'y', 'sp', 'p')} | {'mpr': [0xF8] * 8}
                if state(before) != expected_before or before['SPEED'] != ('7.16 MHz' if plan['divisor'] == 3 else '1.79 MHz'):
                    raise RuntimeError('Reference block CPU setup differs')
                if before['TIMER'] or any(before[key] for key in ('IRQ1_asserted', 'IRQ2_asserted', 'TIQ_asserted')):
                    raise RuntimeError('Active reference timer/IRQ outside block check scope')
                if plan['timing']:
                    client.call('set_trace_log', enabled=True, output='memory', memory_size='100K', filters=['cpu.instructions'])
                    tail = client.call('get_trace_log', start=-1, count=1)
                    sequence = tail['next_sequence']
                    if sequence != tail['total_logged']:
                        raise RuntimeError('Trace cursor did not reach current tail')
                client.call('debug_step_into')
                observed = client.call('get_huc6280_status')
                expected = state(observed)
                wanted_ram = bytes.fromhex(client.call('read_memory', area=area, offset='0000', size=8192)['data']).hex()
                oracle_ticks = None
                if plan['timing']:
                    # An out-of-band sentinel leaves the compared guest RAM intact.
                    sentinel = 0x2700
                    client.call('write_memory', area=area, offset='0700', bytes='EA')
                    client.call('write_huc6280_register', name='PC', value=f'{sentinel:X}')
                    client.call('debug_step_into')
                    trace = client.call('get_trace_log', start=sequence, count=2)
                    client.call('set_trace_log', enabled=False)
                    try:
                        oracle_ticks = measured_ticks(trace, plan['pc'], sentinel)
                    except RuntimeError:
                        (out / 'failure-trace.json').write_text(json.dumps({'plan': plan, 'trace': trace}, indent=2) + '\n')
                        raise
                plan_path = out / 'plan.txt'
                write_plan(plan_path, plan)
                for tier in counts:
                    completed = subprocess.run([str(probe), str(plan_path), tier], capture_output=True, text=True, check=True, timeout=5)
                    actual = json.loads(completed.stdout)
                    actual_cpu = {key: actual['cpu'][key] for key in expected}
                    expected_counts = (1, 0) if tier == 'native' else (0, 1)
                    if actual_cpu != expected or actual['ram'] != wanted_ram or (actual['native_steps'], actual['interpreter_steps']) != expected_counts:
                        (out / 'failure.json').write_text(json.dumps({'plan': plan, 'tier': tier,
                            'actual': actual, 'expected': {'cpu': expected, 'ram': wanted_ram}}, indent=2) + '\n')
                        raise RuntimeError(f'Block reference mismatch: {plan["id"]}, {tier}')
                    if oracle_ticks is not None and (actual['cpu']['ticks'] != oracle_ticks or actual['cpu']['cycles'] * plan['divisor'] != oracle_ticks):
                        (out / 'failure.json').write_text(json.dumps({'plan': plan, 'tier': tier,
                            'actual_cpu': actual['cpu'], 'oracle_ticks': oracle_ticks}, indent=2) + '\n')
                        raise RuntimeError(f'Block timing mismatch: {plan["id"]}, {tier}')
                    counts[tier]['states'] += 1
                    counts[tier]['ram'] += 1
                    counts[tier]['matching_tick_deltas'] += int(oracle_ticks is not None)
                    counts[tier]['native_steps'] += actual['native_steps']
                    counts[tier]['interpreter_steps'] += actual['interpreter_steps']
            report = {'schema': 1, 'result': 'pass', 'suite': 'block-transfer', 'oracle': info['serverInfo'],
                'oracle_exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
                'probe_sha256': hashlib.sha256(probe.read_bytes()).hexdigest(),
                'shard': {'index': args.shard_index, 'count': args.shard_count},
                'checked_plans': [p['id'] for p in selected], 'comparisons': counts,
                'scope': 'completed instruction CPU/MPR state and all 8 KiB RAM, including stack; complete-instruction entry trace clock deltas',
                'not_checked': ['opcode overwritten during transfer', 'bus phase accuracy', 'MMIO', 'IRQ delivery', 'hardware', 'gameplay']}
            (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({key: value for key, value in report.items() if key != 'checked_plans'}, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT / '.local/block-check/live')
    parser.add_argument('--shard-index', type=int, default=0)
    parser.add_argument('--shard-count', type=int, default=1)
    arguments = parser.parse_args()
    try:
        run(arguments)
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
