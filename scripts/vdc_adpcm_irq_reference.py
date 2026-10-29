"""Autonomous READ-fed ADPCM IRQ2 and VDC IRQ1 during queued VRAM waits.

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
from vdc_adpcm_irq_fixture import cases,fixtures,program,expected_ram,expected_wram,expected_vram,ACCESS,POLICIES,WORDS,OPCODES,LIMIT
from scripts import mapper_reference as infra,filtered_audio_reference as ref,hucard_reference as common
from pcerecomp.project import source_identity,ABI
COMMIT=ref.COMMIT
OBSERVATION_COLUMNS=('pc','a','x','y','sp','p','clock_divisor','ticks','irq_entries','rti_steps','irq_mask','irq_requests','cd_enable','cd_active','signals','dma','length','write_address','half','end','dma_counter','write_pending','irq2','vdc_status','irq1','vram_dma_pending','vram_read_pending','vram_write_pending','vram_read_buffer','marr','mawr','sour','desr','lenr','vram_bus','transfer_delay','wait_ticks','vce_divider','vdc_counter','cpu_sample','selected_ar','last_vector')
sha=lambda path:ref.sha(Path(path))
def require(value,message):
    if not value:raise ValueError(message)

def sources(tool):
    names=['scripts/vdc_adpcm_irq_reference.py','scripts/vdc_adpcm_irq_qualify.py','tests/vdc_adpcm_irq_fixture.py','tests/dma_irq_checkpoint_fixture.py','tests/vdc_adpcm_irq_support.hpp','tests/vdc_adpcm_irq_probe.cpp','tests/geargrafx_vdc_adpcm_irq_probe.cpp','tests/test_vdc_adpcm_irq_reference.py','tests/irq_trace_support.hpp','tests/reference_trace_support.hpp','tests/reset_probe_support.hpp','scripts/mapper_reference.py','scripts/filtered_audio_reference.py','scripts/psg_reference.py','scripts/hucard_reference.py']
    paths=[ROOT/name for name in names]+[tool/'CMakeLists.txt']+sorted((tool/'pcerecomp').glob('*.py'))+sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'cmake').rglob('*.cmake'))
    return {str(p.resolve()):sha(p) for p in paths}

def build_tool(args,out,report,bindings,compiler,fixture):
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve() for v in (args.cmake,args.ninja));require(cmake.is_file()and ninja.is_file(),'CMake/Ninja required')
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)});q=infra.cmake_quote;wrapper=out/'wrapper';wrapper.mkdir()
    lines=['cmake_minimum_required(VERSION 3.20)','project(VdcAdpcmIrq LANGUAGES CXX)',*['set('+v+' OFF CACHE BOOL "" FORCE)'for v in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],f'add_subdirectory({q(args.tool_source.resolve())} tool)',f'pce_add_native_module(_module MODULE {q(fixture/"module.cpp")} MANIFEST {q(fixture/"module.json")})',f'add_executable(vdc-adpcm-irq {q(ROOT/"tests/vdc_adpcm_irq_probe.cpp")})',f'target_include_directories(vdc-adpcm-irq PRIVATE {q(fixture)} {q(ROOT/"tests")})','target_link_libraries(vdc-adpcm-irq PRIVATE ${_module} pce-runtime)']
    config=wrapper/'CMakeLists.txt';config.write_text('\n'.join(lines)+'\n');bindings['tool_build_inputs']={str(config):sha(config)};build=out/'tool-build'
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],'tool-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','vdc-adpcm-irq','--parallel','4'],'tool-build',out,report,bindings,600)
    binary=build/('vdc-adpcm-irq.exe'if os.name=='nt'else'vdc-adpcm-irq');bindings['tool_binary']={str(binary):sha(binary)}
    bindings['tool_objects']={str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.o','.obj','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))};return binary

def build_gear(args,out,report,bindings,compiler):
    checkout,originals=infra.pinned_snapshot(args.gear_source.resolve(),out,bindings);cpp,c=ref.compile_sources(checkout,originals);cpp.append(ROOT/'tests/geargrafx_vdc_adpcm_irq_probe.cpp');deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(checkout/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    objects=out/'gear-objects';objects.mkdir();jobs=[];report['compilations']=[]
    for i,path in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+path.stem+'.o');command=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((command,obj));report['commands'].append(command)
    def one(job):
        command,obj=job;done=subprocess.run(command,capture_output=True,text=True,timeout=180);log=obj.with_suffix('.log');log.write_text(done.stdout+done.stderr);report['compilations'].append(dict(object=str(obj),log=str(log),returncode=done.returncode));done.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(one,jobs))
    libraries=[p.resolve()for p in args.library];require(libraries and all(p.is_file()for p in libraries),'Explicit existing external libraries required');bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-vdc-adpcm-irq.exe'
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
    fields={'instructions','calls','clock_calls','clock_ticks','irqs','rtis','blocks','block_bytes','adpcm_cause_groups','vdc_cause_groups','wait_ticks'}
    require(type(work)is dict and set(work)==fields and all(type(v)is int and v>=0 for v in work.values()),'Exact typed actual work required')
    n=sum(hits.values());blocks=byte_count=extra_calls=0
    for key,count in hits.items():
        raw=key[3]
        if raw[0]in OPCODES:
            length=raw[5]|raw[6]<<8;require(length>0,'Authored nonzero block length required');blocks+=count;byte_count+=count*length;extra_calls+=count*(length+1)
    require(work['instructions']==n<=LIMIT and work['blocks']==blocks and work['block_bytes']==byte_count,'Actual variable-length block/byte retirement extent differs')
    require(work['calls']==n+(extra_calls if gear else 0)and work['clock_ticks']==ticks,'Continuation calls are not retired instructions')
    require(work['clock_calls']>=work['calls']if gear else work['clock_calls']==0,'Actual hardware callback accounting differs')

def validate_observation(row):
    require(type(row)is dict and set(row)=={'values','stack','wram_sha256','vram_sha256'},'Exact observation fields required');ints(row['values'],42);ints(row['stack'],256,256);digest(row['wram_sha256']);digest(row['vram_sha256']);return row['values']

def vram_hash(words):return hashlib.sha256(b''.join(v.to_bytes(2,'little')for v in words)).hexdigest()
def saved_a(case):return 0xa6 if case['access']=='high'else 2
def saved_p(case):return 129 if case['access']=='high'else 1

def stack_literal(case,*,cut=None,second=False):
    result=[0]*256
    if cut==0:result[253:]=[1 if case['divisor']==3 else 0,2,0]
    else:
        ret=program(case)[1]['return_pc']+int(second);result[253:]=[saved_p(case),ret&255,ret>>8]
        if cut!=1:result[252]=saved_a(case)
    return result

def validate_clock_group(row,case,markers):
    """Original actual RunInstruction calls, hardware spans and source edges.

    Structural fixtures may shorten the DMA countdown. The complete report
    separately requires the authored 4096-word command and full memory image.
    """
    v=row['after']['values'];ints(v,42);ints(row['before'],14);raw=row['bytes'];ints(raw,maximum=256)
    block=raw[0]in OPCODES;length=raw[5]|raw[6]<<8 if block else 0
    require(not block or length>0,'Original block operand length required')
    spans=row['clocks'];calls=row['call_rows'];events=row['callbacks'];edges=row['edges']
    require(all(type(x)is list for x in(spans,calls,events,edges))and 0<len(spans)<=1000000 and len(events)<=8192,'Bounded actual original ledger required')
    require(len(calls)==(length+2 if block else 1),'Actual original N+2 calls differ from source operands')
    previous=None;total=waits=0
    for span in spans:
        ints(span,6);start,n,end,waiting,pending,requests=span
        require(n>0 and end==start+n and(previous is None or start==previous)and waiting in(0,1)and pending<8 and requests<8,'Original hardware clock continuity/type differs')
        require(not waiting or n==3,'Original StallFastCycle must be an actual three-tick callback');previous=end;total+=n;waits+=n*waiting
    require(total==row['ticks']and previous==v[7]and waits==row['wait_ticks'],'Original clock/wait totals do not join group endpoint')
    returned=internal=span_end=0
    for i,call in enumerate(calls,1):
        ints(call,10);idx,ticks,inside,complete,first,inside_end,last,extra,irq,causes=call
        require(idx==i and complete==int(i==len(calls))and inside<=ticks and first==span_end and first<=inside_end<=last<=len(spans)and irq in(0,1)and causes<=7,'Original continuation/callback phase differs')
        require(sum(s[1]for s in spans[first:inside_end])==inside and sum(s[1]for s in spans[first:last])==ticks and sum(s[1]for s in spans[first:inside_end]if s[3])==extra and not any(s[3]for s in spans[inside_end:last]),'Original per-call internal/remaining/dynamic clocks differ')
        if block:
            fixed=14 if i==1 else 3 if i==len(calls)else 8 if raw[0]==0xf3 else 6
            require(ticks==(fixed+8*irq)*case['divisor']+extra,'Independent original startup/byte/epilogue clocks differ')
        if irq:require(i==len(calls),'IRQ delivered during incomplete original block')
        if causes:
            require(row['pc']==markers['target']and not row['before'][4]&4 and row['before'][5:10]==[0,0,0,0,0]and extra>0,'Original cause not inside intended I-clear target wait')
            if block:require(i==2 and complete==0,'TAI causes must occur in actual incomplete first-byte call')
        returned+=ticks;internal+=inside;span_end=last
    require(returned==row['ticks']and internal==row['internal']and span_end==len(spans),'Original actual call/group accounting differs')
    for event in events:
        ints(event);require(len(event)>=3 and(event[2],len(event))in((1,6),(2,12),(5,7),(7,9))and 1<=event[0]<=len(calls),'Original callback type/extent/call differs')
        call=calls[event[0]-1];start=spans[call[4]][0];end=spans[call[6]-1][2]
        require(start<=event[1]<=end,'Original callback timestamp outside its actual call')
    irq_events=[e for e in events if e[2]==1]
    require(len(irq_events)==int(bool(row['vector'])),'Original actual IRQ callback missing/duplicated')
    for event in irq_events:
        first=event[3]==0xfff8;require(event[0]==len(calls)and event[3]==row['vector']and event[3]in(0xfff8,0xfff6)and event[4]==markers['return_pc']+int(not first)and event[5]==4,'Original IRQ callback/vector/return-PC/mask differs')
    cause_events=[(e,1 if e[3]==7 else 2)for e in events if e[2]==7 and e[3]in(7,8)and e[7]==1]+[(e,4)for e in events if e[2]==2 and e[3]==6]
    flags=0
    for i,call in enumerate(calls,1):
        bits=0
        for event,bit in cause_events:
            if event[0]==i and not flags&bit:bits|=bit;flags|=bit
        require(call[9]==bits and call[8]==sum(e[0]==i for e in irq_events),'Original cause/IRQ callback does not join its actual call')
    require(flags==row['causes'],'Original source callbacks do not join group cause mask')
    last_edge=-1;prior_sample=spans[0][4]
    for edge in edges:
        require(type(edge)is dict and set(edge)=={'span','kinds','before','after'},'Exact selected original edge required');ints([edge['span'],edge['kinds']]);ints(edge['before'],19);ints(edge['after'],19)
        index=edge['span'];pre,post=edge['before'],edge['after'];require(last_edge<index<len(spans),'Selected actual edge ordering differs')
        # Sample transitions are compared with the preceding hardware callback,
        # not the previous selected edge: all intervening samples are retained.
        prior_sample=spans[index-1][4]if index else spans[0][4]
        kinds=int(pre[3]!=post[3])|2*int(pre[6:8]!=post[6:8])|4*int(pre[5]>0 and post[5]==0)|8*int(pre[14:16]!=post[14:16])|16*int(prior_sample!=pre[2])
        require((edge['kinds']==kinds if index else edge['kinds']&15==kinds&15)and 0<edge['kinds']<32 and pre[2]==spans[index][4]and post[3]==spans[index][5],'Original selected edge/kernel/sample join differs');last_edge=index
    # Every observable IRR/sample transition must be present; queue/source
    # transitions have additional selected kernels rather than guessed clocks.
    edge_indices={e['span']for e in edges}
    for i,span in enumerate(spans):
        if i and span[4]!=spans[i-1][4]:require(i in edge_indices,'Actual pending sample transition omitted')
    if row['pc']==markers['target']:
        require(flags==7 and row['vector']==0xfff8 and row['ticks']==(41 if block else 14)*case['divisor']+row['wait_ticks'],'Independent target fixed/wait/IRQ total differs')
        require(len(cause_events)==3 and sorted(bit for _,bit in cause_events)==[1,2,4],'Exactly three first source callbacks required')
        source_spans={}
        for event,bit in cause_events:
            call=calls[event[0]-1];matching=[i for i in range(call[4],call[5])if spans[i][3]and spans[i][0]<event[1]<=spans[i][2]]
            require(len(matching)==1,'Actual source callback not inside dynamic wait callback');source_spans[bit]=matching[0]
        ends=[e for e in edges if e['kinds']&4];grants=[e for e in edges if e['before'][6]and not e['after'][6]]
        require(len(ends)==1 and grants,'Actual VDC completion/queued read grant missing');end=ends[0];grant=grants[0]
        require(end['span']==source_spans[4]and max(source_spans[1],source_spans[2])<end['span']<grant['span']and end['before'][6]==end['after'][6]==1 and grant['before'][2:4]==[3,3],'Both sources must be sampled before queued VRAM grant')
        for bit,index in((1,14),(2,15)):
            matching=[e for e in edges if e['span']==source_spans[bit]]
            require(len(matching)==1,'Actual source callback has no selected hardware kernel');edge=matching[0];pre,post=edge['before'],edge['after']
            require(pre[index]==0 and post[index]==1 and pre[5]>0 and pre[6]==post[6]==1 and not pre[0]&4 and pre[1]==4 and post[3]&1,'Actual ADPCM callback lacks its source-absent kernel assertion')
        require(end['before'][3]==1 and end['after'][3]==3 and end['after'][4]&16 and end['before'][14:16]==end['after'][14:16]==[1,1],'VDC completion did not preserve independent pending ADPCM source')
        require(all(e['before'][5]>0 for e in edges if e['kinds']&8),'ADPCM source arrived after VDC DMA completion')

# Retained alias for contributors familiar with the preceding block probe.
validate_original_group=validate_clock_group

def validate_phase_journal(work,journal):
    require(work['adpcm_cause_groups']==sum(bool(r['causes']&3)for r in journal)and work['vdc_cause_groups']==sum(bool(r['causes']&4)for r in journal),'Actual device source-edge work belongs to a different phase')
    require(work['irqs']==sum(bool(r['vector'])for r in journal)and work['rtis']==sum(r['bytes']==[0x40]for r in journal),'Actual IRQ/RTI journal work belongs to a different phase')

def validate_provider_witnesses(rows,actual,case,prefix=False,resume=False):
    require(type(rows)is list,'Actual provider witnesses required');wanted=int(not resume and actual['cut_id']>0)if prefix else int(actual['cut_id']==0)
    require(len(rows)==wanted,'Imported/new real provider source witnesses differ')
    markers,plan=authored(case);journal=actual['prefix_journal'if prefix else'journal']
    for row in rows:
        require(type(row)is dict and set(row)=={'pc','mpr','physical','bytes','values'},'Exact real provider witness required');ints(row['values'],9);ints(row['mpr'],8,256);ints(row['physical'],len(row['bytes']),2**21);ints(row['bytes'],maximum=256)
        require(row['pc']==markers['target']and source_key(row)in plan,'Real provider witness full source identity differs')
        targets=[r for r in journal if r['pc']==markers['target']];require(len(targets)==1,'Actual provider witness target group missing');target=targets[0];tick,wait,pending,read,p,entries,half,end,length=row['values'];end_tick=target['after']['values'][7]
        require(end_tick-target['ticks']<=tick<end_tick and target['before'][13]<wait<target['after']['values'][36]and pending>=100 and read==1 and not p&4 and entries==half==end==length==0,'Real provider witness not source-absent inside I-clear pending target wait')
        # VDC pending counts dots. Even divider2 has >2*pending-3 master
        # ticks before completion; DATA capture36 + maximum write slot45
        # completes first, including bus-sync granularity. No exact native
        # event timestamp or mid-instruction snapshot is claimed.
        require(2*pending-3>36+45 and end_tick-tick>36+45,'Independent native source-before-grant lower bound differs')

def validate_report(actual,case,cut,gear=False,resume=False):
    common_keys={'case','cut_id','tier','cut','final','prefix_work','window_work','prefix_hits','window_hits','prefix_journal','journal','ram','vram','dma_counter_role','vdc_counter_role'}
    scalar_keys={'runtime_abi','prefix_native','prefix_interpreted','window_native','window_interpreted','guard_misses','provider_prefix','provider_suffix','origin_frame','prefix_blocks','prefix_block_bytes'}
    tool_keys=scalar_keys|{'mode','checkpoint_sha256','final_sha256','prefix_provider_witnesses','window_provider_witnesses'}
    require(type(actual)is dict and set(actual)==common_keys|(set()if gear else tool_keys),'Exact execution report fields required')
    require(actual['case']==case['id']and type(actual['cut_id'])is int and actual['cut_id']==cut and cut in(0,1,2)and actual['tier']in(('gear',)if gear else('native','interpreter')),'Execution recipe/cut/tier differs')
    require(actual['dma_counter_role']==('committed-writes'if gear else'captured-bytes')and actual['vdc_counter_role']==('source-progress'if gear else'completed-words'),'Actual counters require distinct explicit roles')
    markers,plan=authored(case);initial=validate_observation(actual['cut']);final=validate_observation(actual['final']);retain=case['policy']=='retain';total=2 if retain else 1
    target=(markers['pre_dma'],markers['handler1'],markers['post_ack'])[cut]
    require(initial[0]==target and initial[6]==final[6]==case['divisor']and initial[37]==final[37]==case['vce'],'Independent natural boundary/speed/VCE identity differs')
    stack=stack_literal(case,cut=cut);memory=bytearray(8192)
    if cut==0:
        require(initial[:7]==[target,15,0,0,255,1,case['divisor']]and initial[8:14]==[0,0,4,0,12,0]and initial[15:28]==[2,0,65534,0,0,0,0,0,0,0,0,0,0]and initial[28:34]==[0x5aa5,4096,4096,0,8192,255]and initial[36]==0 and initial[38:]==[0,0,18,0],'Independent source-absent pre-DMA launch differs')
        initial_vram=[0]*32768;initial_vram[0]=0xa65c;initial_vram[WORDS-1]=0x5aa5
    else:
        require(initial[8:11]==[1,0,4]and initial[15]==2 and 0<initial[16]<2048 and initial[17]==(65534+initial[16])&65535 and initial[18:20]==[1,1]and initial[25]==0 and initial[31:34]==[WORDS,8192+WORDS,65535]and initial[38]==WORDS and initial[41]==0xfff8,'Independent delivered cut device/queue/register state differs')
        if cut==1:
            require(initial[:7]==[target,saved_a(case),0,0,252,saved_p(case)|4,case['divisor']]and initial[11:13]==[3,12]and initial[13]in(12,76)and initial[22]==initial[24]==1 and initial[23]&16,'Both pending sources must enter IRQ1 first')
        else:
            require(initial[:7]==[target,12 if retain else 0,0,0,251,5 if retain else 7,case['divisor']]and initial[11]==int(retain)and initial[12]==(12 if retain else 0)and initial[13]in(12,76)and initial[22]==int(retain)and initial[24]==0 and not initial[23]&16,'VDC ACK / CD non-ACK / mask policy differs')
            memory[17]=1;memory[20]=16;memory[22]=12
        if case['access']=='tai':memory[512:514]=bytes([0x5c,0xa6])
        initial_vram=expected_vram()
    memory[256:512]=bytes(stack)
    require(actual['cut']['stack']==stack and actual['cut']['wram_sha256']==hashlib.sha256(memory).hexdigest()and actual['cut']['vram_sha256']==vram_hash(initial_vram),'Independent complete cut WRAM/stack/VRAM differs')
    require(final[:7]==[markers['done'],0,0,0,255,7,case['divisor']]and final[8:13]==[total,total,7,0,0]and final[14:23]==[0,0,2048,2046,1,1,2048,0,0]and final[24:28]==[0,0,0,0]and final[29]==2 and final[31:34]==[WORDS,8192+WORDS,65535]and final[38]==WORDS and final[40:]==[2,0xfff6 if retain else 0xfff8],'Independent completed CPU/IRQ/DMA/queue endpoint differs')
    require(actual['final']['stack']==stack_literal(case,second=retain)and actual['final']['wram_sha256']==hashlib.sha256(bytes(expected_wram(case))).hexdigest()and actual['final']['vram_sha256']==vram_hash(expected_vram()),'Independent complete endpoint WRAM/stack/VRAM differs')
    ints(actual['ram'],65536,256);ints(actual['vram'],32768,65536);require(actual['ram']==expected_ram()and actual['vram']==expected_vram(),'Independent full ADPCM RAM/VRAM image differs')
    prefix=validate_hits(actual['prefix_hits'],case);window=validate_hits(actual['window_hits'],case)
    validate_work(actual['prefix_work'],prefix,0 if resume else initial[7],gear);validate_work(actual['window_work'],window,final[7]-initial[7],gear)
    require(actual['prefix_work']['irqs']==(0 if resume else initial[8])and actual['prefix_work']['rtis']==0 and actual['window_work']['irqs']==final[8]-initial[8]and actual['window_work']['rtis']==total,'Imported versus new IRQ/RTI work differs')
    for key in('adpcm_cause_groups','vdc_cause_groups'):require(actual['prefix_work'][key]==int(not resume and cut>0)and actual['window_work'][key]==int(cut==0),'New/imported device source-edge phase differs')
    require(actual['prefix_work']['wait_ticks']==(0 if resume else initial[36])and actual['window_work']['wait_ticks']==final[36]-initial[36],'Cumulative actual wait clock phase differs')
    imported_blocks=7+case['loops']+int(case['divisor']==12)+int(cut>0 and case['access']=='tai');imported_bytes=24300+1023*case['loops']+300*int(case['divisor']==12)+2*int(cut>0 and case['access']=='tai')
    if not gear:
        require(actual['mode']==('resume'if resume else'write'),'Execution mode differs')
        require(all(type(actual[k])is int and actual[k]>=0 for k in scalar_keys),'Strict actual toolkit work types required')
        require(actual['runtime_abi']==ABI and actual['guard_misses']==0 and actual['provider_prefix']==int(not resume and cut>0)and actual['provider_suffix']==int(cut==0),'ABI/fallback/provider restore purity differs')
        n=actual['prefix_native']+actual['prefix_interpreted'];native=actual['tier']=='native';require(n>0 and(resume or actual['prefix_work']['instructions']==n)and(actual['prefix_native'],actual['prefix_interpreted'])==((n,0)if native else(0,n)),'Imported actual execution tier/retirements differ')
        w=actual['window_work']['instructions'];require((actual['window_native'],actual['window_interpreted'])==((w,0)if native else(0,w)),'New actual execution tier differs')
        require(actual['prefix_blocks']==imported_blocks and actual['prefix_block_bytes']==imported_bytes and actual['window_work']['blocks']==int(cut==0 and case['access']=='tai')and actual['window_work']['block_bytes']==2*int(cut==0 and case['access']=='tai'),'Imported/new actual variable-length block counters differ');digest(actual['checkpoint_sha256']);digest(actual['final_sha256'])
        validate_provider_witnesses(actual['prefix_provider_witnesses'],actual,case,prefix=True,resume=resume);validate_provider_witnesses(actual['window_provider_witnesses'],actual,case,resume=resume)
    entries=[];rtis=[];causes=[];launches=[];ackrows=[]
    for phase,key in(('prefix','prefix_journal'),('window','journal')):
        journal=actual[key];require(type(journal)is list and len(journal)<=64,'Selected detailed journal extent differs');phase_hits=prefix if phase=='prefix'else window;journal_hits={}
        for row in journal:
            keys={'pc','mpr','physical','bytes','before','ticks','wait_ticks','vector','causes','after'}|({'internal','clocks','call_rows','callbacks','edges'}if gear else set())
            require(type(row)is dict and set(row)==keys,'Exact detailed instruction fields required');ints([row['pc'],row['ticks'],row['wait_ticks'],row['vector'],row['causes']]);ints(row['mpr'],8,256);ints(row['bytes'],maximum=256);ints(row['physical'],len(row['bytes']),2**21);ints(row['before'],14);require(source_key(row)in plan and row['vector']in(0,0xfff8,0xfff6)and row['causes']in(0,7),'Detailed source/vector/cause identity differs')
            v=validate_observation(row['after']);before=row['before'];source=source_key(row);journal_hits[source]=journal_hits.get(source,0)+1;require(journal_hits[source]<=phase_hits.get(source,0),'Detailed source does not join actual phase retirements')
            require(v[36]-before[13]==row['wait_ticks'],'Detailed cumulative wait delta differs')
            if gear:validate_clock_group(row,case,markers)
            if row['pc']==markers['pre_dma']:
                launches.append(row);require(row['bytes']==[0x8d,3,0]and before[4:10]==[1,0,0,0,0,0]and v[25]>0 and v[31]+v[33]+1==WORDS and v[32]==8192+v[31],'Actual DMA launch source-absence/full extent differs')
                if gear:require(any(e[2]==2 and e[3]==7 and e[8:12]==[0,8192,2,4096]for e in row['callbacks']),'Original actual 4096-word DMA command callback missing')
            if row['causes']:
                causes.append(row);require(row['pc']==markers['target']and before[0:10]==[2,0,0,255,1,0,0,0,0,0]and before[10]>0 and before[11]==1 and row['wait_ticks']>0 and row['vector']==0xfff8 and row['ticks']==(14 if case['access']=='high'else 41)*case['divisor']+row['wait_ticks'],'Independent target source-absent wait/priority relation differs')
            if row['vector']:
                entries.append(row);first=row['vector']==0xfff8;ret=markers['return_pc']+int(not first)
                require((row['pc']==markers['target']and row['causes']==7)if first else(row['pc']==markers['return_pc']and retain and row['bytes']==[0xea]),'Actual IRQ source/priority differs')
                require(v[:7]==[markers['handler1']if first else markers['handler2'],saved_a(case),0,0,252,saved_p(case)|4,case['divisor']]and v[8:10]==([1,0]if first else[2,1])and row['after']['stack'][253:]==[saved_p(case),ret&255,ret>>8],'Independent delivered vector/descending frame differs')
                if first:require(v[11]==3 and v[18:20]==[1,1]and v[22]==v[24]==1 and v[25]==0,'IRQ1 did not win with both sources pending')
            if row['pc']>=markers['handler1']and row['pc']<markers['handler2']and row['bytes']==[0xad,0,0]:
                ackrows.append(row);require(before[8:10]==[1,1]and v[1]==16 and v[24]==0 and v[22]==1 and v[11]==1 and v[18:20]==[1,1],'VDC status acknowledge cleared unrelated ADPCM source')
            if row['bytes']==[0x40]:
                rtis.append(row);ret=markers['return_pc']+int(v[9]==2);require(v[:7]==[ret,saved_a(case),0,0,255,saved_p(case),case['divisor']]and row['after']['stack'][252]==saved_a(case),'Independent RTI restoration differs')
        validate_phase_journal(actual[phase+'_work'],journal)
        require(actual[phase+'_work']['wait_ticks']==sum(row['wait_ticks']for row in journal),'Actual wait group omitted or assigned to another phase')
    require(len(causes)==int(not resume or cut==0)and len(entries)==total-(initial[8]if resume else 0)and len(rtis)==total and len(launches)==int(not resume or cut==0)and len(ackrows)==int(not resume or cut<2),'Detailed actual source/entry/RTI/ACK coverage differs')
    if cut==1 and not resume:require(entries[0]['after']==actual['cut'],'Completed first entry journal/cut differs')
    return 65536+8192+32768+42


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
            if a!=b:rows.append(dict(case=case['id'],cut=cut,phase=phase,field=OBSERVATION_COLUMNS[i],original=a,tool=b,**(dict(original_role=gear['dma_counter_role'],tool_role=tool['dma_counter_role'])if i==20 else dict(original_role=gear['vdc_counter_role'],tool_role=tool['vdc_counter_role'])if i==38 else{})))
    for name in('prefix_work','window_work'):
        for field in gear[name]:
            if gear[name][field]!=tool[name][field]:rows.append(dict(case=case['id'],cut=cut,phase=name,field=field,original=gear[name][field],tool=tool[name][field]))
    return rows

def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();compiler=Path(shutil.which(str(args.compiler))or'').resolve();require(not out.exists()and out.is_relative_to(ROOT/'.local')and compiler.is_file(),'New private output and compiler required')
    import pcerecomp.project
    require(Path(pcerecomp.project.__file__).resolve()==tool/'pcerecomp/project.py','Explicit toolkit source required');out.mkdir(parents=True);bindings=dict(tools={str(compiler):sha(compiler)},authored_sources=sources(tool));report=dict(schema=1,result='incomplete',oracle_commit=COMMIT,tool=source_identity(tool),tool_root=str(tool),commands=[],bindings=bindings,rows=[],scope=__doc__,not_checked=['Cross-core clock/callback partition equality','Exact native source-event timestamps','Hardware','Retail'])
    try:
        fixture=fixtures(out);bindings['fixtures']={str(p):sha(p)for p in list(out.glob('*.pce'))+[out/'data.bin',out/'data.cue']+list(fixture.iterdir())if p.is_file()};gear=build_gear(args,out,report,bindings,compiler);binary=build_tool(args,out,report,bindings,compiler,fixture)
        for case in cases():
            for cut in(0,1,2):
                stem=case['id']+'-cut'+str(cut);arguments=[case['id'],str(out/(case['id']+'.pce')),str(out/'data.cue'),str(cut)];done=common.evidence([str(gear),*arguments],stem+'-gear',out,report,bindings,120);original=json.loads(done.stdout);validate_report(original,case,cut,gear=True)
                for tier in('native','interpreter'):
                    checkpoint=out/(stem+'-'+tier+'.pcec');pair=[]
                    for mode in('write','resume'):
                        label=stem+'-'+tier+'-'+mode;capture=out/(label+'-capture.json');done=common.evidence([str(binary),*arguments,mode,tier,str(checkpoint),str(capture)],label,out,report,bindings,120);actual=json.loads(done.stdout);requested_tier(actual,tier);validate_report(actual,case,cut,resume=mode=='resume');validate_capture(json.loads(capture.read_text()),actual,case,resume=mode=='resume');paths=[capture]
                        if mode=='write':
                            prefix=Path(str(capture)+'.prefix.json');validate_capture(json.loads(prefix.read_text()),actual,case,prefix=True);paths+=[prefix,checkpoint]
                        bindings['raw_outputs'].update({str(p):sha(p)for p in paths});report['rows'].append(dict(case=case,cut=cut,tier=tier,mode=mode,label=label));pair.append(actual)
                    keys={'case','cut_id','tier','cut','final','window_work','window_hits','journal','ram','vram','window_provider_witnesses','prefix_native','prefix_interpreted','window_native','window_interpreted','origin_frame','checkpoint_sha256','final_sha256','prefix_blocks','prefix_block_bytes'}
                    require(all(pair[0][k]==pair[1][k]for k in keys),'Fresh same-tier exact continuation differs')
        report.update(result='pass',recipes=len(cases()),cases=3*len(cases()))
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:ref.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    from scripts.vdc_adpcm_irq_qualify import qualify
    result=qualify(out/'result.json');(out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

def parser():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[]);return p

if __name__=='__main__':
    try:run(parser().parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
