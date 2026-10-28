"""Authored program/gap DD replies against separately built original Geargrafx.

Real port operations issue successful READs to establish the idle head, then
consume ten-byte DD DATA IN/status/message transactions. Toolkit port accesses
execute statically translated or interpreted opcodes. The supervisor selects
PC/A and advances declared waits; this is not a guest-only CPU timing trace.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from scripts import read_head_reference as shared
from scripts import filtered_audio_reference as reference
from scripts import hucard_reference as common
sha=reference.sha


def geometry(kind,first,audio):
    if kind not in ('plain','virtual','stored') or first not in (4,74,75) or type(audio)is not bool:
        raise ValueError('Explicit authored position geometry required')
    start=first+(0 if kind=='plain' else 2)
    return dict(kind=kind,first=first,audio=audio,start=start,leadout=start+4,
                id=kind+'-'+str(first)+('-audio'if audio else'-data'))


def bcd(value):return value//10*16+value%10
def msf(value):return [bcd(value//4500),bcd(value//75%60),bcd(value%75)]


def position(lba,layout):
    if not 0<=lba<layout['leadout']:track=-1
    elif lba<layout['first']:track=0
    elif lba>=layout['start']:track=1
    else:track=-1
    start=0 if track==0 else layout['start']
    control=0x41 if track==0 or(track==1 and not layout['audio'])else 1
    return [1,control,track+1,1,*msf(lba-start if track>=0 else 0),*msf(lba+150)]


def plans(layout,automatic):
    if type(automatic)is not int or automatic not in (0,1):raise ValueError('Explicit ACK profile required')
    addresses=[0,layout['first']-2,layout['first']-1]
    if not layout['audio']:addresses += [layout['start'],layout['leadout']-1]
    return [dict(id=layout['id']+'-read'+str(lba),operations=[('r',),
                shared.command(8,automatic,lba),('h',),shared.command(0xDD,automatic),('h',)])
            for lba in addresses]


def expected(cases,layout):
    rows=[];head=0
    for case in cases:
        for op in case['operations']:
            if op[0]=='r':head=0
            elif op[0]=='h':rows.append(dict(kind='head',values=[head]))
            elif op[0]=='c':
                _,automatic,count,*raw=op
                if count!=len(raw):raise ValueError('Authored CDB extent differs')
                if raw[0]==8:
                    lba=((raw[1]&31)<<16)|(raw[2]<<8)|raw[3]
                    if raw[4]!=1 or not(lba<layout['first'] or(not layout['audio']and layout['start']<=lba<layout['leadout'])):
                        raise ValueError('Only authored single program-sector READs are admitted')
                    payload=shared.pattern(lba);head=min(lba+1,layout['leadout']-1)
                elif raw[0]==0xDD:payload=position(head,layout)
                else:raise ValueError('Unauthored position command')
                rows.append(dict(kind='reply',automatic=automatic,cdb=raw,data=payload,status=0,message=0))
            else:raise ValueError('Unauthored position operation')
    return rows


def expected_hits(cases,rows):
    from generate_scsi_fixture import make_fixture
    _,sites=make_fixture();lookup={(opcode,address):pc for pc,opcode,address in sites};hits={}
    def add(opcode,address,count):
        if count:
            pc=lookup[opcode,address];hits[pc]=hits.get(pc,0)+count
    for case in cases:
        for op in case['operations']:
            if op[0]=='c':
                add(0x8D,0x1800,1);add(0x8D,0x1801,op[2]);add(0x8D,0x1802,2*op[2])
    for row in rows:
        if row['kind']!='reply':continue
        count=len(row['data'])
        if row['automatic']:
            add(0xAD,0x1808,count);add(0xEA,0,2*count);add(0xAD,0x1801,2);add(0x8D,0x1802,4)
        else:add(0xAD,0x1801,count+2);add(0x8D,0x1802,2*(count+2))
    return hits


def fixtures(out):
    rom=out/'authored.pce';image=bytearray([0xEA]*262144);image[8190:8192]=bytes((0,0xE0));rom.write_bytes(image)
    layouts=[]
    for kind in ('plain','virtual','stored'):
        for first in (4,74,75):
            for audio in (False,True):
                layout=geometry(kind,first,audio);folder=out/layout['id'];folder.mkdir()
                (folder/'first.bin').write_bytes(b''.join(bytes(shared.pattern(lba))for lba in range(first)))
                width=2352 if audio else 2048
                tail=b''.join(bytes(width)if audio else bytes(shared.pattern(lba))for lba in range(layout['start'],layout['leadout']))
                (folder/'tail.bin').write_bytes((bytes(2*width)if kind=='stored'else b'')+tail)
                cue=folder/'disc.cue'
                cue.write_text('FILE "first.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n'+
                    'FILE "tail.bin" BINARY\n TRACK 02 '+('AUDIO'if audio else'MODE1/2048')+'\n'+
                    (' PREGAP 00:00:02\n'if kind=='virtual'else' INDEX 00 00:00:00\n'if kind=='stored'else'')+
                    ' INDEX 01 '+('00:00:02'if kind=='stored'else'00:00:00')+'\n',encoding='ascii')
                layouts.append((layout,cue))
    return rom,layouts


def run(args):
    from pcerecomp.project import source_identity
    tool,out=args.tool_source.resolve(),args.out.resolve()
    compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():raise ValueError('Require compiler and fresh private output')
    sources=[Path(__file__),ROOT/'scripts/read_head_reference.py',ROOT/'tests/read_head_probe.cpp',
        ROOT/'tests/geargrafx_read_head_probe.cpp',ROOT/'tests/geargrafx_sense_probe.cpp',
        ROOT/'tests/sense_probe_support.hpp',ROOT/'tests/reset_probe_support.hpp',ROOT/'tests/generate_scsi_fixture.py',
        ROOT/'scripts/cue_reference.py',ROOT/'scripts/mapper_reference.py',ROOT/'scripts/filtered_audio_reference.py',
        ROOT/'scripts/hucard_reference.py',ROOT/'scripts/psg_reference.py',tool/'CMakeLists.txt',
        *sorted((tool/'pcerecomp').glob('*.py')),*sorted((tool/'runtime').rglob('*.cpp')),
        *sorted((tool/'runtime').rglob('*.hpp')),*sorted((tool/'cmake').glob('*.cmake'))]
    identity=source_identity(tool)
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(path):sha(path)for path in sources})
    report=dict(schema=1,result='incomplete',tool=identity,oracle_commit=reference.COMMIT,commands=[],bindings=bindings,
        scope=__doc__,not_checked=['Cross-core CPU retirement/timing','Electrical or physical drive timing',
            'Captured raw subchannels or index00 response emulation','Direct original Gear POSTGAP semantics',
            'Actual compressed CHD decoding','Retail software'])
    out.mkdir(parents=True)
    try:
        from generate_scsi_fixture import generate
        fixture=out/'fixture';generate(fixture);rom,layouts=fixtures(out)
        bindings['fixtures']={str(path):sha(path)for path in out.rglob('*')if path.is_file()}
        gear=shared.build_gear(args,out,report,bindings,compiler)
        binary=shared.build_tool(args,tool,out,report,bindings,compiler,fixture)
        comparisons=[];native_work=interpreted_work=original_cases=0
        for layout,cue in layouts:
            for automatic in (0,1):
                cases=plans(layout,automatic);wanted=expected(cases,layout);hits=expected_hits(cases,wanted)
                original_cases+=len(cases)
                plan=out/(layout['id']+'-ack'+str(automatic)+'.plan');plan.write_text(shared.serialize(cases),encoding='ascii')
                bindings['fixtures'][str(plan)]=sha(plan)
                label=plan.stem+'-gear';execution=out/(label+'-execution.json')
                actual=common.evidence([str(gear),str(plan),str(rom),str(cue),'gear','3','-',str(execution)],label,out,report,bindings,180)
                original=json.loads(actual.stdout);checks=shared.validate_rows(original,wanted)
                bindings['raw_outputs'][str(execution)]=sha(execution)
                for speed in (3,12):
                    captures={}
                    for tier in ('native','interpreter'):
                        label=plan.stem+'-s'+str(speed)+'-'+tier
                        capture=out/(label+'-capture.json');execution=out/(label+'-execution.json')
                        actual=common.evidence([str(binary),str(plan),str(rom),str(cue),tier,str(speed),str(capture),str(execution)],label,out,report,bindings,180)
                        rows=json.loads(actual.stdout);shared.validate_rows(rows,wanted)
                        if rows!=original:raise ValueError('Original Gear program/gap DD response differs')
                        work=json.loads(execution.read_bytes());captured=json.loads(capture.read_bytes())
                        shared.validate_execution(work,cases,len(rows),speed,tier=='native',hits)
                        retired,sites=shared.validate_capture(captured,work,tier=='native',hits)
                        captures[tier]=captured
                        if tier=='native':native_work+=retired
                        else:interpreted_work+=retired
                        bindings['raw_outputs'].update({str(path):sha(path)for path in(capture,execution)})
                        comparisons.append(dict(layout=layout,automatic=automatic,divisor=speed,tier=tier,
                            cases=len(cases),literal_checks=checks,retired_instructions=retired,source_identities=sites))
                    def normalized(capture):return [dict(pc=r['pc'],mpr=r['mpr'],physical=r['physical'],data=r['data'],hits=r['native_hits']+r['interpreted_hits'])for r in capture['observations']]
                    if normalized(captures['native'])!=normalized(captures['interpreter']):raise ValueError('Full paired source identities/hits differ')
        if source_identity(tool)!=identity:raise ValueError('Tool source changed during qualification')
        report.update(result='pass',layouts=len(layouts),original_cases=original_cases,
            native_cases=original_cases*2,interpreter_cases=original_cases*2,
            comparisons=comparisons,native_steps=native_work,interpreter_steps=interpreted_work,native_fallback=0,
            actual_pure_guards=4*len(layouts)*2*2,
            source_scope='Exact PC/full8MPR/physical/source-byte identities and independently expected per-source retirement counts; host-supervised real port opcodes')
    except Exception as error:
        report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if report['result']!='pass':raise ValueError('Reference source or input preservation failed')
    print(json.dumps({key:value for key,value in report.items()if key not in('bindings','commands','comparisons')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:
        print(error,file=sys.stderr);raise SystemExit(1)
