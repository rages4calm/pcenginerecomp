"""Authored active-display IRQ/ADPCM overlap with exact checkpoint continuation.

Original Gear calls and callback phases remain unadjusted. A live IRQ1 may
precede target entry; this is not a claim that both causes arise in the wait.
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
from tests.active_irq_fixture import cases,fixtures,program,expected_vram,MPR,LIMIT
from scripts import mapper_reference as infra,filtered_audio_reference as reference,hucard_reference as common
from pcerecomp.project import source_identity,ABI

COMMIT=reference.COMMIT
sha=lambda path:reference.sha(Path(path))

def require(value,message):
    if not value: raise ValueError(message)

def source_bindings(tool):
    paths=[ROOT/name for name in (
        'scripts/active_irq_reference.py','scripts/active_irq_qualify.py',
        'tests/active_irq_fixture.py','tests/active_irq_support.hpp',
        'tests/active_irq_probe.cpp','tests/geargrafx_active_irq_probe.cpp',
        'tests/geargrafx_active_irq_observer.hpp','tests/test_active_irq_fixture.py',
        'tests/test_active_irq_reference.py','tests/test_active_irq_native.py','tests/vdc_adpcm_irq_fixture.py',
        'tests/dma_irq_checkpoint_fixture.py','tests/reset_probe_support.hpp',
        'scripts/mapper_reference.py','scripts/filtered_audio_reference.py',
        'scripts/psg_reference.py','scripts/hucard_reference.py')]
    # Conservatively bind the authored Python/helper closure, including imports
    # used by fixture generation and independent admission. A binding is not an
    # assertion that every helper or test was executed by this reference run.
    paths += sorted((ROOT/'scripts').glob('*.py'))
    paths += sorted((ROOT/'tests').glob('*.py'))+sorted((ROOT/'tests').glob('*.hpp'))
    paths += [tool/'CMakeLists.txt']+sorted((tool/'pcerecomp').glob('*.py'))
    paths += sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))
    paths += sorted((tool/'cmake').rglob('*.cmake'))
    return {str(path.resolve()):sha(path) for path in paths}

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(value)) or '').resolve() for value in (args.cmake,args.ninja))
    require(cmake.is_file() and ninja.is_file(),'CMake and Ninja required')
    bindings['tools'].update({str(path):sha(path) for path in (cmake,ninja)})
    quote=infra.cmake_quote
    wrapper=out/'wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(ActiveIrq LANGUAGES CXX)',
        *['set('+key+' OFF CACHE BOOL "" FORCE)' for key in (
            'BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],
        f'add_subdirectory({quote(args.tool_source.resolve())} tool)',
        f'pce_add_native_module(_module MODULE {quote(fixture/"module.cpp")} MANIFEST {quote(fixture/"module.json")})',
        f'add_executable(active-irq {quote(ROOT/"tests/active_irq_probe.cpp")})',
        f'target_include_directories(active-irq PRIVATE {quote(fixture)} {quote(ROOT/"tests")})',
        'target_link_libraries(active-irq PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    bindings['tool_build_inputs']={str(config):sha(config)}
    build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja',
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),
        '-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','active-irq','--parallel','4'],
        'tool-build',out,report,bindings,600)
    binary=build/('active-irq.exe' if os.name=='nt' else 'active-irq')
    bindings['tool_binary']={str(binary):sha(binary)}
    bindings['tool_objects']={str(path):sha(path) for path in build.rglob('*')
        if path.is_file() and (path.suffix in ('.o','.obj','.a') or
            path.name in ('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))}
    return binary

def build_gear(args,out,report,bindings,compiler,fixture):
    checkout,originals=infra.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,originals)
    cpp.append(ROOT/'tests/geargrafx_active_irq_probe.cpp')
    deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections',
           '-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (checkout/'src',ROOT/'tests',fixture,deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):
        flags += ['-I',str(path)]
    folder=out/'gear-objects';folder.mkdir();jobs=[];report['compilations']=[]
    for index,path in enumerate(cpp+c):
        obj=folder/(str(index)+'-'+path.stem+'.o')
        command=[str(compiler),*flags,'-x','c++' if path.suffix=='.cpp' else 'c',
            *(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),
            '-c',str(path),'-o',str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def compile_one(job):
        command,obj=job
        done=subprocess.run(command,capture_output=True,text=True,timeout=180)
        log=obj.with_suffix('.log');log.write_text(done.stdout+done.stderr,encoding='utf-8')
        report['compilations'].append(dict(object=str(obj),log=str(log),returncode=done.returncode))
        done.check_returncode()
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile_one,jobs))
    libraries=[path.resolve() for path in args.library]
    require(libraries and all(path.is_file() for path in libraries),'Explicit existing libraries required')
    bindings['external_libraries']={str(path):sha(path) for path in libraries}
    binary=out/'gear-active-irq.exe'
    common.evidence([str(compiler),*[str(obj) for _,obj in jobs],*map(str,libraries),
        '-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(obj):sha(obj) for _,obj in jobs}
    bindings['gear_compile_logs']={str(obj.with_suffix('.log')):sha(obj.with_suffix('.log')) for _,obj in jobs}
    bindings['gear_binary']={str(binary):sha(binary)}
    report['gear_git_blobs']={name:hashlib.sha1(b'blob '+str((checkout/name).stat().st_size).encode()+b'\0'+
        (checkout/name).read_bytes()).hexdigest() for name in originals}
    return binary

def parser():
    result=argparse.ArgumentParser(description=__doc__)
    result.add_argument('--gear-source',type=Path,required=True)
    result.add_argument('--tool-source',type=Path,default=ROOT)
    result.add_argument('--out',type=Path,required=True)
    result.add_argument('--compiler',default='clang++')
    result.add_argument('--cmake',default='cmake')
    result.add_argument('--ninja',default='ninja')
    result.add_argument('--library',type=Path,action='append',default=[])
    result.add_argument('--case',action='append',default=[],help='Explicit recipe subset for retained diagnostic pilots')
    result.add_argument('--cut',type=int,choices=(0,1,2),action='append',default=[],
                        help='Explicit natural cut subset for retained diagnostic pilots')
    return result

def run(args):
    from scripts.active_irq_qualify import validate_report,validate_capture,qualify
    out=args.out.resolve();tool=args.tool_source.resolve()
    compiler=Path(shutil.which(str(args.compiler)) or '').resolve()
    require(not out.exists() and out.is_relative_to(ROOT/'.local') and compiler.is_file(),
            'New private output and existing compiler required')
    import pcerecomp.project
    require(Path(pcerecomp.project.__file__).resolve()==tool/'pcerecomp/project.py',
            'Execute with the explicit toolkit source')
    known=cases();wanted=set(args.case) if args.case else {case['id'] for case in known}
    require(wanted and wanted<={case['id'] for case in known},'Unknown requested recipe')
    selected=[case for case in known if case['id'] in wanted]
    cuts=sorted(set(args.cut or [0,1,2]))
    out.mkdir(parents=True)
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources=source_bindings(tool))
    report=dict(schema=1,result='incomplete',oracle_commit=COMMIT,tool=source_identity(tool),
        tool_root=str(tool),commands=[],bindings=bindings,rows=[],scope=__doc__,
        plan=dict(cases=[case['id'] for case in selected],cuts=cuts,
                  complete_matrix=len(selected)==len(known) and cuts==[0,1,2]),
        not_checked=['Cross-core clock/callback partition equality','Exact native device-edge timestamps',
                     'Hardware','Retail','Both causes arising during every target wait'])
    try:
        fixture=fixtures(out)
        paths=list(out.glob('*.pce'))+[out/'data.bin',out/'data.cue']+list(fixture.iterdir())
        bindings['fixtures']={str(path):sha(path) for path in paths if path.is_file()}
        gear=build_gear(args,out,report,bindings,compiler,fixture)
        binary=build_tool(args,out,report,bindings,compiler,fixture)
        for case in selected:
            for cut in cuts:
                stem=case['id']+'-cut'+str(cut)
                arguments=[case['id'],str(out/(case['id']+'.pce')),str(out/'data.cue'),str(cut)]
                result=common.evidence([str(gear),*arguments],stem+'-gear',out,report,bindings,120)
                validate_report(json.loads(result.stdout),case,cut,gear=True)
                for tier in ('native','interpreter'):
                    checkpoint=out/(stem+'-'+tier+'.pcec');pair=[]
                    for mode in ('write','resume'):
                        label=stem+'-'+tier+'-'+mode
                        capture=out/(label+'-capture.json')
                        result=common.evidence([str(binary),*arguments,mode,tier,str(checkpoint),str(capture)],
                            label,out,report,bindings,120)
                        actual=json.loads(result.stdout)
                        require(actual.get('tier')==tier and actual.get('mode')==mode,
                                'Requested process differs from reported execution mode')
                        validate_report(actual,case,cut,resume=mode=='resume')
                        validate_capture(json.loads(capture.read_text()),actual,case,resume=mode=='resume')
                        paths=[capture]
                        if mode=='write':
                            prefix=Path(str(capture)+'.prefix.json')
                            validate_capture(json.loads(prefix.read_text()),actual,case,prefix=True)
                            paths += [prefix,checkpoint]
                            require(sha(checkpoint)==actual['checkpoint_sha256'],
                                    'Actual checkpoint file differs from reported imported identity')
                        bindings['raw_outputs'].update({str(path):sha(path) for path in paths})
                        report['rows'].append(dict(case=case,cut=cut,tier=tier,mode=mode,label=label))
                        pair.append(actual)
                    fields=('case','cut_id','tier','cut','final','window_work','window_hits','journal','ram','vram',
                        'window_provider_witnesses','prefix_native','prefix_interpreted','window_native',
                        'window_interpreted','origin_frame','checkpoint_sha256','final_sha256','prefix_blocks',
                        'prefix_block_bytes')
                    require(all(pair[0][key]==pair[1][key] for key in fields),
                            'Fresh same-tier checkpoint continuation differs')
        report['result']='pass'
    except Exception as error:
        report.update(result='fail',error=str(error))
        raise
    finally:
        reference.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    result=qualify(out/'result.json')
    (out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try:run(parser().parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr)
        raise SystemExit(1)
