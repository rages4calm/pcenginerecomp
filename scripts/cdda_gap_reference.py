"""Authored D8 admission versus unchanged original Gear CD/media/controller.

Toolkit mapped port instructions execute direct translated bodies or the
interpreter. Original Gear executes its real register/device implementation;
the supervisor advances the same explicit post-access clocks, without claiming
original CPU instruction retirement. Distance-dependent original seek timing
and the toolkit's bounded seek profile remain separate raw observations.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from generate_cdda_gap_fixture import generate,LAYOUTS,cases,authored_sources
from pcerecomp.project import ABI
from scripts import mapper_reference as infrastructure
from scripts import filtered_audio_reference as reference
from scripts import hucard_reference as common
sha=reference.sha

def require(ok,why):
    if not ok:raise ValueError(why)

def build_gear(args,out,report,bindings,compiler):
    source,hashes=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(source,hashes);cpp.append(ROOT/'tests/geargrafx_cdda_gap_probe.cpp')
    deps=source/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (source/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(path)]
    objects=out/'gear-objects';objects.mkdir();jobs=[]
    for i,path in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+path.stem+'.o')
        cmd=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((cmd,obj));report['commands'].append(cmd)
    def one(job):
        cmd,obj=job;result=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        obj.with_suffix('.log').write_text(result.stdout+result.stderr,encoding='utf8');result.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(one,jobs))
    libraries=[p.resolve()for p in args.library];require(libraries and all(p.is_file()for p in libraries),'Explicit existing reference libraries required')
    bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-cdda-gap.exe'
    common.evidence([str(compiler),*[str(p)for _,p in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_artifacts']={str(p):sha(p)for p in[binary,*[p for _,p in jobs]]};return binary

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja))
    require(cmake.is_file()and ninja.is_file(),'CMake and Ninja required');bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    q=infrastructure.cmake_quote;wrapper=out/'wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(CddaGap LANGUAGES CXX)',
        *['set('+k+' OFF CACHE BOOL "" FORCE)'for k in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
        f'add_subdirectory({q(args.tool_source.resolve())} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',
        f'add_executable(cdda-gap-probe {q(ROOT/"tests/cdda_gap_probe.cpp")})',f'target_include_directories(cdda-gap-probe PRIVATE {q(fixture)} {q(ROOT/"tests")})',
        'target_link_libraries(cdda-gap-probe PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n',encoding='utf8');bindings['tool_build_inputs']={str(config):sha(config)}
    build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('cdda-gap-probe.exe'if os.name=='nt'else'cdda-gap-probe')
    bindings['tool_artifacts']={str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.obj','.o','.a')or p==binary)};return binary

def validate_rows(rows,tier):
    definitions=cases();require(type(rows)is list and len(rows)==len(definitions),'Exact authored case extent required')
    literals=0
    for case,row in zip(definitions,rows):
        require(type(row)is dict and set(row)=={'case','kind','before','after','settled','status','message'},'Strict row fields')
        require(row['case']==case['id']and row['kind']==case['kind'],'Case identity differs')
        require(all(type(row[k])is int and 0<=row[k]<=999 for k in('status','message')),'Typed status/message required')
        for stage in('before','after','settled'):
            state=row[stage];require(type(state)is dict and set(state)=={'ticks','phase','signals','logical','seek_deadline','event','event_deadline'},'Strict raw state fields')
            for k in set(state)-{'logical'}:require(type(state[k])is int and 0<=state[k]<2**64,'Bounded integer state required')
            require(type(state['logical'])is list and len(state['logical'])==7 and all(type(x)is int and 0<=x<2**32 for x in state['logical']),'Audio/head state fields')
        before,after,end=(row[k]for k in('before','after','settled'))
        require(before['ticks']<after['ticks']<=end['ticks'],'Actual timeline must advance')
        require(before['logical'][0]=={'idle':1,'playing':0,'paused':2,'stopped':3,'seeking':0}[case['state']],'Guest-established audio state differs')
        require(before['phase']==(8 if case['state']=='seeking'else 0),'Guest-established controller state differs')
        if case['state']!='idle':
            seek_start=1 if tier!='gear'or case['state']=='seeking'else 10
            require(before['logical']==[{'playing':0,'paused':2,'stopped':3,'seeking':0}[case['state']],10,10,609,seek_start,0,10],'Guest-established audio position differs')
        else:require(before['logical']==[1,0,0,0,0,0,1],'Reset audio state differs')
        if case['kind']=='gap':
            require(after['logical']==before['logical']and after['seek_deadline']==before['seek_deadline'],'Ignored gap D8 changed audio/head/seek')
            busy=case['mode']!=0 or case['state']=='seeking'
            require(after['phase']==(8 if busy else 7)and after['signals']==(128 if busy else 216),'Original gap controller phase differs')
            if busy and case['state']!='seeking':
                require((row['status'],row['message'])==(999,999)and end['phase']==8 and end['signals']==128,'Gap BUSY must not invent completion')
                require(after['event']==0 and after['event_deadline']==0,'Gap BUSY unexpectedly scheduled controller event')
            else:require((row['status'],row['message'])==(0,0)and end['phase']==0,'Retained seek/GOOD completion differs')
            literals+=20
        elif case['kind']=='program':
            require(after['logical'][0]==(2 if case['mode']==0 else 0)and after['logical'][1:4]==[10,10,609],'Program start was not admitted')
            require(after['seek_deadline']>after['ticks']and(row['status'],row['message'])==(0,0)and end['phase']==0,'Program seek/completion differs');literals+=9
        else:
            require(after['logical']==before['logical'],'Out-of-range control changed audio')
            require((row['status'],row['message'])==((0,0)if tier=='gear'else(2,2)),'Declared leadout engine discrepancy changed');literals+=9
    return literals

def expected_port_hits():
    """Independent operation counts from authored CDB lengths/payload sizes."""
    result={0x2800:0,0x2808:0,0x2810:0,0x2818:0}
    def command(count,reply):
        result[0x2800]+=1;result[0x2808]+=count
        result[0x2810]+=2*(count+reply);result[0x2818]+=reply
    for case in cases():
        command(6,2050) # Authored 2048-byte READ plus STATUS and MESSAGE.
        if case['state']in('playing','paused','stopped'):command(10,2)
        if case['state']=='stopped':command(10,2)
        if case['state']=='seeking':command(10,0)
        reply=0 if case['kind']=='gap'and case['mode']and case['state']!='seeking'else 2
        command(10,reply)
    return result

def validate_capture(path,execution,tier):
    from pcerecomp.capture import load_capture
    capture,_=load_capture(path);require(capture['runtime_abi']==ABI and capture['capacity']==16,'Fresh capture ABI/capacity differs')
    require(capture['complete']and capture['retired_instructions']==execution['port_calls'],'Actual port capture count differs')
    expected={(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data']))for r in authored_sources()}
    keys={(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data']))for r in capture['observations']}
    require(keys==expected,'Every authored translated port source must actually execute')
    require({r['pc']:r['native_hits']+r['interpreted_hits']for r in capture['observations']}==expected_port_hits(),'Actual per-source hits differ from authored CDB/payload counts')
    require(all(r['native_hits']==0 if tier=='interpreter'else r['interpreted_hits']==0 for r in capture['observations']),'Unexpected execution tier')
    return capture

def validate_work(value,tier,speed):
    require(type(value)is dict and set(value)=={'schema','tier','divisor','cases','port_calls'},'Strict execution report fields')
    require(type(value['tier'])is str and value['tier']==tier,'Typed execution tier differs')
    for key in('schema','divisor','cases','port_calls'):
        require(type(value[key])is int and 0<=value[key]<2**64,'Typed bounded execution counters required')
    require(value==dict(schema=1,tier=tier,divisor=speed,cases=len(cases()),port_calls=sum(expected_port_hits().values())),'Strict execution report / independent port count')

def qualify(layout,speed,records,captures,work):
    require(type(layout)is dict and set(layout)=={'id','kind','first','start','leadout'}and
            all(type(layout[k])is str for k in('id','kind','first'))and
            all(type(layout[k])is int for k in('start','leadout'))and
            layout in LAYOUTS and type(speed)is int and speed in(3,12),'Authored layout/divisor required')
    require(set(records)==set(work)=={'gear','native','interpreter'}and set(captures)=={'native','interpreter'},'Complete original/native/interpreter records required')
    checks=0
    for tier in records:
        checks+=validate_rows(records[tier],tier)
        validate_work(work[tier],tier,speed)
    require(records['native']==records['interpreter'],'Native/interpreter raw records differ')
    for g,n,case in zip(records['gear'],records['native'],cases()):
        if case['kind']=='gap':
            require((g['after']['phase'],g['after']['signals'],g['status'],g['message'])==(n['after']['phase'],n['after']['signals'],n['status'],n['message']),'Original gap controller outcome differs')
            require(tuple(g['after']['logical'][i]for i in(0,1,2,3,5,6))==tuple(n['after']['logical'][i]for i in(0,1,2,3,5,6)),
                    'Original retained audio state/start/current/stop/mode/head differs')
    from pcerecomp.capture import validate_capture as validate
    projected=[]
    for tier in('native','interpreter'):
        capture=captures[tier];validate(capture)
        require(capture['runtime_abi']==ABI and capture['capacity']==16,'Fresh capture ABI/capacity differs')
        require(capture['complete']and capture['retired_instructions']==work[tier]['port_calls'],'Captured work differs')
        require({r['pc']:r['native_hits']+r['interpreted_hits']for r in capture['observations']}==expected_port_hits(),'Independent captured per-site counts differ')
        expected={(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data']))for r in authored_sources()}
        require({(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data']))for r in capture['observations']}==expected,'Complete captured source identity differs')
        require(all(r['native_hits']==0 if tier=='interpreter'else r['interpreted_hits']==0 for r in capture['observations']),'Captured execution tier differs')
        projected.append([{k:v for k,v in r.items()if k not in('native_hits','interpreted_hits')}|dict(hits=r['native_hits']+r['interpreted_hits'])for r in capture['observations']])
    require(projected[0]==projected[1],'Per-source actual hits differ')
    return dict(layout=layout,divisor=speed,cases=len(cases()),literal_checks=checks,
                native=work['native']['port_calls'],interpreted=work['interpreter']['port_calls'],original_port_calls=work['gear']['port_calls'])

def run(args):
    from pcerecomp.project import source_identity
    tool=args.tool_source.resolve();out=args.out.resolve();compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    require(not out.exists()and out.is_relative_to(ROOT/'.local')and compiler.is_file(),'New private output and compiler required')
    sources=[Path(__file__),ROOT/'tests/generate_cdda_gap_fixture.py',ROOT/'tests/cdda_gap_probe.cpp',ROOT/'tests/geargrafx_cdda_gap_probe.cpp',ROOT/'tests/geargrafx_sense_probe.cpp',ROOT/'tests/sense_probe_support.hpp',ROOT/'tests/reset_probe_support.hpp',
        *sorted((tool/'pcerecomp').glob('*.py')),*sorted((tool/'runtime').rglob('*.cpp')),*sorted((tool/'runtime').rglob('*.hpp')),tool/'CMakeLists.txt',*sorted((tool/'cmake').glob('*.cmake'))]
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p):sha(p)for p in sources})
    report=dict(schema=1,result='incomplete',tool=source_identity(tool),oracle_commit=reference.COMMIT,scope=__doc__,commands=[],bindings=bindings,comparisons=[])
    out.mkdir(parents=True)
    try:
        fixture=out/'fixture';generate(fixture);bindings['fixtures']={str(p):sha(p)for p in fixture.rglob('*')if p.is_file()}
        gear=build_gear(args,out,report,bindings,compiler);native=build_tool(args,out,report,bindings,compiler,fixture)
        totals=dict(native=0,interpreted=0,literal_checks=0,original_port_calls=0)
        for layout in LAYOUTS:
            cue=fixture/layout['id']/'disc.cue'
            for speed in(3,12):
                records={};caps={};works={}
                for tier,binary in(('gear',gear),('native',native),('interpreter',native)):
                    label=f'{layout["id"]}-s{speed}-{tier}';cap=out/(label+'-capture.json');execution=out/(label+'-execution.json')
                    done=common.evidence([str(binary),str(fixture/'cases.txt'),str(fixture/'authored.pce'),str(cue),tier,str(speed),str(cap),str(execution)],label,out,report,bindings,180)
                    rows=json.loads(done.stdout);checks=validate_rows(rows,tier);work=json.loads(execution.read_text());validate_work(work,tier,speed)
                    bindings['raw_outputs'][str(execution)]=sha(execution);records[tier]=rows;totals['literal_checks']+=checks
                    works[tier]=work
                    if tier!='gear':
                        caps[tier]=validate_capture(cap,work,tier);totals['native'if tier=='native'else'interpreted']+=work['port_calls'];bindings['raw_outputs'][str(cap)]=sha(cap)
                    else:totals['original_port_calls']+=work['port_calls']
                admitted=dict(layout=layout,speed=speed,records=records,captures=caps,work=works)
                qualified=qualify(**admitted)
                path=out/(layout['id']+'-s'+str(speed)+'-admission.json');path.write_text(json.dumps(admitted,indent=2)+'\n',encoding='utf8')
                bindings.setdefault('admissions',{})[str(path)]=sha(path)
                report['comparisons'].append(qualified)
        report.update(result='pass',**totals,original_cases=len(LAYOUTS)*2*len(cases()),program_gap_cases=sum(c['kind']=='gap'for c in cases())*len(LAYOUTS)*2)
        require(source_identity(tool)==report['tool'],'In-flight tool source changed')
    except BaseException as e:report.update(result='fail',error=repr(e));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    require(report['result']=='pass','Preservation failed');print(json.dumps({k:v for k,v in report.items()if k not in('commands','bindings','comparisons','processes')},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[])
    try:run(p.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as e:print(e,file=sys.stderr);raise SystemExit(1)
