"""Fresh-process CD to ADPCM DMA continuation with a separate original device oracle.

Toolkit executes authored supervised native/interpreted port instructions;
Gear executes original register/device code with ZERO guest CPU calls. No
cross-core CPU/bus-phase timing, sense, hardware or retail parity is claimed.
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
from cd_adpcm_checkpoint_fixture import cases,fixtures,hits,validate_payload,validate_cut,validate_gear_cut,validate_journal,SITES,MPR
from scripts import mapper_reference as infrastructure,filtered_audio_reference as reference,hucard_reference as common
from pcerecomp.project import source_identity,ABI
COMMIT=reference.COMMIT
def sha(path):return reference.sha(Path(path))

def sources(tool):
    names=['scripts/cd_adpcm_checkpoint_reference.py','scripts/cd_adpcm_checkpoint_qualify.py',
        'tests/cd_adpcm_checkpoint_fixture.py','tests/cd_adpcm_checkpoint_probe.cpp',
        'tests/geargrafx_cd_adpcm_checkpoint_probe.cpp','tests/cd_adpcm_checkpoint_support.hpp',
        'tests/test_cd_adpcm_checkpoint_reference.py','tests/geargrafx_sense_probe.cpp',
        'tests/sense_probe_support.hpp','tests/reset_probe_support.hpp',
        'scripts/mapper_reference.py','scripts/filtered_audio_reference.py','scripts/psg_reference.py','scripts/hucard_reference.py']
    files=[ROOT/name for name in names]+[tool/'CMakeLists.txt']
    files+=sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'cmake').rglob('*.cmake'))
    return {str(p.resolve()):sha(p) for p in files}

def build_gear(args,out,report,bindings,compiler):
    checkout,originals=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,originals);cpp.append(ROOT/'tests/geargrafx_cd_adpcm_checkpoint_probe.cpp')
    deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(include)]
    objects=out/'objects';objects.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=objects/(str(index)+'-'+path.stem+'.o')
        command=[str(compiler),*flags,'-x','c++' if path.suffix=='.cpp' else 'c',
            *(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def compile_one(job):
        command,obj=job;result=subprocess.run(command,capture_output=True,text=True,timeout=180)
        obj.with_suffix('.log').write_text(result.stdout+result.stderr);result.check_returncode()
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile_one,jobs))
    libs=[p.resolve() for p in args.library]
    if not libs or any(not p.is_file() for p in libs):raise ValueError('Explicit existing external libraries required')
    bindings['external_libraries']={str(p):sha(p) for p in libs};binary=out/'gear-cd-adpcm-checkpoint.exe'
    common.evidence([str(compiler),*[str(obj) for _,obj in jobs],*map(str,libs),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(obj):sha(obj) for _,obj in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    report['gear_git_blobs']={name:hashlib.sha1(b'blob '+str((checkout/name).stat().st_size).encode()+b'\0'+(checkout/name).read_bytes()).hexdigest() for name in originals}
    return binary

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(v)) or '').resolve() for v in (args.cmake,args.ninja))
    if not cmake.is_file() or not ninja.is_file():raise ValueError('CMake/Ninja required')
    bindings['tools'].update({str(p):sha(p) for p in (cmake,ninja)});tool=args.tool_source.resolve()
    q=infrastructure.cmake_quote;wrapper=out/'tool-wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(CdAdpcmCheckpoint LANGUAGES CXX)',
        *['set('+option+' OFF CACHE BOOL "" FORCE)' for option in ('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
        f'add_subdirectory({q(tool)} tool)',
        f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',
        f'add_executable(cd-adpcm-checkpoint {q(ROOT/"tests/cd_adpcm_checkpoint_probe.cpp")})',
        f'target_include_directories(cd-adpcm-checkpoint PRIVATE {q(fixture)})',
        'target_link_libraries(cd-adpcm-checkpoint PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n')
    bindings['tool_build_inputs']={str(config):sha(config)};build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','cd-adpcm-checkpoint','--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('cd-adpcm-checkpoint.exe' if os.name=='nt' else 'cd-adpcm-checkpoint')
    bindings['tool_objects']={str(p):sha(p) for p in build.rglob('*') if p.is_file() and (p.suffix in ('.o','.obj','.a') or p.name in ('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))}
    bindings['tool_binary']={str(binary):sha(binary)};return binary

def validate_capture(capture,case,native,prefix,origin=None):
    from pcerecomp.capture import validate_capture as validate
    validate(capture)
    wanted=hits(case,prefix);lookup={pc:(op,address) for pc,op,address in SITES}
    required={'schema','runtime_abi','capacity','dropped_instructions','unreadable_instructions','retired_instructions','complete','observations'}
    if origin is not None:required.add('checkpoint_origin')
    if set(capture)!=required or capture['runtime_abi']!=ABI or capture['complete'] is not True or capture['dropped_instructions'] or capture['unreadable_instructions']:
        raise ValueError('Actual complete capture contract differs')
    if capture['retired_instructions']!=sum(wanted.values()):raise ValueError('Literal retired count differs')
    observed={}
    for row in capture['observations']:
        pc=row['pc'];op,address=lookup.get(pc,(None,None))
        physical=[0x1f0000+(pc&8191)+i for i in range(3)]
        if (pc not in wanted or pc in observed or row['mpr']!=list(MPR) or row['physical']!=physical or
            row['data']!=[op,address&255,address>>8] or type(row['native_hits']) is not int or type(row['interpreted_hits']) is not int or
            row['native_hits']!=(wanted[pc] if native else 0) or row['interpreted_hits']!=(0 if native else wanted[pc])):
            raise ValueError('Actual full source identity/tier/hits differ')
        observed[pc]=wanted[pc]
    if observed!=wanted:raise ValueError('Complete literal source site set differs')
    if origin is not None and capture['checkpoint_origin']!=origin:raise ValueError('Imported capture origin differs')
    return sum(wanted.values())

def validate_execution(work,case,native,resume):
    prefix=sum(hits(case,True).values());suffix=sum(hits(case).values())
    keys={'runtime_abi','prefix_native','prefix_interpreted','suffix_native','suffix_interpreted','guard_misses','provider_reads_before_suffix','provider_reads_suffix'}
    if set(work)!=keys or any(type(v) is not int or v<0 for v in work.values()):raise ValueError('Actual work field/type differs')
    expected=dict(runtime_abi=ABI,prefix_native=prefix if native else 0,prefix_interpreted=0 if native else prefix,
        suffix_native=suffix if native else 0,suffix_interpreted=0 if native else suffix,guard_misses=0)
    if any(work[k]!=v for k,v in expected.items()):raise ValueError('Actual imported/new work differs')
    before=0 if case['cut']==0 else 1
    if work['provider_reads_before_suffix']!=(0 if resume else before):raise ValueError('Save/load/configuration read provider')
    if work['provider_reads_suffix']!=(1 if case['cut'] in (0,5,6,7) else 0):raise ValueError('Continuation provider read count differs')
    return prefix,suffix

def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();compiler=Path(shutil.which(str(args.compiler)) or '').resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.local') or not compiler.is_file():raise ValueError('New private output and compiler required')
    import pcerecomp.project
    if Path(pcerecomp.project.__file__).resolve()!=tool/'pcerecomp/project.py':raise ValueError('Run from explicit toolkit source')
    out.mkdir(parents=True);bindings=dict(tools={str(compiler):sha(compiler)},authored_sources=sources(tool))
    report=dict(schema=1,result='incomplete',oracle_commit=COMMIT,tool=source_identity(tool),tool_root=str(tool),commands=[],bindings=bindings,rows=[],
        scope=__doc__,not_checked=['Gear CPU execution','Bus-phase/cross-core clock parity','Raw original callback timing equality','Hardware','Retail','Sense command parity'])
    try:
        fixture=fixtures(out);bindings['fixtures']={str(p):sha(p) for p in [out/'authored.pce',out/'data.bin',out/'data.cue',*fixture.iterdir()] if p.is_file()}
        gear=build_gear(args,out,report,bindings,compiler);binary=build_tool(args,out,report,bindings,compiler,fixture)
        for case in cases():
            plan=out/(case['id']+'.plan');plan.write_text(f"{case['cut']} {case['mode']} {case['divisor']}\n")
            bindings['fixtures'][str(plan)]=sha(plan);arguments=[str(plan),str(out/'authored.pce'),str(out/'data.cue')]
            label=case['id']+'-gear';result=common.evidence([str(gear),*arguments],label,out,report,bindings,120)
            raw=json.loads(result.stdout);checks=validate_payload(raw,case)+validate_gear_cut(raw,case)+validate_journal(raw,case,gear=True)
            if raw.get('guest_cpu_calls')!=0 or type(raw.get('guest_cpu_calls')) is not int:raise ValueError('Gear CPU scope differs')
            for tier in ('interpreter','native'):
                checkpoint=out/(case['id']+'-'+tier+'.pcec');pair=[]
                for mode in ('write','resume'):
                    label=case['id']+'-'+tier+'-'+mode;capture=out/(label+'-capture.json');execution=out/(label+'-execution.json')
                    result=common.evidence([str(binary),*arguments,mode,tier,str(checkpoint),str(capture),str(execution)],label,out,report,bindings,120)
                    actual=json.loads(result.stdout);checks+=validate_payload(actual,case,mode=='resume')+validate_cut(actual,case)+validate_journal(actual,case,mode=='resume')
                    work=json.loads(execution.read_text());prefix,suffix=validate_execution(work,case,tier=='native',mode=='resume')
                    origin=dict(sha256=sha(checkpoint),ticks=actual['origin_ticks'],frame=0,native_steps=work['prefix_native'],interpreter_steps=work['prefix_interpreted'])
                    validate_capture(json.loads(capture.read_text()),case,tier=='native',False,origin if mode=='resume' else None)
                    paths=[capture,execution]
                    if mode=='write':
                        prefix_capture=Path(str(capture)+'.prefix.json');validate_capture(json.loads(prefix_capture.read_text()),case,tier=='native',True)
                        paths += [prefix_capture,checkpoint]
                    bindings['raw_outputs'].update({str(p):sha(p) for p in paths})
                    report['rows'].append(dict(case=case,tier=tier,mode=mode,label=label,prefix=prefix,suffix=suffix))
                    pair.append(actual)
                for key in ('cut','cut_source','reply','hits','origin_ticks','final_ticks','checkpoint_sha256','final_sha256'):
                    if pair[0][key]!=pair[1][key]:raise ValueError('Fresh-process continuation differs: '+key)
        report.update(result='pass',cases=len(cases()),gear_guest_cpu_calls=0,
            native_steps=sum(r['suffix']+(r['prefix'] if r['mode']=='write' else 0) for r in report['rows'] if r['tier']=='native'),
            interpreter_steps=sum(r['suffix']+(r['prefix'] if r['mode']=='write' else 0) for r in report['rows'] if r['tier']=='interpreter'))
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    from scripts.cd_adpcm_checkpoint_qualify import qualify
    result=qualify(out/'result.json');(out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:print(error,file=sys.stderr);raise SystemExit(1)
