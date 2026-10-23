"""Clock/register/sample integration against separately compiled Geargrafx.

The reference invokes the original Audio::Clock scheduler, original source
decoders and actual filtered EndFrame outputs. No predictor or filter state is
injected. Authored RAM is initialized via GetRAM only, before the timeline.
Direct Audio clocks do not advance core wall time: fader timelines, DMA and
ADPCM bus-slot transactions are explicitly outside this oracle's scope.
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
from scripts import filtered_audio_reference as filters


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plans():
    result = dict(psg=[], adpcm=[], mixed=[])

    def add(mode, name, operations):
        result[mode].append(dict(id=name, operations=[('r',), *operations]))

    def waveform(channel, period):
        regs = [(1, 255), (0, channel), (2, period & 255), (3, period >> 8),
                (5, 255), (4, 64), (4, 0)]
        regs += [(6, (i*i*7+3*i+11) % 32) for i in range(32)]
        regs += [(4, 64), (4, 159)]
        return [('p', 0, reg, value) for reg, value in regs]

    edges = (0, 1, 5, 6, 7, 486, 487, 488, 489, 973, 974, 975, 976, 1461, 1462, 1463)
    add('psg', 'rational-boundaries-silent', [('s', t) for t in edges]+
        [('s',t) for t in (7159090,7159091,7159092,21477272,21477273)])
    for channel in range(6):
        for reg,value in ((6,31),(5,0),(1,0),(4,95),(4,159)):
            ops=[('p',0,r,v) for r,v in ((0,channel),(1,255),(5,255),(4,223),(6,0))]
            ops += [('s',486),('p',487,reg,value),('s',488),('s',489),('s',972),
                    ('p',974,6,7),('s',975),('s',976),('s',1950)]
            add('psg',f'dda-held-{channel}-reg{reg}-value{value}',ops)
    for channel in range(6):
        for period in (0, 1, 5, 6, 127, 4095):
            ops = waveform(channel, period)+[('s', t) for t in edges]
            for t in (1464, 1465, 1466, 1948, 1949, 1950, 1951, 9997):
                ops += [('p', t, 6, (t*11) & 31), ('s', t)]
            ops += [('s', 200003)]
            add('psg', f'wave-{channel}-{period}', ops)
    for channel in (4, 5):
        for divider in (0, 1, 30, 31):
            ops = waveform(channel, 127)+[('p', 0, 7, 128 | divider)]
            ops += [('s', t) for t in edges]+[('s', 200003)]
            add('psg', f'noise-{channel}-{divider}', ops)
    ops = waveform(0, 127)+waveform(1, 6)+[('p', 0, 8, 3), ('p', 0, 9, 1)]
    for t, value in ((487, 2), (488, 3), (1462, 128), (1950, 1), (3001, 0)):
        ops += [('p', t, 9, value), ('s', t)]
    add('psg', 'lfo-timed-control', ops+[('s', 200003)])

    def decoder(rate, length=65535, finite=False):
        return [('a', 0, 8, 255), ('a', 0, 9, 255), ('a', 0, 13, 12),
                ('a', 0, 8, length & 255), ('a', 0, 9, length >> 8),
                ('a', 0, 13, 16), ('s', 1), ('a', 1, 14, rate),
                ('a', 1, 13, 96 if finite else 32)]

    for rate in range(16):
        ops = decoder(rate)+[('s', t) for t in (486, 487, 488, 668, 669, 670, 9997, 100003, 200003)]
        ops += [('a', 200003, 13, 0), ('s', 201001), ('a', 201001, 13, 32), ('s', 300003),
                ('a', 300003, 13, 128), ('s', 300004), ('a', 300004, 13, 0), ('s', 310003)]
        add('adpcm', f'decoder-rate-{rate}', ops)
    for rate in (0, 7, 15):
        ops = decoder(rate, 1, True)+[('s', t) for t in (488, 669, 1339, 30001, 100003)]
        add('adpcm', f'finite-one-byte-{rate}', ops)
    for old,new in ((15,7),(15,0),(7,0)):
        ops=decoder(old)+[('s',100003),('a',100003,14,new),('s',100004),('s',110003),('s',200003)]
        add('adpcm',f'rate-decrease-frequency-{old}-to-{new}',ops)
    ops = waveform(0, 127)+decoder(15)+[('s', t) for t in (488, 669, 975, 100003, 200003)]
    add('mixed', 'real-psg-adpcm-mix', ops)
    return result


def serialize(cases):
    lines, spans, count = [], [], 0
    for case in cases:
        start = count
        for op in case['operations']:
            lines.append(' '.join(map(str, op)))
            count += op[0] == 's'
        spans.append(dict(id=case['id'], start=start, checkpoints=count-start))
    return '\n'.join(lines)+'\n', spans


def overdue_plans():
    """A rate write can leave several decoder periods owed at the same time.

    Original Gear consumes at most one nibble per Clock callback. Qualify the
    fine-grained reference explicitly, and retain the coarser divergence.
    """
    return [dict(id=f'overdue-{old}-to-15',operations=[('r',),
        ('a',0,8,255),('a',0,9,255),('a',0,13,12),('a',0,8,255),('a',0,9,255),
        ('a',0,13,16),('s',1),('a',1,14,old),('a',1,13,32),('s',2501),
        ('a',2501,14,15),('s',2504),('s',3001),('s',6001)]) for old in (0,3,7)]


STATE_FIELDS = ('predictor', 'index', 'control', 'rate', 'read_address', 'length',
                'playing', 'pending', 'nibble', 'end', 'half')


def compare(actual, expected, spans, state=True):
    count = sum(span['checkpoints'] for span in spans)
    if len(actual) != count or len(expected) != count:
        raise ValueError('Timed checkpoint count changed')
    for span in spans:
        for i in range(span['start'], span['start']+span['checkpoints']):
            a, b = actual[i], expected[i]
            if a['time'] != b['time'] or a['pcm'] != b['pcm']:
                return dict(case=span['id'], checkpoint=i-span['start'], field='pcm/time',
                            actual_frames=len(a['pcm']), expected_frames=len(b['pcm']), time=b['time'],
                            first_difference=next((j for j, pair in enumerate(zip(a['pcm'], b['pcm'])) if pair[0] != pair[1]), None))
            for record in (a, b):
                if any(not isinstance(row, list) or len(row) != 2 or
                       any(type(x) is not int or not -32768 <= x <= 32767 for x in row) for row in record['pcm']):
                    raise ValueError('Invalid signed stereo PCM')
            if state:
                fields = (*STATE_FIELDS, 'phase') if b['adpcm']['playing'] else STATE_FIELDS
                for field in fields:
                    if a['adpcm'][field] != b['adpcm'][field]:
                        return dict(case=span['id'], checkpoint=i-span['start'], field='adpcm.'+field,
                                    actual=a['adpcm'][field], expected=b['adpcm'][field], time=b['time'])
    return None


def run(args):
    checkout, out, probe = args.gear_source.resolve(), args.out.resolve(), args.probe.resolve()
    found = shutil.which(str(args.compiler))
    if not found or not probe.is_file() or out.exists():
        raise ValueError('Require compiler, built timed probe and a new output directory')
    compiler = Path(found).resolve()
    sources = filters.source_binding(checkout)
    cpp, c = filters.compile_sources(checkout, sources)
    wrapper = ROOT/'tests/geargrafx_timed_audio_probe.cpp'
    cpp.append(wrapper)
    libraries = [p.resolve() for p in args.library]
    if not libraries or any(not p.is_file() for p in libraries):
        raise ValueError('Require pinned external libchdr dependency libraries')
    authored = [Path(__file__).resolve(), wrapper, ROOT/'tests/timed_audio_probe.cpp',
                ROOT/'scripts/filtered_audio_reference.py', ROOT/'scripts/psg_reference.py']
    authored += list((ROOT/'runtime/src').glob('*.cpp'))+list((ROOT/'runtime/include/pce').glob('*.hpp'))
    bindings = dict(reference_sources={str(checkout/n): v for n, v in sources.items()},
                    authored_sources={str(p): sha(p) for p in authored},
                    external_libraries={str(p): sha(p) for p in libraries}, tools={str(compiler): sha(compiler), str(probe): sha(probe)})
    report = dict(schema=1, result='incomplete', oracle_commit=filters.COMMIT, bindings=bindings,
                  commands=[], comparisons=[], not_checked=['core master-time fader progression', 'ADPCM bus slots/DMA',
                      'retail PCM', 'hardware audio', 'source reconstruction above 44.1k observations',
                      'stopped ADPCM phase equality across callback granularities'])
    out.mkdir(parents=True);objects=out/'objects';objects.mkdir()
    oracle = out/('gear-timed-audio.exe' if os.name == 'nt' else 'gear-timed-audio')
    deps = checkout/'platforms/shared/dependencies'
    common = ['-O2', '-ffp-contract=off', '-ffunction-sections', '-fdata-sections', '-DGG_DISABLE_DISASSEMBLER',
              '-DGG_DISABLE_VGMRECORDER', '-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src', deps/'miniz', deps/'libchdr/include', deps/'minivorbis', deps/'json'):
        common += ['-I', str(include)]
    commands=[]
    for i, path in enumerate(cpp+c):
        target=objects/(f'{i:02}-'+path.stem+'.o')
        command=[str(compiler), *common, '-x', 'c++' if path.suffix=='.cpp' else 'c',
                 *(['-std=c++20', '-include', 'cerrno'] if path.suffix=='.cpp' else ['-std=c11']),
                 '-c', str(path), '-o', str(target)]
        commands.append((command,target))
    report['commands']=[command for command, _ in commands]
    try:
        def compile_one(item):
            command,target=item
            completed=subprocess.run(command,capture_output=True,text=True,timeout=180)
            target.with_suffix('.log').write_text(completed.stdout+completed.stderr,encoding='utf-8');completed.check_returncode()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(compile_one,commands))
        link=[str(compiler), *[str(p) for _,p in commands], *map(str,libraries), '-Wl,--gc-sections','-o',str(oracle)]
        report['commands'].append(link)
        completed=subprocess.run(link,capture_output=True,text=True,timeout=90)
        (out/'link.log').write_text(completed.stdout+completed.stderr,encoding='utf-8');completed.check_returncode()
        bindings['oracle_binary']={str(oracle):sha(oracle)}
        bindings['compiled_objects']={str(p):sha(p) for _,p in commands}
        groups=[(mode,mode,cases,False) for mode,cases in plans().items()]
        groups.append(('adpcm-overdue','adpcm',overdue_plans(),True))
        for label,mode,cases,fine in groups:
            text,spans=serialize(cases);plan=out/(label+'.plan');plan.write_text(text,encoding='ascii')
            spanpath=out/(label+'-cases.json');spanpath.write_text(json.dumps(spans,indent=2)+'\n',encoding='ascii')
            bindings.setdefault('authored_plans',{}).update({str(plan):sha(plan),str(spanpath):sha(spanpath)})
            outputs={}
            executions=[('tool-whole',probe,'whole'),('tool-parts',probe,'parts'),
                        ('gear-whole',oracle,'whole'),('gear-parts',oracle,'single' if fine else 'parts')]
            for name,binary,partition in executions:
                command=[str(binary),mode,str(plan),partition];report['commands'].append(command)
                completed=subprocess.run(command,capture_output=True,text=True,timeout=120,check=True)
                path=out/(label+'-'+name+'.json');path.write_text(completed.stdout,encoding='ascii')
                bindings.setdefault('raw_outputs',{})[str(path)]=sha(path);outputs[name]=json.loads(completed.stdout)
            expected=outputs['gear-parts'] if fine else outputs['gear-whole']
            mismatch=compare(outputs['tool-whole'],expected,spans)
            tool_parts=compare(outputs['tool-parts'],outputs['tool-whole'],spans)
            gear_parts=compare(outputs['gear-parts'],outputs['gear-whole'],spans)
            report['comparisons'].append(dict(source=label,cases=len(cases),checkpoints=len(outputs['tool-whole']),
                stereo_samples=sum(len(x['pcm']) for x in outputs['tool-whole']),mismatch=mismatch,
                toolkit_partition_mismatch=tool_parts,gear_partition_mismatch=gear_parts,
                gear_clock_reference='single-master-tick' if fine else 'whole/irregular',
                gear_callback_dependence_expected=fine))
        report['result']='pass' if all(not c['mismatch'] and not c['toolkit_partition_mismatch'] and
            (bool(c['gear_partition_mismatch']) if c['gear_callback_dependence_expected'] else not c['gear_partition_mismatch'])
            for c in report['comparisons']) else 'fail'
        report['scope']='Original Audio::Clock rational sampling, PSG /6 remainder, actual decoder-to-filter PCM from authored RAM and timestamped writes. PCM equality is measured after independently applied integer /3 mixer headroom; it does not establish exact pre-mix source S16 equality. Decoder state is compared separately. Core wall time is not advanced; fader disabled, no DMA or read/write slot traffic. Stopped callback-quantized phase retained diagnostically but not claimed equal.'
    except Exception as error:
        report.update(result='fail',error=str(error));raise
    finally:
        filters.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands')},indent=2))
    if report['result']!='pass':
        raise ValueError('Timed independent source comparison failed')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--probe',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--compiler',default='g++')
    p.add_argument('--library',type=Path,action='append',default=[])
    try:
        run(p.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as e:
        print(e,file=sys.stderr);raise SystemExit(1)
