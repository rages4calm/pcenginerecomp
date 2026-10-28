"""Finite authored input-latch proof against a separately built original Gear core.

Host changes are held intent, never direct latch writes. Guest STA/LDA $1000
sample active-low button/direction nibbles. Pure NOP delays do not qualify VDC
stalls, timer IRQ timing, retail routes or host presentation scheduling.
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
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from state_route_input_fixture import plans, program, serialize, validate_events, expected_hits
from scripts import mapper_reference as mapper, filtered_audio_reference as reference, hucard_reference as common
from pcerecomp.project import source_identity, ABI

COMMIT, sha = reference.COMMIT, reference.sha


def bound_sources(tool):
    sources=[ROOT/'scripts/state_route_input_reference.py', ROOT/'scripts/state_route_input_qualify.py',
             ROOT/'tests/state_route_input_fixture.py',ROOT/'tests/state_route_input_probe.cpp',
             ROOT/'tests/state_route_input_gear_probe.cpp',ROOT/'tests/state_route_input_support.hpp',
             ROOT/'tests/reset_probe_support.hpp',ROOT/'scripts/mapper_reference.py',ROOT/'scripts/hucard_reference.py',
             ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py',
             ROOT/'tests/test_state_route_input_reference.py',ROOT/'tests/hucard_fixture.py']
    sources+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))
    sources+=sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'cmake').rglob('*.cmake'))+[tool/'CMakeLists.txt']
    return {str(p.resolve()):sha(p) for p in sources}


def build_gear(args, out, report, bindings, compiler):
    checkout, source = mapper.pinned_snapshot(args.gear_source.resolve(), out, bindings)
    cpp, c = reference.compile_sources(checkout, source)
    cpp.append(ROOT/'tests/state_route_input_gear_probe.cpp')
    deps = checkout/'platforms/shared/dependencies'
    flags = ['-O2', '-ffp-contract=off', '-ffunction-sections', '-fdata-sections',
             '-DGG_DISABLE_DISASSEMBLER', '-DGG_DISABLE_VGMRECORDER', '-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src', ROOT/'tests', deps/'miniz', deps/'libchdr/include', deps/'minivorbis', deps/'json'):
        flags += ['-I', str(include)]
    objects = out/'objects';objects.mkdir()
    jobs = []
    for index, path in enumerate(cpp+c):
        obj = objects/(str(index)+'-'+path.stem+'.o')
        command = [str(compiler), *flags, '-x', 'c++' if path.suffix == '.cpp' else 'c',
                   *(['-std=c++20', '-include', 'cerrno'] if path.suffix == '.cpp' else ['-std=c11']),
                   '-c', str(path), '-o', str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def compile_one(job):
        command,obj=job
        result=subprocess.run(command,capture_output=True,text=True,timeout=180)
        log=obj.with_suffix('.log');log.write_text(result.stdout+result.stderr)
        result.check_returncode()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(compile_one,jobs))
    libraries = [p.resolve() for p in args.library]
    if not libraries or any(not p.is_file() for p in libraries):
        raise ValueError('Supply existing external libraries explicitly')
    bindings['external_libraries'] = {str(p):sha(p) for p in libraries}
    binary=out/'gear-input.exe'
    common.evidence([str(compiler),*[str(obj) for _,obj in jobs],*map(str,libraries),
                     '-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(obj):sha(obj) for _,obj in jobs}
    bindings['gear_binary']={str(binary):sha(binary)}
    report['gear_git_blobs'] = {name: hashlib.sha1(b'blob '+str((checkout/name).stat().st_size).encode()+b'\0'+(checkout/name).read_bytes()).hexdigest()
                                for name in source}
    return binary


def build_tool(args,out,report,bindings,compiler,module=None):
    label='native' if module else 'interpreted'
    cmake,ninja=(Path(shutil.which(str(value)) or '').resolve() for value in (args.cmake,args.ninja))
    if not cmake.is_file() or not ninja.is_file():
        raise ValueError('Require CMake and Ninja')
    bindings['tools'].update({str(p):sha(p) for p in (cmake,ninja)})
    quote=mapper.cmake_quote;tool=args.tool_source.resolve();wrapper=out/(label+'-wrapper');wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(AuthoredInput LANGUAGES CXX)',
           *['set('+option+' OFF CACHE BOOL "" FORCE)' for option in
             ('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
           f'add_subdirectory({quote(tool)} tool)']
    source=ROOT/'tests/state_route_input_probe.cpp'
    if module:
        lines += [f'pce_add_native_module(_module MODULE {quote(module/"module.cpp")} MANIFEST {quote(module/"module.json")})',
                  f'add_executable(input-probe {quote(source)})',
                  'target_compile_definitions(input-probe PRIVATE PCE_STATE_ROUTE_INPUT_NATIVE=1)',
                  'target_link_libraries(input-probe PRIVATE ${_module} pce-runtime)']
    else:
        lines += [f'add_executable(input-probe {quote(source)} {quote(tool/"runtime/src/no_module.cpp")})',
                  'target_link_libraries(input-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n')
    bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file)
    build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                     '-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','input-probe','--parallel','4'],label+'-build',out,report,bindings,600)
    binary=build/('input-probe.exe' if os.name=='nt' else 'input-probe')
    bindings.setdefault('tool_build_artifacts',{}).update({str(p):sha(p) for p in build.rglob('*')
        if p.is_file() and (p.suffix in ('.obj','.o','.a') or p.name in ('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))})
    bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary)
    return binary


def validate_capture(capture,case,native):
    from pcerecomp.capture import validate_capture as validate
    validate(capture)
    if capture['runtime_abi']!=ABI or not capture['complete'] or capture['dropped_instructions'] or capture['unreadable_instructions']:
        raise ValueError('Input capture incomplete or wrong ABI')
    if capture['retired_instructions']!=case['instructions']:
        raise ValueError('Input capture total differs')
    counts={common.capture_identity(o):o['native_hits' if native else 'interpreted_hits'] for o in capture['observations']}
    if counts!=expected_hits(case) or any(o['interpreted_hits' if native else 'native_hits'] for o in capture['observations']):
        raise ValueError('Full input source identity/hit/tier counts differ')
    return capture


def validate_execution(work,case,native):
    wanted=dict(runtime_abi=ABI,native_steps=case['instructions'] if native else 0,
                interpreter_steps=0 if native else case['instructions'],guard_misses=0,joypad_reads=24,joypad_writes=16)
    if work!=wanted or any(type(v) is not int for v in work.values()):
        raise ValueError('Actual input opcode/device counts differ')


def execute(label,binary,case,plan,code,out,report,bindings,native=None):
    command=[str(binary),str(plan),str(code)]
    capture,work=out/(label+'-capture.json'),out/(label+'-execution.json')
    if native is not None:command += [str(capture),str(work)]
    result=common.evidence(command,label,out,report,bindings)
    events=json.loads(result.stdout)
    if native is None:
        if not events or events.pop()!=dict(kind='gear_cpu_calls',values=[case['instructions']]):
            raise ValueError('Actual original CPU call accounting differs')
    checks=validate_events(events,case)
    if native is None:return checks,None
    bindings['raw_outputs'].update({str(p):sha(p) for p in (capture,work)})
    validate_execution(json.loads(work.read_text()),case,native)
    return checks,validate_capture(json.loads(capture.read_text()),case,native)


def run(args):
    compiler=Path(shutil.which(str(args.compiler)) or '').resolve();out=args.out.resolve();tool=args.tool_source.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.local') or not compiler.is_file():
        raise ValueError('Require compiler and new private .local output directory')
    import pcerecomp.project
    if Path(pcerecomp.project.__file__).resolve()!=tool/'pcerecomp/project.py':
        raise ValueError('Run adapter from its explicit toolkit source')
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources=bound_sources(tool))
    report=dict(schema=1,result='incomplete',oracle_commit=COMMIT,tool=source_identity(tool),tool_root=str(tool),
                commands=[],bindings=bindings,cases=[],scope='24 authored pure input protocol plans, 8 actual guest polls each; fixed full MPR/fetched-byte source identities',
                not_checked=['VDC stalls','Timer IRQ timing','Retail route causality','TCP/presentation scheduling','Hardware'])
    out.mkdir(parents=True)
    try:
        gear=build_gear(args,out,report,bindings,compiler)
        interpreted=build_tool(args,out,report,bindings,compiler)
        bindings['fixtures']={};fixtures=[];captures=[]
        for case in plans():
            label=case['id'];plan=out/(label+'.plan');code=out/(label+'.code')
            plan.write_text(serialize(case));code.write_bytes(bytes(v for row in program(case['delay'])[0] for v in row['data']))
            bindings['fixtures'].update({str(p):sha(p) for p in (plan,code)})
            g,_=execute('gear-'+label,gear,case,plan,code,out,report,bindings)
            i,capture=execute('interpreted-'+label,interpreted,case,plan,code,out,report,bindings,False)
            report['cases'].append(dict(plan=case,literal_checks=dict(gear=g,interpreted=i)))
            captures.append(capture);fixtures.append((case,plan,code))
        from pcerecomp.capture import load_capture
        from pcerecomp.emitter import emit_capture
        union=common.compose_captures(captures);capture=out/'actual-union.json';capture.write_text(json.dumps(union,indent=2)+'\n')
        bindings['fixtures'][str(capture)]=sha(capture)
        captured,digest=load_capture(capture);module=out/'native-module';manifest=emit_capture(captured,module,digest)
        if manifest['native_instructions_emitted']!=len(union['observations']) or manifest['unsupported_observations'] or manifest['excluded_observations']:
            raise ValueError('Every actual input source must translate')
        bindings['generated_module']={str(p):sha(p) for p in module.iterdir() if p.is_file()}
        native=build_tool(args,out,report,bindings,compiler,module)
        for row,(case,plan,code) in zip(report['cases'],fixtures):
            n,_=execute('native-'+case['id'],native,case,plan,code,out,report,bindings,True)
            row['literal_checks']['native']=n
        total=sum(c['instructions'] for c in plans())
        report.update(result='pass',native_steps=total,interpreter_steps=total,gear_cpu_calls=total,
                      source_identities=len(union['observations']))
    except Exception as error:
        report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Input reference preservation differs')
    from scripts.state_route_input_qualify import qualify
    result=qualify(out/'result.json');(out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
