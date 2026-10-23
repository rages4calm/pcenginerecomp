"""Compare authored BRK/RTI CPU fixtures against unchanged, separate Geargrafx.

The reference uses normal (non-GG_TESTING) CPU execution. Only initial public
CPU registers, MPRs and authored RAM are initialized; no output state is injected.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import filtered_audio_reference as reference

FIELDS={'case','step','pc','a','x','y','p','sp','ticks','mpr','stack'}

def plans():
    rows=[]
    for flags in range(256):
        for sp in (0,1,254,255):
            for speed in (3,12):rows.append((0x2800,flags,sp,speed,0,0,2))
    for pc in (0x3FFF,0xFFFF,0x2100):
        for flags in (0,4,8,0x20,0x28,0x55,0xAA,0xFF):
            for sp in (0,1,254,255):
                for speed in (3,12):rows.append((pc,flags,sp,speed,0,0,2))
    for flags in (0,4,8,0x20,0xFF):
        for requests in range(8):
            for mask in (0,1,2,4,7):
                for sp in (0,255):
                    for speed in (3,12):rows.append((0x2800,flags,sp,speed,requests,mask,1))
    return rows

def serialize(rows):return ''.join(' '.join(map(str,row))+'\n' for row in rows)

def compare(actual,expected,rows):
    positions=[(i,n) for i,row in enumerate(rows) for n in range(1,row[-1]+1)]
    for records in (actual,expected):
        if not isinstance(records,list) or len(records)!=len(positions):raise ValueError('BRK checkpoint count changed')
        for record,(case,step) in zip(records,positions):
            if not isinstance(record,dict) or set(record)!=FIELDS:raise ValueError('BRK checkpoint fields changed')
            for field in FIELDS-{'mpr','stack'}:
                if type(record[field]) is not int or record[field]<0:raise ValueError('BRK fields require nonnegative integers')
            if (record['case'],record['step'])!=(case,step):raise ValueError('BRK checkpoint order changed')
            if any(record[f]>255 for f in ('a','x','y','p','sp')) or record['pc']>65535:
                raise ValueError('BRK register exceeds width')
            if not isinstance(record['mpr'],list) or len(record['mpr'])!=8 or any(type(v)is not int or not 0<=v<=255 for v in record['mpr']):
                raise ValueError('BRK MPR shape changed')
            if not isinstance(record['stack'],str) or re.fullmatch('[0-9a-f]{512}',record['stack']) is None:
                raise ValueError('BRK stack page shape changed')
    for i,(a,b) in enumerate(zip(actual,expected)):
        for field in sorted(FIELDS):
            if a[field]!=b[field]:return dict(checkpoint=i,case=a['case'],step=a['step'],input=list(rows[a['case']]),
                                             field=field,actual=a[field],expected=b[field])
    return None

def run(args):
    checkout,out,probe=args.gear_source.resolve(),args.out.resolve(),args.probe.resolve()
    found=shutil.which(str(args.compiler))
    if not found or not probe.is_file() or out.exists():raise ValueError('Require compiler, built BRK probe and new output directory')
    compiler=Path(found).resolve();sources=reference.source_binding(checkout)
    cpp,c=reference.compile_sources(checkout,sources)
    wrapper=ROOT/'tests/geargrafx_brk_probe.cpp';cpp.append(wrapper)
    libraries=[p.resolve() for p in args.library]
    if not libraries or any(not p.is_file() for p in libraries):raise ValueError('Require explicit libchdr dependency libraries')
    authored=[Path(__file__).resolve(),wrapper,ROOT/'tests/brk_oracle_probe.cpp',ROOT/'tests/generate_brk_fixture.py',
              ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py']
    authored+=list((ROOT/'runtime/src').glob('*.cpp'))+list((ROOT/'runtime/include/pce').glob('*.hpp'))
    authored+=list((ROOT/'pcerecomp').glob('*.py'))
    bindings=dict(reference_sources={str(checkout/n):v for n,v in sources.items()},
        authored_sources={str(p):reference.sha(p) for p in authored},
        external_libraries={str(p):reference.sha(p) for p in libraries},
        tools={str(compiler):reference.sha(compiler),str(probe):reference.sha(probe)})
    report=dict(schema=1,result='incomplete',oracle_commit=reference.COMMIT,bindings=bindings,commands=[],comparisons=[],
        scope='Actual unchanged normal Gear RunInstruction BRK/RTI, directed authored initial registers/RAM/MPRs; both toolkit execution tiers, cumulative instruction clocks and complete 256-byte stack page.',
        not_checked=['CPU bus phases or whole-core device-clock integration','retail execution','complete 8 KiB work-RAM comparison','reserved opcode execution','hardware certification'])
    out.mkdir(parents=True);objects=out/'objects';objects.mkdir();oracle=out/'gear-brk.exe'
    deps=checkout/'platforms/shared/dependencies'
    common=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER',
            '-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):
        common+=['-I',str(include)]
    commands=[]
    for i,path in enumerate(cpp+c):
        target=objects/(f'{i:02}-'+path.stem+'.o')
        command=[str(compiler),*common,'-x','c++' if path.suffix=='.cpp' else 'c',
            *(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),'-c',str(path),'-o',str(target)]
        commands.append((command,target))
    report['commands']=[command for command,_ in commands]
    try:
        def compile_one(item):
            command,target=item;completed=subprocess.run(command,capture_output=True,text=True,timeout=180)
            target.with_suffix('.log').write_text(completed.stdout+completed.stderr,encoding='utf-8');completed.check_returncode()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile_one,commands))
        link=[str(compiler),*[str(p) for _,p in commands],*map(str,libraries),'-Wl,--gc-sections','-o',str(oracle)]
        report['commands'].append(link);completed=subprocess.run(link,capture_output=True,text=True,timeout=90)
        (out/'link.log').write_text(completed.stdout+completed.stderr,encoding='utf-8');completed.check_returncode()
        bindings['oracle_binary']={str(oracle):reference.sha(oracle)}
        bindings['compiled_objects']={str(p):reference.sha(p) for _,p in commands}
        rows=plans();plan=out/'brk.plan';plan.write_text(serialize(rows),encoding='ascii')
        bindings['authored_plans']={str(plan):reference.sha(plan)}
        outputs={}
        for label,command in [('gear',[str(oracle),str(plan)]),('native',[str(probe),str(plan),'native']),
                               ('interpreter',[str(probe),str(plan),'interpreter'])]:
            report['commands'].append(command)
            completed=subprocess.run(command,capture_output=True,text=True,timeout=120)
            (out/(label+'.stderr')).write_text(completed.stderr,encoding='utf-8');completed.check_returncode()
            path=out/(label+'.json');path.write_text(completed.stdout,encoding='ascii')
            bindings.setdefault('raw_outputs',{})[str(path)]=reference.sha(path);outputs[label]=json.loads(completed.stdout)
        for label in ('native','interpreter'):
            report['comparisons'].append(dict(source=label,cases=len(rows),checkpoints=len(outputs[label]),
                mismatch=compare(outputs[label],outputs['gear'],rows)))
        report['result']='pass' if all(c['mismatch'] is None for c in report['comparisons']) else 'fail'
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands')},indent=2))
    if report['result']!='pass':raise ValueError('Independent BRK comparison failed')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='g++')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
