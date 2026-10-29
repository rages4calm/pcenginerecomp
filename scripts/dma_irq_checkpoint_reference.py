"""Autonomous authored guest READ6/DMA/IRQ2 with original Gear CPU callbacks.

Exact same-tier fresh-process checkpoint continuation is distinct from
cross-core semantic agreement. Raw callback, clock and cut differences remain.
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
from dma_irq_checkpoint_fixture import cases,fixtures,program,expected_ram,KINDS,LIMIT
from scripts import mapper_reference as infra,filtered_audio_reference as ref,hucard_reference as common
from pcerecomp.project import source_identity,ABI
COMMIT=ref.COMMIT
OBSERVATION_COLUMNS=('pc','a','x','y','sp','p','clock_divisor','ticks','irq_entries','rti_steps','irq_mask','irq_requests','cd_enable','cd_active','signals','dma','length','write_address','half','end','dma_counter','write_pending','irq2')
sha=lambda path:ref.sha(Path(path))
def require(value,message):
    if not value:raise ValueError(message)

def sources(tool):
    names=['scripts/dma_irq_checkpoint_reference.py','scripts/dma_irq_checkpoint_qualify.py','tests/dma_irq_checkpoint_fixture.py','tests/dma_irq_checkpoint_support.hpp','tests/dma_irq_checkpoint_probe.cpp','tests/geargrafx_dma_irq_checkpoint_probe.cpp','tests/test_dma_irq_checkpoint_reference.py','tests/irq_trace_support.hpp','tests/reference_trace_support.hpp','tests/reset_probe_support.hpp','scripts/mapper_reference.py','scripts/filtered_audio_reference.py','scripts/psg_reference.py','scripts/hucard_reference.py']
    paths=[ROOT/name for name in names]+[tool/'CMakeLists.txt']+sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'cmake').rglob('*.cmake'))
    return {str(p.resolve()):sha(p) for p in paths}

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve() for v in (args.cmake,args.ninja));require(cmake.is_file()and ninja.is_file(),'CMake/Ninja required')
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)});q=infra.cmake_quote;wrapper=out/'wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(DmaIrqCheckpoint LANGUAGES CXX)',*['set('+v+' OFF CACHE BOOL "" FORCE)'for v in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],f'add_subdirectory({q(args.tool_source.resolve())} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',f'add_executable(dma-irq-checkpoint {q(ROOT/"tests/dma_irq_checkpoint_probe.cpp")})',f'target_include_directories(dma-irq-checkpoint PRIVATE {q(fixture)} {q(ROOT/"tests")})','target_link_libraries(dma-irq-checkpoint PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n');bindings['tool_build_inputs']={str(config):sha(config)};build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','dma-irq-checkpoint','--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('dma-irq-checkpoint.exe'if os.name=='nt'else'dma-irq-checkpoint');bindings['tool_binary']={str(binary):sha(binary)}
    bindings['tool_objects']={str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.o','.obj','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))};return binary

def build_gear(args,out,report,bindings,compiler):
    checkout,originals=infra.pinned_snapshot(args.gear_source.resolve(),out,bindings);cpp,c=ref.compile_sources(checkout,originals);cpp.append(ROOT/'tests/geargrafx_dma_irq_checkpoint_probe.cpp');deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(checkout/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    objects=out/'gear-objects';objects.mkdir();jobs=[];report['compilations']=[]
    for i,path in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+path.stem+'.o');command=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def one(job):
        command,obj=job;done=subprocess.run(command,capture_output=True,text=True,timeout=180);log=obj.with_suffix('.log');log.write_text(done.stdout+done.stderr);report['compilations'].append(dict(object=str(obj),log=str(log),returncode=done.returncode));done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(one,jobs))
    libraries=[p.resolve()for p in args.library];require(libraries and all(p.is_file()for p in libraries),'Explicit existing external libraries required');bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-dma-irq-checkpoint.exe'
    common.evidence([str(compiler),*[str(o)for _,o in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings);bindings['gear_objects']={str(o):sha(o)for _,o in jobs};bindings['gear_compile_logs']={str(o.with_suffix('.log')):sha(o.with_suffix('.log'))for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    report['gear_git_blobs']={name:hashlib.sha1(b'blob '+str((checkout/name).stat().st_size).encode()+b'\0'+(checkout/name).read_bytes()).hexdigest()for name in originals};return binary

def ints(values,length=None,maximum=2**64):
    require(type(values)is list and(length is None or len(values)==length)and all(type(v)is int and 0<=v<maximum for v in values),'Strict unsigned integer list required')
def digest(value):require(type(value)is str and len(value)==64 and all(c in'0123456789abcdef'for c in value),'SHA256 required')
def requested_tier(actual,tier):require(actual.get('tier')==tier,'Requested process versus actual execution tier differs')
def source_key(row):return row['pc'],tuple(row['mpr']),tuple(row['physical']),tuple(row.get('data',row.get('bytes',[])))
def authored(case):
    _,markers,plan=program(case);return markers,{source_key(r)for r in plan}
def validate_hits(rows,case):
    require(type(rows)is list,'Actual source hits required');_,plan=authored(case);result={}
    for row in rows:
        require(type(row)is dict and set(row)=={'pc','mpr','physical','data','hits'},'Exact source hit fields required')
        require(type(row['pc'])is int and 0<=row['pc']<65536 and type(row['hits'])is int and 0<row['hits']<=LIMIT,'Actual source/count type or bound differs');ints(row['mpr'],8,256);ints(row['data'],maximum=256);ints(row['physical'],len(row['data']),2**21)
        key=source_key(row);require(key in plan and key not in result,'Actual PC/MPR/physical/bytes differ from authored source');result[key]=row['hits']
    return result
def validate_work(work,hits,ticks,gear):
    require(type(work)is dict and set(work)=={'instructions','calls','clock_calls','clock_ticks','irqs','rtis'},'Exact actual work fields required')
    require(all(type(v)is int and v>=0 for v in work.values()),'Typed actual work required');n=sum(hits.values());require(work['instructions']==work['calls']==n<=LIMIT and work['clock_ticks']==ticks,'Actual retired/CPU-call/clock work differs')
    require(work['clock_calls']>=n if gear else work['clock_calls']==0,'Original hardware callback work missing or toolkit hardware calls invented')
def validate_observation(row):
    require(type(row)is dict and set(row)=={'values','stack','wram_sha256'},'Exact observation fields required');ints(row['values'],23);ints(row['stack'],256,256);digest(row['wram_sha256']);v=row['values']
    require(v[0]<65536 and all(x<256 for x in v[1:6])and v[6]in(3,12)and v[10]<8 and v[11]<8 and v[12]<128 and v[13]<256 and v[14]<512 and v[15]<256 and v[16]<131072 and v[17]<65536 and all(v[i]in(0,1)for i in(18,19,21,22)),'CPU/device observation bounds differ');return v
def expected_stack(case,entry):
    result=[0]*256
    if entry is not None:
        pc=program(case)[1]['pre_cli']+4;a=entry['after']['values'][1];p=1|(2 if a==0 else 0)|(a&128)
        result[252:]=[a,p,pc&255,pc>>8]
    return result
def validate_report(actual,case,cut,gear=False,resume=False):
    common_keys={'case','cut_id','tier','cut','final','prefix_work','window_work','prefix_hits','window_hits','prefix_journal','journal','ram','dma_counter_role'}
    tool_keys={'mode','runtime_abi','prefix_native','prefix_interpreted','window_native','window_interpreted','guard_misses','provider_prefix','provider_suffix','origin_frame','checkpoint_sha256','final_sha256'}
    require(type(actual)is dict and set(actual)==common_keys|(set()if gear else tool_keys),'Exact execution report fields required')
    require(actual['case']==case['id']and type(actual['cut_id'])is int and actual['cut_id']==cut and actual['tier']in(('gear',)if gear else('native','interpreter')),'Execution recipe/cut/tier differs')
    require(actual['dma_counter_role']==('committed-writes'if gear else'captured-bytes'),'Actual DMA counter role differs')
    markers,plan=authored(case);initial=validate_observation(actual['cut']);final=validate_observation(actual['final']);enabled=case['kind']in KINDS[:2]
    target=markers['pre_cli']if cut==0 else 0xf800 if enabled else markers['post_dma']
    require(initial[0]==target and initial[6]==final[6]==case['divisor']and initial[16]>0 and initial[18:20]==[1,1],'Independent semantic cut differs')
    require(initial[4]==(252 if cut==1 and enabled else 255)and initial[8:10]==([1,0]if cut==1 and enabled else[0,0]),'Cut IRQ/stack identity differs')
    require(initial[2:4]==[255,0],'Independent initial X/Y differs')
    require(bool(initial[5]&4)==bool(cut==0 or enabled or case['kind']=='i-masked')and initial[17]==(0xfffe+initial[16])&65535 and(initial[13]&12)==12,'Pending source/CPU-I/address cut differs')
    require(initial[10]==(7 if case['kind']=='cpu-masked'else 6)and initial[12]==(0 if case['kind']=='cd-masked'else 12)and initial[22]==int(case['kind']!='cd-masked'),'Independent source mask relation differs')
    if cut==0:require(initial[1]==8 and initial[5]==7 and initial[16]<2048,'Pending-before-CLI literal differs')
    elif enabled:
        require(initial[16]<2048 and initial[15]==case['mode'],'Handler cut is not active DMA')
        require(initial[1]in(0x88,0xc8),'Handler saved A is not a DATA IN status-port sample')
        expected_p=(1|(2 if initial[1]==0 else 0)|(initial[1]&128)|4)&~40
        require(initial[5]==expected_p,'Independent complete handler-cut P differs')
    else:require(initial[16]==2048 and not initial[21],'Masked cut is not completed DMA')
    initial_stack=expected_stack(case,dict(after=actual['cut']))if cut==1 and enabled else[0]*256
    if cut==1 and enabled:initial_stack[252]=0
    require(actual['cut']['stack']==initial_stack,'Independent initial stack differs')
    initial_memory=bytearray(8192);initial_memory[256:512]=bytes(initial_stack);require(hashlib.sha256(initial_memory).hexdigest()==actual['cut']['wram_sha256'],'Independent initial full WRAM differs')
    require(final[:7]==[markers['done'],0,255,0,255,7,case['divisor']]and final[8:10]==[int(enabled)]*2,'Independent endpoint CPU/IRQ/RTI differs')
    require(final[10]==7 and final[12]==0 and final[14:23]==[0,0,2048,2046,1,1,2048,0,0],'Independent CD/DMA endpoint differs')
    ints(actual['ram'],65536,256);require(actual['ram']==expected_ram(),'Independent complete ADPCM RAM order differs')
    prefix=validate_hits(actual['prefix_hits'],case);window=validate_hits(actual['window_hits'],case)
    validate_work(actual['prefix_work'],prefix,0 if resume else initial[7],gear);validate_work(actual['window_work'],window,final[7]-initial[7],gear)
    require(actual['prefix_work']['irqs']==(0 if resume else initial[8])and actual['prefix_work']['rtis']==(0 if resume else initial[9])and actual['window_work']['irqs']==final[8]-initial[8]and actual['window_work']['rtis']==final[9]-initial[9],'Imported versus new IRQ/RTI work differs')
    if not gear:
        require(actual['mode']==('resume'if resume else'write'),'Execution mode differs')
        for name in tool_keys-{'mode','checkpoint_sha256','final_sha256'}:require(type(actual[name])is int and actual[name]>=0,'Typed toolkit work required')
        require(actual['runtime_abi']==ABI and actual['guard_misses']==0 and actual['provider_prefix']==(0 if resume else 1)and actual['provider_suffix']==0,'ABI/fallback/provider purity differs')
        n=actual['prefix_native']+actual['prefix_interpreted'];require(n>0 and(n if resume else actual['prefix_work']['instructions'])==n,'Imported prefix retirement count differs')
        native=actual['tier']=='native';require((actual['prefix_native'],actual['prefix_interpreted'])==((n,0)if native else(0,n)),'Imported execution tier differs')
        w=actual['window_work']['instructions'];require((actual['window_native'],actual['window_interpreted'])==((w,0)if native else(0,w)),'Fresh execution tier differs');digest(actual['checkpoint_sha256']);digest(actual['final_sha256'])
    entries=[];rtis=[]
    for phase,key in(('prefix','prefix_journal'),('window','journal')):
        journal=actual[key];require(type(journal)is list and len(journal)<=80,'Bounded detailed journal required')
        if phase=='window':require(len(journal)>=min(actual['window_work']['instructions'],64),'Detailed actual suffix prefix omitted')
        detailed_hits={};previous=initial[7]
        actual_hits=prefix if phase=='prefix'else window
        for ordinal,row in enumerate(journal):
            keys={'pc','mpr','physical','bytes','ticks','vector','after'}|({'internal','clocks','callbacks'}if gear else set())
            require(type(row)is dict and set(row)==keys,'Exact detailed instruction journal fields required');ints([row['pc'],row['ticks'],row['vector']]);ints(row['mpr'],8,256);ints(row['bytes'],maximum=256);ints(row['physical'],len(row['bytes']),2**21);require(source_key(row)in plan,'Detailed source identity differs')
            values=validate_observation(row['after']);require(row['ticks']>0 and row['vector']in(0,0xfff6),'Actual instruction clocks/IRQ2 vector required')
            identity=source_key(row);detailed_hits[identity]=detailed_hits.get(identity,0)+1;require(detailed_hits[identity]<=actual_hits.get(identity,0),'Detailed instruction/source aggregate association differs')
            if phase=='window'and ordinal<64:require(values[7]==previous+row['ticks'],'First actual suffix instructions are not contiguous');previous=values[7]
            if gear:
                require(type(row['internal'])is int and 0<=row['internal']<=row['ticks']and type(row['clocks'])is list and type(row['callbacks'])is list,'Original raw callback partition required')
                previous=None;total=0
                for span in row['clocks']:
                    ints(span,3);before,n,after=span;require(n>0 and after==before+n and(previous is None or before==previous),'Original actual callback continuity differs');previous=after;total+=n
                require(total==row['ticks']and previous==values[7],'Original returned time/callback association differs')
                for event in row['callbacks']:ints(event);require(len(event)in(5,6,8),'Original raw CPU/device callback extent differs')
                irqs=[e for e in row['callbacks']if e[1]==1];require(len(irqs)==int(bool(row['vector']))and all(e[2]==0xfff6 for e in irqs),'Original actual CPU IRQ callback missing')
            if row['vector']:
                require(row['pc']==markers['pre_cli']+1 and row['bytes']==[0xad,0,24]and values[0]==0xf800 and values[4]==252,'Independent CLI-delayed delivery source differs')
                require(values[1]in(0x88,0xc8),'IRQ saved A is not DATA IN port status')
                stack=expected_stack(case,row);stack[252]=0;require(row['after']['stack']==stack and values[5]==((stack[253]|4)&~40),'Independent IRQ frame/status differs');entries.append(row)
            if row['bytes']==[0x40]:rtis.append(row)
    require(len(entries)==int(enabled and(not resume or cut==0)),'Detailed actual entry coverage differs');require(len(rtis)==int(enabled),'Detailed RTI coverage differs')
    if cut==1 and enabled and not resume:require(entries[0]['after']==actual['cut'],'Actual completed IRQ-entry journal is not the checkpoint cut')
    entry=entries[0]if entries else None
    if enabled and resume and cut==1:
        # The origin includes the completed entry; its frame is independently constrained by PC and restored RTI.
        entry=next((r for r in actual['journal']if r['bytes']==[0x40]),None)
    if enabled:
        require(entry is not None,'Entry frame witness missing')
        stack=expected_stack(case,entry)
        # RTI's A is the saved input. For resumed handler cut the RTI row supplies it.
        require(actual['final']['stack']==stack and rtis[0]['after']['values'][0]==markers['pre_cli']+4 and rtis[0]['after']['values'][4]==255 and rtis[0]['after']['values'][1]==stack[252]and rtis[0]['after']['values'][5]==stack[253],'Independent saved A/RTI restoration differs')
    else:require(actual['final']['stack']==[0]*256,'Masked guest touched stack')
    memory=bytearray(8192);memory[0x12]=int(enabled);memory[256:512]=bytes(actual['final']['stack']);require(hashlib.sha256(memory).hexdigest()==actual['final']['wram_sha256'],'Independent final full WRAM differs')
    return 65536+256+23

def validate_capture(capture,actual,case,prefix=False,resume=False):
    from pcerecomp.capture import validate_capture as validate
    validate(capture);required={'schema','runtime_abi','capacity','dropped_instructions','unreadable_instructions','retired_instructions','complete','observations'}|({'checkpoint_origin'}if resume else set());require(set(capture)==required and type(capture['runtime_abi'])is int and capture['runtime_abi']==ABI and capture['complete']is True and not capture['dropped_instructions']and not capture['unreadable_instructions'],'Complete actual capture required')
    wanted=validate_hits(actual['prefix_hits'if prefix else'window_hits'],case);native=actual['tier']=='native';got={}
    for row in capture['observations']:
        require(set(row)=={'pc','mpr','physical','data','native_hits','interpreted_hits'},'Strict retired capture fields required');ints([row['pc'],row['native_hits'],row['interpreted_hits']]);key=source_key(row);require(key not in got and row['native_hits']==(wanted.get(key)if native else 0)and row['interpreted_hits']==(0 if native else wanted.get(key)),'Actual retired source/tier differs');got[key]=row['native_hits']+row['interpreted_hits']
    require(got==wanted and type(capture['retired_instructions'])is int and capture['retired_instructions']==sum(wanted.values()),'Actual source capture/count differs')
    if resume:require(capture['checkpoint_origin']==dict(sha256=actual['checkpoint_sha256'],ticks=actual['cut']['values'][7],frame=actual['origin_frame'],native_steps=actual['prefix_native'],interpreter_steps=actual['prefix_interpreted']),'Imported capture origin differs')

def raw_differences(gear,tool,case,cut):
    rows=[]
    for phase in('cut','final'):
        for i,(a,b)in enumerate(zip(gear[phase]['values'],tool[phase]['values'])):
            if a!=b:rows.append(dict(case=case['id'],cut=cut,phase=phase,field=OBSERVATION_COLUMNS[i],original=a,tool=b,**(dict(original_role=gear['dma_counter_role'],tool_role=tool['dma_counter_role'])if i==20 else{})))
    for name in('prefix_work','window_work'):
        for field in gear[name]:
            if gear[name][field]!=tool[name][field]:rows.append(dict(case=case['id'],cut=cut,phase=name,field=field,original=gear[name][field],tool=tool[name][field]))
    return rows

def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();compiler=Path(shutil.which(str(args.compiler))or'').resolve();require(not out.exists()and out.is_relative_to(ROOT/'.local')and compiler.is_file(),'New private output and compiler required')
    import pcerecomp.project
    require(Path(pcerecomp.project.__file__).resolve()==tool/'pcerecomp/project.py','Explicit toolkit source required');out.mkdir(parents=True);bindings=dict(tools={str(compiler):sha(compiler)},authored_sources=sources(tool));report=dict(schema=1,result='incomplete',oracle_commit=COMMIT,tool=source_identity(tool),tool_root=str(tool),commands=[],bindings=bindings,rows=[],scope=__doc__,not_checked=['Cross-core clock/callback partition equality','Hardware','Retail','IRQ1 concurrency'])
    try:
        fixture=fixtures(out);bindings['fixtures']={str(p):sha(p)for p in list(out.glob('*.pce'))+[out/'data.bin',out/'data.cue']+list(fixture.iterdir())if p.is_file()};gear=build_gear(args,out,report,bindings,compiler);binary=build_tool(args,out,report,bindings,compiler,fixture)
        for case in cases():
            for cut in(0,1):
                stem=case['id']+'-cut'+str(cut);arguments=[case['id'],str(out/(case['id']+'.pce')),str(out/'data.cue'),str(cut)];done=common.evidence([str(gear),*arguments],stem+'-gear',out,report,bindings,120);original=json.loads(done.stdout);validate_report(original,case,cut,gear=True)
                for tier in('native','interpreter'):
                    checkpoint=out/(stem+'-'+tier+'.pcec');pair=[]
                    for mode in('write','resume'):
                        label=stem+'-'+tier+'-'+mode;capture=out/(label+'-capture.json');done=common.evidence([str(binary),*arguments,mode,tier,str(checkpoint),str(capture)],label,out,report,bindings,120);actual=json.loads(done.stdout);requested_tier(actual,tier);validate_report(actual,case,cut,resume=mode=='resume');validate_capture(json.loads(capture.read_text()),actual,case,resume=mode=='resume');paths=[capture]
                        if mode=='write':
                            prefix=Path(str(capture)+'.prefix.json');validate_capture(json.loads(prefix.read_text()),actual,case,prefix=True);paths+=[prefix,checkpoint]
                        bindings['raw_outputs'].update({str(p):sha(p)for p in paths});report['rows'].append(dict(case=case,cut=cut,tier=tier,mode=mode,label=label));pair.append(actual)
                    keys={'case','cut_id','tier','cut','final','window_work','window_hits','journal','ram','prefix_native','prefix_interpreted','window_native','window_interpreted','origin_frame','checkpoint_sha256','final_sha256'}
                    require(all(pair[0][k]==pair[1][k]for k in keys),'Fresh same-tier exact continuation differs')
        report.update(result='pass',recipes=len(cases()),cases=2*len(cases()))
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:ref.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    from scripts.dma_irq_checkpoint_qualify import qualify
    result=qualify(out/'result.json');(out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

def parser():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[]);return p

if __name__=='__main__':
    try:run(parser().parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
