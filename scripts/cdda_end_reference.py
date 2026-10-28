"""Original Gear CDDA end-update source/DAC and translated guest latch proof.

Seek/source-admission clocks remain raw and engine-specific. Source samples
are checked independently from the actual admitted frame; native/interpreter
identity is internal evidence. Original Gear device clocks are not CPU work.
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
from generate_cdda_end_fixture import generate,cases,authored_sources,EDGES
from pcerecomp.project import ABI
from scripts import mapper_reference as infrastructure
from scripts import filtered_audio_reference as reference
from scripts import hucard_reference as common
sha=reference.sha

def require(ok,why):
    if not ok:raise ValueError(why)

def build_gear(args,out,report,bindings,compiler):
    source,hashes=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(source,hashes);cpp.append(ROOT/'tests/geargrafx_cdda_end_probe.cpp')
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
    bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-cdda-end.exe'
    common.evidence([str(compiler),*[str(p)for _,p in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_artifacts']={str(p):sha(p)for p in[binary,*[p for _,p in jobs]]};return binary

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja))
    require(cmake.is_file()and ninja.is_file(),'CMake and Ninja required');bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    q=infrastructure.cmake_quote;wrapper=out/'wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(CddaEnd LANGUAGES CXX)',
        *['set('+k+' OFF CACHE BOOL "" FORCE)'for k in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
        f'add_subdirectory({q(args.tool_source.resolve())} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',
        f'add_executable(cdda-end-probe {q(ROOT/"tests/cdda_end_probe.cpp")})',f'target_include_directories(cdda-end-probe PRIVATE {q(fixture)} {q(ROOT/"tests")})',
        'target_link_libraries(cdda-end-probe PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n',encoding='utf8');bindings['tool_build_inputs']={str(config):sha(config)}
    build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('cdda-end-probe.exe'if os.name=='nt'else'cdda-end-probe')
    bindings['tool_artifacts']={str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.obj','.o','.a')or p==binary)};return binary

def integer(value,low=0,high=2**64):
    return type(value)is int and low<=value<high

def expected_port_hits():
    result={site['pc']:0 for site in authored_sources()}
    def command(count,reply):
        result[0x2800]+=1;result[0x2808]+=count
        result[0x2810]+=2*(count+reply);result[0x2818]+=reply
    for case in cases():
        command(6,2050);command(10,2)
        if case['state']=='playing':command(10,2)
        command(10,2 if case['mode']==3 else 0)
        for pc in(0x2820,0x2828,0x2830):result[pc]+=EDGES
    return result

def validate_point(point):
    require(type(point)is dict and set(point)=={'frame','left','right','next_edge','delay','raw','sector_deadline','sector_fraction'},'Strict point fields required')
    require(integer(point['frame'],0,588)and integer(point['next_edge'])and integer(point['delay']),'Source frame/clock differs')
    require(integer(point['sector_deadline'])and integer(point['sector_fraction'],0,75),'Bounded transport deadline/fraction required')
    require(all(integer(point[k],-32768,32768)for k in('left','right')),'Signed source DAC required')
    raw=point['raw']
    require(type(raw)is dict and set(raw)=={'ticks','phase','signals','logical','seek_deadline','event','event_deadline'},'Strict original raw state required')
    require(all(integer(raw[k])for k in set(raw)-{'logical'}),'Typed raw control clocks required')
    require(type(raw['logical'])is list and len(raw['logical'])==7 and all(integer(v,0,2**32)for v in raw['logical']),'Audio/head fields differ')
    require(raw['ticks']<point['next_edge']<=raw['ticks']+488,'Actual next rational source callback differs')

def validate_rows(rows,tier):
    require(type(rows)is list and len(rows)==len(cases()),'Exact authored matrix required')
    checks=tails=0
    for row,case in zip(rows,cases()):
        require(type(row)is dict and set(row)=={'case','before','admitted','ready','edges','settled'},'Strict source row fields')
        require(row['case']==case['id'],'Authored case order/identity differs')
        for key in('before','admitted','ready','settled'):validate_point(row[key])
        before,admitted,ready,settled=(row[k]for k in('before','admitted','ready','settled'))
        require(before['raw']['ticks']<admitted['raw']['ticks']<=ready['raw']['ticks']<settled['raw']['ticks'],'Monotonic actual clock required')
        require(before['raw']['logical'][:4]==[2 if case['state']=='paused'else 0,10,10,609],'Guest-established D8 source differs')
        require(before['frame']==(0 if case['state']=='paused'else 100),'Guest-established source frame differs')
        require(admitted['raw']['logical'][:4]==[0,10,10,case['end']],'D9 end/mode not admitted')
        require(admitted['raw']['logical'][5]=={1:1,2:2,3:0}[case['mode']],'D9 stop mode differs')
        require(admitted['raw']['phase']==(0 if case['mode']==3 else 8),'D9 BUSY/GOOD outcome differs')
        require(ready['delay']==0 and ready['raw']['seek_deadline']==0,'Actual source admission has pending seek/delay')
        if case['state']=='playing':
            elapsed_edges=admitted['raw']['ticks']*44100//21477273-before['raw']['ticks']*44100//21477273
            require(admitted['frame']==100+elapsed_edges<588 and admitted['delay']==0,'Actual CDB source edges/admitted frame differ')
            require(ready==admitted,'Playing admission position/clock drifted')
        else:
            require(admitted['frame']==0 and admitted['delay']>0 and ready['raw']['ticks']==admitted['raw']['ticks']+admitted['delay'],'Paused actual playback deadline/admission differs')
            n=ready['raw']['ticks']*44100//21477273
            on_edge=ready['raw']['ticks']==(n*21477273+44099)//44100
            require(ready['frame']==int(on_edge),'Paused first source callback at resume deadline differs')
        for point in(before,admitted,ready):
            expected=0 if not point['frame']else(point['frame']-1)*17-30000
            require((point['left'],point['right'])==(expected,-expected),'Actual source DAC at CDB admission differs')
        edges=row['edges'];require(type(edges)is list and len(edges)==EDGES,'Exact actual source callback extent required')
        frame=ready['frame'];sector=10;finished=False;last_tick=ready['raw']['ticks'];last_latch_tick=0;right_latch=False;held=0
        control_sector=10;control_state=0;deadline=ready['sector_deadline'];fraction=ready['sector_fraction']
        require((deadline==0 and fraction==0)if tier=='gear'else deadline>last_tick,'Declared original source-driven/toolkit control transport differs')
        def control_to(tick):
            nonlocal control_sector,control_state,deadline,fraction
            while deadline and deadline<=tick:
                control_sector+=1
                if control_sector>case['end']:
                    if case['mode']==1:control_sector=10
                    else:control_state=3;deadline=0;break
                fraction+=48;delta=286363
                if fraction>=75:fraction-=75;delta+=1
                deadline+=delta
            return control_state,control_sector
        for index,edge in enumerate(edges):
            require(type(edge)is list and len(edge)==11 and all(integer(v,-32768 if i in(2,3)else 0,32768 if i in(2,3)else 2**64)for i,v in enumerate(edge)),'Typed complete source edge required')
            tick,actual_frame,left,right,state,current,phase,signals,latch,pre_state,pre_frame=edge
            next_ordinal=last_tick*44100//21477273+1
            require(tick==(next_ordinal*21477273+44099)//44100,'Actual rational source callback clock differs')
            require(pre_frame==frame,'A source frame disappeared before the callback')
            expected_pre=3 if finished else 0
            if tier!='gear':expected_pre=control_to(tick-1)[0]
            require(pre_state==expected_pre,'Raw control state before source callback differs')
            expected=0 if finished else((sector-10)*31+frame*17)%60000-30000
            require((left,right)==(expected,-expected),'Authored current-sector remainder / loop PCM differs: '+case['id']+' edge '+str(index))
            if not finished:
                frame+=1
                if frame==588:
                    frame=0
                    if sector>=case['end']:
                        if case['mode']==1:sector=10
                        else:finished=True
                    else:sector+=1
            require(actual_frame==frame,'Actual source cursor boundary differs')
            if tier=='gear':
                expected_state=3 if finished else 0
                expected_current=max(10,case['end'])+1 if finished else sector
            else:expected_state,expected_current=control_to(tick)
            require((state,current)==(expected_state,expected_current),'Raw source-edge control state/head differs')
            expected_phase=7 if expected_state==3 and case['mode']==2 else 0 if case['mode']==3 else 8
            expected_signals=216 if expected_phase==7 else 128 if expected_phase==8 else 0
            require((phase,signals)==(expected_phase,expected_signals),'Raw source-edge controller phase/signals differ')
            # Public latch write happens exactly at the recorded source edge;
            # reads retire within 180 ticks, before the next source callback.
            if tick-last_latch_tick>=700:
                last_latch_tick=tick;right_latch=not right_latch;held=(right if right_latch else left)&65535
            require(latch==held,'Actual translated $1805/$1806 throttle/channel latch differs')
            tails+=int(pre_state==3 and pre_frame==587 and left!=0)
            last_tick=tick;checks+=10
        final=settled['raw'];require(frame==settled['frame'],'Settled cursor differs')
        if case['mode']==1:
            require(final['logical'][0]==0 and final['phase']==8 and final['signals']==128,'LOOP did not retain active BUSY transport')
        else:
            require(final['logical'][0]==3 and final['logical'][2]==max(10,case['end'])+1,'Natural end did not stop beyond the current/end sector')
            require(final['phase']==(7 if case['mode']==2 else 0),'IRQ/STOP terminal controller phase differs')
        checks+=30
    return dict(literal_checks=checks,rounded_terminal_tail_edges=tails)

def validate_capture(capture,work,tier):
    from pcerecomp.capture import validate_capture as validate
    validate(capture)
    require(capture['runtime_abi']==ABI and capture['capacity']==16 and capture['complete'],'Fresh capture ABI/capacity/completeness differs')
    require(capture['retired_instructions']==work['port_calls'],'Actual captured work differs')
    expected={(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data']))for r in authored_sources()}
    require({(r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data']))for r in capture['observations']}==expected,'Complete PC/MPR/physical/fetched-byte identity differs')
    require({r['pc']:r['native_hits']+r['interpreted_hits']for r in capture['observations']}==expected_port_hits(),'Independent per-site command/latch counts differ')
    require(all(r['native_hits']==0 if tier=='interpreter'else r['interpreted_hits']==0 for r in capture['observations']),'Actual execution tier differs')

def qualify(speed,records,captures,work):
    require(type(speed)is int and speed in(3,12),'Actual CPU divisor required')
    require(set(records)==set(work)=={'gear','native','interpreter'}and set(captures)=={'native','interpreter'},'Original/native/interpreter evidence required')
    qualified={}
    for tier in records:
        value=work[tier];require(type(value)is dict and set(value)=={'schema','tier','divisor','cases','port_calls'},'Strict execution fields required')
        require(all(integer(value[k])for k in set(value)-{'tier'}),'Typed bounded execution counters required')
        require(value==dict(schema=1,tier=tier,divisor=speed,cases=len(cases()),port_calls=sum(expected_port_hits().values())),'Independent actual command/latch count differs')
        qualified[tier]=validate_rows(records[tier],tier)
        if tier!='gear':validate_capture(captures[tier],value,tier)
    require(records['native']==records['interpreter'],'Native/interpreter raw source/clock/callback records differ')
    # Gear and toolkit deliberately retain different seek and source admission
    # clocks. Each complete source sequence above was independently checked
    # against authored media, without rewriting either original raw sequence.
    return dict(divisor=speed,cases=len(cases()),checks=qualified,native=work['native']['port_calls'],interpreted=work['interpreter']['port_calls'],original_port_calls=work['gear']['port_calls'])

def audit_admission(path):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    require(type(data)is dict and set(data)=={'speed','records','captures','work'},'Strict written admission fields required')
    return qualify(**data)

def audit_bindings(result):
    report=json.loads(Path(result).read_text(encoding='utf8'))
    require(report.get('result')=='pass','Completed reference receipt required')
    groups={'tools','authored_sources','fixtures','reference_raw_sources','reference_compile_sources','external_libraries','raw_outputs','gear_artifacts','tool_build_inputs','tool_artifacts','admissions'}
    bindings=report['bindings'];require(type(bindings)is dict and set(bindings)==groups and all(type(group)is dict and group for group in bindings.values()),'Exact nonempty bound file groups required')
    for name,group in bindings.items():
        for file,digest in group.items():
            require(type(digest)is str and len(digest)==64 and all(c in'0123456789abcdef'for c in digest),'SHA256 binding required')
            require(Path(file).is_file()and sha(Path(file))==digest,'Bound evidence changed: '+name+' '+file)
    base=Path(report['artifact_root']);tool=Path(report['tool_source']);gear=Path(report['oracle_source'])
    from pcerecomp.project import source_identity
    require(report['tool']==source_identity(tool)and report['oracle_commit']==reference.COMMIT,'Current tool/original pin differs')
    def extent(group,paths):
        require(set(bindings[group])=={str(p)for p in paths},'Complete binding group extent differs: '+group)
    extent('authored_sources',bound_sources(tool))
    extent('fixtures',(p for p in(base/'fixture').rglob('*')if p.is_file()))
    extent('gear_artifacts',[base/'gear-cdda-end.exe',*sorted((base/'gear-objects').glob('*.o'))])
    extent('tool_artifacts',(p for p in(base/'tool-build').rglob('*')if p.is_file()and(p.suffix in('.obj','.o','.a')or p.name in('cdda-end-probe.exe','cdda-end-probe'))))
    extent('tool_build_inputs',[base/'wrapper/CMakeLists.txt'])
    require(len(bindings['tools'])==3 and len(bindings['external_libraries'])==4,'Compiler/build tools and explicit reference libraries required')
    extent('admissions',[base/f'end-s{speed}-admission.json'for speed in(3,12)])
    # Recheck every unchanged original Git blob, not merely a receipt hash or
    # a few hand-picked CD source files. Compile LF copies retain CRLF policy.
    prefix='platforms/shared/dependencies/'
    tree=subprocess.check_output(['git','-C',str(gear),'ls-tree','-r',reference.COMMIT,'src',*[prefix+p for p in('miniz','minivorbis','qon','json','libchdr/include')]],text=True).splitlines()
    names=[]
    for row in tree:
        metadata,name=row.split('\t',1)
        if Path(name).suffix not in('.cpp','.c','.h','.hpp'):continue
        mode,kind,blob=metadata.split();require(kind=='blob'and mode in('100644','100755'),'Original source tree entry differs')
        original=(gear/name).read_bytes();compiled=(base/'pinned-reference-source'/name).read_bytes()
        normalized=original.replace(b'\r\n',b'\n')
        require(compiled==normalized and hashlib.sha1(b'blob '+str(len(normalized)).encode()+b'\0'+normalized).hexdigest()==blob,'Actual original/compiled Git blob differs: '+name)
        names.append(name)
    require(bool(names),'Original Git source tree missing')
    extent('reference_raw_sources',[gear/name for name in names]);extent('reference_compile_sources',[base/'pinned-reference-source'/name for name in names])
    expected_raw={base/(label+'.'+suffix)for label in('gear-link','tool-configure','tool-build')for suffix in('stdout','stderr')}
    comparisons=[]
    for speed in(3,12):
        admitted_path=base/f'end-s{speed}-admission.json';data=json.loads(admitted_path.read_text(encoding='utf8'))
        require(data['speed']==speed,'Actual admission filename/divisor differs')
        for tier in('gear','native','interpreter'):
            label=f'end-s{speed}-{tier}'
            stdout=base/(label+'.stdout');execution=base/(label+'-execution.json')
            expected_raw.update([stdout,base/(label+'.stderr'),execution])
            require(data['records'][tier]==json.loads(stdout.read_text(encoding='utf8'))and data['work'][tier]==json.loads(execution.read_text(encoding='utf8')),'Admission is not joined to actual raw stdout/execution: '+label)
            if tier!='gear':
                from pcerecomp.capture import load_capture
                path=base/(label+'-capture.json');expected_raw.add(path)
                require(data['captures'][tier]==load_capture(path)[0],'Admission is not joined to actual raw source capture: '+label)
        comparisons.append(audit_admission(admitted_path))
    extent('raw_outputs',expected_raw)
    require(report['comparisons']==comparisons,'Summary differs from actual reloaded raw admissions')
    require(report['native']==sum(c['native']for c in comparisons)and report['interpreted']==sum(c['interpreted']for c in comparisons)and report['original_port_calls']==sum(c['original_port_calls']for c in comparisons)and report['original_cases']==2*len(cases()),'Actual summary counts differ')
    return dict(groups=len(bindings),files=sum(map(len,bindings.values())),admissions=len(bindings['admissions']))

def bound_sources(tool):
    return [Path(__file__),ROOT/'scripts/cdda_gap_reference.py',ROOT/'scripts/mapper_reference.py',ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/hucard_reference.py',
        *[ROOT/'tests'/name for name in('generate_cdda_end_fixture.py','generate_cdda_gap_fixture.py','cdda_end_probe.cpp','cdda_gap_probe.cpp','geargrafx_cdda_end_probe.cpp','geargrafx_sense_probe.cpp','sense_probe_support.hpp','reset_probe_support.hpp','test_cdda_end_reference.py')],
        *sorted((tool/'pcerecomp').glob('*.py')),*sorted((tool/'runtime').rglob('*.cpp')),*sorted((tool/'runtime').rglob('*.hpp')),tool/'CMakeLists.txt',*sorted((tool/'cmake').glob('*.cmake'))]

def run(args):
    from pcerecomp.project import source_identity
    from pcerecomp.capture import load_capture
    tool=args.tool_source.resolve();out=args.out.resolve();compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    require(not out.exists()and out.is_relative_to(ROOT/'.local')and compiler.is_file(),'New private output and compiler required')
    sources=bound_sources(tool)
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p):sha(p)for p in sources})
    report=dict(schema=1,result='incomplete',tool=source_identity(tool),tool_source=str(tool),oracle_commit=reference.COMMIT,oracle_source=str(args.gear_source.resolve()),artifact_root=str(out),scope=__doc__,commands=[],bindings=bindings,comparisons=[])
    out.mkdir(parents=True)
    try:
        fixture=out/'fixture';generate(fixture);bindings['fixtures']={str(p):sha(p)for p in fixture.rglob('*')if p.is_file()}
        gear=build_gear(args,out,report,bindings,compiler);native=build_tool(args,out,report,bindings,compiler,fixture)
        bindings['admissions']={}
        for speed in(3,12):
            records={};caps={};works={}
            for tier,binary in(('gear',gear),('native',native),('interpreter',native)):
                label=f'end-s{speed}-{tier}';cap=out/(label+'-capture.json');execution=out/(label+'-execution.json')
                done=common.evidence([str(binary),str(fixture/'cases.txt'),str(fixture/'authored.pce'),str(fixture/'virtual-data/disc.cue'),tier,str(speed),str(cap),str(execution)],label,out,report,bindings,240)
                records[tier]=json.loads(done.stdout);works[tier]=json.loads(execution.read_text());bindings['raw_outputs'][str(execution)]=sha(execution)
                if tier!='gear':caps[tier]=load_capture(cap)[0];bindings['raw_outputs'][str(cap)]=sha(cap)
            admitted=dict(speed=speed,records=records,captures=caps,work=works)
            path=out/(f'end-s{speed}-admission.json');path.write_text(json.dumps(admitted,indent=2)+'\n',encoding='utf8');bindings['admissions'][str(path)]=sha(path)
            report['comparisons'].append(audit_admission(path))
        report.update(result='pass',native=sum(c['native']for c in report['comparisons']),interpreted=sum(c['interpreted']for c in report['comparisons']),original_port_calls=sum(c['original_port_calls']for c in report['comparisons']),original_cases=2*len(cases()))
        require(source_identity(tool)==report['tool'],'In-flight tool source changed')
    except BaseException as e:report.update(result='fail',error=repr(e));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    require(report['result']=='pass','Evidence preservation failed');audit=audit_bindings(out/'result.json');print(json.dumps(dict(result='pass',native=report['native'],interpreted=report['interpreted'],original_port_calls=report['original_port_calls'],original_cases=report['original_cases'],audit=audit),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[])
    try:run(p.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as e:print(e,file=sys.stderr);raise SystemExit(1)
