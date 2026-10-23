"""Authored sprite-event fixtures checked against a separate unchanged Gear core.

Only synthetic VRAM and SAT memory are seeded through public debug pointers.
Registers, scheduler, sprite fetches, status latches and IRQ wiring execute the
original reference implementation. No emulator implementation is copied into
the toolkit. Exact timestamps qualify this selected emulator timing profile,
not physical VDC timing or CPU access-cycle alignment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import filtered_audio_reference as reference
sha=reference.sha
FIELDS=('time','status','irq','after_status','after_irq')


def plans():
    cases=[]
    def add(name,count=2,flags=0,cr=0x43,mode=0,x=32,pattern=0,plane=0,value=65535,control=0,overrides=()):
        hsr,hdr={0:(0x0202,0x041F),1:(0x0303,0x042B),2:(0x0B01,0x073F)}[min(control&3,2)]
        ops=[('r',),('c',0,control),('w',0,5,cr),('w',0,9,mode),
             ('w',0,10,hsr),('w',0,11,hdr),('w',0,12,0x0F02),('w',0,14,4)]
        # Default untouched SAT entries have Y=-64 and are inactive. The live
        # sprites cover authored Y=0..15, with authored pattern memory.
        for i in range(count):
            ops.extend([('t',i*4,64),('t',i*4+1,x),('t',i*4+2,pattern),('t',i*4+3,flags)])
        for address in range(1024):
            word=value if (address%64)//16==plane else 0
            if word:ops.append(('v',address,word))
        ops.extend(overrides)
        # Two complete frames latch MWR/CR normally. Coarse earlier/later
        # lines cover visible-line gating, and a complete active scanline is
        # observed one master tick at a time to qualify exact event edges.
        frame=1365*(263 if control&4 else 262)*2
        for line in range(21):ops.append(('d',frame+line*1365))
        for at in range(frame+20*1365+1,frame+21*1365):ops.append(('d',at))
        for line in range(21,65):ops.append(('d',frame+line*1365))
        cases.append(dict(id=name,operations=ops))
    for count in (0,1,2,16,17,64):add(f'narrow-count-{count}',count=count)
    for count in (7,8,9):add(f'wide-count-{count}',count=count,flags=0x100)
    for cr in (0,1,2,3,0x40,0x41,0x42,0x43,0x80,0x83,0xC3):add(f'enable-{cr:02x}',count=17,cr=cr)
    for x in (0,16,17,31,32,287,288,1023):add(f'clipping-x-{x}',x=x)
    for flags in (0x800,0x8000,0x8800,0x100,0x900,0x1000,0x3000):
        add(f'flags-{flags:04x}',value=0x8000,overrides=[('t',7,flags)])
    for mode in (0,4,8,12):
        for pattern in (0,1):
            for plane in (0,2,3):add(f'mode-{mode}-pattern-{pattern}-plane-{plane}',mode=mode,pattern=pattern,plane=plane)
    add('transparent-overlap',value=0)
    add('sprite-zero-inactive',overrides=[('t',0,0),('t',8,64),('t',9,32)])
    add('sprite-zero-pattern-transparent',overrides=[('t',2,32)])
    add('priority-does-not-mask-collision',flags=0x80,cr=0xC3)
    add('partial-wide-after-15-cells',count=16,overrides=[('t',63,0x100)])
    add('offscreen-sprites-still-consume-budget',count=17,x=0)
    add('transparent-sprites-still-consume-budget',count=17,value=0)
    for flags in (0,0x8000):
        rows=[('v',row,0 if row else 0x8000) for row in range(16)]
        add(f'vertical-row-flip-{flags}',value=0x8000,overrides=[('t',7,flags),*rows])
    add('wide-pattern-lowbit-alignment',flags=0x100,pattern=2,
        overrides=[('t',2,0),*[('v',64+row,0) for row in range(16)]])
    add('behind-opaque-background-collision',pattern=512,flags=0,cr=0xC3,
        overrides=[*[('v',address,512) for address in range(1024)],
                   *[('v',0x2000+row,65535) for row in range(8)],
                   *[('v',0x4000+row,65535) for row in range(16)]])
    add('reset-display-geometry',count=17,overrides=[('w',0,10,0),('w',0,11,31),('w',0,12,0),('w',0,14,0)])
    for control in (1,2,4):add(f'vce-control-{control}',control=control)
    # Sticky state and enable changes after the event cannot fabricate an
    # event, while a later genuine line can. Keep every edge observable.
    base=1365*262*2+20*1365
    for name,initial,changes in (
        ('sticky-until-read',0x43,[]),
        ('enable-after-event',0x40,[('w',base+500,5,0x43)]),
        ('disable-after-event',0x43,[('w',base+500,5,0x40)]),
    ):
        add(name,count=17,cr=initial)
        ops=cases[-1]['operations'];ops[:]=[op for op in ops if op[0] not in ('s','d')]
        ops.append(('d',base-1365))
        for at in range(base,base+2731):
            ops.extend(change for change in changes if change[1]==at)
            ops.append(('d' if at in (base+1000,base+2000,base+2730) else 's',at))
    for memory in ('sat','vram'):
        for tick in (1000,1200):
            add(f'{memory}-mutation-{tick}',count=2)
            ops=cases[-1]['operations'];ops[:]=[op for op in ops if op[0] not in ('s','d')]
            ops.append(('d',base+tick))
            if memory=='sat':ops.extend([('t',0,0),('t',4,0)])
            else:ops.extend(('v',address,0) for address in range(1024))
            ops.extend(('d',at) for at in range(base+tick+1,base+3*1365))
    return cases


def serialize(cases):
    lines=[];spans=[];count=0
    for case in cases:
        before=count
        for op in case['operations']:
            lines.append(' '.join(map(str,op)));count+=op[0] in ('s','d')
        spans.append(dict(id=case['id'],start=before,checkpoints=count-before))
    return '\n'.join(lines)+'\n',spans


def compare(actual,expected,spans):
    count=sum(row['checkpoints'] for row in spans)
    if not isinstance(actual,list) or not isinstance(expected,list) or len(actual)!=count or len(expected)!=count:
        raise ValueError('Sprite checkpoint count changed')
    mismatches=[]
    for i,(a,b) in enumerate(zip(actual,expected)):
        for row in (a,b):
            if not isinstance(row,dict) or set(row)!=set(FIELDS) or any(type(row[f]) is not int for f in ('time','status','after_status')) or any(type(row[f]) is not bool for f in ('irq','after_irq')):
                raise ValueError('Malformed sprite checkpoint')
            if row['time']<0 or any(not 0<=row[f]<=63 for f in ('status','after_status')) or any(row[f] not in (0,1) for f in ('irq','after_irq')):
                raise ValueError('Invalid sprite checkpoint value')
        if a!=b:
            span=next(s for s in spans if s['start']<=i<s['start']+s['checkpoints'])
            mismatches.append(dict(case=span['id'],checkpoint=i-span['start'],actual=a,expected=b))
            if len(mismatches)==20:break
    return mismatches


def run(args):
    checkout,out=args.gear_source.resolve(),args.out.resolve()
    found=shutil.which(str(args.compiler))
    if not found or out.exists():raise ValueError('Require compiler and new output directory')
    compiler=Path(found).resolve();sources=reference.source_binding(checkout)
    cpp,c=reference.compile_sources(checkout,sources)
    wrapper=ROOT/'tests/geargrafx_sprite_probe.cpp';cpp.append(wrapper)
    libraries=[p.resolve() for p in args.library]
    if not libraries or any(not p.is_file() for p in libraries):raise ValueError('Require explicit dependency static libraries')
    authored=[Path(__file__).resolve(),wrapper,ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py']
    probe=args.probe.resolve() if args.probe else None
    if probe:
        if not probe.is_file():raise ValueError('Toolkit probe does not exist')
        authored.extend([ROOT/'tests/sprite_oracle_probe.cpp',*list((ROOT/'runtime/src').glob('*.cpp')),*list((ROOT/'runtime/include/pce').glob('*.hpp'))])
    bindings=dict(reference_sources={str(checkout/n):v for n,v in sources.items()},
                  authored_sources={str(p):sha(p) for p in authored},external_libraries={str(p):sha(p) for p in libraries},
                  tools={str(compiler):sha(compiler),**({str(probe):sha(probe)} if probe else {})})
    report=dict(schema=1,result='incomplete',oracle_commit=reference.COMMIT,bindings=bindings,commands=[],comparisons=[],
                scope='Original Gear core scheduler and VDC fetch/render events; synthetic public VRAM/SAT seeds; no CPU execution or hardware timing claim',
                not_checked=['CPU access-cycle alignment','physical VDC timing','retail sprite parity','SuperGrafx dual-VDC priority'])
    out.mkdir(parents=True);objects=out/'objects';objects.mkdir()
    archive=out/'authored';archive.mkdir();relocations={}
    for path in authored:
        saved=archive/path.relative_to(ROOT);saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,saved)
        if sha(saved)!=bindings['authored_sources'][str(path)]:raise ValueError('Authored input changed during archive')
        relocations[str(path)]=dict(path=str(saved),sha256=sha(saved))
    report['source_epoch_mappings']=relocations
    oracle=out/('gear-sprite.exe' if os.name=='nt' else 'gear-sprite')
    deps=checkout/'platforms/shared/dependencies'
    common=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):common+=['-I',str(include)]
    commands=[]
    for i,path in enumerate(cpp+c):
        target=objects/(f'{i:02}-'+path.stem+'.o')
        command=[str(compiler),*common,'-x','c++' if path.suffix=='.cpp' else 'c',*(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),'-c',str(path),'-o',str(target)]
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
        bindings['oracle_binary']={str(oracle):sha(oracle)};bindings['compiled_objects']={str(p):sha(p) for _,p in commands}
        text,spans=serialize(plans());plan=out/'sprite.plan';plan.write_text(text,encoding='ascii')
        spanpath=out/'cases.json';spanpath.write_text(json.dumps(spans,indent=2)+'\n',encoding='ascii')
        bindings['authored_plans']={str(p):sha(p) for p in (plan,spanpath)}
        outputs={};jobs=[('gear',[str(oracle),str(plan)])]
        if probe:jobs.extend([('tool-on',[str(probe),str(plan),'--video']),('tool-off',[str(probe),str(plan)])])
        for label,command in jobs:
            report['commands'].append(command);completed=subprocess.run(command,capture_output=True,text=True,timeout=180)
            (out/(label+'.stderr')).write_text(completed.stderr,encoding='utf-8');completed.check_returncode()
            path=out/(label+'.json');path.write_text(completed.stdout,encoding='ascii')
            bindings.setdefault('raw_outputs',{})[str(path)]=sha(path);outputs[label]=json.loads(completed.stdout)
        command=[str(oracle),'--memory'];report['commands'].append(command)
        completed=subprocess.run(command,capture_output=True,text=True,timeout=30)
        (out/'memory.stderr').write_text(completed.stderr,encoding='utf-8');completed.check_returncode()
        path=out/'memory.json';path.write_text(completed.stdout,encoding='ascii');bindings['raw_outputs'][str(path)]=sha(path)
        memory=json.loads(completed.stdout)
        if memory!={'data_checks':131072,'execution':[dict(bank=bank,pc=16389,a=165,stored=165) for bank in range(248,252)]}:
            raise ValueError('Independent standard WRAM alias expectation failed')
        report['wram_reference']=dict(data_checks=131072,instruction_aliases=4,
            scope='Public memory writes/readbacks for all 8192 offsets and four standard F8-FB aliases; two actual authored CPU instructions fetched through each alias, no toolkit comparison')
        for label in ('tool-on','tool-off'):
            if label in outputs:report['comparisons'].append(dict(source=label,cases=len(spans),checkpoints=len(outputs[label]),mismatches=compare(outputs[label],outputs['gear'],spans)))
        report['result']=('pass' if all(not c['mismatches'] for c in report['comparisons']) else 'fail') if probe else 'reference-only-uncompared'
    except Exception as error:
        report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands','source_epoch_mappings')},indent=2))
    if report['result'] not in ('pass','reference-only-uncompared'):raise ValueError('Independent sprite comparison failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--probe',type=Path)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='g++')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
