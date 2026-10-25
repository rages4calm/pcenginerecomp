"""Replay authored NEC REQUEST SENSE against isolated unchanged Beetle and Gear.

Beetle checks payload/lifetime and error classes. Gear checks existing transport
and records its known no-payload REQUEST SENSE disagreement explicitly. Raw
CHECK CONDITION bytes are retained: Beetle1/message0 versus Gear/tool2/message2.
Native proof uses actual READ-error -> SENSE -> TUR guest code, not host commands.
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
ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from scripts import mapper_reference as infrastructure
from scripts import hucard_reference as common
from scripts import filtered_audio_reference as reference
sha=reference.sha
BEETLE='b96c11e095b6a40a412d2da02766ae1c3f4fd539'
BEETLE_FILES=['mednafen/cdrom/'+n for n in ('scsicd.cpp','scsicd.h','SimpleFIFO.h','CDUtility.h','scsicd-pce-commands.inc','scsicd_cdda_filter.inc')]+['mednafen/math_ops.h']


def cdb(op,allocation=18,lba=0):
    if op==8:return [8,(lba>>16)&31,(lba>>8)&255,lba&255,allocation,0]
    if op==0xDE:return [op,allocation,lba,0,0,0,0,0,0,0]
    return [op,0,0,0,allocation,0]


def command(op,allocation=18,lba=0,automatic=0):
    values=cdb(op,allocation,lba);return ('c',automatic,len(values),*values)


def plans():
    cases=[dict(id='empty-and-metadata-error',operations=[('r',0),command(3,0),('p',),command(0xDE,0),('p',),command(3,1,automatic=1),('p',),command(3,255)]),
           dict(id='success-reset-abort-lifetime',operations=[('r',2),command(8,1),('p',),command(0),('p',),('z',),('p',),command(3),('p',),command(8,1),('b',),('p',),command(3),command(8,1),('r',2),('p',),command(3)]),
           dict(id='read-errors-and-prefix',operations=[('r',1),command(8,1,25),('p',),command(3),command(8,2,19,1),('p',),command(3,18,automatic=1),('r',3),command(8,1),('p',),command(3),('r',4),command(8,1),('p',),command(3)]),
           dict(id='all-allocation-bytes',operations=[('r',0),*[command(3,n,automatic=n%2)for n in range(256)]])]
    return cases


def baseline():
    return [dict(id='gear-transport',operations=[('r',0),command(0),command(0xDE,0),('z',),command(0,automatic=1),('r',1),command(0xDE,0),command(0xDE,1,automatic=1),command(0xDE,2,1),command(8,1,0),command(8,1,1,1),('z',)])]


def stub_plan():return [dict(id='gear-sense-explicit-disagreement',operations=[('r',0),*[command(3,n,automatic=i%2)for i,n in enumerate((0,1,18,255))]])]


def serialize(cases):return '\n'.join(' '.join(map(str,o))for case in cases for o in case['operations'])+'\n'


def sense_bytes(pending):
    out=[0]*18;out[0]=0x70;out[2]=pending[0];out[7]=10;out[12:15]=pending[1:];return out


def expected(cases,profile):
    rows=[];pending=[0,0,0,0];mode=0
    for case in cases:
        for op in case['operations']:
            if op[0]=='r':mode=op[1];pending=[0,0,0,0]
            elif op[0]=='p':rows.append(dict(kind='pending',values=pending[:]))
            elif op[0]=='b':pending=[0,0,0,0]
            elif op[0]=='z':pass
            elif op[0]=='c':
                _,automatic,count,*raw=op;data=[];error=None
                if raw[0]==3:
                    if profile!='gear':data=sense_bytes(pending);pending=[0,0,0,0]
                elif raw[0]==0:
                    if profile=='beetle'and not mode:error=[2,0x0B,0,0]
                elif raw[0]==0xDE:
                    if not mode:error=[2,0x0B,0,0]
                    elif raw[1]==0:data=[1,1,0,0]
                    elif raw[1]==1:data=[0,2,0x20,0]
                    elif raw[1]==2:data=[0,2,0,4]
                    else:raise ValueError('Unauthored directory response')
                elif raw[0]==8:
                    lba=((raw[1]&31)<<16)|(raw[2]<<8)|raw[3];count=raw[4]or 256
                    if lba>=20:error=[5,0x25,0,0]
                    elif mode==2:error=[3,0x1D,0,0]
                    elif mode==3:error=[5,0,0,0]
                    elif mode==4:error=[3,0x11,5,0]
                    elif not mode:raise ValueError('Missing-provider READ intentionally excluded')
                    else:
                        for address in range(lba,min(lba+count,20)):data += [(address+i)&255 for i in range(2048)]
                        if lba+count>20:error=[5,0x25,0,0]
                else:raise ValueError('Unauthored opcode')
                if error:pending=error
                rows.append(dict(kind='reply',automatic=automatic,cdb=raw,data=data,status=(1 if profile=='beetle'else 2)if error else 0,message=0 if profile=='beetle'or not error else 2))
            else:raise ValueError('Unauthored plan operation')
    return rows


def validate_rows(rows,wanted):
    if type(rows)is not list or len(rows)!=len(wanted):raise ValueError('Sense record count differs')
    def typed(a,b):
        if type(a)is not type(b):return False
        if type(a)is dict:return a.keys()==b.keys()and all(typed(a[k],b[k])for k in b)
        if type(a)is list:return len(a)==len(b)and all(typed(x,y)for x,y in zip(a,b))
        return a==b
    if not typed(rows,wanted):
        index=next(i for i,(a,b)in enumerate(zip(rows,wanted))if not typed(a,b));raise ValueError('Sense literal/type mismatch at '+str(index))
    return rows


def firmware():
    code=bytearray();fixups=[]
    def emit(*b):code.extend(b)
    def store(address,value):emit(0xA9,value,0x8D,address&255,address>>8)
    def wait(mask,wanted):
        pos=len(code);emit(0xAD,0,0x18,0x29,mask,0xC9,wanted,0xD0,0)
        code[-1]=(pos-len(code))&255
    def ack():store(0x1802,128);store(0x1802,0)
    def read_to(offset):wait(64,64);emit(0xAD,1,0x18,0x8D,offset,0x20);ack()
    emit(0xA9,255,0x53,1,0xA9,248,0x53,2)
    for raw,payload,status in ((cdb(8,1),0,0x40),(cdb(3),18,0x20),(cdb(0),0,0x44)):
        store(0x1800,0)
        for byte in raw:wait(64,64);store(0x1801,byte);ack()
        for i in range(payload):read_to(i)
        read_to(status);read_to(status+1);wait(128,0)
    end=0xE100+len(code);emit(0x80,0xFE)
    if len(code)>7000:raise ValueError('Authored guest ROM bound')
    image=bytearray([0xEA]*262144);image[256:256+len(code)]=code;image[8190:8192]=bytes((0,0xE1));return bytes(image),end


def guest_plan():return [dict(id='native-read-error-sense-ready',operations=[('r',2),('g',firmware()[1]),*[('k',n)for n in (*range(18),0x20,0x21,0x40,0x41,0x44,0x45)],('p',)])]


def check_guest(rows):
    if type(rows)is not list or len(rows)!=26:raise ValueError('Guest record count')
    first=rows[0]
    if type(first)is not dict or set(first)!={'kind','values'}or first['kind']!='guest'or len(first['values'])!=19 or any(type(v)is not int for v in first['values']):raise ValueError('Guest CPU type/shape')
    cpu=first['values']
    if cpu[0]!=firmware()[1]or not 0<cpu[16]<=200000 or cpu[17:]!=[1,1]or cpu[8:16]!=[255,248,0,0,0,0,0,0]:raise ValueError('Guest execution endpoints')
    wanted=[dict(kind='ram',values=[i,v])for i,v in enumerate(sense_bytes([3,0x1D,0,0]))]
    wanted += [dict(kind='ram',values=[n,v])for n,v in ((0x20,0),(0x21,0),(0x40,2),(0x41,2),(0x44,0),(0x45,0))]
    wanted += [dict(kind='pending',values=[0,0,0,0])]
    validate_rows(rows[1:],wanted);return cpu[16]


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_sense_probe.cpp')
    deps=checkout/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(path)]
    objects=out/'objects';objects.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=objects/(str(index)+'-'+path.stem+'.o');cmd=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((cmd,obj));report['commands'].append(cmd)
    def compile_one(job):
        cmd,obj=job;r=subprocess.run(cmd,capture_output=True,text=True,timeout=180);obj.with_suffix('.log').write_text(r.stdout+r.stderr);r.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(compile_one,jobs))
    libs=[p.resolve()for p in args.library]
    if not libs or any(not p.is_file()for p in libs):raise ValueError('Supply explicit existing external libraries')
    bindings['external_libraries']={str(p):sha(p)for p in libs};binary=out/'gear-sense.exe'
    common.evidence([str(compiler),*[str(o)for _,o in jobs],*map(str,libs),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(o):sha(o)for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)};return binary


def build_tool(args,out,report,bindings,compiler,module=None):
    tool=args.tool_source.resolve();label='native'if module else'interpreted';q=infrastructure.cmake_quote
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja))
    if not cmake.is_file()or not ninja.is_file():raise ValueError('Require CMake/Ninja')
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    wrapper=out/(label+'-wrapper');wrapper.mkdir();source=ROOT/'tests/sense_oracle_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(SenseProof LANGUAGES CXX)',*['set('+o+' OFF CACHE BOOL "" FORCE)'for o in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],f'add_subdirectory({q(tool)} tool)']
    if module:lines += [f'pce_add_native_module(_module MODULE {q(module/"module.cpp")} MANIFEST {q(module/"module.json")})',f'add_executable(sense-probe {q(source)})','target_compile_definitions(sense-probe PRIVATE PCE_SENSE_NATIVE_ONLY=1)','target_link_libraries(sense-probe PRIVATE ${_module} pce-runtime)']
    else:lines += [f'add_executable(sense-probe {q(source)} {q(tool/"runtime/src/no_module.cpp")})','target_link_libraries(sense-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n');bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file)
    build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','sense-probe','--parallel','4'],label+'-build',out,report,bindings,600)
    binary=build/('sense-probe.exe'if os.name=='nt'else'sense-probe')
    bindings.setdefault('tool_build_artifacts',{}).update({str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.obj','.o','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))})
    bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary);return binary


def build_beetle(args,out,report,bindings,compiler):
    repository=args.beetle_source.resolve();directory=out/'beetle';source=directory/'src';cd=source/'cdrom';cd.mkdir(parents=True)
    originals={};blobs={}
    for name in BEETLE_FILES:
        raw=subprocess.check_output(['git','-C',str(repository),'show',BEETLE+':'+name])
        blob=subprocess.check_output(['git','-C',str(repository),'rev-parse',BEETLE+':'+name],text=True).strip()
        actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if actual!=blob:raise ValueError('Beetle source blob identity differs')
        file=source/Path(name).relative_to('mednafen');file.write_bytes(raw);originals[str(file)]=sha(file);blobs[name]=blob
    bindings['beetle_compile_sources']=originals;report['beetle_source_blobs']=blobs
    (directory/'compat').mkdir();authored={directory/'forced.hpp':FORCED,cd/'cdromif.h':MEDIA_HEADER,source/'state.h':STATE_HEADER,
        source/'mednafen.h':'#pragma once\n#include "../forced.hpp"\n',directory/'compat/msvc.h':'#pragma once\n'}
    for file,text in authored.items():file.write_text(text)
    bindings['beetle_framework']={str(file):sha(file)for file in authored}
    obj=directory/'probe.o';binary=directory/'beetle-sense.exe'
    common.evidence([str(compiler),'-std=c++20','-O2','-ffunction-sections','-fdata-sections','-I',str(directory),'-I',str(cd),'-I',str(ROOT/'tests'),'-include',str(directory/'forced.hpp'),'-c',str(ROOT/'tests/beetle_sense_probe.cpp'),'-o',str(obj)],'beetle-compile',out,report,bindings)
    common.evidence([str(compiler),str(obj),'-Wl,--gc-sections','-o',str(binary)],'beetle-link',out,report,bindings)
    bindings['beetle_artifacts']={str(p):sha(p)for p in(obj,binary)};return binary


def execute(label,binary,plan,arguments,out,report,bindings,wanted=None):
    result=common.evidence([str(binary),str(plan),*map(str,arguments)],label,out,report,bindings)
    rows=json.loads(result.stdout)
    if wanted is not None:validate_rows(rows,wanted)
    return rows


def guest(label,binary,plan,image,out,report,bindings,native):
    capture=out/(label+'-capture.json')
    rows=execute(label,binary,plan,[image,'--capture',capture],out,report,bindings)
    count=check_guest(rows)
    from pcerecomp.capture import load_capture
    from pcerecomp.project import ABI
    observed,_=load_capture(capture);bindings['raw_outputs'][str(capture)]=sha(capture)
    n=sum(o['native_hits']for o in observed['observations']);i=sum(o['interpreted_hits']for o in observed['observations'])
    if observed['runtime_abi']!=ABI or not observed['complete']or observed['retired_instructions']!=count or n!=(count if native else 0)or i!=(0 if native else count):raise ValueError('Guest actual capture execution tier/count differs')
    return rows,observed,count


def run(args):
    compiler=Path(shutil.which(str(args.compiler))or'').resolve();tool=args.tool_source.resolve();out=args.out.resolve()
    if args.native:
        sys.path.insert(0,str(tool));from pcerecomp import project
        if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py':raise ValueError('Compiler imported from wrong toolkit')
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():raise ValueError('Require compiler and NEW private output')
    files=[Path(__file__),*[ROOT/'tests'/n for n in ('beetle_sense_probe.cpp','geargrafx_sense_probe.cpp','sense_oracle_probe.cpp','sense_probe_support.hpp','reset_probe_support.hpp','test_sense_reference.py')],*[ROOT/'scripts'/n for n in ('mapper_reference.py','hucard_reference.py','filtered_audio_reference.py','psg_reference.py')]]
    if args.native:files+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p)for p in files})
    report=dict(schema=1,result='incomplete',commands=[],bindings=bindings,beetle_commit=BEETLE,gear_commit=reference.COMMIT,
        scope='Authored NEC sense payload/lifecycle/error classes, separate unchanged Gear transport baseline, explicit Gear sense disagreement, actual translated READ-error/SENSE/TUR guest',
        differences=['Beetle CHECK CONDITION DB01/message00; Gear/tool DB02/message02 retained raw','Beetle sense DATAIN precedes firstREQ until next Run; toolkit aggregate handshake settles immediately','Gear REQUEST SENSE produces no payload; toolkit/Beetle return18','Existing Gear-profile timing and metadata response lengths remain; settled transactions only','Beetle automatic mode is supervisor-issued ACK pulse; Gear/tool exercise actual1808 register','Authored validator predicate exercises error mapping, not an ECC decoder'],
        not_checked=['Hardware or exact bus phases','Retail compatibility','Disc insertion/tray/unit-attention','Physical data validation/ECC','Audio output','General SCSI compliance','Midstream data-to-audio category equivalence'])
    out.mkdir(parents=True)
    try:
        image=out/'authored-system.pce';image.write_bytes(firmware()[0]);binfile=out/'authored.bin';binfile.write_bytes(bytes((lba+i)&255 for lba in range(20)for i in range(2048)))
        cue=out/'authored.cue';cue.write_text('FILE "authored.bin" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n')
        groups={'beetle':plans(),'baseline':baseline(),'stub':stub_plan(),'guest':guest_plan()};paths={}
        for label,cases in groups.items():file=out/(label+'.plan');file.write_text(serialize(cases));paths[label]=file
        bindings['authored_fixtures']={str(p):sha(p)for p in(image,binfile,cue,*paths.values())}
        beetle=build_beetle(args,out,report,bindings,compiler);expected_beetle=expected(plans(),'beetle')
        golden=execute('beetle',beetle,paths['beetle'],[],out,report,bindings,expected_beetle)
        gear=build_gear(args,out,report,bindings,compiler)
        old=execute('gear-baseline',gear,paths['baseline'],[image,cue],out,report,bindings,expected(baseline(),'gear'))
        stub=execute('gear-stub',gear,paths['stub'],[image,cue],out,report,bindings,expected(stub_plan(),'gear'))
        report.update(beetle_cases=len(plans()),beetle_observations=len(golden),beetle_reply_bytes=sum(len(r['data'])for r in golden if r['kind']=='reply'),gear_baseline_observations=len(old),gear_stub_observations=len(stub))
        if args.native or args.probe:
            probe=build_tool(args,out,report,bindings,compiler)if args.native else args.probe.resolve()
            actual=execute('interpreted-device',probe,paths['beetle'],[image],out,report,bindings,expected(plans(),'tool'))
            differences=[]
            for index,(a,b)in enumerate(zip(golden,actual)):
                if a!=b:
                    if a['kind']!='reply'or(a['status'],a['message'],b['status'],b['message'])!=(1,0,2,2)or{ k:v for k,v in a.items()if k not in('status','message')}!={k:v for k,v in b.items()if k not in('status','message')}:raise ValueError('Unexpected independent sense difference')
                    differences.append(index)
            report['expected_wire_error_differences']=differences
            matched=execute('interpreted-baseline',probe,paths['baseline'],[image],out,report,bindings,expected(baseline(),'gear'))
            if matched!=old:raise ValueError('Gear baseline differs')
            new=execute('interpreted-stub',probe,paths['stub'],[image],out,report,bindings,expected(stub_plan(),'tool'))
            if any(a['data']or len(b['data'])!=18 or(a['status'],a['message'],b['status'],b['message'])!=(0,0,0,0)for a,b in zip(stub,new)):raise ValueError('Expected Gear sense disagreement differs')
            report['expected_gear_sense_payloads']={'gear':[len(r['data'])for r in stub],'tool':[len(r['data'])for r in new]}
            training=guest('interpreted-guest',probe,paths['guest'],image,out,report,bindings,False)
            if args.native:
                from pcerecomp.capture import load_capture
                from pcerecomp.emitter import emit_capture
                from pcerecomp.project import source_identity
                observed,digest=load_capture(out/'interpreted-guest-capture.json');module=out/'native-module';manifest=emit_capture(observed,module,digest)
                if manifest['native_instructions_emitted']!=len(observed['observations'])or manifest['unsupported_observations']or manifest['excluded_observations']:raise ValueError('Every actual source identity must translate')
                if any('interpret_step'in p.read_text()or'interpret_block'in p.read_text()for p in module.glob('*.cpp')):raise ValueError('Interpreter bridge is not native proof')
                bindings['generated_module']={str(p):sha(p)for p in module.iterdir()if p.is_file()};binary=build_tool(args,out,report,bindings,compiler,module)
                completed=guest('native-guest',binary,paths['guest'],image,out,report,bindings,True)
                if completed[0]!=training[0]:raise ValueError('Native guest checkpoints differ')
                if {common.capture_identity(o):o['native_hits']for o in completed[1]['observations']}!={common.capture_identity(o):o['interpreted_hits']for o in training[1]['observations']}:raise ValueError('Native source identity/hit keys differ')
                report['native']=dict(instructions=completed[2],interpreted=0,identities=len(observed['observations']),mpr_contexts=len({tuple(o['mpr'])for o in observed['observations']}),sense_commands=1,sense_errors=1)
                report['tool']=source_identity(tool)
        report['result']='pass'
    except Exception as e:report.update(result='fail',error=str(e));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Reference evidence changed')
    print(json.dumps({k:v for k,v in report.items()if k not in('commands','bindings','beetle_source_blobs')},indent=2))



FORCED = '#pragma once\n#include <cstdint>\n#include <cstring>\n#include <cassert>\n#include <cstdio>\n#include <cstdlib>\n#include <cstdarg>\n#include <stdexcept>\nusing int8=int8_t;using int16=int16_t;using int32=int32_t;using int64=int64_t;\nusing uint8=uint8_t;using uint16=uint16_t;using uint32=uint32_t;using uint64=uint64_t;\n#define INLINE inline\n#define MDFN_UNLIKELY(x) (x)\n#define TRUE true\n#define FALSE false\n#define _(x) x\ninline uint32 round_up_pow2(uint32 x){uint32 n=1;while(n<x)n*=2;return n;}\ninline int16 MDFN_de16lsb(const void* p){auto*q=static_cast<const uint8*>(p);return int16(q[0]|(unsigned(q[1])<<8));}\ninline void MDFN_DispMessage(const char*,...){ }\n'

MEDIA_HEADER = '#pragma once\n#include "CDUtility.h"\nclass CDIF {\npublic:\n    TOC disc_toc;bool raw_ok=true,validation_ok=true;\n    virtual ~CDIF()=default;\n    void ReadTOC(TOC* value){*value=disc_toc;}\n    virtual void HintReadSector(int32_t){}\n    virtual bool ReadRawSector(uint8_t* p,int32_t lba){if(!raw_ok)return false;std::memset(p,0,2448);p[15]=1;for(unsigned i=0;i<2048;++i)p[16+i]=uint8_t(lba+i);return true;}\n    virtual bool ReadRawSectorPWOnly(uint8_t* p,int32_t,bool){std::memset(p,0,96);return true;}\n    bool ValidateRawSector(uint8_t*){return validation_ok;}\n};\n'

STATE_HEADER = '#pragma once\nstruct StateMem{};struct SFORMAT{int unused;};\n#define SFVAR(...) {0}\n#define SFVARN(...) {0}\n#define SFARRAY(...) {0}\n#define SFARRAYN(...) {0}\n#define SFARRAY16(...) {0}\n#define SFEND {0}\ninline int MDFNSS_StateAction(StateMem*,unsigned,bool,SFORMAT*,const char*,bool){throw std::runtime_error("state services outside reference scope");}\n'

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--beetle-source',type=Path,required=True);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--probe',type=Path);p.add_argument('--native',action='store_true');p.add_argument('--out',type=Path,required=True);p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[])
    try:run(p.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as e:print(e,file=sys.stderr);raise SystemExit(1)
