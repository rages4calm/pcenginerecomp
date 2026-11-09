"""Bounded, authored capture-to-native workflow; never accepts retail firmware."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROGRAM = bytes.fromhex('A9 FF 53 01 A9 F8 53 02 A9 20 53 80 D4 A2 FF 9A '
    '73 00 E1 00 22 06 00 20 00 22 AD 30 20 8D 31 20 A9 2A 8D 01 22 '
    '20 00 22 AD 30 20 8D 32 20 A9 40 53 80 A2 00 E8 80 FD')
TEMPLATE = bytes.fromhex('A9 11 8D 30 20 60')
LENGTHS = (2, 2, 2, 2, 2, 2, 1, 2, 1, 7, 3, 3, 3, 2, 3, 3, 3, 3, 2, 2, 2, 1, 2)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def card_bytes():
    card = bytearray(262144)
    card[:len(PROGRAM)] = PROGRAM
    card[0x100:0x106] = TEMPLATE
    card[0x1FFE:0x2000] = bytes.fromhex('00 E0')
    return bytes(card)


def expected_observations(steps=200):
    """Explicit authored boundaries/hits; this is not an instruction executor."""
    if steps not in (200, 202):
        raise ValueError('Choose the authored 200 or 202 instruction window')
    mpr, offset, result = [0]*8, 0, []
    def row(pc, data, hits):
        return dict(pc=pc, mpr=list(mpr), physical=[(mpr[(pc+i) >> 13] << 13)
                    | ((pc+i) & 8191) for i in range(len(data))], data=list(data),
                    native_hits=0, interpreted_hits=hits)
    for index, length in enumerate(LENGTHS):
        hits = 1 if index < 21 else ((steps-27+1)//2 if index == 21 else (steps-27)//2)
        result.append(row(0xE000+offset, PROGRAM[offset:offset+length], hits))
        if index == 1: mpr[0] = 255
        if index == 3: mpr[1] = 248
        if index == 5: mpr[7] = 32
        if index == 19: mpr[7] = 64
        offset += length
    mpr[7] = 32
    result.extend((row(0x2200, bytes.fromhex('A9 11'), 1),
                   row(0x2200, bytes.fromhex('A9 2A'), 1),
                   row(0x2202, bytes.fromhex('8D 30 20'), 2),
                   row(0x2205, bytes.fromhex('60'), 2)))
    return sorted(result, key=lambda item: (item['mpr'], item['pc'], item['data']))


def expected_state(steps=200, native=False):
    if steps not in (200, 202):
        raise ValueError('Choose the authored 200 or 202 instruction window')
    # Prefix: 27 opcodes/159 cycles. Each remaining INX/BRA pair costs 6 cycles.
    return dict(pc=0xE035, a=64, x=87+(steps-200)//2, y=0, sp=255, p=4,
        mpr=[255, 248, 0, 0, 0, 0, 0, 64], cycles=677+(steps-200)*3,
        ticks=2238+(steps-200)*9, native_steps=steps if native else 0,
        interpreter_steps=0 if native else steps)


def expected_ram():
    ram = bytearray(8192)
    ram[0x30:0x33] = bytes.fromhex('2A 11 2A')
    ram[0x1FD:0x200] = bytes.fromhex('FF 27 E0')
    ram[0x200:0x206] = bytes.fromhex('A9 2A 8D 30 20 60')
    return bytes(ram)


def check_state(state, steps=200, native=False):
    expected = expected_state(steps, native)
    if any(type(state.get(k)) is not type(v) or state[k] != v for k, v in expected.items()):
        raise ValueError('Actual endpoint differs from literal authored CPU/tick expectation')
    if native and state.get('guard_misses') != 0:
        raise ValueError('Native qualification incurred source guard misses')


def _write(path, data):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(data, indent=2)+'\n')


def capture(output, runner):
    """Retain two genuine, finite interpreter captures and exact execution logs."""
    from pcerecomp.capture import load_capture
    from pcerecomp.project import source_identity
    output, runner = Path(output).resolve(), Path(runner).resolve()
    if output.exists() or output.is_symlink() or not runner.is_file():
        raise ValueError('Choose a new output directory and an existing headless runner')
    identity, runner_hash = source_identity(ROOT), sha256(runner)
    output.mkdir(parents=True)
    card = output/'authored-card.pce'
    card.write_bytes(card_bytes())
    records = []
    for steps in (200, 202):
        raw = output/f'capture-{steps}.json'
        argv = [str(runner), '--system-card-reset', 'standard', str(card), str(steps),
                '100000', 'hybrid', '--video-output', 'continuous', '--audio-output', 'off',
                '--code-capture', str(raw), '--capture-limit', '128', '--wall-seconds', '5']
        done = subprocess.run(argv, cwd=output, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=15)
        (output/f'capture-{steps}.stdout').write_text(done.stdout, encoding='utf-8')
        (output/f'capture-{steps}.stderr').write_text(done.stderr, encoding='utf-8')
        record = dict(steps=steps, argv=argv, exit_code=done.returncode)
        records.append(record)
        _write(output/f'capture-{steps}-process.json', record)
        if done.returncode:
            raise ValueError('Authored capture failed; process evidence retained')
        state = json.loads(done.stdout)
        check_state(state, steps)
        report, digest = load_capture(raw)
        if (not report['complete'] or report['dropped_instructions'] or report['unreadable_instructions']
                or report['retired_instructions'] != steps
                or report['observations'] != expected_observations(steps)):
            raise ValueError('Actual capture differs from explicit authored source identities/hits')
        record.update(capture_sha256=digest, state=state,
            stdout_sha256=sha256(output/f'capture-{steps}.stdout'),
            stderr_sha256=sha256(output/f'capture-{steps}.stderr'))
    if (sha256(runner) != runner_hash or card.read_bytes() != card_bytes()
            or source_identity(ROOT) != identity):
        raise ValueError('Runner, toolkit source or authored card changed during execution')
    receipt = dict(schema=1, kind='authored-native-workflow-capture', runner_sha256=runner_hash,
        capture_tool_source=identity, helper_sha256=sha256(Path(__file__)),
        card_sha256=sha256(card), windows=records, execution_evidence=True)
    _write(output/'capture-receipt.json', receipt)
    return receipt


def prepare(output):
    """Originals → retained inline baseline → additive history → supported prepare."""
    from pcerecomp.capture import load_capture
    from pcerecomp.observations import compose_observation_profile
    from pcerecomp.history import compose_history
    from pcerecomp.prepare import prepare_project
    output = Path(output).resolve()
    receipt = json.loads((output/'capture-receipt.json').read_text(encoding='utf-8'))
    if [record['steps'] for record in receipt['windows']] != [200, 202]:
        raise ValueError('Expected exactly the original 200/202 instruction windows')
    if receipt['card_sha256'] != sha256(output/'authored-card.pce') or (output/'authored-card.pce').read_bytes() != card_bytes():
        raise ValueError('Authored card binding changed')
    for record in receipt['windows']:
        steps = record['steps']
        raw, digest = load_capture(output/f'capture-{steps}.json')
        if (digest != record['capture_sha256'] or raw['observations'] != expected_observations(steps)
                or not raw['complete'] or raw['retired_instructions'] != steps
                or record['exit_code'] != 0):
            raise ValueError('Original capture changed')
        if (sha256(output/f'capture-{steps}.stdout') != record['stdout_sha256']
                or sha256(output/f'capture-{steps}.stderr') != record['stderr_sha256']
                or json.loads((output/f'capture-{steps}.stdout').read_text(encoding='utf-8')) != record['state']):
            raise ValueError('Original process output changed')
        check_state(record['state'], steps)
    baseline = compose_observation_profile([output/'capture-200.json'], capacity=128)
    _write(output/'baseline-profile.json', baseline)
    history = compose_history([output/'capture-202.json'], output/'history',
                              baseline_profile=output/'baseline-profile.json', capacity=128)
    if len(history.instructions) != 27:
        raise ValueError('Authored history identity union differs')
    if (history.accounting['historical_totals']['interpreted_hits'] != 402
            or history.accounting['selected_historical_totals']['interpreted_hits'] != 200):
        raise ValueError('Additive history lost original or selected tier accounting')
    spec = '''schema = 1
format = "pce-consumer-prepare-1"
name = "authored-native-workflow"
[module]
kind = "history"
path = "history/history.json"
partition_layout = "stable"
[boot]
mode = "system-card-reset"
profile = "standard"
[bios]
path = "authored-card.pce"
[runtime]
tier = "native"
video = "continuous"
audio = "off"
cd_unknown_status = "fault"
joypad = 2
region = "usa"
multitap = "off"
[limits]
steps = 200
ticks = 100000
wall_seconds = 5
'''
    with (output/'prepare.toml').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(spec)
    result = prepare_project(output/'prepare.toml', output/'consumer')
    history.revalidate()
    return result


def qualify(output, *, generator=None, cmake_args=()):
    """Official project build and native-only run; requires the chosen SDK frozen."""
    from pcerecomp.project import build, run
    from pcerecomp.history import load_history
    output = Path(output).resolve()
    history = load_history(output/'history/history.json')
    originals = {str(path): sha256(path) for path in (output/'capture-200.json', output/'capture-202.json',
                                                   output/'authored-card.pce')}
    descriptor = output/'consumer/project.toml'
    built = build(descriptor, output/'consumer-build', generator=generator, cmake_args=cmake_args)
    ran = run(descriptor, output/'consumer-build', output/'native-run.json')
    check_state(ran['result'], native=True)
    if not ran['qualified']:
        raise ValueError('Official native-only run was not qualified')
    history.revalidate()
    if any(sha256(Path(path)) != digest for path, digest in originals.items()):
        raise ValueError('Original capture or input changed during native qualification')
    return dict(build=built, run=ran)


def probe(output):
    """Compile a small checker against the actual official-build runtime archive."""
    from pcerecomp.project import verify
    output = Path(output).resolve()
    checked = verify(output/'consumer/project.toml')
    built = json.loads((output/'consumer-build/build-receipt.json').read_text(encoding='utf-8'))
    if sha256(Path(built['binary'])) != built['binary_sha256']:
        raise ValueError('Official build binary changed')
    build_root = output/'consumer-build/build'
    archives = [p for p in build_root.rglob('*') if p.name in ('libpce-runtime.a', 'pce-runtime.lib')]
    if len(archives) != 1:
        raise ValueError('Expected one runtime archive from the official consumer build')
    archive = archives[0]
    cache = {}
    for line in (build_root/'CMakeCache.txt').read_text(encoding='utf-8').splitlines():
        if '=' in line and ':' in line.split('=', 1)[0]:
            key, value = line.split('=', 1)
            cache[key.split(':', 1)[0]] = value
    root = output/'endpoint-probe'
    if root.exists():
        raise ValueError('Probe output already exists')
    root.mkdir()
    bindings = {str(p): sha256(p) for p in (archive, Path(__file__).with_name('probe.cpp'),
                                         output/'authored-card.pce', Path(built['binary']))}
    module = output/'consumer/module'
    text = f'''cmake_minimum_required(VERSION 3.20)
project(AuthoredNativeWorkflowProbe LANGUAGES CXX)
add_library(pce-runtime STATIC IMPORTED GLOBAL)
set_target_properties(pce-runtime PROPERTIES IMPORTED_LOCATION "{archive.as_posix()}"
  INTERFACE_INCLUDE_DIRECTORIES "{(ROOT/'runtime/include').as_posix()}"
  INTERFACE_COMPILE_FEATURES cxx_std_20)
include("{(ROOT/'cmake/PCEConsumer.cmake').as_posix()}")
pce_add_native_module(native_objects MODULE "{(module/'module.cpp').as_posix()}"
  MANIFEST "{(module/'module.json').as_posix()}")
add_executable(native-workflow-probe "{Path(__file__).with_name('probe.cpp').as_posix()}")
target_link_libraries(native-workflow-probe PRIVATE pce-runtime ${{native_objects}} ${{CMAKE_DL_LIBS}})
if(WIN32)
  target_link_libraries(native-workflow-probe PRIVATE ws2_32)
endif()
'''
    (root/'CMakeLists.txt').write_text(text, encoding='utf-8')
    cmake = shutil.which('cmake')
    if not cmake:
        raise ValueError('CMake must be on PATH')
    commands = [[cmake, '-S', str(root), '-B', str(root/'build'), '-G', cache['CMAKE_GENERATOR'],
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER='+cache['CMAKE_CXX_COMPILER'],
                 '-DCMAKE_MAKE_PROGRAM='+cache['CMAKE_MAKE_PROGRAM']],
                [cmake, '--build', str(root/'build'), '--config', 'Release', '--parallel', '2']]
    for index, argv in enumerate(commands):
        done = subprocess.run(argv, capture_output=True, text=True, timeout=90)
        (root/f'build-{index}.stdout').write_text(done.stdout, encoding='utf-8')
        (root/f'build-{index}.stderr').write_text(done.stderr, encoding='utf-8')
        if done.returncode:
            raise ValueError('Endpoint probe build failed; logs retained')
    binary = root/'build'/('native-workflow-probe.exe' if os.name == 'nt' else 'native-workflow-probe')
    if not binary.is_file():
        binary = binary.parent/'Release'/binary.name
    results = {}
    for mode in ('normal', 'guard'):
        done = subprocess.run([str(binary), str(output/'authored-card.pce'), mode],
                              capture_output=True, text=True, timeout=10)
        (root/f'{mode}.stdout').write_text(done.stdout, encoding='utf-8')
        (root/f'{mode}.stderr').write_text(done.stderr, encoding='utf-8')
        if done.returncode:
            raise ValueError('Actual endpoint/source-guard probe failed; logs retained')
        results[mode] = json.loads(done.stdout)
    if any(sha256(Path(path)) != digest for path, digest in bindings.items()):
        raise ValueError('Probe inputs changed during qualification')
    # Re-admit the full descriptor/history graph after execution as well.
    if verify(output/'consumer/project.toml')['tool_identity'] != checked['tool_identity']:
        raise ValueError('Toolkit identity changed during endpoint qualification')
    receipt = dict(schema=1, kind='authored-native-workflow-probe', bindings=bindings,
        binary_sha256=sha256(binary), results=results, execution_evidence=True,
        scope='authored 200-instruction native endpoint and host-assisted uncaptured-source negative; not title compatibility')
    _write(root/'probe-receipt.json', receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    train = commands.add_parser('capture')
    train.add_argument('output', type=Path)
    train.add_argument('--runner', type=Path, required=True)
    for name in ('prepare', 'qualify', 'probe'):
        sub = commands.add_parser(name)
        sub.add_argument('output', type=Path)
        if name == 'qualify':
            sub.add_argument('--generator')
            sub.add_argument('--cmake-arg', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == 'capture': result = capture(args.output, args.runner)
        elif args.command == 'prepare': result = prepare(args.output)
        elif args.command == 'probe': result = probe(args.output)
        else: result = qualify(args.output, generator=args.generator, cmake_args=args.cmake_arg)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
        parser.exit(2, f'authored native workflow: {error}\n')


if __name__ == '__main__':
    main()
