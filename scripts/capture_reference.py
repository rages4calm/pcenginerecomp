"""Compare authored multi-context capture emission against portable Geargrafx.

No downloads, retail input, owner settings or saves are used. The portable
configuration must be absent on entry and is removed on every exit path.
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
sys.path.insert(0, str(ROOT/'tests'))
from generate_capture_reference_fixture import plans, ram_image, rom_image
from scripts.reference_geargrafx import Mcp, state


def trace_ticks(trace, pcs, mappings):
    if trace.get('overrun') or trace.get('count') != len(pcs) or len(trace.get('lines', [])) != len(pcs):
        raise RuntimeError('Missing, extra or overwritten capture-reference trace entries')
    ticks = []
    for line, pc, mapping in zip(trace['lines'], pcs, mappings):
        match = re.match(r'^@(\d+)\s+.*?\b([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s', line)
        if not match or int(match[2], 16) != mapping[pc >> 13] or int(match[3], 16) != pc:
            raise RuntimeError('Capture-reference trace bank/PC mismatch')
        ticks.append(int(match[1]))
    deltas = [b-a for a, b in zip(ticks, ticks[1:])]
    if any(delta <= 0 for delta in deltas):
        raise RuntimeError('Non-monotonic capture-reference clock')
    return deltas


def run(args):
    exe, probe, out = args.exe.resolve(), args.probe.resolve(), args.out.resolve()
    if not exe.is_relative_to(ROOT/'.deps') or not exe.is_file() or not probe.is_file():
        raise ValueError('Require an existing checkout-local portable emulator and compiled probe')
    config = exe.parent/'config.ini'
    if config.exists():
        raise ValueError('Portable configuration already exists; refuse to overwrite it')
    if not (exe.parent/'portable.ini').exists():
        raise ValueError('Reference executable is not an initialized portable instance')
    out.mkdir(parents=True, exist_ok=True)
    image = out/'synthetic.pce'
    image.write_bytes(rom_image())
    save = out/'isolated-saves'; save.mkdir(exist_ok=True)
    report = dict(schema=1, result='incomplete', suite='observed-code-multi-context',
                  oracle_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                  probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest())
    result_path = out/'result.json'
    result_path.write_text(json.dumps(report, indent=2)+'\n')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    process = None; started = time.monotonic()
    try:
        config.write_text('[General]\nVersion=999\n[Debug]\nDebug=true\n[Emulator]\nStartPaused=true\nPauseWhenInactive=false\nBackupRAMDirOption=2\nBackupRAMPath='+str(save)+'\nSaveFilesDirOption=2\nSaveFilesPath='+str(save)+'\nSaveStatesDirOption=2\nSaveStatesPath='+str(save)+'\n[Rewind]\nEnabled=false\n')
        with (out/'process.log').open('wb') as log:
            process = subprocess.Popen([str(exe), '--headless', '--portable', '--mcp-http', '--mcp-http-port', str(port)],
                cwd=exe.parent, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            report['pid'] = process.pid
            client = Mcp(port)
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Reference exited during startup')
                try:
                    info = client.rpc('initialize', dict(protocolVersion='2025-11-25', capabilities={}, clientInfo=dict(name='capture-reference', version='1')))
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError('Reference startup timeout')
            client.headers['MCP-Protocol-Version'] = info['protocolVersion']
            client.rpc('notifications/initialized')
            client.call('load_media', file_path=str(image))
            client.call('debug_pause')
            # The cartridge bootstrap establishes the permanent RAM window.
            client.call('write_huc6280_register', name='PC', value='E000')
            for _ in range(18):
                client.call('debug_step_into')
            areas = client.call('list_memory_areas')['areas']
            area = next(a['id'] for a in areas if a['name'] == 'SYSTEM RAM' and a['byte_size'] == 8192)
            counts = {tier:dict(states=0, complete_ram=0, matching_instruction_clock_deltas=0, native_steps=0, interpreter_steps=0)
                      for tier in ('native', 'interpreter')}
            guard_checks = 0
            checked = []
            for index, plan in enumerate(plans()):
                if time.monotonic()-started > 240:
                    raise RuntimeError('Reference exceeded 240-second work budget')
                client.call('write_memory', area=area, offset='0000', bytes=ram_image(plan).hex(' '))
                client.call('write_huc6280_register', name='PC', value='2700')
                for _ in range(18):
                    client.call('debug_step_into')
                status = client.call('get_huc6280_status')
                if state(status)['mpr'] != plan['mpr'] or status['SPEED'] != {3:'7.16 MHz', 12:'1.79 MHz'}[plan['divisor']]:
                    raise RuntimeError('Reference mapping/speed bootstrap failed')
                if status['TIMER'] or any(status[k] for k in ('IRQ1_asserted', 'IRQ2_asserted', 'TIQ_asserted')):
                    raise RuntimeError('Reference pending interrupts are outside the authored single-step scope')
                registers = dict(PC=plan['pc'], A=plan['a'], X=plan['x'], Y=plan['y'], S=plan['sp'], P=plan['p'])
                for name, value in registers.items():
                    client.call('write_huc6280_register', name=name, value=f'{value:X}')
                before = state(client.call('get_huc6280_status'))
                if any(before[k] != registers[v] for k,v in (('pc','PC'),('a','A'),('x','X'),('y','Y'),('sp','S'),('p','P'))):
                    raise RuntimeError('Reference input registers differ from requested values')
                client.call('set_trace_log', enabled=True, output='memory', memory_size='100K', filters=['cpu.instructions'])
                tail = client.call('get_trace_log', start=-1, count=1)
                sequence = tail['next_sequence']
                if sequence != tail['total_logged']:
                    raise RuntimeError('Reference trace tail mismatch')
                expected = []
                for pc in (plan['pc'], 0x2600):
                    client.call('write_huc6280_register', name='PC', value=f'{pc:X}')
                    client.call('debug_step_into')
                    expected.append(state(client.call('get_huc6280_status')))
                client.call('write_huc6280_register', name='PC', value='2602')
                client.call('debug_step_into')
                trace = client.call('get_trace_log', start=sequence, count=3)
                client.call('set_trace_log', enabled=False)
                deltas = trace_ticks(trace, (plan['pc'],0x2600,0x2602), (plan['mpr'],plan['next_mpr'],plan['next_mpr']))
                ticks = 0
                for wanted, delta in zip(expected, deltas):
                    if delta % plan['divisor']:
                        raise RuntimeError('Reference master clocks are not integral CPU cycles')
                    ticks += delta
                    wanted.update(ticks=ticks, cycles=ticks//plan['divisor'])
                wanted_ram = bytes.fromhex(client.call('read_memory', area=area, offset='0000', size=8192)['data']).hex()
                for tier in counts:
                    result = subprocess.run([str(probe),str(index),tier], capture_output=True, text=True, check=True, timeout=5)
                    actual = json.loads(result.stdout)
                    wanted = dict(states=expected, ram=wanted_ram, mpr_latch=expected[-1]['a'],
                                  native_steps=2 if tier=='native' else 0, interpreter_steps=2 if tier=='interpreter' else 0)
                    if actual != wanted:
                        mismatch = {k:dict(actual=actual.get(k),expected=v) for k,v in wanted.items() if actual.get(k)!=v}
                        (out/'failure.json').write_text(json.dumps(dict(plan=plan['id'], tier=tier, mismatch=mismatch),indent=2)+'\n')
                        raise RuntimeError(f'Capture reference mismatch: {plan["id"]}, {tier}')
                    for key, value in dict(states=2, complete_ram=1, matching_instruction_clock_deltas=2,
                                           native_steps=wanted['native_steps'],interpreter_steps=wanted['interpreter_steps']).items():
                        counts[tier][key] += value
                guards = subprocess.run([str(probe),str(index),'guards'], capture_output=True, text=True, check=True, timeout=5)
                guard_checks += json.loads(guards.stdout)['guard_checks']
                checked.append(plan['id'])
                if len(checked) % 16 == 0:
                    print(f'Compared {len(checked)} capture-reference plans per tier',file=sys.stderr,flush=True)
            report.update(result='pass', oracle=info['serverInfo'], plans=len(checked), checked_plans=checked,
                          comparisons=counts, local_guard_checks=guard_checks,
                          scope='Authored direct capture module; per-instruction CPU/MPR states and master clocks, hidden latch through TMA #0, complete final 8 KiB RAM; both native and interpreter with exact tier counters',
                          guard_scope='Local unchanged-state misses for every encoded byte, unknown PC and full MPR context; not an independent emulator guard claim',
                          not_checked=['IRQ delivery (RTI only)', 'bus phases', 'hardware', 'CD/devices', 'retail game route', 'all CPU encodings'])
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        config.unlink(missing_ok=True)
        report.update(config_restored=not config.exists(), child_stopped=process is None or process.poll() is not None,
                      elapsed_seconds=time.monotonic()-started)
        result_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='checked_plans'},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/native-coverage/reference')
    try:
        run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr)
        raise SystemExit(1)
