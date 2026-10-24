"""Independently check authored CUE media against original Geargrafx readers.

The external GPL code is built into a separate executable using only its
public media API; it is never linked to the MIT runtime. These checks concern
geometry and exact data/audio bytes, not drive seeks or CPU bus timing.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from cue_fixture import definitions, expected, write_case, write_plan, composite_identity, data_sector
from scripts import filtered_audio_reference as filters


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def difference(actual, wanted, path='$'):
    """Return the first typed mismatch; bool/int equality cannot hide a defect."""
    if type(actual) is not type(wanted):
        return dict(path=path, reason='type', actual=type(actual).__name__, expected=type(wanted).__name__)
    if isinstance(wanted, dict):
        if set(actual) != set(wanted):
            return dict(path=path, reason='keys', actual=sorted(actual), expected=sorted(wanted))
        for key in wanted:
            result = difference(actual[key], wanted[key], path + '.' + key)
            if result:
                return result
    elif isinstance(wanted, list):
        if len(actual) != len(wanted):
            return dict(path=path, reason='length', actual=len(actual), expected=len(wanted))
        for index, value in enumerate(wanted):
            result = difference(actual[index], value, f'{path}[{index}]')
            if result:
                return result
    elif actual != wanted:
        return dict(path=path, reason='value', actual=actual, expected=wanted)
    return None


def stream_expectations(case):
    """At most two sectors per declared contiguous data range, per CPU tier."""
    data = [(lba, seed, frame) for lba, kind, seed, frame in case['mapping'] if kind == 'd']
    runs = []
    for item in data:
        if not runs or item[0] != runs[-1][-1][0] + 1:
            runs.append([])
        runs[-1].append(item)
    return [dict(lba=run[0][0], count=min(len(run), 2),
                 sectors=[data_sector(seed, frame).hex() for _, seed, frame in run[:2]])
            for run in runs]


def compare_stream(actual, request, tier):
    wanted = dict(sectors=request['sectors'], status_port=0xD8, status=0,
                  message_port=0xF8, final_port=0, guard_misses=0,
                  sectors_read=request['count'], read_errors=0,
                  data_bytes_acked=2048 * request['count'])
    if not isinstance(actual, dict) or set(actual) != set(wanted) | {'native_steps', 'interpreter_steps'}:
        return dict(reason='stream fields')
    for key in ('native_steps', 'interpreter_steps'):
        if type(actual[key]) is not int or actual[key] < 0:
            return dict(reason='stream tier counter type', field=key)
    selected = 'native_steps' if tier == 'native' else 'interpreter_steps'
    other = 'interpreter_steps' if tier == 'native' else 'native_steps'
    if not actual[selected] or actual[other]:
        return dict(reason='stream tier execution', selected=actual[selected], other=actual[other])
    return difference({key: actual[key] for key in wanted}, wanted)


def python_observations(cue, wanted):
    from pcerecomp.cue import Cue
    image = Cue(cue)
    result = dict(leadout=image.leadout_lba,
                  tracks=[[track.disc_start, 0 if track.type == 'AUDIO' else 4]
                          for track in image.tracks], observations=[])
    for request in wanted['observations']:
        op, lba = request['op'], request['lba']
        row = dict(op=op, lba=lba)
        if op == 'p':
            row['playable'] = image.audio_playable(lba)
        elif op == 'd':
            row['bytes'] = image.read(lba).hex()
        else:
            row['samples'] = list(image.read_audio(lba))
        result['observations'].append(row)
    return result, image.image_sha256()


def compile_reference(checkout, compiler, out, report):
    sources = filters.source_binding(checkout)
    selected = ['src/cdrom_image.cpp', 'src/cdrom_cuebin_image.cpp',
                'src/media_file.cpp', 'src/media_file_native.cpp', 'src/ogg_vorbis_decoder.cpp',
                'platforms/shared/dependencies/minivorbis/minivorbis.c',
                'platforms/shared/dependencies/miniz/miniz.c']
    if any(name not in sources for name in selected):
        raise ValueError('Reference dependency missing from pinned source graph')
    wrapper = ROOT / 'tests/geargrafx_cue_probe.cpp'
    report['bindings']['reference_sources'] = {str(checkout / name): digest for name, digest in sources.items()}
    report['bindings']['compiled_reference_sources'] = [str(checkout / name) for name in selected]
    paths = [checkout / name for name in selected] + [wrapper]
    objects = out / 'objects'
    objects.mkdir()
    common = ['-O2', '-ffunction-sections', '-fdata-sections', '-DGG_DISABLE_DISASSEMBLER',
              '-DGG_DISABLE_VGMRECORDER', '-DGG_DISABLE_MMI_THREADS']
    deps = checkout / 'platforms/shared/dependencies'
    for include in (checkout / 'src', deps / 'miniz', deps / 'minivorbis'):
        common += ['-I', str(include)]
    jobs = []
    for index, path in enumerate(paths):
        target = objects / f'{index:02}-{path.stem}.o'
        cpp = path.suffix == '.cpp'
        command = [str(compiler), *common, '-x', 'c++' if cpp else 'c',
                   *(['-std=c++20', '-include', 'cerrno'] if cpp else ['-std=c11']),
                   '-c', str(path), '-o', str(target)]
        jobs.append((command, target))
        report['commands'].append(command)

    def compile_one(job):
        command, target = job
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        target.with_suffix('.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        result.check_returncode()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(compile_one, jobs))
    executable = out / ('gear-cue.exe' if os.name == 'nt' else 'gear-cue')
    command = [str(compiler), *[str(target) for _, target in jobs], '-Wl,--gc-sections', '-o', str(executable)]
    report['commands'].append(command)
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (out / 'link.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    result.check_returncode()
    report['bindings']['compiled_objects'] = {str(target): sha(target) for _, target in jobs}
    report['bindings']['oracle_binary'] = {str(executable): sha(executable)}
    return executable


def run(args):
    checkout, probe, out = args.gear_source.resolve(), args.probe.resolve(), args.out.resolve()
    found = shutil.which(str(args.compiler))
    if not found or not probe.is_file() or out.exists():
        raise ValueError('Require compiler, built CUE probe and new output directory')
    compiler = Path(found).resolve()
    out.mkdir(parents=True)
    report = dict(schema=1, result='incomplete', oracle_commit=filters.COMMIT,
                  bindings=dict(authored_sources={}, tools={str(compiler): sha(compiler), str(probe): sha(probe)}),
                  commands=[], cases=[], streams=[],
                  scope='Authored CUE TOC, stored/virtual pregaps, data bytes, signed little-endian audio and playback gate; separate native/interpreted MMIO READ through toolkit provider',
                  not_checked=['Physical hardware', 'Drive seek timing', 'CPU access-phase alignment',
                               'ECC/EDC validation', 'Unsupported CUE modes/directives', 'Retail media'])
    for path in (Path(__file__).resolve(), ROOT / 'tests/cue_fixture.py', ROOT / 'tests/cue_oracle_probe.cpp',
                 ROOT / 'tests/geargrafx_cue_probe.cpp', ROOT / 'tests/generate_scsi_fixture.py',
                 ROOT / 'pcerecomp/cue.py', ROOT / 'pcerecomp/media.py'):
        report['bindings']['authored_sources'][str(path)] = sha(path)
    report['bindings']['observed_tool_sources'] = {
        str(path): sha(path) for path in sorted((ROOT / 'runtime').rglob('*'))
        if path.is_file() and path.suffix in ('.cpp', '.hpp')}
    report['probe_build_provenance'] = ('Supplied executable hash and observed runtime source hashes; '
                                         'the caller must retain its actual fresh CMake build record')
    try:
        gear = compile_reference(checkout, compiler, out, report)

        def execute(label, command):
            report['commands'].append(command)
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
            stdout, stderr = out / (label + '.json'), out / (label + '.stderr')
            stdout.write_text(completed.stdout, encoding='utf-8')
            stderr.write_text(completed.stderr, encoding='utf-8')
            report['bindings'].setdefault('raw_outputs', {}).update({str(stdout): sha(stdout), str(stderr): sha(stderr)})
            completed.check_returncode()
            return json.loads(completed.stdout)

        for case in definitions():
            directory = out / case['id']
            cue = write_case(directory, case)
            wanted = expected(case)
            plan = directory / 'observations.plan'
            write_plan(plan, wanted)
            expected_path = directory / 'independent-expected.json'
            expected_path.write_text(json.dumps(wanted) + '\n', encoding='utf-8')
            report['bindings'].setdefault('authored_inputs', {}).update(
                {str(path): sha(path) for path in directory.rglob('*') if path.is_file()})
            oracle = execute(case['id'] + '-gear', [str(gear), str(cue), str(plan)])
            actual = execute(case['id'] + '-tool', [str(probe), '--inspect', str(cue), str(plan)])
            if not isinstance(actual, dict):
                raise ValueError('Toolkit CUE observation is not an object')
            identity = actual.pop('image_sha256', None)
            wanted_identity = composite_identity(cue, case)
            python_actual, python_identity = python_observations(cue, wanted)
            python_path = out / (case['id'] + '-python.json')
            python_path.write_text(json.dumps(python_actual) + '\n', encoding='utf-8')
            report['bindings']['raw_outputs'][str(python_path)] = sha(python_path)
            row = dict(id=case['id'], observations=len(wanted['observations']),
                       data_bytes=sum(2048 for item in wanted['observations'] if item['op'] == 'd'),
                       audio_samples=sum(1176 for item in wanted['observations'] if item['op'] == 'a'),
                       oracle_mismatch=difference(oracle, wanted), toolkit_mismatch=difference(actual, wanted),
                       python_mismatch=difference(python_actual, wanted),
                       identity_mismatch=identity != wanted_identity or python_identity != wanted_identity,
                       image_sha256=wanted_identity)
            report['cases'].append(row)
            if row['oracle_mismatch'] or row['toolkit_mismatch'] or row['python_mismatch'] or row['identity_mismatch']:
                raise ValueError('Authored CUE comparison differs: ' + case['id'])
            for index, request in enumerate(stream_expectations(case)):
                for tier in ('native', 'interpreter'):
                    label = f"{case['id']}-stream-{index}-{tier}"
                    actual = execute(label, [str(probe), '--stream', str(cue), tier, str(request['lba']), str(request['count'])])
                    mismatch = compare_stream(actual, request, tier)
                    report['streams'].append(dict(case=case['id'], tier=tier, lba=request['lba'],
                                                   sectors=request['count'], native_steps=actual.get('native_steps'),
                                                   interpreter_steps=actual.get('interpreter_steps'), mismatch=mismatch))
                    if mismatch:
                        raise ValueError('CUE translated CD stream differs: ' + label)
            print(f"Qualified {case['id']}: {row['observations']} observations", flush=True)
        report['result'] = 'pass'
    except Exception as error:
        report.update(result='fail', error=str(error))
        raise
    finally:
        changes = []
        for category, entries in report['bindings'].items():
            if isinstance(entries, dict):
                for path, digest in entries.items():
                    if sha(path) != digest:
                        changes.append(path)
        report['binding_changes'] = changes
        if changes:
            report['result'] = 'fail'
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('bindings', 'commands')}, indent=2))
    if report['result'] != 'pass':
        raise ValueError('Independent CUE comparison failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--compiler', default='g++')
    try:
        run(parser.parse_args())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
