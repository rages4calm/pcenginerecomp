"""Finite BRAM guest-access/raw roundtrip checks against unchanged Geargrafx.

Only authored code/data are used. Both probes explicitly replace Gear's default
formatted BRAM with the same deterministic seed. Host export/import is raw 2 KiB,
not an oracle for the toolkit's namespaced/atomic persistent-store policy.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from scripts import mapper_reference as infrastructure
from scripts import hucard_reference as common
from scripts import filtered_audio_reference as reference
sha = reference.sha


def seed():
    return bytes((i*13+(i>>8)*37+0x31)&255 for i in range(2048))


def written():
    return bytes(((i&255)^((i>>8)*37)^0xA5)&255 for i in range(2048))


def firmware():
    operations = []
    def emit(*values): operations.append(bytes(values))
    def store(address, value): emit(0xA9, value); emit(0x8D, address&255, address>>8)
    def sample(address, slot): emit(0xAD, address&255, address>>8); emit(0x8D, slot, 0x20)
    emit(0xA9, 255); emit(0x53, 1); emit(0xA9, 248); emit(0x53, 2)
    emit(0xA9, 247); emit(0x53, 4); emit(0x53, 8); emit(0xA9, 255); emit(0x53, 16)
    for address, slot in ((0x1807,0),(0x4000,1),(0x6000,2),(0x1803,3),(0x9807,4)):
        sample(address, slot)
    store(0x4000, 0x11); store(0x67FF, 0x22)
    sample(0x4000, 5); sample(0x4800, 6)
    store(0x9807, 255); sample(0x1807, 7)
    prefix = len(operations)
    for page in range(8):
        emit(0xA2, 0)
        emit(0x8A); emit(0x49, ((page*37)^0xA5)&255)
        emit(0x9D, 0, 0x40+page); emit(0xE8); emit(0xD0, 0xF7)
    store(0x4800, 0x77); emit(0x8D, 255, 0x7F)
    for address, slot in ((0x4800,8),(0x7FFF,9),(0x1803,10),(0x9807,11)):
        sample(address, slot)
    # Each 5-instruction loop retires 256 times rather than once.
    body = len(operations)-prefix+8*5*255
    image = bytearray([0xEA]*262144)
    code = b''.join(operations)+b'\x80\xFE'
    if len(code)>7000: raise ValueError('Authored BRAM ROM bound')
    image[256:256+len(code)] = code
    image[8190:8192] = bytes((0, 0xE1))
    return bytes(image), prefix, body


def plans():
    _, prefix, body = firmware()
    return [dict(id='bram-'+('high' if fast else 'low'), operations=[
        ('r', fast), ('b',), ('i', prefix), ('b',), ('i', body), ('b',),
        ('x',), ('l',), ('b',), ('i', prefix), ('b',), ('x',)]) for fast in (0,1)]


def serialize(cases):
    return '\n'.join(' '.join(map(str, op)) for case in cases for op in case['operations'])+'\n'


def validate_records(records, cases):
    tags = []
    for case in cases:
        for op in case['operations']:
            if op[0]=='b': tags.extend((('cpu',16),('bram',2048),('ram',16),('gate',1)))
            elif op[0]=='x': tags.append(('export',2048))
    if type(records) is not list or len(records)!=len(tags): raise ValueError('BRAM record count differs')
    for row, (kind,width) in zip(records,tags):
        if (type(row) is not dict or set(row)!={'kind','values'} or row['kind']!=kind
                or type(row['values']) is not list or len(row['values'])!=width
                or any(type(value) is not int or not 0<=value<(2**64 if kind=='cpu' else 256) for value in row['values'])):
            raise ValueError('BRAM record type/shape differs')
    return records


def literal_checks(records, cases):
    validate_records(records,cases)
    index=checks=0
    _,prefix,body=firmware()
    for case in cases:
        for op in case['operations']:
            name=op[0]
            if name=='r': memory=list(seed());ram=[0]*16;gate=1;saved=None
            elif name=='i':
                if op[1]==prefix:
                    ram[:8]=[128,memory[0],memory[0],18,0,255,255,128];gate=1
                elif op[1]==body:
                    memory=list(written());ram[8:12]=[255,255,18,0];gate=0
                else: raise ValueError('Unauthored instruction count')
            elif name=='l':
                if saved is None: raise ValueError('Restore before export')
                memory=saved[:];ram=[0]*16;gate=1
            elif name=='x':
                saved=memory[:]
                if records[index]!=dict(kind='export',values=memory): raise ValueError('BRAM export literal differs')
                index+=1;checks+=2048
            elif name=='b':
                # CPU including timestamps is compared across all three paths.
                # The independent literal model specifies RAM, gate and all payload bytes.
                index+=1
                for kind, values in (('bram',memory),('ram',ram),('gate',[gate])):
                    if records[index]!=dict(kind=kind,values=values): raise ValueError(f'BRAM {kind} literal differs at {index}')
                    index+=1;checks+=len(values)
            else: raise ValueError('Unauthored plan operation')
    if index!=len(records): raise ValueError('BRAM observation accounting differs')
    return checks


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_bram_probe.cpp')
    deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'): flags+=['-I',str(path)]
    objects=out/'objects';objects.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=objects/(str(index)+'-'+path.stem+'.o')
        cmd=[str(compiler),*flags,'-x','c++' if path.suffix=='.cpp' else 'c',*(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((cmd,obj));report['commands'].append(cmd)
    def compile_one(job):
        cmd,obj=job;r=subprocess.run(cmd,capture_output=True,text=True,timeout=180);obj.with_suffix('.log').write_text(r.stdout+r.stderr);r.check_returncode()
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(compile_one,jobs))
    libs=[p.resolve() for p in args.library]
    if not libs or any(not p.is_file() for p in libs): raise ValueError('Supply explicit existing external libraries')
    bindings['external_libraries']={str(p):sha(p) for p in libs};binary=out/'gear-bram.exe'
    common.evidence([str(compiler),*[str(o) for _,o in jobs],*map(str,libs),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(o):sha(o) for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    return binary


def build_tool(args,out,report,bindings,compiler,module=None):
    tool=args.tool_source.resolve();label='native' if module else 'interpreted';q=infrastructure.cmake_quote
    cmake,ninja=(Path(shutil.which(str(v)) or '').resolve() for v in (args.cmake,args.ninja))
    if not cmake.is_file() or not ninja.is_file(): raise ValueError('Require CMake/Ninja')
    bindings['tools'].update({str(p):sha(p) for p in (cmake,ninja)})
    wrapper=out/(label+'-wrapper');wrapper.mkdir();source=ROOT/'tests/bram_oracle_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(BramProof LANGUAGES CXX)',*['set('+o+' OFF CACHE BOOL "" FORCE)' for o in ('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],f'add_subdirectory({q(tool)} tool)']
    if module: lines += [f'pce_add_native_module(_module MODULE {q(module/"module.cpp")} MANIFEST {q(module/"module.json")})',f'add_executable(bram-probe {q(source)})','target_compile_definitions(bram-probe PRIVATE PCE_BRAM_NATIVE_ONLY=1)','target_link_libraries(bram-probe PRIVATE ${_module} pce-runtime)']
    else: lines += [f'add_executable(bram-probe {q(source)} {q(tool/"runtime/src/no_module.cpp")})','target_link_libraries(bram-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n');bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file)
    build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','bram-probe','--parallel','4'],label+'-build',out,report,bindings,600)
    binary=build/('bram-probe.exe' if os.name=='nt' else 'bram-probe')
    bindings.setdefault('tool_build_artifacts',{}).update({str(p):sha(p) for p in build.rglob('*') if p.is_file() and (p.suffix in ('.obj','.o','.a') or p.name in ('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))})
    bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary)
    return binary


def execute(label,binary,plan,image,cases,out,report,bindings,tier=None):
    prefix=out/(label+'-export');command=[str(binary),str(plan),str(image),str(prefix)]
    capture=out/(label+'-capture.json')
    if tier is not None: command+=['--capture',str(capture)]
    result=common.evidence(command,label,out,report,bindings)
    rows=validate_records(json.loads(result.stdout),cases)
    files=sorted(out.glob(label+'-export-*.bram'))
    if len(files)!=sum(op[0]=='x' for case in cases for op in case['operations']): raise ValueError('Actual raw export file count differs')
    bindings.setdefault('raw_exports',{}).update({str(p):sha(p) for p in files})
    if tier is None: return rows,None
    from pcerecomp.capture import load_capture
    from pcerecomp.project import ABI
    observed,_=load_capture(capture);bindings['raw_outputs'][str(capture)]=sha(capture)
    count=sum(op[1] for case in cases for op in case['operations'] if op[0]=='i')
    if (observed['runtime_abi']!=ABI or not observed['complete'] or observed['retired_instructions']!=count
            or observed['unreadable_instructions'] or observed['dropped_instructions']
            or sum(o['native_hits'] for o in observed['observations'])!=(count if tier=='native' else 0)
            or sum(o['interpreted_hits'] for o in observed['observations'])!=(0 if tier=='native' else count)):
        raise ValueError('Actual BRAM capture execution tier/count differs')
    return rows,observed


def run(args):
    compiler=Path(shutil.which(str(args.compiler)) or '').resolve();tool=args.tool_source.resolve();out=args.out.resolve()
    if args.native:
        sys.path.insert(0,str(tool));from pcerecomp import project
        if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py': raise ValueError('Compiler imported from wrong toolkit')
    if out.exists() or not out.is_relative_to(ROOT/'.local') or not compiler.is_file(): raise ValueError('Require compiler and NEW private output')
    files=[Path(__file__),*[ROOT/'tests'/n for n in ('bram_probe_support.hpp','geargrafx_bram_probe.cpp','bram_oracle_probe.cpp','test_bram_reference.py','reset_probe_support.hpp')],*[ROOT/'scripts'/n for n in ('mapper_reference.py','hucard_reference.py','filtered_audio_reference.py','psg_reference.py')]]
    if args.native: files+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p) for p in files})
    report=dict(schema=1,result='incomplete',oracle_commit=reference.COMMIT,commands=[],bindings=bindings,execution_paths=['geargrafx'],
        scope='Authored full 2048-byte BRAM, guest lock/unlock/upper-hole/MPR aliases, raw file export/reload with guest-neutral export and CPU/gate-neutral reload; optional actual interpreted and emitted native CPU execution',
        configuration=['Gear default formatted BRAM explicitly replaced by deterministic seed via original LoadRam','Explicit synthetic low/high CPU entry speeds, no speed-transition inference','Gear CD-presence configuration and public EnableBackupRam(true) are enabled for authored HuCard fixture; toolkit uses Standard System Card map','Raw reload creates fresh CPU/device instance before original Gear LoadRam or toolkit loader copy','Toolkit raw save uses the actual export_bram_new primitive; Gear uses original Memory::SaveRam'],
        not_checked=['Retail firmware/gameplay','Physical hardware or electrical access phases','Guest formatting policy','Atomic publication, namespaced persistence, crash durability or concurrent-store policy','Save states/rewind or complete device restore'])
    out.mkdir(parents=True)
    try:
        image=out/'authored.pce';image.write_bytes(firmware()[0]);plan=out/'bram.plan';cases=plans();plan.write_text(serialize(cases))
        bindings['authored_fixtures']={str(p):sha(p) for p in (image,plan)}
        gear=build_gear(args,out,report,bindings,compiler);golden=execute('gear',gear,plan,image,cases,out,report,bindings)
        literal={'gear':literal_checks(golden[0],cases)}
        probe=build_tool(args,out,report,bindings,compiler) if args.native else args.probe.resolve() if args.probe else None
        if probe:
            actual=execute('interpreted',probe,plan,image,cases,out,report,bindings,'interpreted')
            if actual[0]!=golden[0]:
                index=next(i for i,(a,b) in enumerate(zip(actual[0],golden[0])) if a!=b)
                raise ValueError(f'Independent BRAM mismatch at {index}: {actual[0][index]} vs {golden[0][index]}')
            literal['interpreter']=literal_checks(actual[0],cases)
            report['execution_paths'].append('interpreter')
        if args.native:
            from pcerecomp.capture import load_capture
            from pcerecomp.emitter import emit_capture
            from pcerecomp.project import source_identity
            observed,digest=load_capture(out/'interpreted-capture.json');module=out/'native-module';manifest=emit_capture(observed,module,digest)
            if manifest['native_instructions_emitted']!=len(observed['observations']) or manifest['unsupported_observations'] or manifest['excluded_observations']: raise ValueError('All actual identities must translate')
            bindings['generated_module']={str(p):sha(p) for p in module.iterdir() if p.is_file()}
            binary=build_tool(args,out,report,bindings,compiler,module);completed=execute('native',binary,plan,image,cases,out,report,bindings,'native')
            if completed[0]!=golden[0]: raise ValueError('Native BRAM records differ')
            if {common.capture_identity(o):o['native_hits'] for o in completed[1]['observations']}!={common.capture_identity(o):o['interpreted_hits'] for o in actual[1]['observations']}: raise ValueError('Native BRAM source hit keys differ')
            literal['native']=literal_checks(completed[0],cases);report['tool']=source_identity(tool)
            report['execution_paths'].append('emitted-native')
            report['native']=dict(retirements=completed[1]['retired_instructions'],interpreted=0,identities=len(observed['observations']),mpr_contexts=len({tuple(o['mpr']) for o in observed['observations']}))
        report.update(result='pass',cases=len(cases),observations=len(golden[0]),literal_checks=literal,guest_segments=list(firmware()[1:]),gear_invalid_import_checks=6,raw_exports_per_path=4)
    except Exception as error: report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass': raise ValueError('BRAM evidence changed')
    print(json.dumps({k:v for k,v in report.items() if k not in ('bindings','commands')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT);parser.add_argument('--probe',type=Path);parser.add_argument('--native',action='store_true');parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja');parser.add_argument('--library',type=Path,action='append',default=[])
    try: run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error: print(error,file=sys.stderr);raise SystemExit(1)
