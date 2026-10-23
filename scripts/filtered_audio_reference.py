"""Check authored presentation inputs against unmodified Geargrafx filters.

The GPL reference is compiled separately in a private output directory. No
reference implementation is linked to the runtime. ADPCM fixtures restore
only a held predictor through its public version-44 state API, preserving
filter history, then compare actual Sample/EndFrame S16 output. They do not
qualify decoder clocks, bus phases, analog circuits or a hardware resampler.
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
from scripts import psg_reference

COMMIT = psg_reference.GEAR_COMMIT


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plans():
    psg = psg_reference.plans()
    # Complete filter histories, half-integer inputs and sums beyond S16 must
    # survive frame-buffer drains without premature truncation or clipping.
    for name, values in (
        ('fractional-stereo', [(1, -1), (3, -5), (-7, 9), (65535, -65535)]),
        ('unclipped-stereo', [(196602, -196608), (-196608, 196602), (0, 0)]),
        ('dc-decay', [(24001, -17003)]*4096+[(0, 0)]*4096),
        ('impulse', [(1, -1), (0, 0)]*1024),
    ):
        psg.append(dict(id=name, operations=[('r', 1), *[('x', *v) for v in values]]))
    adpcm = []
    for rate in range(16):
        values = [(2048, 1)]*3+[(4095, 1)]*128+[(0, 1)]*128
        values += [(2048, 1)]*1024+[(3101, 0)]*256+[(3101, 1)]*256
        values += [(x, i % 2) for i, x in enumerate(range(0, 4096, 17))]
        adpcm.append(dict(id=f'held-predictor-rate-{rate:02}',
                          operations=[('r', 1), ('v', rate), *[('a', *v) for v in values]]))
    adpcm.append(dict(id='reset-history', operations=[('r', 1), *[('a', 4095, 0)]*512,
                                                       ('r', 1), *[('a', 2048, 1)]*1024]))
    return dict(psg=psg, adpcm=adpcm)


def serialize(cases):
    lines, spans, count = [], [], 0
    for case in cases:
        before = count
        for op in case['operations']:
            lines.append(' '.join(map(str, op)))
            count += op[0] in ('s', 'x', 'a')
        spans.append(dict(id=case['id'], start=before, samples=count-before))
    return '\n'.join(lines)+'\n', spans


def compare(actual, expected, spans):
    count = sum(row['samples'] for row in spans)
    if not isinstance(actual, list) or not isinstance(expected, list) or len(actual) != count or len(expected) != count:
        raise ValueError('Filtered reference sample count changed')
    for records in (actual, expected):
        if any(not isinstance(row, list) or len(row) != 2 or
               any(type(value) is not int or not -32768 <= value <= 32767 for value in row) for row in records):
            raise ValueError('Malformed filtered reference stereo record')
    for span in spans:
        for i in range(span['start'], span['start']+span['samples']):
            if actual[i] != expected[i]:
                return dict(case=span['id'], sample=i-span['start'], actual=actual[i], expected=expected[i])
    return None


def source_binding(checkout):
    """Require exact Git blobs, including transitive source/header dependencies."""
    prefix = 'platforms/shared/dependencies/'
    names = subprocess.run(['git', '-C', str(checkout), 'ls-tree', '-r', '--name-only', COMMIT,
                            'src', prefix+'miniz', prefix+'minivorbis', prefix+'qon', prefix+'json', prefix+'libchdr/include'],
                           check=True, capture_output=True, text=True, timeout=20).stdout.splitlines()
    names = [name for name in names if Path(name).suffix in ('.cpp', '.c', '.h', '.hpp')]
    if not names:
        raise ValueError('No pinned Gear source files found')
    result = {}
    for name in names:
        expected = subprocess.run(['git', '-C', str(checkout), 'rev-parse', COMMIT+':'+name],
                                  check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        actual = subprocess.run(['git', '-C', str(checkout), 'hash-object', '--no-filters', name],
                                check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        if actual != expected:
            raise ValueError('Reference source differs from immutable commit: '+name)
        result[name] = sha(checkout/name)
    return result


def compile_sources(checkout, source):
    """Never compile an unbound file discovered through the working tree."""
    excluded = {'media_file_libretro.cpp', 'cdrom_drive_linux.cpp', 'cdrom_drive_macos.cpp',
                'cdrom_drive_win32.cpp', 'cdrom_physical_image.cpp', 'cdrom_drive.cpp'}
    discovered = {p.relative_to(checkout).as_posix() for p in (checkout/'src').glob('*.cpp')}
    if discovered-set(source):
        raise ValueError('Unexpected unpinned Gear source: '+', '.join(sorted(discovered-set(source))))
    cpp = [checkout/name for name in sorted(source)
           if Path(name).parent == Path('src') and Path(name).suffix == '.cpp' and Path(name).name not in excluded]
    cpp.append(checkout/'platforms/shared/dependencies/qon/qon.cpp')
    c = [checkout/'platforms/shared/dependencies/miniz/miniz.c',
         checkout/'platforms/shared/dependencies/minivorbis/minivorbis.c']
    for path in cpp+c:
        name = path.relative_to(checkout).as_posix()
        if name not in source or not path.is_file() or sha(path) != source[name]:
            raise ValueError('Compile input is missing, changed or unpinned: '+name)
    return cpp, c


def record_preservation(report, bindings):
    flags = {}
    for group, files in bindings.items():
        try:
            flags[group] = all(sha(Path(name)) == digest for name, digest in files.items())
        except OSError:
            flags[group] = False
    report['preservation'] = flags
    if not all(flags.values()):
        report['result'] = 'failed-preservation'


def run(args):
    checkout, out, probe = args.gear_source.resolve(), args.out.resolve(), args.probe.resolve()
    compiler_name = shutil.which(str(args.compiler))
    if not compiler_name or not probe.is_file() or out.exists():
        raise ValueError('Require C++ compiler, built toolkit filter probe and a new output directory')
    compiler = Path(compiler_name).resolve()
    source = source_binding(checkout)
    libraries = [path.resolve() for path in args.library]
    if not libraries or any(not p.is_file() for p in libraries):
        raise ValueError('Supply the external libchdr and dependency static libraries explicitly')
    wrapper = ROOT/'tests/geargrafx_filter_probe.cpp'
    adapter = Path(__file__).resolve()
    toolkit_files = [ROOT/name for name in ('tests/filter_oracle_probe.cpp', 'runtime/src/audio.cpp',
                                            'runtime/src/audio_dsp.cpp', 'runtime/include/pce/audio.hpp',
                                            'runtime/include/pce/audio_dsp.hpp', 'scripts/psg_reference.py')]
    bindings = dict(reference_sources={str(checkout/name): value for name, value in source.items()},
                    external_libraries={str(p): sha(p) for p in libraries},
                    tools={str(compiler): sha(compiler), str(probe): sha(probe)},
                    authored_sources={str(p): sha(p) for p in [wrapper, adapter, *toolkit_files]})
    report = dict(schema=1, result='incomplete', oracle='Separately compiled unmodified Geargrafx 1.8.4 filters',
                  oracle_commit=COMMIT, source_url=f'https://github.com/drhelius/Geargrafx/tree/{COMMIT}',
                  bindings=bindings, compiler_version=subprocess.run([str(compiler), '--version'], check=True,
                      capture_output=True, text=True, timeout=10).stdout, commands=[], comparisons=[])
    out.mkdir(parents=True)
    objects = out/'objects';objects.mkdir()
    oracle = out/('gear-filter-probe.exe' if os.name == 'nt' else 'gear-filter-probe')
    deps = checkout/'platforms/shared/dependencies'
    cpp, c = compile_sources(checkout, source)
    cpp.append(wrapper)
    includes = [checkout/'src', deps/'miniz', deps/'libchdr/include', deps/'minivorbis', deps/'json']
    common = ['-O2', '-ffp-contract=off', '-ffunction-sections', '-fdata-sections', '-DGG_DISABLE_DISASSEMBLER',
              '-DGG_DISABLE_VGMRECORDER', '-DGG_DISABLE_MMI_THREADS']
    for include in includes:
        common += ['-I', str(include)]
    commands = []
    for i, path in enumerate(cpp+c):
        target = objects/(f'{i:02}-'+path.stem+'.o')
        command = [str(compiler), *common, '-x', 'c++' if path.suffix == '.cpp' else 'c',
                   *(['-std=c++20', '-include', 'cerrno'] if path.suffix == '.cpp' else ['-std=c11']),
                   '-c', str(path), '-o', str(target)]
        commands.append((command, target))
    report['commands'] = [command for command, _ in commands]
    try:
        def compile_one(item):
            command, target = item
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            target.with_suffix('.log').write_text(result.stdout+result.stderr, encoding='utf-8')
            result.check_returncode()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(compile_one, commands))
        command = [str(compiler), *[str(target) for _, target in commands], *[str(p) for p in libraries],
                   '-Wl,--gc-sections', '-o', str(oracle)]
        report['commands'].append(command)
        linked = subprocess.run(command, capture_output=True, text=True, timeout=90)
        (out/'link.log').write_text(linked.stdout+linked.stderr, encoding='utf-8');linked.check_returncode()
        report['oracle_exe_sha256'] = sha(oracle)
        bindings['oracle_binary'] = {str(oracle): sha(oracle)}
        for mode, cases in plans().items():
            text, spans = serialize(cases)
            plan = out/(mode+'.plan');plan.write_text(text, encoding='ascii')
            spanpath = out/(mode+'-cases.json');spanpath.write_text(json.dumps(spans, indent=2)+'\n', encoding='ascii')
            binding = bindings.setdefault('authored_plans', {})
            binding.update({str(plan): sha(plan), str(spanpath): sha(spanpath)})
            outputs = {}
            for label, command in [('toolkit', [str(probe), mode, str(plan)]),
                                   ('gear-chunk-1', [str(oracle), mode, str(plan), '1']),
                                   ('gear-chunk-509', [str(oracle), mode, str(plan), '509'])]:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=True)
                path = out/(mode+'-'+label+'.json');path.write_text(completed.stdout, encoding='ascii')
                outputs[label] = json.loads(completed.stdout)
                bindings.setdefault('raw_outputs', {})[str(path)] = sha(path)
            mismatch = compare(outputs['toolkit'], outputs['gear-chunk-1'], spans)
            chunk_mismatch = compare(outputs['gear-chunk-509'], outputs['gear-chunk-1'], spans)
            report['comparisons'].append(dict(source=mode, cases=len(cases), stereo_samples=sum(s['samples'] for s in spans),
                                             mismatch=mismatch, chunk_mismatch=chunk_mismatch,
                                             chunk_invariance_checked=mode == 'psg',
                                             actual_drain_frames=[1, 509] if mode == 'psg' else [1]))
            if mismatch or chunk_mismatch:
                raise ValueError('Independent filtered output mismatch: '+mode)
        report.update(result='pass', scope='Actual independent Sample/EndFrame S16: PSG synthesis plus half-integer/unclipped synthetic sums; ADPCM held predictor and fader targets 0/1 with reset/decay histories. ADPCM fixtures restore only predictor/rate and CD fader controls through public save-state APIs; no decoder/clock parity claim.',
                      not_checked=['ADPCM decoder clock integration', 'continuous fader clock timeline', 'resampler parity',
                                   'hardware analog response', 'retail PCM', 'audio device playback'])
    except Exception as error:
        report.update(result='fail', error=str(error))
        raise
    finally:
        record_preservation(report, bindings)
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('bindings', 'commands')}, indent=2))
    if report['result'] != 'pass':
        raise ValueError('Independent filter reference failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source', type=Path, required=True, help='Complete immutable upstream checkout')
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--library', type=Path, action='append', default=[], help='External libchdr/dependency static library, link order')
    try:
        run(parser.parse_args())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr);raise SystemExit(1)
