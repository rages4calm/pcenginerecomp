"""Guest-only base-HuCard DMA phase sweep with original per-call evidence.

Forty-six recipes admit the narrow blank/no-HSW arithmetic profile; two
natural HSW controls execute with full memory expectations but explicitly
refuse that profile. Raw cross-core reset/phase differences remain.
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
from tests.vdc_phase_fixture import cases,fixtures,program,expected_vram,expected_wram,MPR,LIMIT
from scripts import mapper_reference as infra,filtered_audio_reference as ref,hucard_reference as common
from scripts.vdc_phase import predict_blank_dma_read_wait,PROFILE
from scripts.vdc_adpcm_irq_reference import ints,digest,require,source_key,requested_tier
from pcerecomp.project import source_identity,ABI
COMMIT=ref.COMMIT
sha=lambda path:ref.sha(Path(path))

def sources(tool):
    names=['scripts/vdc_phase_reference.py','scripts/vdc_phase_qualify.py','scripts/vdc_phase.py','tests/vdc_phase_fixture.py','tests/vdc_phase_probe.cpp','tests/geargrafx_vdc_phase_probe.cpp','tests/test_vdc_phase.py','tests/test_vdc_phase_reference.py','tests/vdc_adpcm_irq_fixture.py','tests/dma_irq_checkpoint_fixture.py','scripts/vdc_adpcm_irq_reference.py','tests/reset_probe_support.hpp','scripts/mapper_reference.py','scripts/filtered_audio_reference.py','scripts/psg_reference.py','scripts/hucard_reference.py']
    paths=[ROOT/name for name in names]+[tool/'CMakeLists.txt']+sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'cmake').rglob('*.cmake'))
    return {str(p.resolve()):sha(p)for p in paths}

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve() for v in (args.cmake,args.ninja));require(cmake.is_file()and ninja.is_file(),'CMake/Ninja required')
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)});q=infra.cmake_quote;wrapper=out/'wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(VdcPhase LANGUAGES CXX)',*['set('+v+' OFF CACHE BOOL "" FORCE)'for v in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],f'add_subdirectory({q(args.tool_source.resolve())} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',f'add_executable(vdc-phase {q(ROOT/"tests/vdc_phase_probe.cpp")})',f'target_include_directories(vdc-phase PRIVATE {q(fixture)} {q(ROOT/"tests")})','target_link_libraries(vdc-phase PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n');bindings['tool_build_inputs']={str(config):sha(config)};build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','vdc-phase','--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('vdc-phase.exe'if os.name=='nt'else'vdc-phase');bindings['tool_binary']={str(binary):sha(binary)}
    bindings['tool_objects']={str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.o','.obj','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))};return binary

def build_gear(args,out,report,bindings,compiler):
    checkout,originals=infra.pinned_snapshot(args.gear_source.resolve(),out,bindings);cpp,c=ref.compile_sources(checkout,originals);cpp.append(ROOT/'tests/geargrafx_vdc_phase_probe.cpp');deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(checkout/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    objects=out/'gear-objects';objects.mkdir();jobs=[];report['compilations']=[]
    for i,path in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+path.stem+'.o');command=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def one(job):
        command,obj=job;done=subprocess.run(command,capture_output=True,text=True,timeout=180);log=obj.with_suffix('.log');log.write_text(done.stdout+done.stderr);report['compilations'].append(dict(object=str(obj),log=str(log),returncode=done.returncode));done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(one,jobs))
    libraries=[p.resolve()for p in args.library];require(libraries and all(p.is_file()for p in libraries),'Explicit existing external libraries required');bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-vdc-phase.exe'
    common.evidence([str(compiler),*[str(o)for _,o in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings);bindings['gear_objects']={str(o):sha(o)for _,o in jobs};bindings['gear_compile_logs']={str(o.with_suffix('.log')):sha(o.with_suffix('.log'))for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    report['gear_git_blobs']={name:hashlib.sha1(b'blob '+str((checkout/name).stat().st_size).encode()+b'\0'+(checkout/name).read_bytes()).hexdigest()for name in originals};return binary

PHASE_COLUMNS=('ticks','hclock','dot','vdc_line','vce_line','vstate','hstate','hremaining','divider','read_pending','write_pending','delay','carry','dma_pending','satb_pending','burst','latched_cr','latched_mwr','sprites','bg_start','bg_end','hsync_start','read_buffer','marr','mawr','sour','desr','lenr','vram_bus','selected','status','irq1','hsr','hdr','cr')

def authored(case):
    _,markers,plan=program(case);return markers,{source_key(r):r for r in plan}

def validate_hits(rows,case):
    _,plan=authored(case);require(type(rows)is list,'Actual source ledger required');got={}
    for row in rows:
        require(type(row)is dict and set(row)=={'pc','mpr','physical','data','hits'},'Exact fetched source/count fields required');ints([row['pc'],row['hits']]);ints(row['mpr'],8,256);ints(row['data'],maximum=256);ints(row['physical'],len(row['data']),2**21);key=source_key(row)
        require(key in plan and key not in got and row['hits']==1,'Actual whole PC/MPR/physical/byte source/count differs');got[key]=1
    done=program(case)[1]['done'];require(set(got)=={key for key in plan if key[0]!=done},'Executed source extent differs or terminal BRA falsely retired');return got

def validate_capture(capture,case,tier):
    from pcerecomp.capture import validate_capture as validate
    validate(capture);require(type(capture)is dict and set(capture)=={'schema','runtime_abi','capacity','dropped_instructions','unreadable_instructions','retired_instructions','complete','observations'}and capture['runtime_abi']==ABI and capture['complete']is True and capture['dropped_instructions']==capture['unreadable_instructions']==0,'Complete same-ABI retired capture required')
    rows=[]
    for row in capture['observations']:
        require(set(row)=={'pc','mpr','physical','data','native_hits','interpreted_hits'},'Exact retired source/tier fields required');ints([row['native_hits'],row['interpreted_hits']]);require((row['native_hits'],row['interpreted_hits'])==((1,0)if tier=='native'else(0,1)),'Actual retired execution tier differs');rows.append({k:v for k,v in row.items()if k not in('native_hits','interpreted_hits')}|dict(hits=1))
    got=validate_hits(rows,case);require(type(capture['retired_instructions'])is int and capture['retired_instructions']==len(got),'Actual retired capture count differs');return got

def validate_work(actual,case,hits,gear):
    for key in('instructions','calls','clock_calls','blocks','block_bytes','wait_ticks'):require(type(actual[key])is int and actual[key]>=0,'Strict actual work fields required')
    raw=[key[3]for key in hits];lengths=[data[5]|data[6]<<8 for data in raw if data[0]in(0x73,0xf3)];n=len(raw)
    require(actual['instructions']==n<=LIMIT and actual['blocks']==len(lengths)and actual['block_bytes']==sum(lengths),'Variable-length block retirement/byte counts differ')
    require(actual['calls']==n+(sum(length+1 for length in lengths)if gear else 0)and(actual['clock_calls']>=actual['calls']if gear else actual['clock_calls']==0),'Actual N+2 calls are not whole-instruction retirements')

def validate_phase(row):
    ints(row,35);require(row[1]<1365 and row[8]in(2,3,4)and row[5]<4 and row[6]<4 and row[12]<3 and row[11]%3==0 and all(row[i]in(0,1)for i in(9,10,15,31)),'Typed actual raster/queue phase differs');return row

def classify_hsw(launch,target,case):
    """Derive whether HSW gates any post-DMA eligible callback.

    This is an authored-geometry admission proof, not a general VDC solver.
    HSR/HDR and the observed line-start latch force HSW at each new line,
    followed by HDS longer than the remainder of a line. Only the first eight
    dots can gate a queued read. Neither CR0 nor burst alone proves this fact.
    """
    l=validate_phase(launch['before']);s=validate_phase(target['before']);d=case['vce']
    require(l[8]==s[8]==d and l[14:19]==s[14:19]==[0,1,0,0,0]and l[19:22]==s[19:22]==[1365,0,0]and l[32:]==s[32:]==[0x7f1f,0x7f7f,0],'Actual blank geometry/latches do not prove declared HSW profile')
    require(l[5]==s[5]==3 and l[6]==s[6]==0 and l[1]//d==(l[2])and s[1]//d==s[2]and l[7]==(32 if d==3 else 24)+1024-l[2]and s[7]==(32 if d==3 else 24)+1024-s[2],'Actual HSW/HDS state/countdown does not match authored forced-line geometry')
    require(s[9:15]==[1,0,0,0,s[13],0]and s[29]==2,'Read queue, expired delay and zero carry are required facts')
    require((l[1]+s[0]-l[0])%1365==s[1],'Actual launch/target clock phases disagree')
    per=1365//d;position=l[1]+s[0]-l[0];elapsed_dots=(position//1365)*per+(position%1365)//d-l[1]//d
    require(s[13]==max(0,4*case['words']-elapsed_dots),'Actual DMA countdown disagrees with observed launch/target phase')
    final=l[1]//d+4*case['words'];line,ordinal=divmod(final-1,per);completion=l[0]+line*1365+(ordinal+1)*d-l[1]
    require(completion>s[0]+case['divisor']*(1 if case['access']=='high'else 16),'This fixture requires a live DMA barrier beyond the fixed prefix')
    first=s[0]+((completion-s[0]+2)//3)*3;candidates=[]
    for k in range(455):
        tick=first+3*k;hclock=(l[1]+tick-l[0])%1365;hstate=3 if hclock//d<(32 if d==3 else 24)else 0;gated=hstate==3 and(hclock+3)%1365<8*d
        candidates.append(dict(tick=tick,hclock=hclock,hstate=hstate,hsync_start=0,gated=gated))
        if not gated and(hclock//d)%2==0:break
    else:raise ValueError('Authored blank geometry did not grant within one phase period')
    return dict(hsw_excluded=not any(c['gated']for c in candidates),completion_tick=completion,candidates=candidates)

def predict(launch,target,case,proof):
    l=launch['before'];s=target['before']
    return predict_blank_dma_read_wait(profile=PROFILE,access='high'if case['access']=='high'else'tai2',cpu_divisor=case['divisor'],vce_divider=case['vce'],dma_words=case['words'],launch_tick=l[0],launch_hclock=l[1],target_tick=s[0],target_hclock=s[1],pending_dma_dots=s[13],transfer_delay=s[11],queue_carry=s[12],read_pending=s[9]==1,write_pending=s[10]==1,satb_pending_dots=s[14],display_control=s[16],burst=s[15]==1,sprite_count=s[18],selected_register=s[29],hsw_excluded=proof['hsw_excluded'])

def validate_original_group(row,case):
    spans=row['clocks'];calls=row['call_rows'];events=row['events'];raw=row['bytes'];is_block=raw[0]==0xf3;count=4 if is_block else 1
    require(type(spans)is list and 0<len(spans)<=100000 and type(calls)is list and len(calls)==count and row['calls']==count and type(events)is list and len(events)<=8192,'Original bounded per-call ledger required')
    last=None;waits=total=0
    for span in spans:
        ints(span,12);start,n,end,dynamic,hclock,pre,post,read_before,read_after,carry,hstate,hsync=span
        require(n>0 and end==start+n and(last is None or last==start)and dynamic in(0,1)and(not dynamic or n==3)and hclock<1365 and carry<3 and hstate<4 and hsync<1365 and read_before in(0,1)and read_after in(0,1),'Original clock continuity/typed kernel differs');last=end;total+=n;waits+=dynamic*n
    require(total==row['ticks']and waits==row['wait_ticks']and spans[0][0]==row['before'][0]and last==row['after'][0],'Actual original group endpoint/clock/wait totals differ')
    returned=internal=cursor=0
    for i,call in enumerate(calls,1):
        ints(call,8);idx,ticks,inside,complete,first,end,last,extra=call
        require(idx==i and complete==int(i==count)and first==cursor and first<=end<=last<=len(spans),'Original N+2 call completion/span partition differs')
        require(sum(s[1]for s in spans[first:end])==inside and sum(s[1]for s in spans[first:last])==ticks and sum(s[1]for s in spans[first:end]if s[3])==extra and not any(s[3]for s in spans[end:last]),'Original internal/remaining/dynamic call clocks differ')
        fixed=(14 if i==1 else 3 if i==4 else 8)if is_block else 6
        require(ticks==fixed*case['divisor']+extra,'Independent scalar/TAI startup-byte-epilogue clock formula differs');returned+=ticks;internal+=inside;cursor=last
    require(returned==row['ticks']and internal==row['internal']and cursor==len(spans),'Original actual call sums differ')
    for event in events:ints(event,12);require(event[2]==2 and 1<=event[0]<=count,'Original callback type/extent/call differs')
    for event in events:
        call=calls[event[0]-1];require(spans[call[4]][0]<=event[1]<=spans[call[6]-1][2],'Original event timestamp outside actual call')

def validate_candidate_spans(spans,proof,*,prediction=None):
    """Join authored candidate facts to actual original hardware callbacks."""
    for span in spans:ints(span,12)
    grant=next((s for s in spans if s[7]and not s[8]),None);require(grant is not None,'Original actual queued grant missing')
    if prediction:require(grant[0]==prediction['predicted_grant_start_tick'],'Original actual grant does not match predicted callback start')
    for i,candidate in enumerate(proof['candidates']):
        matching=[s for s in spans if s[0]==candidate['tick']];require(len(matching)==1,'Actual candidate callback missing');s=matching[0];require(s[4]==candidate['hclock']and s[5]==0 and s[7]==1 and s[10]==candidate['hstate']and s[11]==candidate['hsync_start'],'Actual original HSW/kernel facts disagree with geometry proof')
        require(s[8]==int(i<len(proof['candidates'])-1),'Actual original candidate hold/first-grant sequence differs')
    if not prediction:require(grant[4]==24 and grant[10:]==[3,0],'Actual HSW control did not first grant at hclock24')

def validate_report(actual,case,hits=None):
    gear=actual.get('tier')=='gear';keys={'schema','case','tier','runtime_abi','instructions','calls','clock_calls','blocks','block_bytes','wait_ticks','records','final_cpu','final_phase','wram','vram'}|({'hits'}if gear else set())
    require(type(actual)is dict and set(actual)==keys and type(actual['schema'])is int and actual['schema']==1 and actual['case']==case['id']and actual['tier']in('gear','native','interpreter')and(actual['runtime_abi']is None if gear else type(actual['runtime_abi'])is int and actual['runtime_abi']==ABI),'Exact execution report identity/schema/tier required')
    hits=validate_hits(actual['hits'],case)if gear else hits;require(type(hits)is dict,'Retired source admission is required');validate_work(actual,case,hits,gear);markers,plan=authored(case)
    records=actual['records'];require(type(records)is list and len(records)==2 and[r['pc']for r in records]==[markers['launch'],markers['target']],'Actual launch/target source order differs')
    for row in records:
        require(type(row)is dict and set(row)=={'pc','mpr','physical','bytes','before','after','cpu_before','cpu_after','ticks','wait_ticks','calls','internal','clocks','call_rows','events'},'Exact selected instruction fields required');ints([row['pc'],row['ticks'],row['wait_ticks'],row['calls'],row['internal']]);ints(row['mpr'],8,256);ints(row['physical'],len(row['bytes']),2**21);ints(row['bytes'],maximum=256);require(source_key(row)in hits and source_key(row)in plan,'Actual selected source does not join full MPR/byte retirement identity')
        before=validate_phase(row['before']);after=validate_phase(row['after']);ints(row['cpu_before'],16);ints(row['cpu_after'],16);require(row['cpu_before'][0]==row['pc']and row['cpu_before'][6:8]==[case['divisor'],before[0]]and row['cpu_after'][6:8]==[case['divisor'],after[0]]and row['cpu_before'][8:]==row['cpu_after'][8:]==list(MPR)and after[0]-before[0]==row['ticks'],'CPU/raster/source timeline joins differ')
        if gear:validate_original_group(row,case)
        else:require(row['calls']==1 and row['internal']==0 and row['clocks']==row['call_rows']==row['events']==[],'Native adapter invented original per-call observations')
    launch,target=records;v=target['before'];a=0xa6 if case['access']=='high'else 2
    require(launch['bytes']==[0x8d,3,0]and launch['wait_ticks']==0 and launch['before'][13:15]==[0,0]and launch['before'][29]==18 and launch['before'][27]==(case['words']-1)&255 and launch['ticks']==6*case['divisor'],'Observed source-absent DMA trigger/fixed clocks differ')
    require(target['cpu_before'][:7]==[markers['target'],2,255,0,255-case['pad'],4,case['divisor']]and target['cpu_after'][:7]==[markers['after_target'],a,255,0,255-case['pad'],132 if case['access']=='high'else 4,case['divisor']]and target['wait_ticks']>0 and actual['wait_ticks']==target['wait_ticks'],'Independent target CPU/stack/wait literals differ')
    proof=classify_hsw(launch,target,case)
    if proof['hsw_excluded']:
        prediction=predict(launch,target,case,proof);require(prediction['predicted_wait_ticks']==target['wait_ticks'],'Independent blank-profile prediction differs from actual wait')
    else:
        try:predict(launch,target,case,proof)
        except ValueError:pass
        else:raise ValueError('Truthful active-HSW facts admitted by no-HSW profile')
        prediction=None
        require(case['divisor']==12 and case['vce']==3 and case['words']==127 and case['pad']==1,'Unexpected authored HSW control classification')
        require([c['hclock']for c in proof['candidates']]==[9,12,15,18,21,24]and[c['gated']for c in proof['candidates']]==[True]*4+[False]*2,'Independent literal HSW control sequence differs')
        require(target['wait_ticks']==(1074 if case['access']=='high'else 894),'Independent finite HSW control wait literal differs')
    if gear:
        starts=[e for e in launch['events']if e[3]==7];require(len(starts)==1 and starts[0][1]==launch['before'][0]and starts[0][8:12]==[0,8192,2,case['words']],'Original actual LENR-high trigger tick/extent differs')
        ends=[e for e in target['events']if e[3]==6];require(len(ends)==1,'Original DMA-end event missing/duplicated');spans=target['clocks'];completion=[s for s in spans if s[5]>0 and s[6]==0];require(len(completion)==1 and completion[0][0]<proof['completion_tick']<=completion[0][2]and completion[0][0]<=ends[0][1]<=completion[0][2],'Exact VCE final dot does not join its original enclosing callback')
        validate_candidate_spans(spans,proof,prediction=prediction)
    ints(actual['wram'],8192,256);ints(actual['vram'],32768,65536);require(actual['wram']==expected_wram(case)and actual['vram']==expected_vram(case),'Independent full WRAM/VRAM/stack/payload differs')
    ints(actual['final_cpu'],16);f=validate_phase(actual['final_phase']);require(actual['final_cpu'][:7]==[markers['done'],a,255,0,255-case['pad'],132 if case['access']=='high'else 4,case['divisor']]and actual['final_cpu'][7]==f[0]and actual['final_cpu'][8:]==list(MPR)and f[9:15]==[0,0,0,0,0,0]and f[22:28]==[0,2,case['words'],case['words'],8192+case['words'],65535]and f[29:]==[2,16,1,0x7f1f,0x7f7f,0],'Independent final CPU/DMA/queue/register literals differ')
    return dict(profile=PROFILE,hsw_excluded=proof['hsw_excluded'],proof=proof,prediction=prediction,actual_wait_ticks=target['wait_ticks'])

def raw_differences(gear,tool,case):
    result=[]
    for a,b in zip(gear['records'],tool['records']):
        for phase in('before','after'):
            for field,original,current in zip(PHASE_COLUMNS,a[phase],b[phase]):
                if original!=current:result.append(dict(case=case['id'],pc=a['pc'],phase=phase,field=field,original=original,tool=current))
        for field in('ticks','wait_ticks','calls','internal'):
            if a[field]!=b[field]:result.append(dict(case=case['id'],pc=a['pc'],phase='instruction',field=field,original=a[field],tool=b[field]))
    return result

def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();compiler=Path(shutil.which(str(args.compiler))or'').resolve();require(not out.exists()and out.is_relative_to(ROOT/'.local')and compiler.is_file(),'New private output and compiler required')
    import pcerecomp.project
    require(Path(pcerecomp.project.__file__).resolve()==tool/'pcerecomp/project.py','Explicit toolkit source required');out.mkdir(parents=True);bindings=dict(tools={str(compiler):sha(compiler)},authored_sources=sources(tool));report=dict(schema=1,result='incomplete',oracle_commit=COMMIT,tool=source_identity(tool),tool_root=str(tool),commands=[],bindings=bindings,rows=[],scope=__doc__,not_checked=['General HSW/active-display solver','Hardware timing precision','Cross-core clock equality','Retail gameplay'])
    try:
        fixture=fixtures(out);bindings['fixtures']={str(p):sha(p)for p in list(out.glob('*.pce'))+list(fixture.iterdir())if p.is_file()};gear=build_gear(args,out,report,bindings,compiler);binary=build_tool(args,out,report,bindings,compiler,fixture)
        from scripts.vdc_phase_qualify import load
        for case in cases():
            for tier in('gear','native','interpreter'):
                label=case['id']+'-'+tier;capture=out/(label+'-capture.json');command=[str(gear),case['id'],str(out/(case['id']+'.pce'))]if tier=='gear'else[str(binary),case['id'],str(out/(case['id']+'.pce')),tier,str(capture)]
                common.evidence(command,label,out,report,bindings,120);actual=load(out/(label+'.stdout'));requested_tier(actual,tier);hits=None
                if tier!='gear':hits=validate_capture(load(capture),case,tier);bindings['raw_outputs'][str(capture)]=sha(capture)
                validate_report(actual,case,hits);report['rows'].append(dict(case=case,tier=tier,label=label))
        report.update(result='pass',recipes=48,cases=48)
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:ref.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    from scripts.vdc_phase_qualify import qualify
    result=qualify(out/'result.json');(out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

def parser():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[]);return p

if __name__=='__main__':
    try:run(parser().parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)

