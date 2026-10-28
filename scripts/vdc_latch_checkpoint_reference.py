"""Original Gear CR/MWR/burst latch clocks and fresh-process checkpoints.

The shared authored initial register/VRAM fixture is host configured. Original
positive device clocks generate every compared phase and queue endpoint; this
is explicitly not a guest opcode/native-retirement or electrical-bus proof.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts import mapper_reference as infrastructure
from scripts import filtered_audio_reference as reference
from scripts import hucard_reference as common

LINE=1365
FRAME=262*LINE
OFFSETS=(0,3,6,9,12,15,18,21,24,27,30,48,96,192,1365,2730,4095,FRAME,FRAME+24000)
HEX=re.compile('[0-9a-f]{64}').fullmatch

def require(ok,why):
    if not ok:raise ValueError(why)

def sha(path):
    with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def cases():
    result=[]
    for edge,latch in [('cr-hds',2*FRAME+64*LINE+96),('mwr-vsw',2*FRAME+258*LINE+1092),
                       ('mwr-vsync',2*FRAME+259*LINE),('burst-frame',3*FRAME)]:
        for delta,position in [(-3,'before'),(0,'at'),(3,'after')]:
            for queue,name in [(1,'read'),(2,'write'),(3,'both')]:
                result.append(dict(id=edge+'-'+position+'-'+name,edge=edge,delta=delta,
                                   queue=queue,latch=latch,write=latch+delta))
    return result

def expected(case,row,offset,original_gear=False):
    require(type(row)is list and len(row)==38 and all(type(n)is int and 0<=n<2**64 for n in row),'Strict typed complete latch/index row required')
    ticks=case['write']+offset
    require(row[:4]==[ticks,ticks%LINE,(ticks//LINE)%262,(ticks//LINE)%262],'Independent exact clock/line phase differs')
    edge,delta,queue,latch=map(case.get,('edge','delta','queue','latch'))
    mwr=edge.startswith('mwr-')
    require(row[6]==(128 if mwr or edge=='burst-frame' else 192) and row[7]==(17 if mwr else 0),'Independent CR/MWR register literals differ')
    h=ticks%LINE;line=(ticks//LINE)%262
    horizontal=3 if h<96 else 0 if h<192 else 1 if h<1152 else 2
    vertical=0 if line<16 or line==16 and h<1092 or line==261 and h>=1092 else 1 if line<256 or line==256 and h<1092 else 2 if line<258 or line==258 and h<1092 else 3
    require(row[4:6]==[horizontal,vertical],'Independent horizontal/vertical phase differs')
    index=1 if edge!='burst-frame' or offset>FRAME or delta<0 and offset==FRAME else 256 if original_gear else 0
    require(row[22:]==[index]*16,'Independent rendered/stale index literals differ')
    if offset==0:
        require(row[8]==(0 if edge=='burst-frame' else 128) and row[9]==0,'Write changed an already-held latch immediately')
        require(row[11:19]==[int(bool(queue&1)),int(bool(queue&2)),24 if queue&1 else 21,0,0x1900,0x1800,0x1234,0],'Independent actual queued port request differs')
    if edge=='cr-hds' and latch<=ticks<latch+LINE:
        require(row[8]==(192 if delta<0 else 128),'CR HDS before/at/after latch differs')
    if edge=='mwr-vsw' and latch<=ticks<2*FRAME+259*LINE:
        require(row[9]==(17 if delta<0 else 0),'Natural VSW MWR before/at/after latch differs')
    if edge=='mwr-vsync' and latch<=ticks<latch+FRAME-273:
        require(row[9]==(17 if delta<0 else 0),'Forced VSync MWR before/at/after latch differs')
    if edge=='burst-frame' and latch<=ticks<latch+FRAME:
        require(row[10]==(0 if delta<0 else 1),'Frame-only burst admission differs')
    if offset>=4095:
        require(row[11:13]==[0,0] and row[15:19]==[0x1901 if queue&1 else 0x1900,
            0x1801 if queue&2 else 0x1800,0x5678 if queue&1 else 0x1234,0xABCD if queue&2 else 0],
            'Independent completed queue addresses/data differ')

def qualify(case,gear,created,resumed,payload_digest,final_digest):
    require(type(case)is dict and set(case)=={'id','edge','delta','queue','latch','write'},'Strict canonical latch case fields required')
    require(type(case['id'])is str and type(case['edge'])is str and
            all(type(case[key])is int for key in ('delta','queue','latch','write')),'Canonical case types must be exact, without boolean integers')
    canonical={item['id']:item for item in cases()}.get(case['id'])
    require(canonical is not None and case==canonical,'Latch case differs from canonical authored schedule')
    for report,kind in [(gear,'gear'),(created,'tool'),(resumed,'tool')]:
        fields={'case','scope','native','interpreted','rows'}
        if kind=='tool':fields|={'checkpoint_sha256','final_payload_sha256'}
        require(type(report)is dict and set(report)==fields,'Strict direct-device report fields required')
        require(report['case']==case['id'] and type(report['scope'])is str and 'no opcode retirements' in report['scope'],
                'Case or direct-device scope differs')
        require(type(report['native'])is int and type(report['interpreted'])is int and report['native']==report['interpreted']==0,
                'Direct hardware clocks cannot be counted as retired opcodes')
        require(type(report['rows'])is list and len(report['rows'])==len(OFFSETS),'Exact observation extent required')
        for offset,row in zip(OFFSETS,report['rows']):expected(case,row,offset,kind=='gear')
        if kind=='tool':
            require(type(report['checkpoint_sha256'])is str and HEX(report['checkpoint_sha256']) and report['checkpoint_sha256']==payload_digest,'Actual saved payload digest differs')
            require(type(report['final_payload_sha256'])is str and HEX(report['final_payload_sha256']) and report['final_payload_sha256']==final_digest,'Actual final payload digest differs')
    require(created==resumed,'Fresh-process checkpoint and uninterrupted suffix differ')
    differences=[]
    for ordinal,(old,new)in enumerate(zip(gear['rows'],created['rows'])):
        require(old[:22]==new[:22],'Actual original Gear latch/queue fields differ')
        if old[22:]!=new[22:]:
            # Complete raw records remain intact. The independently checked
            # constants above are allowed only in these unused burst histories.
            require(case['edge']=='burst-frame','Ordinary active indices differ')
            differences.append(dict(row=ordinal,gear=old[22:],tool=new[22:],reason='unused pre-refresh burst line history'))
    return dict(case=case['id'],rows=len(OFFSETS),checked_scalars=3*len(OFFSETS)*38,native=0,interpreted=0,declared_index_differences=differences)

def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source)
    cpp.append(ROOT/'tests/geargrafx_vdc_latch_checkpoint_probe.cpp')
    deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(path)]
    folder=out/'gear-objects';folder.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=folder/(str(index)+'-'+path.stem+'.o')
        command=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',
                 *(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        report['commands'].append(command);jobs.append((command,obj))
    def compile_one(job):
        command,obj=job;done=subprocess.run(command,capture_output=True,timeout=180)
        for suffix,data in [('stdout',done.stdout),('stderr',done.stderr)]:
            log=obj.with_suffix('.'+suffix);log.write_bytes(data);bindings.setdefault('raw_outputs',{})[str(log)]=sha(log)
        done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(compile_one,jobs))
    libraries=[p.resolve(strict=True)for p in args.library]
    require(libraries and all(p.is_file()for p in libraries),'Supply existing explicit Gear dependency libraries')
    bindings['external_libraries']={str(p):sha(p)for p in libraries}
    binary=out/('original-gear-latches.exe'if os.name=='nt'else'original-gear-latches')
    common.evidence([str(compiler),*[str(o)for _,o in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(o):sha(o)for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    return binary

def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();probe=args.probe.resolve()
    compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    require(not out.exists() and out.is_relative_to(ROOT/'.local') and probe.is_file() and compiler.is_file(),'New private output and existing probe/compiler required')
    sys.path.insert(0,str(tool));from pcerecomp import project
    require(Path(project.__file__).resolve()==tool/'pcerecomp/project.py','Selected toolkit import required')
    paths=[Path(__file__),probe,*[ROOT/'tests'/n for n in ('vdc_latch_checkpoint_tests.cpp','vdc_latch_checkpoint_support.hpp','geargrafx_vdc_latch_checkpoint_probe.cpp','irq_trace_support.hpp','reference_trace_support.hpp')],
           *[ROOT/'scripts'/n for n in ('mapper_reference.py','filtered_audio_reference.py','hucard_reference.py','psg_reference.py')],tool/'CMakeLists.txt']
    for folder in ('runtime','pcerecomp','cmake'):
        paths += [p for p in (tool/folder).rglob('*')if p.is_file() and p.suffix in ('.cpp','.hpp','.h','.py','.cmake') and '__pycache__'not in p.parts]
    bindings={'inputs':{str(p):sha(p)for p in paths},'tools':{str(compiler):sha(compiler)}}
    report=dict(schema=1,result='incomplete',tool=project.source_identity(tool),oracle_commit=reference.COMMIT,commands=[],bindings=bindings,cases=[],
        scope='Host-configured authored initial register/VRAM fixture; positive original device clocks, queued ports, CR/MWR/burst before/at/after edges. Fresh-process payload continuations. Zero native/interpreted retirements; not electrical bus or complete rendered-frame parity.')
    out.mkdir(parents=True)
    try:
        gear=build_gear(args,out,report,bindings,compiler)
        for case in cases():
            folder=out/case['id'];folder.mkdir();payload=folder/'saved.pcec';values={}
            original=common.evidence([str(gear),case['id']],'gear',folder,report,bindings);values['gear']=json.loads(original.stdout)
            for mode in ('create','resume'):
                final=folder/(mode+'-final.pcec')
                actual=common.evidence([str(probe),case['id'],mode,str(payload),'json',str(final)],mode,folder,report,bindings)
                values[mode]=json.loads(actual.stdout);bindings.setdefault('payloads',{})[str(final)]=sha(final)
            require((folder/'create-final.pcec').read_bytes()==(folder/'resume-final.pcec').read_bytes(),'Actual full final payload bytes differ')
            bindings.setdefault('payloads',{})[str(payload)]=sha(payload)
            result=qualify(case,values['gear'],values['create'],values['resume'],sha(payload),sha(folder/'create-final.pcec'))
            admission=dict(case=case,reports=values,payload_digest=sha(payload),final_digest=sha(folder/'create-final.pcec'))
            path=folder/'admission.json';path.write_text(json.dumps(admission,indent=2)+'\n',encoding='utf8');bindings.setdefault('admissions',{})[str(path)]=sha(path)
            report['cases'].append(result)
        require(project.source_identity(tool)==report['tool'],'In-flight toolkit source changed');report['result']='pass'
    except BaseException as error:report['error']=repr(error);report['result']='fail';raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    require(report['result']=='pass','Evidence preservation failed')
    print(json.dumps(dict(result='pass',cases=len(report['cases']),rows_per_engine=len(cases())*len(OFFSETS),checked_scalars=sum(c['checked_scalars']for c in report['cases']),native=0,interpreted=0),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--library',type=Path,action='append',default=[])
    parser.add_argument('--out',type=Path,required=True)
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
