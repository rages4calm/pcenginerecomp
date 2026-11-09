"""Authored guest-driven capture beyond the legacy identity limit, then native execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
STEPS = 73701
CAPACITY = 131072
LEGACY_CAPACITY = 65536
PHYSICAL_LOAD = 0x1F0000
PC = 0x4000
MPR = [248] * 8


def payload_bytes():
    return b'\xD4' + b'\xEA' * 8184 + bytes.fromhex('E8 8A 53 80 4C 00 40')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def expected_observations(*, legacy=False, native=False):
    """Explicit authored boundaries and mappings, not an instruction executor.

    TAM changes MPR7 before the following JMP is fetched. The initial context
    lacks JMP and the final ninth context contains only that last JMP.
    """
    source = payload_bytes()
    result = []
    for round_index in range(9):
        mapping = [248] * 7 + [248 if round_index == 0 else round_index]
        boundaries = [(index, 1) for index in range(8187)] + [(8187, 2), (8189, 3)]
        for offset, size in boundaries:
            if legacy and len(result) == LEGACY_CAPACITY:
                break
            fetch_mapping = mapping if offset != 8189 else [248] * 7 + [round_index + 1]
            result.append(dict(pc=PC + offset, mpr=fetch_mapping,
                physical=[PHYSICAL_LOAD + offset + index for index in range(size)],
                data=list(source[offset:offset + size]), native_hits=1 if native else 0,
                interpreted_hits=0 if native else 1))
        if legacy and len(result) == LEGACY_CAPACITY:
            break
    return sorted(result, key=lambda item: (item['mpr'], item['pc'], item['data']))


def expected_state(*, native=False):
    # Each round: 8189 instructions, 16384 cycles. The explicit payload sandbox
    # starts at divider 3, so the first CSH is already fast: 147456*3 ticks.
    return dict(pc=16384, a=9, x=9, y=0, sp=255, p=4,
                mpr=[248] * 7 + [9], cycles=147456, ticks=442368,
                native_steps=73701 if native else 0,
                interpreter_steps=0 if native else 73701)


def check_state(state, *, native=False):
    if type(state) is not dict:
        raise ValueError('Missing actual CPU endpoint')
    for key, value in expected_state(native=native).items():
        if type(state.get(key)) is not type(value) or state[key] != value:
            raise ValueError('Endpoint differs from literal authored CPU/tick expectation: ' + key)
    if native and state.get('guard_misses') != 0:
        raise ValueError('Native run incurred source guard misses')


def check_capture(value, *, legacy=False, native=False):
    expected_schema = 1 if legacy else 2
    expected_capacity = LEGACY_CAPACITY if legacy else CAPACITY
    if (type(value) is not dict or value.get('schema') != expected_schema
            or value.get('capacity') != expected_capacity
            or value.get('complete') is not (not legacy)
            or value.get('dropped_instructions') != (8165 if legacy else 0)
            or value.get('unreadable_instructions') != 0
            or value.get('retired_instructions') != STEPS
            or value.get('observations') != expected_observations(legacy=legacy, native=native)):
        raise ValueError('Capture differs from authored complete identities, tiers or loss counters')


def _write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def _process(output, name, argv, timeout, *, cwd=None):
    destinations = [output / (name + suffix) for suffix in ('.stdout', '.stderr', '-process.json')]
    if any(path.exists() or path.is_symlink() for path in destinations):
        raise ValueError('Process evidence destinations must be new: ' + name)
    timed_out = False
    try:
        done = subprocess.run(argv, cwd=output if cwd is None else cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        done = subprocess.CompletedProcess(argv, -1, error.stdout or b'', error.stderr or b'')
    for suffix, value in (('stdout', done.stdout), ('stderr', done.stderr)):
        with (output / (name + '.' + suffix)).open('xb') as stream:
            stream.write(value)
    record = dict(argv=argv, exit_code=done.returncode, timed_out=timed_out,
                  stdout_sha256=sha256(output / (name + '.stdout')),
                  stderr_sha256=sha256(output / (name + '.stderr')))
    _write(output / (name + '-process.json'), record)
    if done.returncode:
        raise ValueError('Process failed; retained stdout/stderr and process receipt: ' + name)
    return done.stdout, record


def capture(output, runner):
    from pcerecomp.capture import load_capture
    from pcerecomp.project import source_identity
    output, runner = Path(output).resolve(), Path(runner).resolve()
    if output.exists() or output.is_symlink() or not runner.is_file():
        raise ValueError('Choose a new output directory and existing headless runner')
    identity, runner_hash = source_identity(ROOT), sha256(runner)
    output.mkdir(parents=True)
    payload = output / 'authored-work-ram.bin'
    payload.write_bytes(payload_bytes())
    records = []
    for legacy in (True, False):
        name = 'legacy' if legacy else 'extended'
        path = output / (name + '-capture.jsonl' if not legacy else name + '-capture.json')
        argv = [str(runner), str(payload), str(PHYSICAL_LOAD), str(PC), ','.join(map(str, MPR)),
                str(STEPS), '1000000', 'hybrid', '--video-output', 'snapshot',
                '--audio-output', 'off', '--code-capture', str(path),
                '--capture-limit', str(LEGACY_CAPACITY if legacy else CAPACITY),
                '--wall-seconds', '30']
        if not legacy:
            argv += ['--capture-profile', 'extended']
        stdout, process = _process(output, name, argv, 45)
        state = json.loads(stdout)
        check_state(state)
        report, digest = load_capture(path)
        check_capture(report, legacy=legacy)
        records.append(dict(kind=name, capture_sha256=digest, state=state, process=process))
    if (source_identity(ROOT) != identity or sha256(runner) != runner_hash
            or payload.read_bytes() != payload_bytes()):
        raise ValueError('Toolkit, runner or authored payload changed during capture')
    receipt = dict(schema=1, kind='authored-extended-capture', producer_tool=identity,
        runner_sha256=runner_hash, helper_sha256=sha256(__file__), payload_sha256=sha256(payload),
        windows=records, execution_evidence=True,
        scope='Guest-driven interpreter captures; no native compilation or hardware parity claimed')
    _write(output / 'capture-receipt.json', receipt)
    return receipt


def _admit(output):
    from pcerecomp.capture import load_capture
    from pcerecomp.project import source_identity
    receipt = json.loads((output / 'capture-receipt.json').read_text(encoding='utf-8'))
    if (receipt['producer_tool'] != source_identity(ROOT)
            or receipt['helper_sha256'] != sha256(__file__)
            or receipt['payload_sha256'] != sha256(output / 'authored-work-ram.bin')
            or (output / 'authored-work-ram.bin').read_bytes() != payload_bytes()
            or [item['kind'] for item in receipt['windows']] != ['legacy', 'extended']):
        raise ValueError('Authored capture producer or payload binding changed')
    for item in receipt['windows']:
        legacy = item['kind'] == 'legacy'
        source = output / ('legacy-capture.json' if legacy else 'extended-capture.jsonl')
        value, digest = load_capture(source)
        check_capture(value, legacy=legacy)
        check_state(item['state'])
        if item['capture_sha256'] != digest or item['process']['exit_code'] != 0:
            raise ValueError('Original capture binding changed')
        for suffix in ('stdout', 'stderr'):
            if sha256(output / (item['kind'] + '.' + suffix)) != item['process'][suffix + '_sha256']:
                raise ValueError('Original process output changed')
        if json.loads((output / (item['kind'] + '.stdout')).read_text(encoding='utf-8')) != item['state']:
            raise ValueError('Original process endpoint changed')
    return receipt


def prepare(output):
    from pcerecomp.history import compose_history
    from pcerecomp.prepare import prepare_project
    output = Path(output).resolve()
    _admit(output)
    history = compose_history([output / 'extended-capture.jsonl'], output / 'history',
                              history_version=2, capacity=CAPACITY)
    if len(history.instructions) != STEPS or history.index['historical_totals']['interpreted_hits'] != STEPS:
        raise ValueError('History lost authored identities or original tier accounting')
    recipe = '''schema = 1
format = "pce-consumer-prepare-1"
name = "authored-extended-capture"
[module]
kind = "history"
path = "history/history.json"
history_version = 2
capacity = 131072
partition_layout = "stable"
[payload]
path = "authored-work-ram.bin"
physical_load = 2031616
pc = 16384
mpr = [248, 248, 248, 248, 248, 248, 248, 248]
[runtime]
tier = "native"
video = "snapshot"
audio = "off"
cd_unknown_status = "fault"
joypad = 2
region = "usa"
multitap = "off"
[limits]
steps = 73701
ticks = 1000000
wall_seconds = 30
'''
    with (output / 'prepare.toml').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(recipe)
    receipt = prepare_project(output / 'prepare.toml', output / 'consumer')
    if receipt['native_instructions_emitted'] != STEPS:
        raise ValueError('Preparation did not emit every observed identity')
    history.revalidate()
    return receipt


def qualify(output, *, generator=None, cmake_args=()):
    """Use official build/run interfaces; never substitute a private native executor."""
    from pcerecomp.capture import load_capture
    from pcerecomp.history import load_history
    from pcerecomp.project import build
    output = Path(output).resolve()
    originals = _admit(output)
    history = load_history(output / 'history')
    descriptor = output / 'consumer/project.toml'
    built = build(descriptor, output / 'consumer-build', generator=generator, cmake_args=cmake_args)
    argv = [sys.executable, '-m', 'pcerecomp.project', 'run', str(descriptor),
            '--build-dir', str(output / 'consumer-build'), '--receipt', str(output / 'native-run.json'),
            '--code-capture', str(output / 'native-capture.jsonl'),
            '--capture-profile', 'extended', '--capture-limit', str(CAPACITY)]
    # Invoke from the toolkit so the official module is importable without installation.
    # The outer process output is retained; project.run owns the execution receipt.
    _process(output, 'native-official', argv, 60, cwd=ROOT)
    ran = json.loads((output / 'native-run.json').read_text(encoding='utf-8'))
    check_state(ran['result'], native=True)
    if not ran['qualified']:
        raise ValueError('Official run did not qualify')
    actual, digest = load_capture(output / 'native-capture.jsonl')
    check_capture(actual, native=True)
    history.revalidate()
    if _admit(output) != originals:
        raise ValueError('Original evidence changed during native qualification')
    receipt = dict(schema=1, kind='authored-extended-native-qualification', execution_evidence=True,
        build_receipt_sha256=sha256(output / 'consumer-build/build-receipt.json'),
        run_receipt_sha256=sha256(output / 'native-run.json'), native_capture_sha256=digest,
        native_steps=73701, interpreter_steps=0, guard_misses=0,
        expected_payload_sha256=hashlib.sha256(payload_bytes()).hexdigest(),
        ram_endpoint_measured=False,
        scope='Authored native identities, registers and clocks; payload digest is input identity, not a final RAM measurement')
    _write(output / 'qualification-receipt.json', receipt)
    return dict(build=built, run=ran, qualification=receipt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    train = commands.add_parser('capture')
    train.add_argument('output', type=Path)
    train.add_argument('--runner', type=Path, required=True)
    for name in ('prepare', 'qualify'):
        sub = commands.add_parser(name)
        sub.add_argument('output', type=Path)
        if name == 'qualify':
            sub.add_argument('--generator')
            sub.add_argument('--cmake-arg', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == 'capture':
            result = capture(args.output, args.runner)
        elif args.command == 'prepare':
            result = prepare(args.output)
        else:
            result = qualify(args.output, generator=args.generator, cmake_args=args.cmake_arg)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
        parser.exit(2, f'authored extended workflow: {error}\n')


if __name__ == '__main__':
    main()
