"""Independent CDDA latch check using separately compiled, unchanged Geargrafx.

Only authored synthetic CUE/BIN media is generated. The reference wrapper's
member-pointer bridge invokes Geargrafx's real core scheduler one master tick
at a time; no latch, DAC, predictor, fader, clock or save state is injected.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import filtered_audio_reference as filters

sha = filters.sha


def plans():
    cases = []
    def add(name, operations):
        cases.append(dict(id=name, operations=[('r',), *operations]))
    add('admission-boundaries-and-ignored-high-write', [
        ('s',0),('w',0,5,255),('s',0),('w',699,5,0),('s',699),
        ('w',700,5,17),('s',700),('s',701),('w',1399,5,19),('s',1399),
        ('w',1400,6,255),('w',1400,7,128),('s',1400),('w',1400,5,0),('s',1400),
        ('w',2099,5,255),('s',2099),('w',2100,5,85),('s',2100)])
    ops=[]
    for value in range(256):
        ops.extend([('w',700*(value+1),5,value),('s',700*(value+1))])
    add('all-write-values-ignore-payload',ops)
    ops=[('a',0,'play'),('s',3221589),('s',3221590)]
    # Read/write edges around actual global sample boundaries, signed source
    # extrema, right-first selection and no read-triggered capture.
    for at in range(3222100,3236101,700):
        ops.extend([('w',at,5,at&255),('s',at),('s',at+1),('w',at+699,5,0),('s',at+699)])
    add('playing-signed-stereo-and-gate',ops)
    add('first-active-edge-right-and-stable-signed-halves',[
        ('a',0,'play'),('s',3221590),('s',3221591),('w',3221591,5,0),('s',3221591),
        ('w',3221592,6,255),('s',3221592),('s',3222077),('s',3222078),
        ('w',3222290,5,0),('s',3222290),('w',3222291,5,255),('s',3222291),
        ('s',3222564),('s',3222565),('w',3222991,5,1),('s',3222991)])
    add('pause-stop-held-until-next-edge',[
        ('a',0,'play'),('w',3222100,5,1),('s',3222100),
        ('a',3222101,'pause'),('s',3222101),('s',3222200),('s',3222560),
        ('w',3222800,5,2),('s',3222800),('a',3222801,'stop'),
        ('s',3222801),('w',3223500,5,3),('s',3223500)])
    add('transport-reset-keeps-latch',[
        ('a',0,'play'),('w',3222100,5,1),('s',3222100),
        ('w',3222101,4,2),('s',3222101),('s',3222560),
        ('w',3222800,5,1),('s',3222800),('w',3222801,4,0),('s',3222801)])
    add('fresh-machine-reset-clears-prior-latch',[
        ('s',0),('w',699,5,1),('s',699),('w',700,5,0),('s',700)])
    add('idle-data-silence',[
        ('a',0,'data'),('w',4000000,5,1),('s',4000000),
        ('a',4000001,'idle'),('s',4000001),('w',4000700,5,0),('s',4000700)])
    add('fader-postsource-held-and-unrelated-adpcm-target',[
        ('a',0,'play'),('s',3222100),('w',3222101,15,12),
        ('s',3222101),('w',3222800,5,0),('s',3222800),
        ('w',4222800,5,255),('s',4222800),('w',4222801,15,14),
        ('s',4222801),('w',4223500,5,0),('s',4223500),
        ('w',4223501,15,0),('s',4223501)])
    return cases


def serialize(cases):
    lines=[];spans=[];count=0
    for case in cases:
        start=count
        for op in case['operations']:
            lines.append(' '.join(map(str,op)));count += op[0]=='s'
        spans.append(dict(id=case['id'],start=start,checkpoints=count-start))
    return '\n'.join(lines)+'\n',spans


def write_fixture(directory):
    """Eight AUDIO + eight data sectors; signed samples authored algebraically."""
    pattern=(-32768,32767,-1,1,-12345,23456,0,16384)
    values=[]
    for frame in range(16*588):
        values.extend((pattern[(frame*3)%8],pattern[(frame*5+1)%8]))
    binary=directory/'authored.bin'
    binary.write_bytes(struct.pack('<'+'h'*len(values),*values))
    cue=directory/'authored.cue'
    cue.write_text('FILE "authored.bin" BINARY\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n'
                   '  TRACK 02 MODE1/2352\n    INDEX 01 00:00:08\n',encoding='ascii')
    return cue,binary


FIELDS=('time','lo','hi','channel','bram_before','bram_after','left','right')
def compare(actual,expected,spans):
    count=sum(s['checkpoints'] for s in spans)
    if len(actual)!=count or len(expected)!=count:
        raise ValueError('Latch checkpoint count changed')
    for i,(a,b) in enumerate(zip(actual,expected)):
        if set(a)!=set(FIELDS) or set(b)!=set(FIELDS):
            raise ValueError('Latch checkpoint fields changed')
        for record in (a,b):
            if any(type(record[f]) is not int for f in FIELDS):
                raise ValueError('Latch field must be integer')
            if any(not 0<=record[f]<=255 for f in ('lo','hi')) or record['channel'] not in (0,2):
                raise ValueError('Invalid port value')
            if any(record[f] not in (0,128) for f in ('bram_before','bram_after')):
                raise ValueError('Invalid BRAM status')
            if any(not -32768<=record[f]<=32767 for f in ('left','right')):
                raise ValueError('Invalid source S16')
        for field in FIELDS:
            if a[field]!=b[field]:
                span=next(s for s in spans if s['start']<=i<s['start']+s['checkpoints'])
                return dict(case=span['id'],checkpoint=i-span['start'],field=field,
                            actual=a[field],expected=b[field],time=b['time'])
    return None


def run(args):
    checkout,out,probe=args.gear_source.resolve(),args.out.resolve(),args.probe.resolve()
    found=shutil.which(str(args.compiler))
    if not found or not probe.is_file() or out.exists():
        raise ValueError('Require compiler, built latch probe and new output directory')
    compiler=Path(found).resolve();sources=filters.source_binding(checkout)
    cpp,c=filters.compile_sources(checkout,sources)
    wrapper=ROOT/'tests/geargrafx_latch_probe.cpp';cpp.append(wrapper)
    libraries=[p.resolve() for p in args.library]
    if not libraries or any(not p.is_file() for p in libraries):
        raise ValueError('Require explicit external libchdr dependency libraries')
    authored=[Path(__file__).resolve(),wrapper,ROOT/'tests/cdda_latch_probe.cpp',
              ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py']
    authored+=list((ROOT/'runtime/src').glob('*.cpp'))+list((ROOT/'runtime/include/pce').glob('*.hpp'))
    bindings=dict(reference_sources={str(checkout/n):v for n,v in sources.items()},
                  authored_sources={str(p):sha(p) for p in authored},external_libraries={str(p):sha(p) for p in libraries},
                  tools={str(compiler):sha(compiler),str(probe):sha(probe)})
    report=dict(schema=1,result='incomplete',oracle_commit=filters.COMMIT,bindings=bindings,commands=[],comparisons=[],
                clock_bridge='Authored C++ member-pointer access calls original private Core::ClockHardware<true,false,false>(1); no state injection',
                not_checked=['CPU bus-cycle scheduling','physical drive seek latency variations','retail audio parity','hardware analog output'])
    out.mkdir(parents=True);objects=out/'objects';objects.mkdir()
    oracle=out/('gear-latch.exe' if os.name=='nt' else 'gear-latch')
    deps=checkout/'platforms/shared/dependencies'
    common=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER',
            '-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):
        common+=['-I',str(include)]
    commands=[]
    for i,path in enumerate(cpp+c):
        target=objects/(f'{i:02}-'+path.stem+'.o')
        command=[str(compiler),*common,'-x','c++' if path.suffix=='.cpp' else 'c',
                 *(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),
                 '-c',str(path),'-o',str(target)]
        commands.append((command,target))
    report['commands']=[command for command,_ in commands]
    try:
        def compile_one(item):
            command,target=item;completed=subprocess.run(command,capture_output=True,text=True,timeout=180)
            target.with_suffix('.log').write_text(completed.stdout+completed.stderr,encoding='utf-8');completed.check_returncode()
        with ThreadPoolExecutor(max_workers=4) as executor:list(executor.map(compile_one,commands))
        link=[str(compiler),*[str(p) for _,p in commands],*map(str,libraries),'-Wl,--gc-sections','-o',str(oracle)]
        report['commands'].append(link);completed=subprocess.run(link,capture_output=True,text=True,timeout=90)
        (out/'link.log').write_text(completed.stdout+completed.stderr,encoding='utf-8');completed.check_returncode()
        bindings['oracle_binary']={str(oracle):sha(oracle)}
        bindings['compiled_objects']={str(p):sha(p) for _,p in commands}
        cue,binary=write_fixture(out)
        text,spans=serialize(plans());plan=out/'latch.plan';plan.write_text(text,encoding='ascii')
        spanpath=out/'cases.json';spanpath.write_text(json.dumps(spans,indent=2)+'\n',encoding='ascii')
        bindings['authored_plans']={str(p):sha(p) for p in (cue,binary,plan,spanpath)}
        outputs={}
        for label,command in [('gear',[str(oracle),str(plan),str(cue)]),
                              ('tool-on',[str(probe),str(plan),'on']),('tool-off',[str(probe),str(plan),'off'])]:
            report['commands'].append(command)
            completed=subprocess.run(command,capture_output=True,text=True,timeout=180)
            (out/(label+'.stderr')).write_text(completed.stderr,encoding='utf-8');completed.check_returncode()
            path=out/(label+'.json');path.write_text(completed.stdout,encoding='ascii')
            bindings.setdefault('raw_outputs',{})[str(path)]=sha(path);outputs[label]=json.loads(completed.stdout)
        for label in ('tool-on','tool-off'):
            report['comparisons'].append(dict(source=label,cases=len(spans),checkpoints=len(outputs[label]),
                mismatch=compare(outputs[label],outputs['gear'],spans)))
        report['result']='pass' if all(not c['mismatch'] for c in report['comparisons']) else 'fail'
        report['scope']='Actual original Gear CDROM register latch and core master clock with authored CUE audio, real source scheduler and post-fader signed S16 holds; toolkit on/off comparison. Public start/stop/pause/idle controls isolate port/source behavior from SCSI command transport.'
    except Exception as error:
        report.update(result='fail',error=str(error));raise
    finally:
        filters.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands')},indent=2))
    if report['result']!='pass':raise ValueError('Independent latch comparison failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='g++')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
