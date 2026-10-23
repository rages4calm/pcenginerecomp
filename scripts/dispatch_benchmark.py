"""Measure explicit build commands and instrumented simulation independently.

Scenario JSON contains schema=1, workload, cwd, pinned inputs (path/sha256),
implementation files (path), and controls (compiler, compiler_version, flags,
configuration, architecture). Optional build has command, scope (compile_only
or total_build), cache_state, samples and optional prepare command. Required
run has command, samples and warmups. Commands are argv arrays, never shells.
The simulation command must print exactly one JSON object with semantic and
simulation_seconds fields. Semantic JSON must include all workload counters
and final checksums; no fields are projected away by this measurement tool.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time

MAX_OUTPUT = 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def fingerprint(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def argv(value):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v for v in value):
        raise ValueError('Commands must be nonempty argv arrays of nonempty strings')
    return value


def count(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in [{low}, {high}]')
    return value


def command(command_argv, cwd, scratch, timeout):
    """Bound retained and live command output; do not include JSON parsing time."""
    with tempfile.TemporaryFile(dir=scratch) as output:
        started = time.perf_counter()
        process = subprocess.Popen(argv(command_argv), cwd=cwd, stdout=output,
                                   stderr=subprocess.STDOUT,
                                   start_new_session=os.name != 'nt',
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        try:
            while process.poll() is None:
                if time.perf_counter()-started > timeout:
                    raise RuntimeError('Benchmark command exceeded timeout')
                if output.tell() > MAX_OUTPUT:
                    raise RuntimeError('Benchmark command exceeded 1 MiB output limit')
                time.sleep(0.01)
            elapsed = time.perf_counter()-started
            if output.tell() > MAX_OUTPUT:
                raise RuntimeError('Benchmark command exceeded 1 MiB output limit')
            output.seek(0)
            data = output.read()
            if process.returncode:
                raise RuntimeError(f'Benchmark command exited {process.returncode}: {data[-4096:].decode(errors="replace")}')
            return elapsed, data
        finally:
            if process.poll() is None:
                # Compiler/build commands can own children. End only this
                # process tree, so a refused benchmark cannot leave compilers
                # producing unbounded output after the receipt is rejected.
                if os.name == 'nt':
                    try:
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                            timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
                    except (OSError,subprocess.SubprocessError):
                        pass
                else:
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)


def summary(values):
    return dict(samples=values, median=statistics.median(values),
                minimum=min(values), maximum=max(values))


def parse_simulation(raw):
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {'semantic', 'simulation_seconds'}:
        raise ValueError('Simulation output requires exactly semantic and simulation_seconds')
    semantic = value['semantic']
    seconds = value['simulation_seconds']
    if not isinstance(semantic, dict) or not semantic:
        raise ValueError('Simulation semantic must be a nonempty JSON object')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('simulation_seconds must be positive and finite')
    # Canonicalization also rejects nested NaN/infinity.
    digest(semantic)
    return semantic, seconds


def compare(baseline, result):
    if baseline.get('schema') != 1 or baseline.get('result') != 'pass':
        raise ValueError('Baseline is not a successful benchmark receipt')
    for key in ('workload', 'inputs', 'controls', 'host', 'semantic', 'semantic_sha256'):
        if baseline.get(key) != result[key]:
            raise ValueError(f'Baseline differs in {key}; refuse a speed comparison')
    old, new = baseline['simulation']['instrumented_seconds']['median'], result['simulation']['instrumented_seconds']['median']
    values = dict(instrumented_simulation_ratio_baseline_over_candidate=old/new,
                  scope='Instrumented simulation only; excludes process startup, build and TCP pacing')
    if 'build' in baseline and 'build' in result:
        for key in ('scope', 'cache_state'):
            if baseline['build'][key] != result['build'][key]:
                raise ValueError(f'Build comparison differs in {key}')
        values['build_wall_ratio_baseline_over_candidate'] = baseline['build']['process_wall_seconds']['median']/result['build']['process_wall_seconds']['median']
    return values


def benchmark(spec, base, scratch, baseline=None):
    if spec.get('schema') != 1 or not isinstance(spec.get('workload'), str) or not spec['workload']:
        raise ValueError('Require schema=1 and a named workload')
    cwd = (base / spec.get('cwd', '.')).resolve()
    controls = spec.get('controls', {})
    for key in ('compiler', 'compiler_version', 'flags', 'configuration', 'architecture'):
        if key not in controls or not controls[key]:
            raise ValueError(f'Missing explicit benchmark control: {key}')
    inputs = spec.get('inputs', [])
    if not inputs:
        raise ValueError('At least one immutable workload input is required')
    pinned = []
    for item in inputs:
        path = (base / item['path']).resolve()
        actual = fingerprint(path)
        if actual != item['sha256']:
            raise ValueError(f'Input checksum mismatch: {path.name}')
        pinned.append((path, actual))
    implementation = []
    for item in spec.get('implementation', []):
        path = (base / item['path']).resolve()
        implementation.append((path, fingerprint(path)))
    if not implementation:
        raise ValueError('Record at least one implementation file')
    result = dict(schema=1, result='incomplete', workload=spec['workload'],
        inputs=[dict(path=item['path'], sha256=sha) for item, (_,sha) in zip(inputs,pinned)],
        implementation=[dict(path=str(path),sha256=sha) for path,sha in implementation],
        controls=controls, host=dict(system=platform.system(), release=platform.release(),
                                   machine=platform.machine(), processor=platform.processor()))
    timeout = count(spec.get('timeout_seconds', 300), 1, 3600, 'timeout_seconds')
    if 'build' in spec:
        build = spec['build']
        if build.get('scope') not in ('compile_only', 'total_build') or not build.get('cache_state'):
            raise ValueError('Build requires explicit scope and cache_state')
        samples = count(build.get('samples',1),1,20,'build samples')
        if samples > 1 and not build.get('prepare'):
            raise ValueError('Repeated build samples need a prepare command to establish cache state')
        durations, outputs = [], []
        for _ in range(samples):
            if build.get('prepare'):
                command(build['prepare'], cwd, scratch, timeout)
            elapsed, raw = command(build['command'], cwd, scratch, timeout)
            durations.append(elapsed); outputs.append(hashlib.sha256(raw).hexdigest())
        result['build'] = dict(scope=build['scope'],cache_state=build['cache_state'],
            command=build['command'],prepare=build.get('prepare'),
            process_wall_seconds=summary(durations),output_sha256=outputs)
    run = spec['run']
    samples = count(run.get('samples',5),1,50,'run samples')
    warmups = count(run.get('warmups',1),0,10,'warmups')
    executable_name = argv(run['command'])[0]
    executable = (cwd / executable_name).resolve()
    if not executable.is_file():
        located = shutil.which(executable_name)
        executable = Path(located).resolve() if located else None
    executable_sha = fingerprint(executable) if executable else None
    wall, simulated, semantics = [], [], None
    for index in range(warmups+samples):
        elapsed, raw = command(run['command'],cwd,scratch,timeout)
        semantic, seconds = parse_simulation(raw)
        if semantics is not None and semantic != semantics:
            raise ValueError('Semantic result changed between benchmark samples')
        semantics = semantic
        if index >= warmups:
            wall.append(elapsed); simulated.append(seconds)
    for path, sha in pinned+implementation:
        if fingerprint(path) != sha:
            raise ValueError(f'Pinned file changed while benchmarking: {path.name}')
    if executable and fingerprint(executable) != executable_sha:
        raise ValueError('Simulation executable changed while benchmarking')
    result.update(result='pass',semantic=semantics,semantic_sha256=digest(semantics),
                  simulation=dict(command=run['command'],warmups=warmups,
                    executable_sha256=executable_sha,
                    process_wall_seconds=summary(wall),instrumented_seconds=summary(simulated)))
    if baseline is not None:
        result['comparison'] = compare(baseline,result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compare',type=Path)
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise ValueError('Refuse to overwrite a benchmark receipt')
        args.out.parent.mkdir(parents=True,exist_ok=True)
        spec = json.loads(args.spec.read_text(encoding='utf-8'))
        prior = json.loads(args.compare.read_text(encoding='utf-8')) if args.compare else None
        result = benchmark(spec,args.spec.resolve().parent,args.out.parent,prior)
        args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(result='pass',semantic_sha256=result['semantic_sha256'],
                             simulation=result['simulation'],comparison=result.get('comparison')),indent=2))
    except (ValueError,KeyError,TypeError,RuntimeError,OSError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
