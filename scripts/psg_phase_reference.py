"""Original HuC6280 guest PSG phase at a real PCM boundary, both CPU speeds.

Host-authored identical initial device state; actual guest opcode in all three
engines. Only the first PCM boundary qualifies write phase. Later raw synthesis
samples are retained as differences, never treated as full synthesis parity.
"""
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
from pcerecomp import project

def require(ok,message):
    if not ok:raise ValueError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def parse_fixture(path):
    rows=re.findall(r'\{"([^"]+)",(\d+),(\d+),(\d+),(\d+),(\d+),\{([^}]+)\}\}',path.read_text())
    require(len(rows)==36,'Exact authored 36-case fixture required')
    return [dict(name=n,pc=int(pc),size=int(size),cycles=int(cycles),old=int(old),new=int(new),data=list(map(int,data.split(','))))for n,pc,size,cycles,old,new,data in rows]
def expected_write_values(case):
    data=case['data'];op=data[0]
    if case['size']==7:
        values=[0,0,0]if data[2]==0 else [31,1,31]if op==0xc3 else [31,31,31]
        regs={0x73:[6,7,8],0xc3:[6,5,4],0xd3:[6,6,6],0xe3:[6,7,6],0xf3:[6,7,8]}[op]
        return list(zip(regs,values))
    value=31 if op in (0x8d,0x9d,0x99,0x81,0x91,0x92,0x0c)else 1 if op in (0x8e,0x8c)else 0 if op in (0x9c,0x9e,0x1c)else {0x0e:62,0x1e:62,0x2e:63,0x3e:63,0x4e:15,0x5e:15,0x6e:143,0x7e:143,0xee:32,0xfe:32,0xce:30,0xde:30}[op]
    return [(6,value)]
def qualify(case,speed,gear,native,interpreted):
    start=488-(19 if case['size']==7 else 4)*speed
    base=dict(case=case['name'],divisor=speed,pc=case['pc'],mpr=[255,248,248,248,248,255,248,0],physical=list(range(case['pc']&8191,(case['pc']&8191)+case['size'])),bytes=case['data'],start=start,end=start+case['cycles']*speed,final_pc=case['pc']+case['size'],dda=case['new'])
    for row,extra in ((gear,{'calls','writes'}),(native,{'native','interpreted'}),(interpreted,{'native','interpreted'})):
        require(type(row)is dict and set(row)==set(base)|extra|{'pcm'},'Strict complete report fields required')
        for key,value in row.items():
            if key=='case':require(type(value)is str,'Strict case string required')
            elif key=='writes':require(type(value)is list and all(type(r)is list and len(r)==3 and all(type(x)is int and x>=0 for x in r)for r in value),'Strict actual PSG port rows required')
            elif type(base.get(key))is list or key=='pcm':require(type(value)is list and all(type(x)is int for x in value),'Strict integer arrays required')
            else:require(type(value)is int and value>=0,'Strict unsigned report integers required')
        require(all(type(row[k])is type(v)and row[k]==v for k,v in base.items()),'CPU/source identity, final device state or independently expected clocks differ: '+case['name'])
        require(type(row['pcm'])is list and len(row['pcm'])==4 and all(type(n)is int for n in row['pcm']),'Exact two stereo PCM frames required')
    for row,is_native in ((native,True),(interpreted,False)):
        require(row['native']==int(is_native)and row['interpreted']==int(not is_native),'Actual execution tiers differ')
    require(gear['calls']==(5 if case['size']==7 else 1),'Original microstep/completion extent differs')
    stride=8 if case['size']==7 and case['data'][2]==0 else 6
    writes=[[start+(14+(i+1)*stride)*speed if case['size']==7 else base['end'],reg,value]for i,(reg,value)in enumerate(expected_write_values(case))]
    require(gear['writes']==writes,'Original actual PSG trace differs from independent pending-cycle phase: '+case['name'])
    first=5285 if case['old']else -5285
    require(gear['pcm'][:2]==[first,first]and native['pcm'][:2]==[int(first/3)]*2 and interpreted['pcm'][:2]==native['pcm'][:2],'First PCM boundary observed early PSG value')
    require(native==dict(interpreted,native=1,interpreted=0),'Actual generated and interpreted observations differ')
    # Preserve whole raw observations and explicitly expose later synthesis
    # differences. Their gain/smoothing is outside this CPU-write-phase check.
    differences=[dict(sample=i,gear_raw=g,gear_divided_by_three=int(g/3),tool_mixed=t)for i,(g,t)in enumerate(zip(gear['pcm'],native['pcm']))if int(g/3)!=t]
    return dict(case=case['name'],divisor=speed,original_cpu_calls=gear['calls'],original_psg_writes=len(writes),native=1,interpreted=1,first_stereo_boundary_exact=True,later_pcm_differences=differences)

def audit_receipt(path):
    path=Path(path);report=json.loads(path.read_text());bindings=report['bindings']
    required={'inputs','tools','reference_raw_sources','reference_compile_sources','raw_outputs','external_libraries','gear_objects','gear_binary','authored_fixture','admissions'}
    require(report['result']=='pass'and set(bindings)==required,'Exact complete evidence groups required')
    inputs={Path(p).name for p in bindings['inputs']}
    require({'psg_phase_reference.py','psg_phase_oracle_probe.cpp','geargrafx_psg_phase_probe.cpp','generate_psg_phase_fixture.py','runtime.hpp','runtime.cpp','block.cpp','pcm.cpp','emitter.py','data_ops.py','project.py'}.issubset(inputs),'Exact required source keys missing')
    for group in ('reference_raw_sources','reference_compile_sources'):
        require({'huc6280.cpp','huc6280_inline.h','huc6280_opcodes_inline.h','memory_inline.h','huc6280_psg.cpp','audio.cpp','geargrafx_core.cpp'}.issubset({Path(p).name for p in bindings[group]}),'Exact original source keys missing')
    for group in required:
        require(type(bindings[group])is dict and bool(bindings[group]),'Nonempty exact binding group required')
        for name,digest in bindings[group].items():require(type(name)is str and type(digest)is str and sha(name)==digest,'Preserved file binding differs')
    headers=[Path(p)for p in bindings['authored_fixture']if Path(p).name=='psg_phase_fixture.hpp']
    require(len(headers)==1,'Exact authored source matrix required');cases=parse_fixture(headers[0]);matrix=[(c,speed)for c in cases for speed in (3,12)]
    require(len(report['cases'])==len(matrix)==len(bindings['admissions']),'Exact complete 36 by 2 matrix required')
    used=set()
    require({Path(p).name for p in bindings['authored_fixture']}=={'module.cpp','module.json','psg_phase_fixture.hpp','authored.pce'},'Exact generated source/manifest fixture keys required')
    for result,(case,speed) in zip(report['cases'],matrix):
        folder=path.parent/(case['name']+'-'+str(speed));admission=folder/'admission.json'
        require(str(admission)in bindings['admissions'],'Case admission binding missing')
        payload=json.loads(admission.read_text());require(set(payload)=={'case','speed','reports','raw_stdout'}and payload['case']==case and type(payload['speed'])is int and payload['speed']==speed,'Strict canonical case association required')
        require(set(payload['reports'])==set(payload['raw_stdout'])=={'gear','native','interpreted'},'Exact three engine observations required')
        for tier,raw in payload['raw_stdout'].items():
            raw_path=folder/(tier+'.stdout');require(raw==str(raw_path)and raw not in used and raw in bindings['raw_outputs'],'Raw stdout case association differs');used.add(raw)
            require(str(folder/(tier+'.stderr'))in bindings['raw_outputs'],'Raw stderr binding missing')
            require(json.loads(raw_path.read_text())==payload['reports'][tier],'Raw stdout differs from admitted report')
        require(result==qualify(case,speed,**payload['reports']),'Recomputed source/clock/PCM phase admission differs')
    return dict(result='pass',cases=len(matrix),native=len(matrix),interpreted=len(matrix),raw_stdout=len(used),required_groups=sorted(required))

def build_gear(args,out,report,bindings,compiler,fixture):
    checkout,sources=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,sources);cpp.append(ROOT/'tests/geargrafx_psg_phase_probe.cpp')
    deps=checkout/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (checkout/'src',fixture,deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(path)]
    folder=out/'gear-objects';folder.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=folder/(str(index)+'-'+path.stem+'.o');cmd=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)];report['commands'].append(cmd);jobs.append((cmd,obj))
    def one(job):
        cmd,obj=job;done=subprocess.run(cmd,capture_output=True,timeout=180)
        for suffix,data in [('stdout',done.stdout),('stderr',done.stderr)]:
            path=obj.with_suffix('.'+suffix);path.write_bytes(data);bindings.setdefault('raw_outputs',{})[str(path)]=sha(path)
        done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(one,jobs))
    libraries=[p.resolve(strict=True)for p in args.library];require(bool(libraries),'Explicit original dependency libraries required')
    bindings['external_libraries']={str(p):sha(p)for p in libraries}
    binary=out/('original-gear-psg-phase.exe'if os.name=='nt'else'original-gear-psg-phase')
    common.evidence([str(compiler),*[str(obj)for _,obj in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(obj):sha(obj)for _,obj in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    return binary

def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();probe=args.probe.resolve();compiler=Path(shutil.which(args.compiler)or'').resolve()
    require(not out.exists()and out.is_relative_to(ROOT/'.local')and probe.is_file()and compiler.is_file(),'Require NEW private .local output, probe and compiler')
    require(Path(project.__file__).resolve()==tool/'pcerecomp/project.py','Selected toolkit import differs')
    inputs=[Path(__file__),ROOT/'tests/geargrafx_psg_phase_probe.cpp',ROOT/'tests/psg_phase_oracle_probe.cpp',ROOT/'tests/generate_psg_phase_fixture.py',ROOT/'scripts/mapper_reference.py',ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/hucard_reference.py',ROOT/'scripts/psg_reference.py',tool/'CMakeLists.txt',probe]
    for folder in ('runtime','pcerecomp','cmake'):inputs += [p for p in (tool/folder).rglob('*')if p.is_file()and p.suffix in ('.cpp','.hpp','.py','.cmake')and'__pycache__'not in p.parts]
    bindings=dict(inputs={str(p):sha(p)for p in inputs},tools={str(compiler):sha(compiler)})
    report=dict(schema=1,result='incomplete',tool=project.source_identity(tool),oracle_commit=reference.COMMIT,commands=[],bindings=bindings,cases=[],scope='Host-authored equal initial state; one retired guest instruction per case/tier; original CPU PSG traces, first output sample boundary, exact completed clocks. Functional VDC READ_BUFFER explicitly seeded zero in both engines; not reset parity. Later synthesis values retained and excluded from phase parity.')
    out.mkdir(parents=True)
    try:
        fixture=out/'module';common.evidence([sys.executable,str(ROOT/'tests/generate_psg_phase_fixture.py'),str(fixture)],'fixture',out,report,bindings)
        cases=parse_fixture(fixture/'psg_phase_fixture.hpp');bindings['authored_fixture']={str(p):sha(p)for p in fixture.iterdir()if p.is_file()}
        rom=bytearray([0xea])*8192
        for case in cases:offset=case['pc']&8191;rom[offset:offset+case['size']]=bytes(case['data'])
        rom[-4:]=bytes([0,224,0,224]);image=out/'authored.pce';image.write_bytes(rom);bindings['authored_fixture'][str(image)]=sha(image)
        gear=build_gear(args,out,report,bindings,compiler,fixture)
        bindings['admissions']={}
        for case in cases:
            for speed in (3,12):
                folder=out/(case['name']+'-'+str(speed));folder.mkdir();values={}
                for tier,binary,extra in [('gear',gear,[str(image)]),('native',probe,['native']),('interpreted',probe,['interpreted'])]:
                    done=common.evidence([str(binary),case['name'],str(speed),*extra],tier,folder,report,bindings);values[tier]=json.loads(done.stdout)
                report['cases'].append(qualify(case,speed,values['gear'],values['native'],values['interpreted']))
                admission=folder/'admission.json';admission.write_text(json.dumps(dict(case=case,speed=speed,reports=values,raw_stdout={tier:str(folder/(tier+'.stdout'))for tier in values}),indent=2)+'\n');bindings['admissions'][str(admission)]=sha(admission)
        require(project.source_identity(tool)==report['tool'],'Toolkit source changed during phase proof');report['result']='pass'
    except BaseException as error:report['result']='fail';report['error']=repr(error);raise
    finally:reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    require(report['result']=='pass','Source/evidence preservation failed')
    audited=audit_receipt(out/'result.json');(out/'audit.json').write_text(json.dumps(audited,indent=2)+'\n')
    print(json.dumps(dict(result='pass',cases=len(report['cases']),native=len(report['cases']),interpreted=len(report['cases']),original_cpu_calls=sum(c['original_cpu_calls']for c in report['cases']),original_psg_writes=sum(c['original_psg_writes']for c in report['cases']),later_pcm_differences=sum(len(c['later_pcm_differences'])for c in report['cases'])),indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT);parser.add_argument('--compiler',default='clang++');parser.add_argument('--library',type=Path,action='append',default=[]);parser.add_argument('--out',type=Path,required=True)
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
