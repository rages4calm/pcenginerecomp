"""Observe every retirement of authored native spans against original Gear.

Fresh interpreted execution supplies the only captured translations. Each
native limit uses the same compiled module and independent CPU/source literals.
Outer-call reduction is reported separately from any elapsed-time benchmark.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from scripts import context_reference as original
from scripts import stable_context_reference as context
from scripts import filtered_audio_reference as infrastructure
from scripts import hucard_reference as common
from scripts.mapper_reference import cmake_quote
from generate_context_fixture import generate,STEPS

LIMITS=(1,2,16,256)
sha=infrastructure.sha


def work(raw,native,limit):
    if not raw.startswith('SPAN_WORK '):
        raise ValueError('Missing actual span work report')
    value=json.loads(raw[len('SPAN_WORK '):])
    fields={'native','interpreted','limit','calls','attempts','after','max_batch',
            'guards','literal_checks','batches','generated_calls','local_continuations'}
    if (type(value)is not dict or set(value)!=fields or
            any(type(value[k])is not int or value[k]<0 for k in fields-{'batches'})):
        raise ValueError('Invalid span work schema')
    guards=sum((2+len(key[3]))*hits for key,hits in context.expected_sources().items())
    if (value['native']!=(2*STEPS if native else 0) or
            value['interpreted']!=(0 if native else 2*STEPS) or value['limit']!=limit or
            value['attempts']!=2*STEPS or value['after']!=2*STEPS or
            value['guards']!=(guards if native else 0) or value['literal_checks']!=40*STEPS):
        raise ValueError('Actual span tier/callback/guard/literal work differs')
    batches=value['batches']
    if (type(batches)is not list or not batches or
            any(type(v)is not int or not 1<=v<=min(limit,STEPS) for v in batches) or
            value['calls']!=len(batches) or sum(batches)!=2*STEPS or
            value['max_batch']!=max(batches)):
        raise ValueError('Actual span call/retirement partition differs')
    partial=0
    for size in batches:
        if partial<STEPS<partial+size:
            raise ValueError('Span batch crosses independently reset CPU case')
        partial+=size
    if limit==1:
        if (value['calls']!=2*STEPS or value['max_batch']!=1 or value['local_continuations']!=0 or
                value['generated_calls']!=(2*STEPS if native else 0)):
            raise ValueError('Limit-one reference is not single retirement')
    elif native and (value['calls']>=2*STEPS or value['max_batch']<=1):
        raise ValueError('Native span did not execute multiple actual retirements')
    if native:
        if (not value['calls']<=value['generated_calls']<=2*STEPS or
                value['local_continuations']!=2*STEPS-value['generated_calls'] or
                (limit>1 and value['local_continuations']==0)):
            raise ValueError('Native span dispatch/local-continuation evidence differs')
    elif value['generated_calls'] or value['local_continuations']:
        raise ValueError('Interpreter bootstrap claims native dispatch work')
    return value


def qualify(gear_raw,bootstrap_raw,bootstrap_work,bootstrap_capture,
            native_cases,manifest,bootstrap_capture_sha256):
    context.records(gear_raw);context.records(bootstrap_raw)
    baseline=work(bootstrap_work,False,1)
    if type(native_cases)is not list or len(native_cases)!=len(LIMITS):
        raise ValueError('Require every declared native span limit')
    reports=[]
    for expected,case in zip(LIMITS,native_cases):
        if type(case)is not dict or set(case)!={'limit','raw','capture','work'} or type(case['limit'])is not int or case['limit']!=expected:
            raise ValueError('Native span case identity/extent differs')
        base=context.qualify(gear_raw,bootstrap_raw,case['raw'],bootstrap_capture,
                             case['capture'],manifest,bootstrap_capture_sha256)
        observed=work(case['work'],True,expected)
        reports.append(dict(limit=expected,work=observed,source_identities=base['native']['source_identities']))
    marker=manifest.get('native_span')
    if (type(marker)is not dict or set(marker)!={'schema','protocol'} or
            type(marker['schema'])is not int or marker['schema']!=1 or
            marker['protocol']!='per_instruction_v1'):
        raise ValueError('Manifest does not declare the observed span protocol')
    return dict(records_per_engine=2*STEPS,literal_checks=(2+len(LIMITS))*40*STEPS,
                interpreted=baseline, native=reports,
                native_instructions=sum(row['work']['native']for row in reports),
                source_identities=len(context.expected_sources()),
                executed_parts=base['executed_parts'],full_mpr_contexts=base['full_mpr_contexts'],
                logical_pc_buckets=base['logical_pc_buckets'],
                scope='Per-retirement original-Gear/independent state and full source-hit equality; actual outer-call partitions, not elapsed speed or hardware conformance.')


def build_tool(args,out,report,bindings,compiler,fixture):
    tool=args.tool_source.resolve()
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja))
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    wrapper=out/'tool-wrapper';wrapper.mkdir()
    source=ROOT/'tests/context_span_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(NativeSpanProof LANGUAGES CXX)',
        *['set('+name+' OFF CACHE BOOL "" FORCE)'for name in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
        f'add_subdirectory({cmake_quote(tool)} tool)',
        f'pce_add_native_module(_module MODULE {cmake_quote(fixture/"module.cpp")} MANIFEST {cmake_quote(fixture/"module.json")})',
        f'add_executable(context-span-probe {cmake_quote(source)})',
        f'target_include_directories(context-span-probe PRIVATE {cmake_quote(fixture)} {cmake_quote(ROOT/"tests")})',
        'target_link_libraries(context-span-probe PRIVATE ${_module} pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n')
    bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file);build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                     '-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],
                    'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','context-span-probe','--parallel','2'],
                    'tool-build',out,report,bindings,600)
    binary=build/('context-span-probe.exe'if os.name=='nt'else'context-span-probe')
    bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary)
    return binary


def run(args):
    tool,out=args.tool_source.resolve(),args.out.resolve()
    compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():
        raise ValueError('NEW private output and existing compiler required')
    sys.path.insert(0,str(tool))
    from pcerecomp import project
    from pcerecomp.capture import load_capture
    from pcerecomp.emitter import emit_capture
    if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py':
        raise ValueError('Exact selected source import required')
    sources=[Path(__file__),ROOT/'scripts/stable_context_reference.py',ROOT/'scripts/context_reference.py',
        ROOT/'tests/context_span_probe.cpp',ROOT/'tests/generate_context_fixture.py',
        ROOT/'tests/geargrafx_context_probe.cpp',ROOT/'tests/geargrafx_mapper_probe.cpp',
        ROOT/'tests/reset_probe_support.hpp',*[ROOT/'scripts'/name for name in
        ('mapper_reference.py','hucard_reference.py','filtered_audio_reference.py')]]
    sources+=sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p)for p in sources})
    report=dict(schema=1,result='incomplete',commands=[],bindings=bindings,oracle_commit=infrastructure.COMMIT,
        scope='Fresh authored interpretation supplies span translations; same native module runs limits1/2/16/256 against original separate Gear and independent every-retirement CPU/source literals.')
    out.mkdir(parents=True);epoch=out/'authored-inputs';epoch.mkdir();bindings['authored_epoch']={}
    for index,path in enumerate(sources):
        saved=epoch/str(index)/path.name;saved.parent.mkdir();shutil.copyfile(path,saved)
        bindings['authored_epoch'][str(saved)]=sha(saved)
    try:
        fixture=out/'fixture';generate(fixture,spread=True)
        bindings['fixture']={str(p):sha(p)for p in fixture.iterdir()if p.is_file()}
        rom=fixture/'authored.pce';gear=original.build_gear(args,out,report,bindings,compiler)
        golden=common.evidence([str(gear),str(rom)],'gear',out,report,bindings);context.records(golden.stdout)
        bootstrap_dir=out/'bootstrap';bootstrap_dir.mkdir()
        bootstrap_binary=build_tool(args,bootstrap_dir,report,bindings,compiler,fixture)
        capture_path=out/'bootstrap-capture.json'
        bootstrap=common.evidence([str(bootstrap_binary),'--probe',str(rom),'interpreted',str(capture_path)],
                                  'bootstrap',out,report,bindings)
        discovery,digest=load_capture(capture_path);bindings['raw_outputs'][str(capture_path)]=digest
        context.capture_work(discovery,False);context.records(bootstrap.stdout);work(bootstrap.stderr,False,1)
        module=out/'span-module'
        manifest=emit_capture(discovery,module,digest,partition_layout='stable',native_span=True)
        for name in('authored.pce','context_fixture.hpp'):shutil.copyfile(fixture/name,module/name)
        bindings['span_module']={str(p):sha(p)for p in module.iterdir()if p.is_file()}
        native_dir=out/'native';native_dir.mkdir()
        native_binary=build_tool(args,native_dir,report,bindings,compiler,module)
        cases=[]
        for limit in LIMITS:
            capture_path=out/f'native-{limit}-capture.json'
            result=common.evidence([str(native_binary),'--probe',str(rom),'native',str(capture_path),str(limit)],
                                   f'native-{limit}',out,report,bindings)
            capture,digest_native=load_capture(capture_path)
            bindings['raw_outputs'][str(capture_path)]=digest_native
            cases.append(dict(limit=limit,raw=result.stdout,capture=capture,work=result.stderr))
        arguments=dict(gear_raw=golden.stdout,bootstrap_raw=bootstrap.stdout,bootstrap_work=bootstrap.stderr,
                       bootstrap_capture=discovery,native_cases=cases,manifest=manifest,bootstrap_capture_sha256=digest)
        admission=out/'admission.json';admission.write_text(json.dumps(arguments,indent=2)+'\n')
        bindings['qualification_inputs']={str(admission):sha(admission)}
        report.update(result='pass',tool=project.source_identity(tool),qualification=qualify(**arguments),
                      admission=str(admission),capture_sha256=digest,
                      bootstrap_binary=str(bootstrap_binary),native_binary=str(native_binary))
    except Exception as error:
        report.update(result='fail',error=str(error));raise
    finally:
        infrastructure.record_preservation(report,bindings)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Native span evidence preservation failed')
    print(json.dumps({key:value for key,value in report.items()if key not in('commands','bindings')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True)
    parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake')
    parser.add_argument('--ninja',default='ninja');parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:
        print(error,file=sys.stderr);raise SystemExit(1)
