"""Autonomous READ-fed IRQ2 assertion inside whole block-transfer instructions.

Exact same-tier fresh-process checkpoint continuation is distinct from
cross-core semantic agreement. Original N+2 continuation calls count as one
retired block; checkpoints occur only at completed instruction boundaries.
Raw callback, clock and cut differences remain.
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
from block_dma_irq_fixture import cases,fixtures,program,expected_ram,expected_wram,FAMILIES,OPCODES,LENGTH,KINDS,LIMIT
from scripts import mapper_reference as infra,filtered_audio_reference as ref,hucard_reference as common
from pcerecomp.project import source_identity,ABI
COMMIT=ref.COMMIT
OBSERVATION_COLUMNS=('pc','a','x','y','sp','p','clock_divisor','ticks','irq_entries','rti_steps','irq_mask','irq_requests','cd_enable','cd_active','signals','dma','length','write_address','half','end','dma_counter','write_pending','irq2')
sha=lambda path:ref.sha(Path(path))
def require(value,message):
    if not value:raise ValueError(message)

def sources(tool):
    names=['scripts/block_dma_irq_reference.py','scripts/block_dma_irq_qualify.py','tests/block_dma_irq_fixture.py','tests/dma_irq_checkpoint_fixture.py','tests/block_dma_irq_support.hpp','tests/block_dma_irq_probe.cpp','tests/geargrafx_block_dma_irq_probe.cpp','tests/test_block_dma_irq_reference.py','tests/irq_trace_support.hpp','tests/reference_trace_support.hpp','tests/reset_probe_support.hpp','scripts/mapper_reference.py','scripts/filtered_audio_reference.py','scripts/psg_reference.py','scripts/hucard_reference.py']
    paths=[ROOT/name for name in names]+[tool/'CMakeLists.txt']+sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'cmake').rglob('*.cmake'))
    return {str(p.resolve()):sha(p) for p in paths}

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve() for v in (args.cmake,args.ninja));require(cmake.is_file()and ninja.is_file(),'CMake/Ninja required')
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)});q=infra.cmake_quote;wrapper=out/'wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(BlockDmaIrq LANGUAGES CXX)',*['set('+v+' OFF CACHE BOOL "" FORCE)'for v in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],f'add_subdirectory({q(args.tool_source.resolve())} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',f'add_executable(block-dma-irq {q(ROOT/"tests/block_dma_irq_probe.cpp")})',f'target_include_directories(block-dma-irq PRIVATE {q(fixture)} {q(ROOT/"tests")})','target_link_libraries(block-dma-irq PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n');bindings['tool_build_inputs']={str(config):sha(config)};build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','block-dma-irq','--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('block-dma-irq.exe'if os.name=='nt'else'block-dma-irq');bindings['tool_binary']={str(binary):sha(binary)}
    bindings['tool_objects']={str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.o','.obj','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))};return binary

def build_gear(args,out,report,bindings,compiler):
    checkout,originals=infra.pinned_snapshot(args.gear_source.resolve(),out,bindings);cpp,c=ref.compile_sources(checkout,originals);cpp.append(ROOT/'tests/geargrafx_block_dma_irq_probe.cpp');deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(checkout/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    objects=out/'gear-objects';objects.mkdir();jobs=[];report['compilations']=[]
    for i,path in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+path.stem+'.o');command=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def one(job):
        command,obj=job;done=subprocess.run(command,capture_output=True,text=True,timeout=180);log=obj.with_suffix('.log');log.write_text(done.stdout+done.stderr);report['compilations'].append(dict(object=str(obj),log=str(log),returncode=done.returncode));done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(one,jobs))
    libraries=[p.resolve()for p in args.library];require(libraries and all(p.is_file()for p in libraries),'Explicit existing external libraries required');bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-block-dma-irq.exe'
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
    fields={'instructions','calls','clock_calls','clock_ticks','irqs','rtis','blocks','block_bytes','cause_blocks'}
    require(type(work)is dict and set(work)==fields and all(type(v)is int and v>=0 for v in work.values()),'Exact typed actual work required')
    n=sum(hits.values());blocks=sum(value for key,value in hits.items()if key[3][0]in OPCODES)
    require(work['instructions']==n<=LIMIT and work['blocks']==blocks and work['block_bytes']==blocks*LENGTH,'Actual block/byte retirement extent differs')
    require(work['calls']==n+(blocks*(LENGTH+1)if gear else 0)and work['clock_ticks']==ticks,'Continuation calls are not retired instructions')
    require(work['clock_calls']>=work['calls']if gear else work['clock_calls']==0,'Actual hardware callback accounting differs')

def validate_observation(row):
    require(type(row)is dict and set(row)=={'values','stack','wram_sha256'},'Exact observation fields required');ints(row['values'],23);ints(row['stack'],256,256);digest(row['wram_sha256']);return row['values']

def block_p(case,x):return 1|(0 if x==case['loops']else x&128)

def stack_literal(case,*,entry_x=None,final=False,handler_saved=False):
    result=[0]*256
    if entry_x is not None:
        ret=program(case)[1]['block']+7;result[253:]=[block_p(case,entry_x),ret&255,ret>>8]
        if handler_saved:result[252]=2
    elif final:result[252:]=[2 if case['kind']=='enabled'else 0,1,2,0]
    return result

def validate_original_group(row,case,markers):
    v=row['after']['values'];before=row['before'];ints(v,23);ints(before,8);ints(row['bytes'],maximum=256);require(bool(row['bytes'])and type(row['cause'])is bool,'Typed original grouped source/cause required');is_block=row['bytes'][0]in OPCODES
    require(type(row['internal'])is int and 0<=row['internal']<=row['ticks']and type(row['clocks'])is list and type(row['call_rows'])is list and type(row['callbacks'])is list,'Original grouped clock/call ledger required')
    calls=row['call_rows'];require(len(calls)==(LENGTH+2 if is_block else 1),'N+2 original calls per block required');require(len(row['clocks'])<=16*len(calls)and len(row['callbacks'])<=8192,'Original bounded callback storage extent differs')
    previous=None;total=0
    for span in row['clocks']:
        ints(span,3);start,n,end=span;require(n>0 and end==start+n and(previous is None or start==previous),'Original callback continuity differs');previous=end;total+=n
    require(total==row['ticks']and previous==v[7],'Original clocks do not join completed group')
    returned=clocked=span_end=0;cause_calls=[];irq_calls=[]
    for i,call in enumerate(calls,1):
        ints(call,9);idx,ticks,inside,complete,first,internal_end,last,cause,irq=call
        require(idx==i and complete==int(i==len(calls))and inside<=ticks and first==span_end and first<=internal_end<=last<=len(row['clocks'])and last-first<=16,'Original continuation/callback phase differs')
        require(sum(s[1]for s in row['clocks'][first:internal_end])==inside and sum(s[1]for s in row['clocks'][first:last])==ticks,'Original per-call internal/remaining clocks differ')
        if is_block:require(ticks==((14 if i==1 else 3 if i==len(calls)else 6)+(8 if irq else 0))*case['divisor'],'Independent original startup/byte/epilogue call clocks differ')
        require(cause in(0,1,2,3)and irq in(0,1),'Actual cause/IRQ extent differs')
        if cause:cause_calls.append(i);require(is_block and 1<i<len(calls)and complete==0 and before[5]==0 and not before[4]&4,'Actual source cause not inside incomplete I-clear block')
        if irq:irq_calls.append(i);require(i==len(calls),'Actual IRQ did not wait for block completion')
        returned+=ticks;clocked+=inside;span_end=last
    require(returned==row['ticks']and clocked==row['internal']and span_end==len(row['clocks'])and bool(cause_calls)==row['cause']and len(irq_calls)==int(bool(row['vector'])),'Actual grouped work/cause/IRQ association differs')
    for event in row['callbacks']:ints(event);require(len(event)>=3 and(event[2],len(event))in((1,6),(5,7),(7,9))and 1<=event[0]<=len(calls),'Original callback type/extent/group association differs')
    irqs=[e for e in row['callbacks']if e[2]==1];require(len(irqs)==int(bool(row['vector']))and all(e[0]==len(calls)and e[3]==0xfff6 and e[4]==markers['block']+7 for e in irqs),'Actual original IRQ callback/source association differs')
    half=[e for e in row['callbacks']if len(e)==9 and e[2]==7 and e[3]in(7,8)and e[7]==1]

    if row['cause']:require(bool(half),'Original actual HALF/END cause callback missing')
    for i,call in enumerate(calls,1):
        flags=0
        for event in half:
            if event[0]==i:flags|=1 if event[3]==7 else 2
        require(call[7]==flags and call[8]==sum(event[0]==i for event in irqs),'Original cause/IRQ event does not join its actual continuation call')


def validate_phase_journal(work,journal):
    require(work['cause_blocks']==sum(row['cause']for row in journal),'Actual source-edge work belongs to a different phase')
    require(work['irqs']==sum(bool(row['vector'])for row in journal)and work['rtis']==sum(row['bytes']==[0x40]for row in journal),'Actual IRQ/RTI journal work belongs to a different phase')

def validate_report(actual,case,cut,gear=False,resume=False):
    common_keys={'case','cut_id','tier','cut','final','prefix_work','window_work','prefix_hits','window_hits','prefix_journal','journal','ram','dma_counter_role'}
    tool_keys={'mode','runtime_abi','prefix_native','prefix_interpreted','window_native','window_interpreted','guard_misses','provider_prefix','provider_suffix','origin_frame','checkpoint_sha256','final_sha256','prefix_blocks','prefix_block_bytes'}
    require(type(actual)is dict and set(actual)==common_keys|(set()if gear else tool_keys),'Exact execution report fields required')
    require(actual['case']==case['id']and type(actual['cut_id'])is int and actual['cut_id']==cut and actual['tier']in(('gear',)if gear else('native','interpreter')),'Execution recipe/cut/tier differs')
    require(actual['dma_counter_role']==('committed-writes'if gear else'captured-bytes'),'Actual DMA counter role differs')
    markers,plan=authored(case);initial=validate_observation(actual['cut']);final=validate_observation(actual['final']);enabled=case['kind']=='enabled'
    target=markers['pre_arm']if cut==0 else markers['handler']if enabled else markers['post_dma']
    require(initial[0]==target and initial[6]==final[6]==case['divisor'],'Independent natural boundary identity differs')
    if cut==0:
        require(initial[:7]==[target,2,case['loops'],0,255,1,case['divisor']]and initial[8:10]==[0,0]and initial[15:23]==[0,0,65534,0,0,0,0,0],'Source-absent I-clear pre-arm literal differs')
        stack=stack_literal(case);memory=bytearray(8192)
    elif enabled:
        x=initial[2];require(1<=x<=case['loops']and initial[:7]==[target,2,x,0,252,block_p(case,x)|4,case['divisor']]and initial[8:10]==[1,0],'Completed IRQ2 entry cut differs')
        require(initial[15]==2 and 0<initial[16]<2048 and initial[18:20]==[1,1]and initial[22]==1,'Handler entry did not retain active DMA/source')
        stack=stack_literal(case,entry_x=x);memory=bytearray(expected_wram(case));memory[18]=0;memory[256:512]=bytes(stack)
    else:
        require(initial[:7]==[target,0,0,0,255,3,case['divisor']]and initial[8:10]==[0,0]and initial[15:23]==[2,2048,2046,1,1,2048,0,1],'Masked completed-DMA cut differs')
        stack=stack_literal(case,final=True);memory=bytearray(expected_wram(case))
    require(initial[10]==(6 if enabled else 7)and initial[12]==12,'Independent CPU/CD mask relation differs')
    require(initial[17]==(0xfffe+initial[16])&65535 and actual['cut']['stack']==stack,'Independent cut address/stack differs')
    require(hashlib.sha256(memory).hexdigest()==actual['cut']['wram_sha256'],'Independent initial complete WRAM differs')
    require(final[:7]==[markers['done'],0,0,0,255,7,case['divisor']]and final[8:10]==[int(enabled)]*2,'Independent endpoint CPU/IRQ/RTI differs')
    require(final[10]==7 and final[12]==0 and final[14:23]==[0,0,2048,2046,1,1,2048,0,0],'Independent READ/DMA endpoint differs')
    require(actual['final']['stack']==stack_literal(case,final=True)and actual['final']['wram_sha256']==hashlib.sha256(bytes(expected_wram(case))).hexdigest(),'Independent endpoint block data/witness/stack residue differs')
    ints(actual['ram'],65536,256);require(actual['ram']==expected_ram(),'Independent complete ADPCM RAM differs')
    prefix=validate_hits(actual['prefix_hits'],case);window=validate_hits(actual['window_hits'],case)
    validate_work(actual['prefix_work'],prefix,0 if resume else initial[7],gear);validate_work(actual['window_work'],window,final[7]-initial[7],gear)
    require(actual['prefix_work']['irqs']==(0 if resume else initial[8])and actual['prefix_work']['rtis']==(0 if resume else initial[9])and actual['window_work']['irqs']==final[8]-initial[8]and actual['window_work']['rtis']==final[9]-initial[9],'Imported versus new IRQ/RTI work differs')
    require(actual['prefix_work']['cause_blocks']+actual['window_work']['cause_blocks']==int(not resume or cut==0),'New versus imported source-edge work differs')
    imported_blocks=0 if cut==0 else case['loops']-initial[2]+1 if enabled else case['loops']
    if not gear:
        require(actual['mode']==('resume'if resume else'write'),'Execution mode differs')
        for name in tool_keys-{'mode','checkpoint_sha256','final_sha256'}:require(type(actual[name])is int and actual[name]>=0,'Strict actual toolkit work types required')
        require(actual['runtime_abi']==ABI and actual['guard_misses']==0 and actual['provider_prefix']==(0 if resume or cut==0 else 1)and actual['provider_suffix']==int(cut==0),'ABI/fallback/provider purity differs')
        n=actual['prefix_native']+actual['prefix_interpreted'];require(n>0 and(n if resume else actual['prefix_work']['instructions'])==n,'Imported prefix retirements differ')
        native=actual['tier']=='native';require((actual['prefix_native'],actual['prefix_interpreted'])==((n,0)if native else(0,n)),'Imported actual execution tier differs')
        w=actual['window_work']['instructions'];require((actual['window_native'],actual['window_interpreted'])==((w,0)if native else(0,w)),'New execution tier differs')
        require(actual['prefix_blocks']==imported_blocks and actual['prefix_block_bytes']==imported_blocks*LENGTH and actual['window_work']['blocks']==case['loops']-imported_blocks,'Imported/new block-byte counters differ');digest(actual['checkpoint_sha256']);digest(actual['final_sha256'])
    entries=[];rtis=[];causes=[]
    for phase,key in(('prefix','prefix_journal'),('window','journal')):
        journal=actual[key];require(type(journal)is list and len(journal)<=40,'Selected detailed journal extent differs')
        for row in journal:
            keys={'pc','mpr','physical','bytes','before','ticks','vector','block_index','cause','after'}|({'internal','clocks','call_rows','callbacks'}if gear else set())
            require(type(row)is dict and set(row)==keys,'Exact detailed instruction fields required');ints([row['pc'],row['ticks'],row['vector'],row['block_index']]);ints(row['mpr'],8,256);ints(row['bytes'],maximum=256);ints(row['physical'],len(row['bytes']),2**21);ints(row['before'],8);require(type(row['cause'])is bool and source_key(row)in plan,'Detailed actual source identity differs')
            v=validate_observation(row['after']);before=row['before'];is_block=row['bytes'][0]in OPCODES;require(row['vector']in(0,0xfff6),'Actual IRQ2 vector differs')
            if is_block:
                index=row['block_index'];x=case['loops']-index+1;p=block_p(case,x);require(1<=index<=case['loops']and before[:5]==[2,x,0,255,p],'Independent pre-block A/X/Y/SP/P differs')
                require(row['ticks']==(17+6*LENGTH+(8 if row['vector']else 0))*case['divisor'],'Independent grouped block clock total differs')
            if gear:validate_original_group(row,case,markers)
            if row['cause']:
                require(is_block and before[5:8]==[0,0,0]and v[18:20]==[1,1],'Independent first source-edge relation differs');causes.append(row)
            if row['vector']:
                require(enabled and is_block and row['cause']and v[:7]==[markers['handler'],2,before[1],0,252,before[4]|4,case['divisor']]and v[8:10]==[1,0],'Independent deferred IRQ entry differs')
                require(row['after']['stack']==stack_literal(case,entry_x=before[1]),'Independent completed-block IRQ stack differs');entries.append(row)
            if row['bytes']==[0x40]:
                require(v[0]==markers['block']+7 and v[1]==2 and v[2]==before[1]and v[3]==0 and v[4]==255 and v[5]==block_p(case,before[1])and v[8:10]==[1,1],'Independent IRQ RTI restoration differs');rtis.append(row)
        validate_phase_journal(actual[phase+'_work'],journal)
        phase_hits=prefix if phase=='prefix'else window
        journal_hits={}
        for row in journal:
            key=source_key(row);journal_hits[key]=journal_hits.get(key,0)+1
            require(key in phase_hits and journal_hits[key]<=phase_hits[key],'Detailed journal source does not join actual phase retirements')
    require(len(causes)==int(not resume or cut==0)and len(entries)==int(enabled and(not resume or cut==0))and len(rtis)==int(enabled),'Detailed actual new cause/entry/RTI coverage differs')
    if enabled and cut==1 and not resume:require(entries[0]['after']==actual['cut'],'Completed entry journal/cut snapshot differs')
    return 65536+8192+23


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
                    keys={'case','cut_id','tier','cut','final','window_work','window_hits','journal','ram','prefix_native','prefix_interpreted','window_native','window_interpreted','origin_frame','checkpoint_sha256','final_sha256','prefix_blocks','prefix_block_bytes'}
                    require(all(pair[0][k]==pair[1][k]for k in keys),'Fresh same-tier exact continuation differs')
        report.update(result='pass',recipes=len(cases()),cases=2*len(cases()))
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:ref.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    from scripts.block_dma_irq_qualify import qualify
    result=qualify(out/'result.json');(out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

def parser():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[]);return p

if __name__=='__main__':
    try:run(parser().parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
