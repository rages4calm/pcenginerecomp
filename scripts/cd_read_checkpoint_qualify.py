"""Rehash authored CD READ continuation evidence; never rerun a guest."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from cd_read_checkpoint_fixture import cases,hits,validate_payload,validate_cut,validate_gear_cut
from scripts.cd_read_checkpoint_reference import COMMIT,sha,sources,validate_capture,validate_execution
from pcerecomp.project import source_identity

BUILD_LABELS=frozenset({'gear-link','tool-configure','tool-build'})

def validate_stderr(label,text):
    """Successful build diagnostics are retained, guest stderr stays exact-empty.

    Process success and complete raw bindings are checked independently. CMake
    can emit a nonfatal object-path warning during a successful configuration;
    treating it as a guest protocol failure would discard valid execution.
    """
    if label not in BUILD_LABELS and text:
        raise ValueError('Unexpected actual execution stderr: '+label)

def load(path):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate evidence field')
            result[key]=value
        return result
    def constant(value):raise ValueError('Nonfinite evidence number')
    return json.loads(Path(path).read_text(),object_pairs_hook=unique,parse_constant=constant)

def qualify(path):
    path=Path(path).resolve();out=path.parent;r=load(path)
    fields={'schema','result','oracle_commit','tool','tool_root','commands','bindings','rows','scope','not_checked','gear_git_blobs','cases','gear_guest_cpu_calls','native_steps','interpreter_steps','preservation','processes'}
    if set(r)!=fields or type(r['schema']) is not int or r['schema']!=1 or r['result']!='pass' or r['oracle_commit']!=COMMIT:raise ValueError('Reference result/schema differs')
    groups={'tools','authored_sources','reference_raw_sources','reference_compile_sources','external_libraries','gear_objects','gear_binary','tool_build_inputs','tool_objects','tool_binary','fixtures','raw_outputs'}
    b=r['bindings']
    if set(b)!=groups or set(r['preservation'])!=groups or any(v is not True for v in r['preservation'].values()):raise ValueError('Complete bindings/preservation required')
    count=0
    for group,table in b.items():
        if type(table) is not dict or not table:raise ValueError('Nonempty binding table required')
        for name,digest in table.items():
            if type(name) is not str or not Path(name).is_absolute() or type(digest) is not str or sha(name)!=digest:raise ValueError('Changed bound artifact: '+str(name))
            count+=1
    tool=Path(r['tool_root'])
    if r['tool']!=source_identity(tool) or b['authored_sources']!=sources(tool):raise ValueError('Exact toolkit revision or complete authored sources differ')
    raw=b['reference_raw_sources'];checkouts={str(Path(name).resolve().parents[1]) for name in raw if name.replace('\\','/').endswith('/src/input.h')}
    if len(checkouts)!=1:raise ValueError('Original checkout binding differs')
    tree=subprocess.check_output(['git','-C',next(iter(checkouts)),'ls-tree','-r',COMMIT],text=True).splitlines()
    originals={line.split('\t',1)[1]:line.split()[2] for line in tree}
    prefixes=('src/','platforms/shared/dependencies/miniz/','platforms/shared/dependencies/minivorbis/','platforms/shared/dependencies/qon/','platforms/shared/dependencies/json/','platforms/shared/dependencies/libchdr/include/')
    required={name:digest for name,digest in originals.items() if name.startswith(prefixes) and Path(name).suffix in ('.c','.cpp','.h','.hpp')}
    if r['gear_git_blobs']!=required:raise ValueError('Complete original Git blob set differs')
    pinned=out/'pinned-reference-source'
    if set(b['reference_compile_sources'])!={str(pinned/name) for name in required}:raise ValueError('Complete compile-source set differs')
    for name,digest in required.items():
        data=(pinned/name).read_bytes()
        if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=digest:raise ValueError('Original Git source changed')
    if (type(r['commands']) is not list or any(type(c) is not list or any(type(v) is not str for v in c) for c in r['commands']) or
        type(r['processes']) is not list or any(type(p) is not dict or set(p)!={'label','returncode'} or type(p['label']) is not str or type(p['returncode']) is not int for p in r['processes'])):raise ValueError('Actual process/command types differ')
    matrix=cases();labels=['gear-link','tool-configure','tool-build']
    expected_rows=[dict(case=c,tier=tier,mode=mode,label=c['id']+'-'+tier+'-'+mode,prefix=sum(hits(c,True).values()),suffix=sum(hits(c).values()))
        for c in matrix for tier in ('interpreter','native') for mode in ('write','resume')]
    if json.dumps(r['rows'],sort_keys=True)!=json.dumps(expected_rows,sort_keys=True):raise ValueError('Actual matrix/expected work differs')
    labels += [c['id']+'-gear' for c in matrix]+[row['label'] for row in expected_rows]
    if sorted(r['processes'],key=lambda p:p['label'])!=sorted([dict(label=label,returncode=0) for label in labels],key=lambda p:p['label']):raise ValueError('Complete actual successful process set differs')
    raw_paths={str(out/(label+'.'+suffix)) for label in labels for suffix in ('stdout','stderr')}
    for row in expected_rows:
        raw_paths|={str(out/(row['label']+suffix)) for suffix in ('-capture.json','-execution.json')}
        if row['mode']=='write':raw_paths|={str(out/(row['label']+'-capture.json.prefix.json')),str(out/(row['case']['id']+'-'+row['tier']+'.pcec'))}
    if set(b['raw_outputs'])!=raw_paths:raise ValueError('Complete raw output/checkpoint binding set differs')
    module=out/'fixture';manifest=load(module/'module.json')
    generated={'module.json','module.cpp','cd_read_checkpoint_fixture.hpp'}
    fixture_paths={str(out/name) for name in ('authored.pce','data.bin','data.cue')}|{str(module/name) for name in generated}|{str(out/(c['id']+'.plan')) for c in matrix}
    if set(b['fixtures'])!=fixture_paths:raise ValueError('Complete fixture/module binding set differs')
    from cd_read_checkpoint_fixture import pattern,authored_rom,header,source_memory,SITES,MPR
    from pcerecomp.analysis import Snapshot,analyze
    from pcerecomp.emitter import emit
    snapshot=Snapshot(MPR,source_memory(),tuple(pc for pc,_,_ in SITES),'authored-cd-read-checkpoint-v1')
    # Re-emission uses only the trusted literal authored fixture, never a report
    # expression. Static CFG manifests do not carry observed-module file hashes.
    with tempfile.TemporaryDirectory() as temp:
        expected_module=Path(temp);emit(analyze(snapshot),expected_module)
        if any((expected_module/name).read_bytes()!=(module/name).read_bytes() for name in ('module.cpp','module.json')):
            raise ValueError('Literal static native module emission differs')
    if (out/'authored.pce').read_bytes()!=authored_rom() or (module/'cd_read_checkpoint_fixture.hpp').read_text()!=header():raise ValueError('Authored ROM/source header differs')
    if (out/'data.bin').read_bytes()!=b''.join(bytes(pattern(lba)) for lba in range(4)):raise ValueError('Authored data pattern differs')
    if (out/'data.cue').read_text()!='FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n':raise ValueError('Authored CUE differs')
    binary=out/'tool-build'/('cd-checkpoint.exe' if sys.platform=='win32' else 'cd-checkpoint');gear=out/'gear-cd-checkpoint.exe'
    if set(b['tool_binary'])!={str(binary)} or set(b['gear_binary'])!={str(gear)}:raise ValueError('Actual binary association differs')
    checks=joins=0;native=interpreted=0
    for case in matrix:
        plan=out/(case['id']+'.plan');args=[str(plan),str(out/'authored.pce'),str(out/'data.cue')]
        if plan.read_text()!=f"{case['cut']} {case['automatic']} {case['divisor']}\n":raise ValueError('Authored case plan differs')
        label=case['id']+'-gear';g=load(out/(label+'.stdout'));checks+=validate_payload(g,case)+validate_gear_cut(g,case)
        if type(g.get('guest_cpu_calls')) is not int or g['guest_cpu_calls']!=0:raise ValueError('Gear scope differs')
        if r['commands'].count([str(gear),*args])!=1:raise ValueError('Original command association differs')
        joins+=1
        for tier in ('interpreter','native'):
            pair=[];checkpoint=out/(case['id']+'-'+tier+'.pcec')
            for mode in ('write','resume'):
                label=case['id']+'-'+tier+'-'+mode;capture=out/(label+'-capture.json');execution=out/(label+'-execution.json')
                if r['commands'].count([str(binary),*args,mode,tier,str(checkpoint),str(capture),str(execution)])!=1:raise ValueError('Actual continuation command association differs')
                actual=load(out/(label+'.stdout'));checks+=validate_payload(actual,case,mode=='resume')+validate_cut(actual,case);work=load(execution)
                prefix,suffix=validate_execution(work,case,tier=='native',mode=='resume')
                origin=dict(sha256=sha(checkpoint),ticks=actual['origin_ticks'],frame=0,native_steps=work['prefix_native'],interpreter_steps=work['prefix_interpreted'])
                validate_capture(load(capture),case,tier=='native',False,origin if mode=='resume' else None)
                if actual['checkpoint_sha256']!=sha(checkpoint) or actual['hits']!={str(k):v for k,v in hits(case).items()}:raise ValueError('Checkpoint/per-source suffix association differs')
                if mode=='write':validate_capture(load(str(capture)+'.prefix.json'),case,tier=='native',True)
                total=suffix+(prefix if mode=='write' else 0)
                if tier=='native':native+=total
                else:interpreted+=total
                pair.append(actual);joins+=1
            if any(pair[0][k]!=pair[1][k] for k in ('cut','timing','cut_source','reply','hits','origin_ticks','final_ticks','checkpoint_sha256','final_sha256')):raise ValueError('Fresh-process canonical continuation differs')
    for label in labels:
        validate_stderr(label,(out/(label+'.stderr')).read_text())
    wanted=dict(cases=32,gear_guest_cpu_calls=0,native_steps=native,interpreter_steps=interpreted)
    if any(type(r[k]) is not int or r[k]!=v for k,v in wanted.items()):raise ValueError('Actual total work/counts differ')
    return dict(schema=1,result='pass',receipt_sha256=sha(path),tool=r['tool'],bindings=count,original_git_blobs=len(required),
                cases=32,actual_process_joins=joins,native_steps=native,interpreter_steps=interpreted,gear_guest_cpu_calls=0,
                literal_payload_checks=checks,fresh_restoring_processes=64,scope=r['scope'],not_checked=r['not_checked'])

def controls(path,out):
    path=Path(path).resolve();out=Path(out).resolve()
    if out.exists() or not out.is_relative_to(path.parent):raise ValueError('New receipt-local controls directory required')
    out.mkdir();original=load(path);rows=[]
    mutations=[('native-count',lambda r:r.__setitem__('native_steps',r['native_steps']+1)),
        ('original-cpu-scope',lambda r:r.__setitem__('gear_guest_cpu_calls',1)),
        ('tool-revision',lambda r:r['tool'].__setitem__('revision','0'*40)),
        ('missing-outputs',lambda r:r['bindings'].pop('raw_outputs')),
        ('wrong-case',lambda r:r['rows'][0]['case'].__setitem__('cut',7)),
        ('missing-process',lambda r:r['processes'].pop()),
        ('lost-git-blob',lambda r:r['gear_git_blobs'].pop(next(iter(r['gear_git_blobs'])))),
        ('unpreserved',lambda r:r['preservation'].__setitem__('fixtures',False)),
        ('boolean-schema',lambda r:r.__setitem__('schema',True)),
        ('boolean-returncode',lambda r:r['processes'][0].__setitem__('returncode',False))]
    for name,mutate in mutations:
        changed=copy.deepcopy(original);mutate(changed);file=path.parent/('changed-cd-read-'+name+'.json')
        with file.open('x') as stream:json.dump(changed,stream,indent=2)
        try:qualify(file)
        except (ValueError,OSError,KeyError) as error:rows.append(dict(control=name,path=str(file),sha256=sha(file),refused=str(error)))
        else:raise ValueError('Changed-copy control admitted: '+name)
    (out/'result.json').write_text(json.dumps(dict(result='pass',refused=rows),indent=2)+'\n');return rows

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('receipt',type=Path);parser.add_argument('--written-controls',type=Path);args=parser.parse_args()
    result=qualify(args.receipt)
    if args.written_controls:result['written_changed_copies_refused']=len(controls(args.receipt,args.written_controls))
    print(json.dumps(result,indent=2))
