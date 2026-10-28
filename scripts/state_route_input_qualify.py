"""Requalify retained input-latch evidence; no guest execution or source mutation."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from state_route_input_fixture import plans, program, serialize, validate_events
from scripts import hucard_reference as common
from scripts.state_route_input_reference import COMMIT, sha, validate_capture, validate_execution, bound_sources
from pcerecomp.project import source_identity

GROUPS={'tools','authored_sources','reference_raw_sources','reference_compile_sources','external_libraries',
        'gear_objects','gear_binary','tool_build_inputs','tool_build_artifacts','tool_binaries','fixtures',
        'raw_outputs','generated_module'}


def qualify(path):
    path=Path(path).resolve();out=path.parent;report=json.loads(path.read_text())
    fields={'schema','result','oracle_commit','tool','tool_root','commands','bindings','cases','scope','not_checked',
            'gear_git_blobs','native_steps','interpreter_steps','gear_cpu_calls','source_identities','preservation','processes'}
    if set(report)!=fields or type(report['schema']) is not int or report['schema']!=1 or report['result']!='pass' or report['oracle_commit']!=COMMIT:
        raise ValueError('Input receipt fields/result/original reference identity differ')
    if (not isinstance(report['commands'],list) or any(not isinstance(command,list) or
            any(type(arg) is not str for arg in command) for command in report['commands']) or
            not isinstance(report['processes'],list) or any(not isinstance(process,dict) or
            set(process)!={'label','returncode'} or type(process['label']) is not str or
            type(process['returncode']) is not int for process in report['processes'])):
        raise ValueError('Malformed actual input commands/process counts')
    bindings=report['bindings']
    if set(bindings)!=GROUPS or set(report['preservation'])!=GROUPS or any(v is not True for v in report['preservation'].values()):
        raise ValueError('Required input binding/preservation groups differ')
    count=0
    for group,items in bindings.items():
        if not isinstance(items,dict) or not items:raise ValueError('Empty input binding group '+group)
        for name,digest in items.items():
            if not Path(name).is_absolute() or sha(Path(name))!=digest:raise ValueError('Input artifact changed: '+name)
            count+=1
    tool=Path(report['tool_root'])
    if report['tool']!=source_identity(tool):raise ValueError('Exact current toolkit revision/source identity differs')
    if bindings['authored_sources']!=bound_sources(tool):raise ValueError('Complete authored/toolkit source binding set differs')
    extension='.exe' if sys.platform=='win32' else ''
    if set(bindings['gear_binary'])!={str(out/'gear-input.exe')} or set(bindings['tool_binaries'])!={
            str(out/(tier+'-build')/('input-probe'+extension)) for tier in ('native','interpreted')}:
        raise ValueError('Actual input binary associations differ')
    # Verify raw immutable Git bytes, rather than trusting only a HEAD label.
    pinned=out/'pinned-reference-source';blobs=report['gear_git_blobs']
    raw_sources=bindings['reference_raw_sources'];checkouts={str(Path(name).resolve().parents[len(Path(relative).parts)-1])
        for name in raw_sources for relative in ('src/input.h',) if name.replace('\\','/').endswith('/'+relative)}
    if len(checkouts)!=1:raise ValueError('Original input reference checkout association differs')
    checkout=Path(next(iter(checkouts)))
    rows=subprocess.check_output(['git','-C',str(checkout),'ls-tree','-r',COMMIT],text=True).splitlines()
    actual_blobs={row.split('\t',1)[1]:row.split()[2] for row in rows}
    prefixes=('src/','platforms/shared/dependencies/miniz/','platforms/shared/dependencies/minivorbis/',
              'platforms/shared/dependencies/qon/','platforms/shared/dependencies/json/',
              'platforms/shared/dependencies/libchdr/include/')
    required_blobs={name:digest for name,digest in actual_blobs.items()
                    if name.startswith(prefixes) and Path(name).suffix in ('.c','.cpp','.h','.hpp')}
    if blobs!=required_blobs or len(blobs)!=len(bindings['reference_compile_sources']):
        raise ValueError('Input original source coverage differs')
    for name,digest in blobs.items():
        file=pinned/name;raw=file.read_bytes()
        git_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if git_blob!=digest or actual_blobs.get(name)!=digest or bindings['reference_compile_sources'].get(str(file))!=sha(file):
            raise ValueError('Pinned original Git source differs: '+name)
    cases=plans();expected_count=sum(c['instructions'] for c in cases)
    if set(bindings['fixtures'])!={str(out/(c['id']+suffix)) for c in cases for suffix in ('.plan','.code')}|{str(out/'actual-union.json')}:
        raise ValueError('Complete authored input fixture binding set differs')
    labels=[tier+'-'+c['id'] for tier in ('gear','interpreted','native') for c in cases]
    labels+=['gear-link','interpreted-configure','interpreted-build','native-configure','native-build']
    raw={str(out/(label+'.'+suffix)) for label in labels for suffix in ('stdout','stderr')}
    raw|={str(out/(tier+'-'+c['id']+suffix)) for tier in ('interpreted','native') for c in cases for suffix in ('-capture.json','-execution.json')}
    if set(bindings['raw_outputs'])!=raw:raise ValueError('Complete actual input output binding set differs')
    if any(type(report[key]) is not int or report[key]!=expected_count for key in ('native_steps','interpreter_steps','gear_cpu_calls')):
        raise ValueError('Actual input work totals differ')
    if len(report['cases'])!=len(cases):raise ValueError('Input case count differs')
    captures=[];joins=checks=0
    for row,case in zip(report['cases'],cases):
        if (set(row)!={'plan','literal_checks'} or json.dumps(row['plan'],sort_keys=True)!=json.dumps(case,sort_keys=True) or
                set(row['literal_checks'])!={'gear','interpreted','native'}):
            raise ValueError('Input authored case contract differs')
        plan,code=out/(case['id']+'.plan'),out/(case['id']+'.code')
        for file in (plan,code):
            if bindings['fixtures'].get(str(file))!=sha(file):raise ValueError('Input case file association differs')
        if plan.read_text()!=serialize(case) or code.read_bytes()!=bytes(v for r in program(case['delay'])[0] for v in r['data']):
            raise ValueError('Authored input plan/program differs')
        for tier in ('gear','interpreted','native'):
            label=tier+'-'+case['id'];stdout=out/(label+'.stdout');stderr=out/(label+'.stderr')
            if any(bindings['raw_outputs'].get(str(p))!=sha(p) for p in (stdout,stderr)) or stderr.read_text():
                raise ValueError('Raw actual input output association differs')
            if report['processes'].count(dict(label=label,returncode=0))!=1:
                raise ValueError('Actual successful input process association differs')
            binary=next((Path(p) for p in bindings['gear_binary'] if tier=='gear'),None)
            if tier!='gear':
                binary=out/(tier+'-build')/('input-probe.exe' if sys.platform=='win32' else 'input-probe')
            command=[str(binary),str(plan),str(code)]
            events=json.loads(stdout.read_text())
            if tier=='gear':
                if events.pop()!=dict(kind='gear_cpu_calls',values=[case['instructions']]):raise ValueError('Original input CPU call count differs')
            else:
                capture,work=out/(label+'-capture.json'),out/(label+'-execution.json')
                command += [str(capture),str(work)]
                if any(bindings['raw_outputs'].get(str(p))!=sha(p) for p in (capture,work)):
                    raise ValueError('Capture/execution binding association differs')
                validate_execution(json.loads(work.read_text()),case,tier=='native')
                captured=validate_capture(json.loads(capture.read_text()),case,tier=='native')
                if tier=='interpreted':captures.append(captured)
            if report['commands'].count(command)!=1:raise ValueError('Actual input command association differs')
            literal=validate_events(events,case)
            if type(row['literal_checks'][tier]) is not int or row['literal_checks'][tier]!=literal:
                raise ValueError('Input literal check count differs')
            checks+=literal;joins+=1
    union=common.compose_captures(captures)
    if (bindings['fixtures'].get(str(out/'actual-union.json'))!=sha(out/'actual-union.json') or
            json.loads((out/'actual-union.json').read_text())!=union or report['source_identities']!=len(union['observations'])):
        raise ValueError('Input actual capture union differs')
    manifest=json.loads((out/'native-module/module.json').read_text())
    if (manifest['code_capture_sha256']!=sha(out/'actual-union.json') or
            manifest['native_instructions_emitted']!=len(union['observations']) or manifest['unsupported_observations'] or manifest['excluded_observations']):
        raise ValueError('Input native module source accounting differs')
    generated={'module.json',*[item['file'] for key in ('translation_units','generated_headers') for item in manifest[key]]}
    if set(bindings['generated_module'])!={str(out/'native-module'/name) for name in generated}:
        raise ValueError('Input complete native module binding set differs')
    for key in ('translation_units','generated_headers'):
        for item in manifest[key]:
            if sha(out/'native-module'/item['file'])!=item['sha256']:
                raise ValueError('Input emitted file/manifest association differs')
    return dict(schema=1,result='pass',receipt_sha256=sha(path),bindings=count,original_git_blobs=len(blobs),
                actual_execution_joins=joins,cases=len(cases),polls_per_case=8,source_identities=len(union['observations']),
                native_steps=expected_count,interpreter_steps=expected_count,gear_cpu_calls=expected_count,
                independent_scalar_checks=checks,scope=report['scope'],not_checked=report['not_checked'])


def written_controls(path,out):
    """Each rejection is an actual written changed receipt, originals preserved."""
    path=Path(path).resolve();out=Path(out).resolve()
    if out.exists() or not out.is_relative_to(path.parent):raise ValueError('Require new receipt-local control directory')
    out.mkdir();original=json.loads(path.read_text());rows=[]
    mutations=[('native-count',lambda r:r.__setitem__('native_steps',r['native_steps']+1)),
               ('gear-count',lambda r:r.__setitem__('gear_cpu_calls',r['gear_cpu_calls']-1)),
               ('tool-revision',lambda r:r['tool'].__setitem__('revision','0'*40)),
               ('missing-bindings',lambda r:r['bindings'].pop('raw_outputs')),
               ('wrong-case',lambda r:r['cases'][0]['plan'].__setitem__('divisor',12)),
               ('check-count',lambda r:r['cases'][0]['literal_checks'].__setitem__('gear',0)),
               ('lost-process',lambda r:r.__setitem__('processes',r['processes'][:-1])),
               ('wrong-source-count',lambda r:r.__setitem__('source_identities',0)),
               ('wrong-reference',lambda r:r.__setitem__('oracle_commit','0'*40)),
               ('unverified-preservation',lambda r:r['preservation'].__setitem__('gear_objects',False)),
               ('boolean-schema',lambda r:r.__setitem__('schema',True)),
               ('boolean-process-result',lambda r:r['processes'][0].__setitem__('returncode',False))]
    # Receipts stay beside their original artifacts, so even semantic controls
    # preserve their original path associations and cannot fail just by moving.
    for name,mutate in mutations:
        value=copy.deepcopy(original);mutate(value);file=path.parent/('changed-input-'+name+'.json')
        with file.open('x') as stream:json.dump(value,stream,indent=2)
        try:qualify(file)
        except (ValueError,OSError,KeyError) as error:rows.append(dict(control=name,path=str(file),sha256=sha(file),refused=str(error)))
        else:raise ValueError('Written changed-copy input control admitted: '+name)
    (out/'result.json').write_text(json.dumps(dict(result='pass',refused=rows),indent=2)+'\n')
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('receipt',type=Path)
    parser.add_argument('--written-controls',type=Path);args=parser.parse_args()
    result=qualify(args.receipt)
    if args.written_controls:result['written_changed_copies_refused']=len(written_controls(args.receipt,args.written_controls))
    print(json.dumps(result,indent=2))
