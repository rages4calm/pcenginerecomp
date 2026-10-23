"""Compare authored digital PSG plans against separately compiled Geargrafx.

Supply the unmodified src files from the pinned GPL reference and a miniz
include directory. They remain external inputs: no Geargrafx implementation
is distributed or linked into the toolkit. This checks raw digital synthesis,
including the half-gain and signed-16 clamp, before filters or source mixing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
GEAR_COMMIT = '1c62a549328241518101f5be5bf3e6840b96ea5d'
GEAR_FILES = {
    'bit_ops.h': '96ed0abf496df201248c3b9435e186a23313629593ffc3d2c61a1467ec8e69ae',
    'common.h': '8c8a17fc7deef5f083b31e2fc266d8d714f44dc145a8512a6e7f4f1b31b1e167',
    'defines.h': '34db3382395299131d0e3b3b90a12976a134177344684e4eae6d22e9c9fcf67e',
    'huc6280_psg_inline.h': 'e72eac73c6dec4b8725fa6027473323aafd4431e01cb98b7c27d4b3ab3d9fc8e',
    'huc6280_psg.cpp': 'c5d28c0da135883f1ba3faaab4e50f2eddec9b259f6e013e41b9f33d12df9b39',
    'huc6280_psg.h': '91cc894a73af28a5857d62583a979c5e37103639fae8113ca07f3b50bd065ebb',
    'log.h': '913a42dafa0f5d0851ea398aba19a1f35edaa43431bda8eff74f459e0b4ddb9f',
    'types.h': '9d41b5124e4fe9dd895472f3038530983db70973e4ed9a2926cf84dbde9dc74e',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_sources(directory):
    actual = {name: sha(directory/name) for name in GEAR_FILES}
    if actual != GEAR_FILES:
        raise ValueError('Geargrafx source differs from the pinned 1.8.4 files')
    return actual


def plans():
    """Authored registers and waveforms; no sampled or extracted game data."""
    result = []

    def add(name, centered, ops):
        result.append(dict(id=name, operations=[('r', int(centered)), *ops]))

    def setup(channel, period, wave, control=159, balance=255):
        return [('w', 1, 255), ('w', 0, channel), ('w', 2, period & 255),
                ('w', 3, period >> 8), ('w', 5, balance), ('w', 4, 64),
                ('w', 4, 0), *[('w', 6, value) for value in wave],
                ('w', 4, 64), ('w', 4, control)]

    shapes = [[0]*32, [31]*32, list(range(32)),
              [((i*i*7+3*i+11) % 32) for i in range(32)],
              [31]+[0]*31, [0]+[31]*31]
    for centered in (False, True):
        for channel in range(6):
            for period in (0, 1, 2, 3, 4, 5, 6, 7, 32, 127, 4095):
                for shape, wave in enumerate(shapes):
                    ops = setup(channel, period, wave)
                    ops += [('s', n) for n in (1, 1, 2, 5, 6, 11, 31, 63, 127, 511, 4096, 8193)]
                    add(f'wave-{int(centered)}-{channel}-{period}-{shape}', centered, ops)
            # Every 5-bit channel amplitude and all 4-bit side amplitude codes,
            # with every possible DDA value, on each physical channel.
            modes = [(255, 255, volume) for volume in range(32)]
            modes += [(level << 4 | (15-level), 255, 31) for level in range(16)]
            modes += [(255, level << 4 | (15-level), 31) for level in range(16)]
            for mode, (main, balance, volume) in enumerate(modes):
                ops = [('w', 1, main), ('w', 0, channel), ('w', 5, balance), ('w', 4, 192 | volume)]
                for value in range(32):
                    ops += [('w', 6, value), ('s', 1+value % 7)]
                add(f'dda-gain-{int(centered)}-{channel}-{mode}', centered, ops)
                for shape in (4, 5):
                    # Nonintegral positive/negative means must be rounded
                    # after side gain, never truncated to a 5-bit DAC value.
                    mean_ops = setup(channel, 3, shapes[shape], control=128 | volume, balance=balance)
                    mean_ops += [('w', 1, main), ('s', 1), ('s', 31)]
                    add(f'mean-gain-{int(centered)}-{channel}-{mode}-{shape}', centered, mean_ops)
        for channel in (4, 5):
            for noise in range(32):
                ops = setup(channel, 53, shapes[3]) + [('w', 7, 128 | noise)]
                ops += [('s', n) for _ in range(8) for n in (1, 31, 32, 63, 64, 127, 511, 1984)]
                # The noise clock runs while disabled and in DDA mode too.
                ops += [('w', 4, 0), ('s', 10003), ('w', 4, 223), ('w', 6, 23), ('s', 7049)]
                add(f'noise-{int(centered)}-{channel}-{noise}', centered, ops)
        for depth in (1, 2, 3):
            for divider in (0, 1, 7):
                for held in (False, True):
                    ops = setup(0, 127, shapes[3]) + setup(1, 31, shapes[2])
                    ops += [('w', 8, divider), ('w', 9, 128 | depth), ('w', 9, depth | (128 if held else 0))]
                    ops += [('s', n) for _ in range(12) for n in (1, 7, 29, 53, 127, 311, 997)]
                    ops += [('w', 9, 0), ('s', 521), ('w', 9, 128), ('s', 809)]
                    add(f'lfo-{int(centered)}-{depth}-{divider}-{int(held)}', centered, ops)
        # Six simultaneous channels, enabled waveform-memory updates, channel
        # select aliases, DDA transitions, disable/re-enable and noise edges.
        ops = []
        for channel in range(6):
            ops += setup(channel, (channel+1)*97, shapes[channel % 4], balance=255-channel*17)
        for index in range(128):
            channel = index % 6
            ops += [('w', 0, channel), ('s', 1+(index*193) % 811),
                    ('w', 6, (index*13) % 32), ('s', 97)]
        for channel in range(6):
            ops += [('w', 0, channel), ('w', 4, 223), ('w', 6, channel*5), ('s', 137),
                    ('w', 4, 159), ('s', 499), ('w', 4, 31), ('s', 139), ('w', 4, 159), ('s', 809)]
        ops += [('w', 0, 7), ('w', 4, 255), ('w', 6, 31), ('s', 177)]
        add(f'six-channel-transitions-{int(centered)}', centered, ops)
    return result


def serialize(cases):
    lines, spans, count = [], [], 0
    for case in cases:
        before = count
        for op in case['operations']:
            lines.append(' '.join(map(str, op)))
            count += op[0] == 's'
        spans.append(dict(id=case['id'], start=before, samples=count-before))
    return '\n'.join(lines)+'\n', spans


def compare(actual, expected, spans):
    expected_count = sum(span['samples'] for span in spans)
    if len(actual) != expected_count or len(expected) != expected_count:
        raise ValueError('PSG reference sample count differs from authored plan')
    for records in (actual, expected):
        for row in records:
            if (not isinstance(row, list) or len(row) != 4 or
                    any(type(value) is not int or not -32768 <= value <= 32767 for value in row[:2]) or
                    not isinstance(row[2], list) or len(row[2]) != 6 or
                    any(type(value) is not int or not 0 <= value < 32 for value in row[2]) or
                    not isinstance(row[3], list) or len(row[3]) != 2 or
                    any(type(value) is not int or not 0 <= value < (1 << 18) for value in row[3])):
                raise ValueError('Malformed PSG reference sample/state record')
    for span in spans:
        for index in range(span['start'], span['start']+span['samples']):
            if actual[index] != expected[index]:
                return dict(case=span['id'], sample=index-span['start'],
                            actual=actual[index], expected=expected[index])
    return None


def record_preservation(report, sources, binding, probe):
    """A successful comparison cannot survive changed or missing inputs."""
    try:
        sources_unchanged = bind_sources(sources) == binding
    except (OSError, ValueError):
        sources_unchanged = False
    try:
        probe_unchanged = sha(probe) == report['probe_sha256']
    except OSError:
        probe_unchanged = False
    report.update(oracle_sources_unchanged=sources_unchanged,
                  probe_unchanged=probe_unchanged)
    if not sources_unchanged or not probe_unchanged:
        report['result'] = 'failed-preservation'


def run(args):
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Reference output directory must be new')
    sources = args.gear_source.resolve()
    binding = bind_sources(sources)
    compiler_name = shutil.which(str(args.compiler))
    if not compiler_name:
        raise ValueError('C++ compiler does not exist')
    compiler = Path(compiler_name).resolve()
    probe, miniz = args.probe.resolve(), args.miniz.resolve()
    if not probe.is_file() or not (miniz/'miniz.h').is_file():
        raise ValueError('Require compiled toolkit PCM probe and miniz headers')
    out.mkdir(parents=True)
    wrapper = ROOT/'tests/geargrafx_psg_probe.cpp'
    oracle = out/('gear-psg-probe.exe' if os.name == 'nt' else 'gear-psg-probe')
    command = [str(compiler), '-std=c++20', '-O2', '-ffp-contract=off',
               '-I', str(sources), '-I', str(miniz), str(wrapper),
               str(sources/'huc6280_psg.cpp'), '-o', str(oracle)]
    report = dict(schema=1, result='incomplete', oracle='Geargrafx 1.8.4 external PSG source',
                  oracle_commit=GEAR_COMMIT, oracle_sources=binding,
                  source_url=f'https://github.com/drhelius/Geargrafx/tree/{GEAR_COMMIT}',
                  compiler=dict(path=str(compiler), sha256=sha(compiler),
                                version=subprocess.run([str(compiler), '--version'], check=True,
                                                       capture_output=True, text=True, timeout=10).stdout),
                  compile_command=command, adapter_sha256=sha(Path(__file__).resolve()),
                  wrapper_sha256=sha(wrapper), probe_sha256=sha(probe),
                  external_headers={p.name: sha(p) for p in miniz.glob('*.h')})
    try:
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=90)
        (out/'compile.log').write_text(compiled.stdout+compiled.stderr, encoding='utf-8')
        compiled.check_returncode()
        cases = plans()
        text, spans = serialize(cases)
        plan = out/'plan.txt'; plan.write_text(text, encoding='ascii')
        (out/'cases.json').write_text(json.dumps(spans, indent=2)+'\n', encoding='utf-8')
        report.update(plan_sha256=sha(plan), cases=len(spans),
                      stereo_samples=sum(span['samples'] for span in spans),
                      oracle_exe_sha256=sha(oracle))
        outputs = {}
        for name, command in (('gear', [str(oracle), str(plan)]),
                              ('toolkit', [str(probe), 'psg-plan', str(plan), '0'])):
            completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
            target = out/(name+'.json'); target.write_text(completed.stdout, encoding='ascii')
            outputs[name] = json.loads(completed.stdout)
            report[name+'_output_sha256'] = sha(target)
        mismatch = compare(outputs['toolkit'], outputs['gear'], spans)
        report.update(result='fail' if mismatch else 'pass', first_mismatch=mismatch,
                      scope='Exact authored raw signed-16 stereo PSG and six waveform indices/two noise seeds; unfiltered half-gain digital profile',
                      not_checked=['PSG output high-pass filter', 'ADPCM decoder/filters', 'mixed PCM',
                                   'resampling clock', 'bus access timing', 'audio device', 'retail gameplay', 'hardware'])
    finally:
        # Source rehash makes accidental or concurrent reference mutation fail.
        record_preservation(report, sources, binding, probe)
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    if report['result'] != 'pass' or not report['probe_unchanged']:
        raise ValueError('Independent PSG comparison failed; see result.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source', type=Path, required=True)
    parser.add_argument('--miniz', type=Path, required=True)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    try:
        run(parser.parse_args())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr); raise SystemExit(1)
