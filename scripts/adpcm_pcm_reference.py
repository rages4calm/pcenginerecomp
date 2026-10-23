"""Finite authored raw ADPCM decoder/clock checks against unmodified Geargrafx.

Reads Geargrafx 1.8.4 Windows v44 save states, never loads or patches them.
The 64 KiB authored RAM identity locates the serialized device exactly once;
the pinned little-endian widths, header, and all public device fields must
agree before hidden predictor/index/phase values are accepted. Layout facts
come from https://github.com/drhelius/Geargrafx/tree/1.8.4/src (types.h,
adpcm.cpp, adpcm_inline.h, geargrafx_core.cpp), GPL-3.0 research references.
No emulator implementation is copied into the runtime or this reader.
This checks digital state before Gear's separate filter/gain/resampling path.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.reference_geargrafx import Mcp
from scripts.cd_reference import prepare_media
from scripts.raster_reference import delay_program

EXE_SHA = '742b2d8d21060368134324e1ce6c32a9751e7a9776549ed78448eca93e6e8563'
SOURCE_SHA = {'src__adpcm.cpp': '5a52c147534c1d15515f6461f278655002da5edb4d9bc3db14680ac98b0ccd25',
              'src__adpcm_inline.h': '06ce995525f8c35a4e8616c79eb428bf7493297c150317d089b0d16993e22950',
              'src__geargrafx_core.cpp': 'a69e71d18eb9b59d7f80136e8099a8595399afc481d5c5b1021dcfd189a27833',
              'src__defines.h': '34db3382395299131d0e3b3b90a12976a134177344684e4eae6d22e9c9fcf67e',
              'src__audio_inline.h': '8e458c60de1823b4ddab1ac3e610949cc4ba299ef47838eae413523626420d64',
              'src__geargrafx_core_inline.h': '549d78f09899a950d635084fbc00a9ff78014eb217c26f07eb4055b4a9b85dcb',
              'src__types.h': '9d41b5124e4fe9dd895472f3038530983db70973e4ed9a2926cf84dbde9dc74e',
              'src__huc6280_opcodes.cpp': '68df46432e4da9c0a68ba6dd132bda270df7e90b393ddce25ef974090a6d3326',
              'src__huc6280_opcodes_inline.h': '750303e55d1e923344448ed1c8ce9cb5f5da2608af2d821bc51005ce5abb0142',
              'src__huc6280_timing.h': '42ed58c25d9e2c9263582c7a90136ad6f039d56dc43f441ec0540627263e831d',
              'src__huc6280_inline.h': '28ecd6fdd06c6a6a031899c9f992bb285c9b7322ec43b40db24358e2554efb78'}
HEADER_SIZE = 200  # Win64 C++ natural layout, checked against size/build/CRC.
FIELDS = ('predictor', 'index', 'control', 'rate', 'phase', 'period', 'read_address', 'length',
          'playing', 'pending', 'nibble', 'end', 'half')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(reference):
    """Accept the flattened local cache or an ordinary upstream src directory."""
    paths = {}
    for name, expected in SOURCE_SHA.items():
        path = reference/name
        if not path.is_file():
            path = reference/name.removeprefix('src__')
        if not path.is_file() or digest(path) != expected:
            raise ValueError('Gear layout/source identity changed: '+name)
        paths[name] = path.resolve()
    return paths


def authored_ram():
    """Unique full-block marker with intentional positive/negative/clamp ramps."""
    ram = bytearray(b''.join(hashlib.sha256(b'authored-adpcm-v1'+struct.pack('<I', i)).digest()
                            for i in range(2048)))
    vector = bytes([0x77]*20+[0xff]*20+[0]*100+list(range(256)))
    for i, byte in enumerate(vector):
        ram[(65535+i)&65535] = byte
    return bytes(ram)


def parse_state(data, ram, public):
    """Reject unknown formats/ambiguous markers before reading hidden fields."""
    if len(ram) != 65536 or len(data) < 65536+63+HEADER_SIZE or len(data) > 4*1024*1024:
        raise ValueError('Invalid finite Gear state/RAM size')
    header = data[-HEADER_SIZE:]
    magic, version, size = struct.unpack_from('<III', header)
    if magic != 0x82190619 or version != 44 or size != len(data):
        raise ValueError('Require pinned little-endian Windows Gear state v44/header size')
    if data[0] != 1 or header[165:197].split(b'\0', 1)[0] != b'1.8.4':
        raise ValueError('Require pinned Gear 1.8.4 CD-enabled state')
    if struct.unpack_from('<I', data, 1)[0] != struct.unpack_from('<I', header, 152)[0]:
        raise ValueError('Body/header media CRC disagree')
    if struct.unpack_from('<IHHB', header, 156) != (0, 0, 0, 0):
        raise ValueError('Reference must save without screenshots')
    start = data.find(ram)
    if start < 13 or data.find(ram, start+1) != -1 or start+65536+63 > len(data)-HEADER_SIZE:
        raise ValueError('Authored ADPCM RAM identity missing, ambiguous, or truncated')
    tail = data[start+65536:start+65536+63]
    if any(value not in (0, 1) for value in tail[27:32]):
        raise ValueError('Invalid serialized bool widths/values')
    state = dict(read_latch=tail[0], write_latch=tail[1],
                 read_cycles=struct.unpack_from('<i', tail, 2)[0],
                 write_cycles=struct.unpack_from('<i', tail, 6)[0],
                 read_address=struct.unpack_from('<H', tail, 10)[0],
                 write_address=struct.unpack_from('<H', tail, 12)[0],
                 address=struct.unpack_from('<H', tail, 14)[0], rate=tail[16],
                 period=struct.unpack_from('<i', tail, 17)[0], control=tail[21], dma=tail[22],
                 dma_cycles=struct.unpack_from('<i', tail, 23)[0],
                 end=bool(tail[27]), half=bool(tail[28]), playing=bool(tail[29]),
                 pending=bool(tail[30]), nibble=bool(tail[31]),
                 length=struct.unpack_from('<I', tail, 32)[0],
                 predictor=struct.unpack_from('<h', tail, 36)[0], index=tail[38],
                 phase=struct.unpack_from('<i', tail, 39)[0],
                 frame_samples=struct.unpack_from('<i', tail, 43)[0],
                 master_ticks=struct.unpack_from('<Q', data, 5)[0])
    expected_period = (21477273*65536*(16-(state['rate']&15))+16050)//32100
    if (not 0 <= state['predictor'] <= 4095 or not 0 <= state['index'] <= 48 or
            not 0 <= state['phase'] < state['period']+36*65536 or
            state['period'] != expected_period or not 0 <= state['length'] <= 131071 or
            not 0 <= state['frame_samples'] <= 2048 or
            any(state[k] < 0 for k in ('read_cycles', 'write_cycles', 'dma_cycles')) or
            not all(math.isfinite(x) for x in struct.unpack_from('<ffff', tail, 47))):
        raise ValueError('Serialized scalar widths/ranges/clock incompatible')
    match = dict(read_address=int(public['read_address'], 16),
                 write_address=int(public['write_address'], 16), address=int(public['address'], 16),
                 length=public['length'], control=int(public['control'], 16), dma=int(public['dma'], 16),
                 playing=public['playing'], frame_samples=public['frame_samples'])
    if any(state[k] != value for k, value in match.items()):
        raise ValueError('Serialized/public ADPCM fields disagree')
    status = ((8 if state['playing'] else 0) | (1 if state['end'] else 0) |
              (128 if state['read_cycles'] else 0) | (4 if state['write_cycles'] else 0))
    if int(public['status_register'], 16) != status:
        raise ValueError('Serialized/public ADPCM status disagree')
    frequency = public['frequency_khz']
    if (type(frequency) not in (int, float) or not 0 < frequency <= 32.1 or
            not math.isfinite(frequency) or abs(frequency-32.1/(16-(state['rate']&15))) > 0.00001):
        raise ValueError('Serialized/public ADPCM rate disagree')
    return state


def initial_line(state):
    keys = ('rate', 'control', 'read_address', 'length', 'playing', 'pending', 'nibble',
            'predictor', 'index', 'phase', 'master_ticks', 'end', 'half')
    return ' '.join(str(int(state[key])) for key in keys)+'\n'


def compare_checkpoint(actual, expected, finite_anchor=None):
    """Exact running clocks; separately verify a finite stop's held residue.

    This particular finite vector reaches its final low nibble in plain NOPs:
    each CPU instruction advances Gear's hardware by six master ticks. Gear
    adds that whole callback before noticing finite end on its next callback;
    the toolkit stops at the exact integer master tick. Verify BOTH residues
    from the initial phase and two-sample length, never ignore an arbitrary
    phase difference. This is not a claim of identical stopped clock state.
    """
    if any(actual[k] != expected[k] for k in FIELDS if k != 'phase'):
        raise ValueError('Independent raw ADPCM decoder/control mismatch')
    if finite_anchor is None:
        if actual['phase'] != expected['phase']:
            raise ValueError('Independent running ADPCM phase mismatch')
        return 0
    if (actual['playing'] or actual['pending'] or actual['length'] or actual['nibble'] or
            not actual['end'] or not actual['half'] or finite_anchor['length'] != 1 or
            finite_anchor['nibble'] or finite_anchor['control'] != 0x60):
        raise ValueError('Finite-stop phase exception used outside the exact authored vector')
    needed = finite_anchor['period']*2-finite_anchor['phase']
    reference_stop_ticks = ((needed+6*65536-1)//(6*65536))*6
    runtime_stop_ticks = (needed+65535)//65536
    reference_phase = finite_anchor['phase']+reference_stop_ticks*65536-finite_anchor['period']*2
    runtime_phase = finite_anchor['phase']+runtime_stop_ticks*65536-finite_anchor['period']*2
    difference = reference_phase-runtime_phase
    if (actual['phase'] != reference_phase or expected['phase'] != runtime_phase or
            not 0 <= difference < 6*65536):
        raise ValueError('Unsupported finite-stop phase residue/clock quantum')
    return difference


def run(args):
    exe, probe, out = args.exe.resolve(), args.probe.resolve(), args.out.resolve()
    if not exe.is_relative_to(ROOT/'.deps') or not exe.is_file() or digest(exe) != EXE_SHA or not probe.is_file():
        raise ValueError('Require pinned checkout-local Geargrafx 1.8.4 and compiled ADPCM probe')
    reference = (args.gear_source or ROOT/'.research/Geargrafx_1.8.4').resolve()
    sources = source_files(reference)
    config = exe.parent/'config.ini'
    if config.exists() or not (exe.parent/'portable.ini').is_file() or out.exists():
        raise ValueError('Require unused portable config and a new output directory')
    out.mkdir(parents=True)
    setup = bytes.fromhex('78 D4 A9 FF 53 01 A9 F8 53 FE')
    image, bios = prepare_media(out/'media', setup)
    ram = authored_ram(); (out/'authored.ram').write_bytes(ram)
    inputs = {str(p.relative_to(out)): digest(p) for p in (image, bios, image.parent/'synthetic-disc.bin', out/'authored.ram')}
    savedir = out/'isolated-saves'; savedir.mkdir()
    report = dict(schema=1, result='incomplete', oracle_exe_sha256=EXE_SHA, probe_sha256=digest(probe),
                  reference_source_sha256=SOURCE_SHA, reference_source_paths={k: str(v) for k, v in sources.items()},
                  adapter_sha256=digest(Path(__file__)),
                  toolkit_source_sha256={str(p.relative_to(ROOT)): digest(p) for p in
                      (ROOT/'tests/adpcm_oracle_probe.cpp', ROOT/'runtime/src/adpcm.cpp', ROOT/'runtime/include/pce/adpcm.hpp')},
                  authored_inputs=inputs, cases=[])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    process = None; started = time.monotonic()
    try:
        config.write_text('[General]\nVersion=999\n[Debug]\nDebug=true\n[Emulator]\nStartPaused=true\nPauseWhenInactive=false\nBackupRAMDirOption=2\nBackupRAMPath='+str(savedir)+'\nSaveFilesDirOption=2\nSaveFilesPath='+str(savedir)+'\nSaveStatesDirOption=2\nSaveStatesPath='+str(savedir)+'\n[Rewind]\nEnabled=false\n')
        with (out/'process.log').open('wb') as log:
            process = subprocess.Popen([str(exe), '--headless', '--portable', '--mcp-http', '--mcp-http-port', str(port)],
                cwd=exe.parent, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            report['pid'] = process.pid; client = Mcp(port)
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('Gear exited during startup')
                try:
                    info = client.rpc('initialize', dict(protocolVersion='2025-11-25', capabilities={}, clientInfo=dict(name='adpcm-reference', version='1')))
                    break
                except OSError: time.sleep(.05)
            else: raise RuntimeError('Gear startup timeout')
            client.headers['MCP-Protocol-Version'] = info['protocolVersion']; client.rpc('notifications/initialized')
            client.call('load_bios', file_path=str(bios), type='syscard')

            def guard():
                if time.monotonic()-started > 300 or (out/'process.log').stat().st_size > 2*1024*1024:
                    raise RuntimeError('Finite ADPCM verification exceeded deadline/log bound')

            def code(data):
                guard()
                if not 0 < len(data) < 4096: raise ValueError('Helper exceeds authored scratch RAM')
                client.call('write_memory', area=areas['SYSTEM RAM'], offset='1000', bytes=data.hex(' '))
                client.call('write_huc6280_register', name='PC', value='3000')
                endpoint = f'{0x3000+len(data):04X}'; client.call('debug_run_to_cursor', address=endpoint)
                for _ in range(100):
                    status = client.call('debug_get_status')
                    if status['paused'] and status['pc'] == endpoint: return
                    time.sleep(.01)
                raise RuntimeError('Authored finite helper failed to stop')

            def write(port, value):
                code(bytes((0xa9, value, 0x8d, port&255, port>>8)))

            def advance(ticks):
                while ticks:
                    chunk = min(ticks, 600000); chunk -= chunk%6
                    if not chunk: raise ValueError('Delay must be a positive multiple of six master ticks')
                    code(delay_program(chunk)); ticks -= chunk

            def snapshot(name):
                guard(); path = out/(name+'.state')
                response = client.call('save_state_file', file_path=str(path))
                if response.get('success') is not True: raise RuntimeError('Gear state serialization failed')
                public = client.call('get_adpcm_status')
                value = parse_state(path.read_bytes(), ram, public)
                cd = client.call('get_cdrom_status')
                if (value['end'] != cd['irq_adpcm_end'] or value['half'] != cd['irq_adpcm_half']):
                    raise ValueError('Serialized/public CD ADPCM interrupt fields disagree')
                return value, dict(file=path.name, sha256=digest(path), public=public,
                                   public_cd_irqs={k: cd[k] for k in ('irq_adpcm_end', 'irq_adpcm_half')}, state=value)

            specifications = [(f'rate-{rate:02}', rate, 256, 0x60) for rate in range(16)]
            specifications += [('finite-end', 15, 1, 0x60), ('stop-restart', 15, 256, 0x20)]
            for name, rate, length, control in specifications:
                client.call('load_media', file_path=str(image)); client.call('debug_pause')
                client.call('write_huc6280_register', name='PC', value='E000')
                for _ in range(6): client.call('debug_step_into')
                areas = {v['name']: v['id'] for v in client.call('list_memory_areas')['areas']}
                client.call('write_memory', area=areas['ADPCM'], offset='0000', bytes=ram.hex(' '))
                for port, value in ((0x180d, 128), (0x180d, 0), (0x1808, 255), (0x1809, 255),
                                    (0x180d, 12), (0x180d, 0), (0x1808, length&255), (0x1809, length>>8),
                                    (0x180d, 16), (0x180d, 0), (0x180e, rate), (0x180d, control)):
                    write(port, value)
                anchor, raw = snapshot(name+'-anchor')
                if (anchor['predictor'], anchor['index'], anchor['read_address'], anchor['length'], anchor['pending']) != (2048, 0, 65535, length, True):
                    raise RuntimeError('Authored pending-play setup changed')
                case = dict(id=name, anchor=raw, checkpoints=[]); report['cases'].append(case)
                plan = initial_line(anchor); previous = anchor
                for i, samples in enumerate((1, 1, 7, 32, 48, 100)):
                    delay = math.ceil(anchor['period']*samples/65536/6)*6
                    if name == 'finite-end' and i < 2 and delay_program(delay) != bytes((0xea,))*(delay//6):
                        raise RuntimeError('Finite-stop verification requires plain six-tick NOP callbacks')
                    advance(delay); actual, raw = snapshot(name+f'-{i}')
                    delta = actual['master_ticks']-previous['master_ticks']; previous = actual
                    plan += f's {delta}\n'; planpath = out/(name+'.plan'); planpath.write_text(plan)
                    expected = json.loads(subprocess.run([str(probe), str(out/'authored.ram'), str(planpath)],
                        check=True, capture_output=True, text=True, timeout=10).stdout)[-1]
                    try:
                        difference = compare_checkpoint(actual, expected, anchor if name == 'finite-end' and i >= 1 else None)
                    except ValueError:
                        case['failure'] = dict(actual=actual, expected=expected)
                        raise RuntimeError(f'Independent raw ADPCM state/clock mismatch: {name} checkpoint {i}')
                    if expected['pcm'] != (actual['predictor']-2048)*16:
                        raise RuntimeError('Held raw digital PCM scale mismatch')
                    case['checkpoints'].append(dict(**raw, runtime=expected, elapsed_ticks=delta,
                                                   reference_minus_runtime_stopped_phase=difference))
                    if name == 'finite-end':
                        if i == 0 and (not actual['nibble'] or actual['length'] != 1): raise RuntimeError('High nibble ordering failed')
                        if i >= 1 and (actual['playing'] or actual['length'] or not actual['end']): raise RuntimeError('Finite end/hold failed')
                if name.startswith('rate-') and (case['checkpoints'][3]['state']['index'] != 48 or case['checkpoints'][-1]['state']['index'] != 0):
                    raise RuntimeError('Authored sequence did not reach both decoder index clamps')
                if name == 'stop-restart':
                    # Exercise stop without resetting the held decoder, then
                    # restart at the extant nibble/address/clock phase.
                    write(0x180d, 0); stopped, stoppedraw = snapshot(name+'-stopped')
                    advance(6000); held, heldraw = snapshot(name+'-held')
                    if any(stopped[k] != held[k] for k in FIELDS): raise RuntimeError('Stop failed to hold decoder/phase')
                    write(0x180d, 32); restart, restartraw = snapshot(name+'-restart')
                    if not restart['pending'] or restart['predictor'] != held['predictor'] or restart['index'] != held['index']:
                        raise RuntimeError('Restart prematurely reset held predictor')
                    advance(1200); after, afterraw = snapshot(name+'-after-restart')
                    restartplan = out/'restart.plan'; restartplan.write_text(initial_line(restart)+f"s {after['master_ticks']-restart['master_ticks']}\n")
                    expected = json.loads(subprocess.run([str(probe), str(out/'authored.ram'), str(restartplan)], capture_output=True, text=True, check=True, timeout=10).stdout)[0]
                    if any(after[k] != expected[k] for k in FIELDS): raise RuntimeError('Restart decode mismatch')
                    write(0x180d, 128); reset, resetraw = snapshot(name+'-reset')
                    if any(reset[k] != v for k, v in dict(predictor=2048, index=0, nibble=False, read_address=0, length=0, pending=False, playing=False, end=False, half=False).items()):
                        raise RuntimeError('Soft reset raw decoder mismatch')
                    case['controls'] = dict(stopped=stoppedraw, held=heldraw, restart=restartraw,
                                            after_restart=afterraw, runtime_after_restart=expected, reset=resetraw)
                    # Replay every control transition continuously. Gear's
                    # authored LDA #value; STA absolute helper places the port
                    # write after the six-tick LDA, followed by fifteen ticks
                    # for the STA. These boundaries are from the pinned CPU
                    # timing/store implementation, not fitted to predictor
                    # values. All measured helper deltas must also be 21 ticks.
                    for before, after_control in ((previous, stopped), (held, restart), (after, reset)):
                        if after_control['master_ticks']-before['master_ticks'] != 21:
                            raise RuntimeError('Authored control helper timing changed')
                    control_plan = (initial_line(previous)+'s 6\nw 13 0\ns 15\n'+
                                    f"s {held['master_ticks']-stopped['master_ticks']}\n"+
                                    's 6\nw 13 32\ns 15\n'+
                                    f"s {after['master_ticks']-restart['master_ticks']}\n"+
                                    's 6\nw 13 128\ns 15\n')
                    controlpath = out/'continuous-controls.plan'; controlpath.write_text(control_plan)
                    controls = json.loads(subprocess.run([str(probe), str(out/'authored.ram'), str(controlpath)],
                        capture_output=True, text=True, check=True, timeout=10).stdout)
                    pairs = (('stopped', stopped, 1), ('held', held, 2), ('restart', restart, 4),
                             ('after_restart', after, 5), ('reset', reset, 7))
                    for label, actual, position in pairs:
                        compare_checkpoint(actual, controls[position])
                        case['controls']['runtime_continuous_'+label] = controls[position]
            report.update(result='pass', oracle=info['serverInfo'], checkpoints=sum(len(c['checkpoints']) for c in report['cases']),
                          scope='Unmodified pinned Gear binary: raw 12-bit ADPCM predictor/index, nibble/address/length/IRQs and 16.16 sample phase at observed elapsed master ticks; all 16 rates; finite end, stop/restart, soft reset',
                          stopped_phase_limit='Gear retains its final whole six-tick NOP callback remainder; runtime stops at the exact integer master tick. Both finite-vector residues are independently checked; stopped phases are not claimed identical.',
                          control_clock_scope='Continuous stop/hold/restart/reset replay uses authored LDA immediate six-tick then STA absolute fifteen-tick helpers; exact state and phase checked. Other bus/instruction edge alignments are unqualified.',
                          not_checked=['Other instruction/bus-edge control alignments', 'Gear filtered/scaled output', 'analog DAC/filter', 'mixed or resampled PCM', 'device playback', 'retail audio', 'hardware'])
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        config.unlink(missing_ok=True)
        report.update(config_restored=not config.exists(), child_stopped=process is None or process.poll() is not None,
                      elapsed_seconds=time.monotonic()-started, inputs_unchanged=all(digest(out/name)==sha for name, sha in inputs.items()),
                      executable_unchanged=digest(exe)==EXE_SHA, probe_unchanged=digest(probe)==report['probe_sha256'],
                      adapter_unchanged=digest(Path(__file__))==report['adapter_sha256'],
                      reference_source_unchanged=all(digest(path)==SOURCE_SHA[name] for name, path in sources.items()),
                      toolkit_source_unchanged=all(digest(ROOT/name)==sha for name, sha in report['toolkit_source_sha256'].items()))
        if report['result'] == 'pass' and not all(report[k] for k in
                ('config_restored', 'child_stopped', 'inputs_unchanged', 'executable_unchanged', 'probe_unchanged',
                 'adapter_unchanged', 'reference_source_unchanged', 'toolkit_source_unchanged')):
            report['result'] = 'failed-preservation'
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    if report['result'] != 'pass': raise RuntimeError('Independent reference preservation/qualification failed')
    print(json.dumps({k:v for k,v in report.items() if k != 'cases'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True); parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--gear-source', type=Path, help='Pinned Geargrafx 1.8.4 src directory (default: local flattened research cache)')
    try: run(parser.parse_args())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr); raise SystemExit(1)
