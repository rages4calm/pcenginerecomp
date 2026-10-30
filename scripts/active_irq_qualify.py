"""Strict source/event/work admission for authored active-display IRQ probes.

This module never runs a guest. Original callback partitions and phase values
are retained, not shifted to obtain cross-engine agreement.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tests.active_irq_fixture import cases,program,fixtures,expected_vram,expected_wram,DATA,LIMIT
from pcerecomp.project import ABI,source_identity
from scripts import filtered_audio_reference as reference

COMMIT=reference.COMMIT
BUILDS={'gear-link','tool-configure','tool-build'}
GROUPS={'tools','authored_sources','reference_raw_sources','reference_compile_sources',
    'external_libraries','gear_objects','gear_compile_logs','gear_binary',
    'tool_build_inputs','tool_objects','tool_binary','fixtures','raw_outputs'}
PHASE_KEYS=set('hpos vpos hstate vstate hremaining raster sprite_count bg_start bg_end hsync sat_pending burst latched_cr latched_mwr cr mwr rcr divider carry'.split())
KERNEL_KEYS=set('p mask irr sample status dma read_pending write_pending carry delay read_buffer marr mawr bus divider burst latched_cr latched_mwr hpos vpos hstate vstate hremaining raster sprite_count bg_start bg_end hsync sat_pending cd_enabled cd_active signals half end length write_address read_address cr mwr rcr selected'.split())
OBSERVATION_COLUMNS='pc a x y sp p clock_divisor ticks irq_entries rti_steps irq_mask irq_requests cd_enable cd_active signals dma length write_address half end dma_counter write_pending irq2 vdc_status irq1 vram_dma_pending vram_read_pending vram_write_pending vram_read_buffer marr mawr sour desr lenr vram_bus transfer_delay wait_ticks vce_divider vdc_counter cpu_sample selected_ar last_vector'.split()
sha=lambda path:reference.sha(Path(path))

def require(value,message):
    if not value:raise ValueError(message)

def load(path):
    def unique(rows):
        result={}
        for key,value in rows:
            require(key not in result,'Duplicate evidence key');result[key]=value
        return result
    def number(value):raise ValueError('Evidence numeric tokens must be finite integers')
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique,parse_float=number,parse_constant=number)

def ints(values,length=None,maximum=2**64):
    require(type(values)is list and(length is None or len(values)==length)and
        all(type(v)is int and 0<=v<maximum for v in values),'Strict unsigned integer list required')

def digest(value):
    require(type(value)is str and len(value)==64 and all(c in'0123456789abcdef'for c in value),'SHA256 required')

def source_key(row):
    return row['pc'],tuple(row['mpr']),tuple(row['physical']),tuple(row.get('data',row.get('bytes',[])))

def authored(case):
    _,markers,plan=program(case)
    return markers,{source_key(row)for row in plan}

def saved_a(case):return 0xa6 if case['access']=='high'else 2
def saved_p(case):return 129 if case['access']=='high'else 1
def selected_status(case):return 4 if case['source']=='raster'else 1
def expected_ram():
    return [((n*17+(n>>8)*7+0x53)&255)if n<2048 else 0 for n in ((i-65534)&65535 for i in range(65536))]
def vram_hash(words):return hashlib.sha256(b''.join(v.to_bytes(2,'little')for v in words)).hexdigest()

def stack_literal(case,cut=None,second=False):
    result=[0]*256
    if cut==0:result[253:]=[0,2 if case['source']=='raster'else 0x60,0]
    else:
        ret=program(case)[1]['return_pc']+int(second)
        result[253:]=[saved_p(case),ret&255,ret>>8]
        if cut!=1:result[252]=saved_a(case)
    return result

def validate_phase(value,kernel=False):
    require(type(value)is dict and set(value)==(KERNEL_KEYS if kernel else PHASE_KEYS),'Exact active phase/kernel fields required')
    signed={'hpos','vpos','hstate','vstate','hremaining','raster','sprite_count','bg_start','bg_end','hsync','delay','sample'}
    boolean={'burst','read_pending','write_pending','half','end'}
    words={'read_buffer','marr','mawr','bus','latched_cr','latched_mwr','sat_pending','write_address','read_address','cr','mwr','rcr'}
    bytes_={'p','mask','irr','status','cd_enabled','cd_active','signals','selected'}
    for key,v in value.items():
        require(type(v)is int,'Strict actual phase integer fields required')
        if key in boolean:require(v in(0,1),'Actual kernel boolean field must be zero or one')
        elif key in words:require(0<=v<65536,'Actual kernel register/address word out of range')
        elif key in bytes_:require(0<=v<256,'Actual kernel byte field out of range')
        elif key in signed:require(-(2**31)<=v<2**31,'Actual signed phase field out of range')
        else:require(0<=v<2**32,'Actual unsigned phase field out of range')
    if kernel:require(value['mask']<8 and value['irr']<8 and 0<=value['sample']<8 and value['length']<=65536,'Actual kernel IRQ/sample/length range differs')
    require(0<=value['hpos']<1365 and value['divider']in(2,3,4)and value['burst']in(0,1),'Actual phase range differs')
    require(value['hstate']in(0,1,2,3)and value['vstate']in(0,1,2,3)and 0<=value['sprite_count']<=16,'Actual phase state/sprite domain differs')
    return value

def validate_observation(row):
    require(type(row)is dict and set(row)=={'values','stack','wram_sha256','vram_sha256','active'},'Exact observation fields required')
    ints(row['values'],42);ints(row['stack'],256,256)
    values=row['values']
    require(values[0]<65536 and all(v<256 for v in values[1:6])and values[6]in(3,12),'Actual CPU field range differs')
    require(values[10]<8 and values[11]<8 and all(values[i]<256 for i in(12,13,14,15,23)),'Actual IRQ/CD byte field range differs')
    require(all(values[i]in(0,1)for i in(18,19,21,22,24,26,27))and values[16]<=65536 and values[17]<65536 and values[25]<=65536,'Actual device boolean/length/address field range differs')
    require(all(values[i]<65536 for i in range(28,35))and values[35]<2**32 and values[37]in(2,3,4)and values[39]<8 and values[40]<32 and values[41]<65536,'Actual VDC/sample/vector field range differs')
    digest(row['wram_sha256']);digest(row['vram_sha256']);validate_phase(row['active'])
    require(row['active']['divider']==row['values'][37],'Observation VCE phase/CPU row differs')
    return row['values']

def validate_prefetch(values,initial=False):
    """Source-designed DEAD -> A65C -> 5AA5 read sequence, without clock fit."""
    if initial:
        require(values[26:30]==[1,0,expected_vram()[DATA],DATA+1],'Initial completed/pending prefetch identity differs')
    else:
        require(values[26]in(0,1)and values[27]==0,'Post-target prefetch queue identity differs')
        wanted=[expected_vram()[DATA+1],DATA+2]if values[26]else[expected_vram()[DATA+2],DATA+3]
        require(values[28:30]==wanted,'Post-target pending/completed prefetch bytes or address differ')

def validate_target_scope(before,active):
    """Selected HDW/VDW fetch scope, not a forced assignment to either core."""
    ints(before,14);validate_phase(active,kernel='p'in active)
    require(not before[4]&4 and before[8]==1 and before[11]==1 and
        active['hstate']==1 and active['vstate']==1 and active['sprite_count']==2 and
        active['burst']==0 and active['latched_cr']&128 and active['latched_mwr']==3 and
        active['sat_pending']==0 and active['bg_start']<=active['hpos']<active['bg_end'],
        'Target must enter actual HDW/VDW two-sprite BG arbitration with IRQ1 and queued read pending')

def validate_first_causes(prefix_masks,window_masks,cut,resume=False):
    """First IRQ1 is imported at cut0; only its new ADPCM edges may follow."""
    ints(prefix_masks,maximum=8);ints(window_masks,maximum=8)
    expected_prefix={1:int(not resume and cut>0),2:int(not resume and cut>0),4:int(not resume)}
    expected_window={1:int(cut==0),2:int(cut==0),4:0}
    for masks,expected in((prefix_masks,expected_prefix),(window_masks,expected_window)):
        actual={bit:sum(bool(mask&bit)for mask in masks)for bit in(1,2,4)}
        require(actual==expected,'Unique first source causes assigned to wrong creating/imported/window phase')

def validate_hits(rows,case):
    require(type(rows)is list,'Actual source hit list required');_,plan=authored(case);result={}
    for row in rows:
        require(type(row)is dict and set(row)=={'pc','mpr','physical','data','hits'},'Exact source hit fields required')
        require(type(row['pc'])is int and 0<=row['pc']<65536 and type(row['hits'])is int and 0<row['hits']<=LIMIT,'Actual source/count type differs')
        ints(row['mpr'],8,256);ints(row['data'],maximum=256);ints(row['physical'],len(row['data']),2**21)
        key=source_key(row);require(key in plan and key not in result,'Actual PC/all-MPR/physical/bytes differ from authored source');result[key]=row['hits']
    return result

def validate_work(work,hits,ticks,gear):
    fields=set('instructions calls clock_calls clock_ticks irqs rtis blocks block_bytes adpcm_cause_groups vdc_cause_groups wait_ticks'.split())
    require(type(work)is dict and set(work)==fields and all(type(v)is int and 0<=v<2**64 for v in work.values()),'Exact typed actual work required')
    n=sum(hits.values());blocks=byte_count=extra=0
    for key,count in hits.items():
        raw=key[3]
        if raw[0]in(0x73,0xf3):
            length=raw[5]|raw[6]<<8;require(length>0,'Authored nonzero transfer length required')
            blocks+=count;byte_count+=count*length;extra+=count*(length+1)
    require(work['instructions']==n<=LIMIT and work['blocks']==blocks and work['block_bytes']==byte_count,'Actual retired block/byte work differs')
    require(work['calls']==n+(extra if gear else 0)and work['clock_ticks']==ticks,'Original continuation calls are not retired opcodes')
    require(work['clock_calls']>=work['calls']if gear else work['clock_calls']==0,'Actual hardware callback extent differs')

def validate_clock_group(row,case,markers):
    """Join original calls, callbacks and selected read-only source kernels."""
    spans,calls,events,edges=(row[key]for key in('clocks','call_rows','callbacks','edges'))
    require(all(type(value)is list for value in(spans,calls,events,edges))and 0<len(spans)<=1000000 and len(events)<=8192,'Bounded actual original ledger required')
    raw=row['bytes'];ints(raw,maximum=256);ints(row['before'],14);ints(row['after']['values'],42)
    require(1<=len(raw)<=7,'Original decoded instruction extent differs')
    block=raw[0]in(0x73,0xf3);length=raw[5]|raw[6]<<8 if block else 0
    require(len(calls)==(length+2 if block else 1),'Original N+2 call count differs from operands')
    previous=None;total=waits=0
    for span in spans:
        ints(span,10);start,n,end,waiting,sample,irr,hpos,vpos,vstate,hstate=span
        require(n>0 and end==start+n and(previous is None or start==previous)and waiting in(0,1)and sample<8 and irr<8 and hpos<1365,'Original callback continuity/type differs')
        require(not waiting or n==3,'Original dynamic wait is not an actual three-tick callback')
        previous=end;total+=n;waits+=n*waiting
    require(total==row['ticks']and previous==row['after']['values'][7]and waits==row['wait_ticks'],'Original callback endpoint/wait sums differ')
    returned=internal=span_end=0
    for index,call in enumerate(calls,1):
        ints(call,10);number,ticks,inside,complete,first,inside_end,last,extra,irq,causes=call
        require(number==index and complete==int(index==len(calls))and inside<=ticks and first==span_end and first<=inside_end<=last<=len(spans)and irq in(0,1)and causes<=7,'Original actual call partition differs')
        require(sum(s[1]for s in spans[first:inside_end])==inside and sum(s[1]for s in spans[first:last])==ticks and sum(s[1]for s in spans[first:inside_end]if s[3])==extra and not any(s[3]for s in spans[inside_end:last]),'Original per-call internal/remaining/wait clocks differ')
        if block:
            fixed=14 if index==1 else 3 if index==len(calls)else(8 if raw[0]==0xf3 else 6)
            require(ticks==(fixed+8*irq)*case['divisor']+extra,'Independent original transfer fixed/IRQ clocks differ')
        require(not irq or index==len(calls),'Original IRQ delivered inside an incomplete block')
        returned+=ticks;internal+=inside;span_end=last
    require(returned==row['ticks']and internal==row['internal']and span_end==len(spans),'Original group/call clock totals differ')
    for event in events:
        ints(event);require(len(event)>=3 and(event[2],len(event))in((1,6),(2,12),(5,7),(7,9))and 1<=event[0]<=len(calls),'Original callback type/call differs')
        call=calls[event[0]-1];require(spans[call[4]][0]<=event[1]<=spans[call[6]-1][2],'Original event timestamp outside its actual call')
    irq_events=[event for event in events if event[2]==1]
    require(len(irq_events)==int(bool(row['vector'])),'Original IRQ callback missing or duplicated')
    for event in irq_events:
        require(event[0]==len(calls)and event[3]==row['vector']and event[4]==markers['return_pc']+int(event[3]==0xfff6)and event[5]==4,'Original actual IRQ callback/vector/return differs')
    selected_event=2 if case['source']=='raster'else 4
    causes=[(e,1 if e[3]==7 else 2)for e in events if e[2]==7 and e[3]in(7,8)and e[7]==1]
    if row['causes']&4:causes += [(e,4)for e in events if e[2]==2 and e[3]==selected_event][:1]
    flags=0
    for index,call in enumerate(calls,1):
        bits=0
        for event,bit in causes:
            if event[0]==index and not flags&bit:bits|=bit;flags|=bit
        require(call[9]==bits and call[8]==sum(e[0]==index for e in irq_events),'Original callback causes/IRQ do not join calls')
    require(flags==row['causes'],'Original first source callback mask differs')
    previous_index=-1;edge_by_index={};prior_sample=row['active_before']['sample']
    for edge in edges:
        require(type(edge)is dict and set(edge)=={'span','kinds','before','after'},'Exact selected edge fields required')
        ints([edge['span'],edge['kinds']]);index=edge['span'];pre=validate_phase(edge['before'],True);post=validate_phase(edge['after'],True)
        require(previous_index<index<len(spans),'Original selected edge ordering differs')
        prior_sample=spans[index-1][4]if index else row['active_before']['sample']
        kinds=int(pre['irr']!=post['irr'])|2*int((pre['read_pending'],pre['write_pending'])!=(post['read_pending'],post['write_pending']))|4*int(pre['status']!=post['status'])|8*int((pre['half'],pre['end'])!=(post['half'],post['end']))|16*int(prior_sample!=pre['sample'])|32*int((pre['hstate'],pre['vstate'],pre['raster'])!=(post['hstate'],post['vstate'],post['raster']))|64*int((pre['cd_active'],pre['signals'])!=(post['cd_active'],post['signals']))
        require(edge['kinds']==kinds and 0<kinds<128,'Original selected edge kind differs from actual kernels')
        span=spans[index];require(pre['sample']==span[4]and post['irr']==span[5]and [pre[k]for k in('hpos','vpos','vstate','hstate')]==span[6:10],'Original selected kernel/callback phase differs')
        previous_index=index;edge_by_index[index]=edge
    for index,span in enumerate(spans):
        if span[4]!=(spans[index-1][4]if index else row['active_before']['sample']):
            require(index in edge_by_index,'Original CPU sample transition omitted')
    for event,bit in causes:
        if bit not in(1,2):continue
        indices=[i for i,span in enumerate(spans)if span[0]<event[1]<=span[2]]
        require(len(indices)==1 and indices[0]in edge_by_index,'Original source callback lacks unique actual selected kernel')
        edge=edge_by_index[indices[0]];key='half'if bit==1 else'end'
        require(not edge['before'][key]and edge['after'][key]and edge['before']['read_pending']==1 and edge['before']['irr']&2 and edge['after']['irr']&3==3,'Original first ADPCM assertion lacks pending active IRQ1/queued-read kernel')
    if row['pc']==markers['target']:
        require(row['vector']==0xfff8 and row['ticks']==(41 if block else 14)*case['divisor']+row['wait_ticks'],'Independent target fixed/wait/IRQ total differs')
        grants=[edge for edge in edges if edge['before']['read_pending']and not edge['after']['read_pending']and spans[edge['span']][3]]
        require(bool(grants),'Actual first dynamic queued-read grant missing');grant=grants[0]
        require(grant['before']['irr']&3==3 and grant['before']['sample']&3==3 and grant['before']['half']==grant['before']['end']==1,'Competing IRQ sources not sampled before first dynamic grant')
        for event,bit in causes:
            if bit not in(1,2):continue
            indices=[i for i,s in enumerate(spans)if s[0]<event[1]<=s[2]]
            require(len(indices)==1,'Original source callback has no unique actual clock span')
            index=indices[0];require(index<=grant['span']and index in edge_by_index,'Original source assertion lacks pre-grant kernel')
            edge=edge_by_index[index];key='half'if bit==1 else'end'
            require(not edge['before'][key]and edge['after'][key]and edge['before']['read_pending']and not edge['before']['p']&4,'Original ADPCM source assertion is not inside I-clear queued target work')
    return dict(dynamic_grants=sum(bool(edge['before']['read_pending']and not edge['after']['read_pending']and spans[edge['span']][3])for edge in edges),hardware_callbacks=len(spans))

def validate_capture(capture,actual,case,prefix=False,resume=False):
    from pcerecomp.capture import validate_capture as validate
    validate(capture)
    fields={'schema','runtime_abi','capacity','dropped_instructions','unreadable_instructions','retired_instructions','complete','observations'}|({'checkpoint_origin'}if resume else set())
    require(set(capture)==fields and capture['runtime_abi']==ABI and type(capture['runtime_abi'])is int and capture['complete']is True and capture['capacity']==4096 and not capture['dropped_instructions']and not capture['unreadable_instructions'],'Complete exact-ABI lossless capture required')
    wanted=validate_hits(actual['prefix_hits'if prefix else'window_hits'],case);native=actual['tier']=='native';got={}
    for row in capture['observations']:
        key=source_key(row);require(key not in got and row['native_hits']==(wanted.get(key)if native else 0)and row['interpreted_hits']==(0 if native else wanted.get(key)),'Actual capture source/tier hits differ');got[key]=row['native_hits']+row['interpreted_hits']
    require(got==wanted and capture['retired_instructions']==sum(wanted.values()),'Actual capture phase retirements differ')
    if resume:
        require(capture['checkpoint_origin']==dict(sha256=actual['checkpoint_sha256'],ticks=actual['cut']['values'][7],frame=actual['origin_frame'],native_steps=actual['prefix_native'],interpreter_steps=actual['prefix_interpreted']),'Actual imported capture origin differs')

def validate_report(actual,case,cut,gear=False,resume=False):
    common=set('dma_counter_role vdc_counter_role case cut_id tier cut final prefix_work window_work prefix_hits window_hits prefix_journal journal ram vram'.split())
    scalars=set('runtime_abi prefix_native prefix_interpreted window_native window_interpreted guard_misses provider_prefix provider_suffix prefix_blocks prefix_block_bytes origin_frame'.split())
    tool=scalars|{'mode','checkpoint_sha256','final_sha256','prefix_provider_witnesses','window_provider_witnesses'}
    require(type(actual)is dict and set(actual)==common|(set()if gear else tool),'Exact actual execution report required')
    require(actual['case']==case['id']and type(actual['cut_id'])is int and actual['cut_id']==cut and cut in(0,1,2)and actual['tier']in(('gear',)if gear else('native','interpreter')),'Actual recipe/cut/tier differs')
    require(actual['dma_counter_role']==('committed-writes'if gear else'captured-bytes')and actual['vdc_counter_role']==('source-progress'if gear else'completed-words'),'Distinct actual counter roles required')
    markers,plan=authored(case);initial=validate_observation(actual['cut']);final=validate_observation(actual['final']);retain=case['policy']=='retain';total=2 if retain else 1
    require(initial[0]==(markers['pre_dma'],markers['handler1'],markers['post_ack'])[cut]and initial[6]==final[6]==case['divisor']and initial[37]==final[37]==case['vce'],'Natural source cut/speed/VCE differs')
    memory=bytearray(8192);stack=stack_literal(case,cut=cut)
    if cut==0:
        require(initial[:7]==[markers['pre_dma'],2,0,0,255,5,case['divisor']]and initial[8:13]==[0,0,4,2,12]and initial[15:23]==[0,0,65534,0,0,0,0,0]and initial[24:28]==[1,0,1,0]and initial[36]==0,'Independent I-set source-absent pre-DMA cut differs')
    else:
        require(initial[8:11]==[1,0,4]and initial[15]==2 and 0<initial[16]<2048 and initial[17]==(65534+initial[16])&65535 and initial[18:20]==[1,1]and initial[25]==0 and initial[41]==0xfff8,'Independent delivered IRQ cut device state differs')
        if cut==1:
            require(initial[:7]==[markers['handler1'],saved_a(case),0,0,252,saved_p(case)|4,case['divisor']]and initial[11]==3 and initial[22]==initial[24]==1,'Both pending sources must enter IRQ1 first')
        else:
            require(initial[:7]==[markers['post_ack'],12 if retain else 0,0,0,251,5 if retain else 7,case['divisor']]and initial[11]==int(retain)and initial[12]==(12 if retain else 0)and initial[22]==int(retain)and initial[24]==0,'Independent VDC ACK / CD masking cut differs')
            memory[17]=1;memory[20]=selected_status(case);memory[22]=12
        if case['access']=='tai':memory[512:514]=bytes([0x5c,0xa6])
    memory[256:512]=bytes(stack)
    require(actual['cut']['stack']==stack and actual['cut']['wram_sha256']==hashlib.sha256(memory).hexdigest()and actual['cut']['vram_sha256']==vram_hash(expected_vram()),'Independent full cut WRAM/stack/VRAM differs')
    validate_prefetch(initial,initial=cut==0)
    require(final[:7]==[markers['done'],0,0,0,255,7,case['divisor']]and final[8:13]==[total,total,7,0,0]and final[14:23]==[0,0,2048,2046,1,1,2048,0,0]and final[24:28]==[0,0,0,0]and final[29]==final[30]==DATA+3 and final[31:34]==[0,0,0]and final[38]==0 and final[41]==(0xfff6 if retain else 0xfff8),'Independent completed CPU/IRQ/DMA endpoint differs')
    require(final[28]==expected_vram()[DATA+2]and final[35]==0 and final[39:41]==[0,5]and actual['final']['active']['carry']==0,'Independent final queued VRAM tail/delay/selector/sample differs')
    require(actual['final']['stack']==stack_literal(case,second=retain)and actual['final']['wram_sha256']==hashlib.sha256(bytes(expected_wram(case))).hexdigest()and actual['final']['vram_sha256']==vram_hash(expected_vram()),'Independent full endpoint WRAM/stack/VRAM differs')
    require(actual['final']['active']['cr']==192 and actual['final']['active']['mwr']==3,'Final source masks/profile differ')
    ints(actual['ram'],65536,256);ints(actual['vram'],32768,65536)
    require(actual['ram']==expected_ram()and actual['vram']==expected_vram(),'Independent complete ADPCM RAM/VRAM differs')
    prefix=validate_hits(actual['prefix_hits'],case);window=validate_hits(actual['window_hits'],case)
    validate_work(actual['prefix_work'],prefix,0 if resume else initial[7],gear)
    validate_work(actual['window_work'],window,final[7]-initial[7],gear)
    require(actual['prefix_work']['irqs']==(0 if resume else initial[8])and actual['prefix_work']['rtis']==0 and actual['window_work']['irqs']==final[8]-initial[8]and actual['window_work']['rtis']==total,'Imported/new IRQ/RTI work differs')
    require(actual['prefix_work']['wait_ticks']==(0 if resume else initial[36])and actual['window_work']['wait_ticks']==final[36]-initial[36],'Actual phase wait clocks differ')
    if not gear:
        require(actual['mode']==('resume'if resume else'write')and all(type(actual[k])is int and 0<=actual[k]<2**64 for k in scalars),'Strict actual toolkit work/mode required')
        require(actual['runtime_abi']==ABI and actual['guard_misses']==0 and actual['provider_prefix']==int(not resume)and actual['provider_suffix']==0,'ABI/fallback/provider restore purity differs')
        n=actual['prefix_native']+actual['prefix_interpreted'];is_native=actual['tier']=='native';w=actual['window_work']['instructions']
        require(n>0 and(resume or actual['prefix_work']['instructions']==n)and(actual['prefix_native'],actual['prefix_interpreted'])==((n,0)if is_native else(0,n))and(actual['window_native'],actual['window_interpreted'])==((w,0)if is_native else(0,w)),'Imported versus new actual execution tier differs')
        setup=[row for row in program(case)[2]if row['pc']<markers['pre_dma']and row['data'][0]==0x73]
        require(actual['prefix_blocks']==len(setup)+int(cut>0 and case['access']=='tai')and actual['prefix_block_bytes']==sum(row['data'][5]|row['data'][6]<<8 for row in setup)+2*int(cut>0 and case['access']=='tai'),'Independent imported block/byte totals differ')
        digest(actual['checkpoint_sha256']);digest(actual['final_sha256'])
        for key in('prefix_provider_witnesses','window_provider_witnesses'):
            witnesses=actual[key];require(type(witnesses)is list and len(witnesses)==int(key.startswith('prefix')and not resume),'Actual provider read phase differs')
            for row in witnesses:
                require(type(row)is dict and set(row)=={'pc','mpr','physical','bytes','values'},'Exact actual provider witness required');ints(row['values'],9)
                ints([row['pc']]);ints(row['mpr'],8,256);ints(row['bytes'],maximum=256);ints(row['physical'],len(row['bytes']),2**21)
                require(source_key(row)in plan and row['pc']<markers['pre_dma']and row['values'][0]<initial[7]and row['values'][1:4]==[0,0,0]and row['values'][4]&4 and row['values'][5:]==[0,0,0,0],'Real provider source must be pre-DMA/I-set setup, not invented target work')
    entries=[];rtis=[];targets=[];acks=[];all_causes=0;topology=[]
    for phase,key in(('prefix','prefix_journal'),('window','journal')):
        journal=actual[key];require(type(journal)is list and len(journal)<=256,'Selected journal extent differs')
        phase_hits=prefix if phase=='prefix'else window;counts=Counter()
        for row in journal:
            fields={'pc','mpr','physical','bytes','before','ticks','wait_ticks','vector','causes','after','active_before'}|({'internal','clocks','call_rows','callbacks','edges'}if gear else set())
            require(type(row)is dict and set(row)==fields,'Exact detailed instruction fields required')
            ints([row['pc'],row['ticks'],row['wait_ticks'],row['vector'],row['causes']]);ints(row['mpr'],8,256);ints(row['bytes'],maximum=256);ints(row['physical'],len(row['bytes']),2**21);ints(row['before'],14)
            source=source_key(row);require(source in plan and row['vector']in(0,0xfff8,0xfff6)and row['causes']<=7,'Detailed source/vector/cause differs')
            counts[source]+=1;require(counts[source]<=phase_hits.get(source,0),'Journal source does not join actual phase retirements')
            v=validate_observation(row['after']);before=row['before'];require(v[36]-before[13]==row['wait_ticks'],'Detailed actual cumulative waits differ')
            if gear:validate_phase(row['active_before'],True);validate_clock_group(row,case,markers)
            else:require(type(row['active_before'])is dict and(not row['active_before']or set(row['active_before'])==PHASE_KEYS),'Toolkit phase attaches only to target')
            all_causes|=row['causes']
            if row['pc']==markers['target']:
                targets.append(row);active=validate_phase(row['active_before'],gear)
                validate_prefetch(v)
                validate_target_scope(before,active)
                require(row['wait_ticks']>0 and row['vector']==0xfff8 and row['ticks']==(14 if case['access']=='high'else 41)*case['divisor']+row['wait_ticks'],'Independent target wait/fixed/IRQ total differs')
                topology.append(dict(irq1_pending_before=True,adpcm_pending_before=before[6:8]==[1,1],adpcm_asserts_in_target=bool(row['causes']&3)))
            if row['vector']:
                entries.append(row);first=row['vector']==0xfff8;ret=markers['return_pc']+int(not first)
                require(row['pc']==(markers['target']if first else markers['return_pc'])and(first or retain),'Actual priority/return source differs')
                require(v[:7]==[markers['handler1']if first else markers['handler2'],saved_a(case),0,0,252,saved_p(case)|4,case['divisor']]and v[8:10]==([1,0]if first else[2,1])and row['after']['stack'][253:]==[saved_p(case),ret&255,ret>>8],'Independent delivered CPU/descending IRQ frame differs')
                if first:require(v[11]==3 and v[18:20]==[1,1]and v[22]==v[24]==1,'IRQ1 did not retain competing IRQ2')
            if markers['handler1']<=row['pc']<markers['handler2']and row['bytes']==[0xad,0,0]:
                acks.append(row);require(before[8:10]==[1,1]and v[1]&63==selected_status(case)and v[24]==0 and v[22]==1 and v[11]==1,'VDC ACK cleared unrelated ADPCM IRQ source')
            if row['bytes']==[0x40]:
                rtis.append(row);ret=markers['return_pc']+int(v[9]==2)
                require(v[:7]==[ret,saved_a(case),0,0,255,saved_p(case),case['divisor']]and row['after']['stack'][252]==saved_a(case),'Independent RTI restoration differs')
        work=actual[phase+'_work']
        require(work['irqs']==sum(bool(row['vector'])for row in journal)and work['rtis']==sum(row['bytes']==[0x40]for row in journal)and work['adpcm_cause_groups']==sum(bool(row['causes']&3)for row in journal)and work['vdc_cause_groups']==sum(bool(row['causes']&4)for row in journal),'Actual event work assigned to wrong phase')
        require(work['wait_ticks']==sum(row['wait_ticks']for row in journal),'Actual wait group omitted from detailed journal')
    require(len(targets)==int(not resume or cut==0)and len(entries)==total-(initial[8]if resume else 0)and len(rtis)==total and len(acks)==int(not resume or cut<2),'Selected actual target/entry/RTI/ACK coverage differs')
    validate_first_causes([row['causes']for row in actual['prefix_journal']],
                          [row['causes']for row in actual['journal']],cut,resume)
    return dict(admitted_values=65536+8192+32768+42,topology=topology)

def raw_differences(gear,tool,case,cut):
    result=[]
    for phase in('cut','final'):
        for index,(a,b)in enumerate(zip(gear[phase]['values'],tool[phase]['values'])):
            if a!=b:result.append(dict(case=case['id'],cut=cut,phase=phase,field=OBSERVATION_COLUMNS[index],original=a,tool=b))
        for key,a in gear[phase]['active'].items():
            b=tool[phase]['active'][key]
            if a!=b:result.append(dict(case=case['id'],cut=cut,phase=phase+'.active',field=key,original=a,tool=b))
    for phase in('prefix_work','window_work'):
        for field,a in gear[phase].items():
            b=tool[phase][field]
            if a!=b:result.append(dict(case=case['id'],cut=cut,phase=phase,field=field,original=a,tool=b))
    return result

def qualify(path):
    # Import only here: the execution driver imports the report validators.
    from scripts import active_irq_reference as driver
    path=Path(path).resolve();out=path.parent;r=load(path)
    fields={'schema','result','oracle_commit','tool','tool_root','commands','bindings','rows','plan',
            'scope','not_checked','compilations','gear_git_blobs','preservation','processes'}
    require(type(r)is dict and set(r)==fields and type(r['schema'])is int and r['schema']==1 and r['result']=='pass'and r['oracle_commit']==COMMIT,'Exact successful reference receipt/schema required')
    selected,cuts,complete=validate_plan(r['plan'])
    require(type(r['scope'])is str and r['scope']==driver.__doc__ and type(r['not_checked'])is list and all(type(v)is str for v in r['not_checked'])and 'Hardware'in r['not_checked']and 'Retail'in r['not_checked'],'Explicit diagnostic/non-hardware scope required')
    b=r['bindings']
    require(type(b)is dict and set(b)==GROUPS and type(r['preservation'])is dict and set(r['preservation'])==GROUPS and all(v is True for v in r['preservation'].values()),'Complete preserved binding groups required')
    bound=0
    for group,table in b.items():
        require(type(table)is dict and bool(table),'Nonempty artifact binding group required')
        for name,value in table.items():
            require(type(name)is str and Path(name).is_absolute(),'Absolute bound artifact path required');digest(value)
            require(sha(name)==value,'Changed bound artifact: '+name);bound+=1
    tool=Path(r['tool_root'])
    require(r['tool']==source_identity(tool)and b['authored_sources']==driver.source_bindings(tool),'Exact toolkit identity/authored source set differs')
    roots={str(Path(name).resolve().parents[1])for name in b['reference_raw_sources']if name.replace('\\','/').endswith('/src/input.h')}
    require(len(roots)==1,'Original raw source checkout identity differs');raw_root=Path(next(iter(roots)))
    tree=subprocess.check_output(['git','-C',str(raw_root),'ls-tree','-r',COMMIT],text=True).splitlines()
    originals={line.split('\t',1)[1]:line.split()[2]for line in tree}
    prefixes=('src/','platforms/shared/dependencies/miniz/','platforms/shared/dependencies/minivorbis/',
              'platforms/shared/dependencies/qon/','platforms/shared/dependencies/json/','platforms/shared/dependencies/libchdr/include/')
    required={name:value for name,value in originals.items()if name.startswith(prefixes)and Path(name).suffix in('.c','.cpp','.h','.hpp')}
    require(r['gear_git_blobs']==required,'Complete original Git blob source set differs');pinned=out/'pinned-reference-source'
    for group,root in(('reference_raw_sources',raw_root),('reference_compile_sources',pinned)):
        require(set(b[group])=={str(root/name)for name in required},'Complete original raw/compile source binding set differs')
        for name,value in required.items():
            data=(root/name).read_bytes()
            if group=='reference_raw_sources':data=data.replace(b'\r\n',b'\n')
            actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            require(actual==value,'Original raw/compiled Git blob differs')
    fixture_names=[case['id']+'.pce'for case in cases()]+['data.bin','data.cue','fixture/module.cpp',
        'fixture/module.json','fixture/fixture.json','fixture/active_irq_fixture.hpp']
    require(set(b['fixtures'])=={str(out/name)for name in fixture_names},'Complete authored/generated fixture binding set differs')
    with tempfile.TemporaryDirectory(prefix='pce-active-irq-reemit-')as temporary:
        expected=Path(temporary);fixtures(expected)
        require(all((expected/name).read_bytes()==(out/name).read_bytes()for name in fixture_names),'Independently reauthored ROM/media/header/translation differs')
    rows=[dict(case=case,cut=cut,tier=tier,mode=mode,label=case['id']+'-cut'+str(cut)+'-'+tier+'-'+mode)
          for case in selected for cut in cuts for tier in('native','interpreter')for mode in('write','resume')]
    require(canonical(r['rows'])==canonical(rows),'Exact selected case/cut/tier/mode matrix differs')
    guest_labels=[case['id']+'-cut'+str(cut)+'-gear'for case in selected for cut in cuts]+[row['label']for row in rows]
    labels=list(BUILDS)+guest_labels
    processes=r['processes']
    require(type(processes)is list and all(type(v)is dict and set(v)=={'label','returncode'}and type(v['label'])is str and type(v['returncode'])is int for v in processes),'Strict actual process records required')
    require(sorted(processes,key=lambda v:v['label'])==sorted([dict(label=label,returncode=0)for label in labels],key=lambda v:v['label']),'Exact successful actual process set differs')
    require(type(r['commands'])is list and all(type(command)is list and command and all(type(v)is str for v in command)for command in r['commands']),'Typed actual command ledger required')
    raw_outputs={str(out/(label+'.'+suffix))for label in labels for suffix in('stdout','stderr')}
    for row in rows:
        raw_outputs.add(str(out/(row['label']+'-capture.json')))
        if row['mode']=='write':
            raw_outputs.add(str(out/(row['label']+'-capture.json.prefix.json')))
            raw_outputs.add(str(out/(row['case']['id']+'-cut'+str(row['cut'])+'-'+row['tier']+'.pcec')))
    require(set(b['raw_outputs'])==raw_outputs,'Complete raw output/capture/checkpoint binding set differs')
    for label in labels:
        require(label in BUILDS or (out/(label+'.stderr')).read_text()=='','Unexpected actual guest stderr: '+label)
    binary=str(out/'tool-build'/('active-irq.exe'if sys.platform=='win32'else'active-irq'))
    gear_binary=str(out/'gear-active-irq.exe')
    require(set(b['tool_binary'])=={binary}and set(b['gear_binary'])=={gear_binary},'Exact probe binary association differs')
    compiler=r['commands'][0][0];require(compiler in b['tools'],'Actual compiler binding missing')
    cpp,c=reference.compile_sources(pinned,{name:sha(pinned/name)for name in required});original_compile_count=len(cpp+c)
    cpp.append(ROOT/'tests/geargrafx_active_irq_probe.cpp');deps=pinned/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for folder in(pinned/'src',ROOT/'tests',out/'fixture',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):
        flags+=['-I',str(folder)]
    compile_commands=[];objects=[];expected_compilations=[]
    for index,source in enumerate(cpp+c):
        obj=out/'gear-objects'/(str(index)+'-'+source.stem+'.o');objects.append(obj)
        compile_commands.append([compiler,*flags,'-x','c++'if source.suffix=='.cpp'else'c',
            *(['-std=c++20','-include','cerrno']if source.suffix=='.cpp'else['-std=c11']),'-c',str(source),'-o',str(obj)])
        expected_compilations.append(dict(object=str(obj),log=str(obj.with_suffix('.log')),returncode=0))
    require(type(r['compilations'])is list and all(type(v)is dict and set(v)=={'object','log','returncode'}and type(v['object'])is str and type(v['log'])is str and type(v['returncode'])is int for v in r['compilations']),'Strict actual compilation records required')
    require(sorted(r['compilations'],key=lambda v:v['object'])==sorted(expected_compilations,key=lambda v:v['object']),'Complete original/dependency/authored-probe compilation set differs')
    require(set(b['gear_objects'])=={str(obj)for obj in objects}and set(b['gear_compile_logs'])=={str(obj.with_suffix('.log'))for obj in objects},'Exact compiled object/diagnostic bindings differ')
    link=[compiler,*map(str,objects),*b['external_libraries'],'-Wl,--gc-sections','-o',gear_binary]
    cmakes=[name for name in b['tools']if Path(name).stem.lower()=='cmake'];ninjas=[name for name in b['tools']if Path(name).stem.lower()=='ninja']
    require(len(cmakes)==len(ninjas)==1,'Exact CMake/Ninja tool association required');cmake,ninja=cmakes[0],ninjas[0]
    configure=[cmake,'-S',str(out/'wrapper'),'-B',str(out/'tool-build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
               '-DCMAKE_CXX_COMPILER='+compiler,'-DCMAKE_MAKE_PROGRAM='+ninja]
    build=[cmake,'--build',str(out/'tool-build'),'--target','active-irq','--parallel','4']
    require(r['commands'][:len(compile_commands)+3]==compile_commands+[link,configure,build],'Exact compile/link/configure/build command association differs')
    from scripts.mapper_reference import cmake_quote as quote
    config=out/'wrapper/CMakeLists.txt';fixture=out/'fixture'
    lines=['cmake_minimum_required(VERSION 3.20)','project(ActiveIrq LANGUAGES CXX)',
        *['set('+key+' OFF CACHE BOOL "" FORCE)'for key in('BUILD_TESTING','PCE_BUILD_TESTS','PCE_BUILD_TOOLS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE')],
        f'add_subdirectory({quote(tool)} tool)',
        f'pce_add_native_module(_module MODULE {quote(fixture/"module.cpp")} MANIFEST {quote(fixture/"module.json")})',
        f'add_executable(active-irq {quote(ROOT/"tests/active_irq_probe.cpp")})',
        f'target_include_directories(active-irq PRIVATE {quote(fixture)} {quote(ROOT/"tests")})',
        'target_link_libraries(active-irq PRIVATE ${_module} pce-runtime)']
    require(set(b['tools'])=={compiler,cmake,ninja}and set(b['tool_build_inputs'])=={str(config)}and config.read_text()=='\n'.join(lines)+'\n','Exact wrapper/tools/module/probe association differs')
    built={str(p)for p in(out/'tool-build').rglob('*')if p.is_file()and(p.suffix in('.o','.obj','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))}
    require(set(b['tool_objects'])==built,'Complete toolkit object/build metadata binding set differs')
    checks=joins=native=interpreted=original_calls=original_instructions=original_clocks=0
    differences=[];observed=set();phase_work=Counter();wanted_commands=[];topologies=[];final_hashes={}
    for case in selected:
        for cut in cuts:
            stem=case['id']+'-cut'+str(cut);arguments=[case['id'],str(out/(case['id']+'.pce')),str(out/'data.cue'),str(cut)]
            gear=load(out/(stem+'-gear.stdout'));admission=validate_report(gear,case,cut,gear=True)
            checks+=admission['admitted_values'];joins+=1;full_hits(gear['prefix_hits'],gear['window_hits'],case)
            topologies += [dict(case=case['id'],cut=cut,tier='gear',**value)for value in admission['topology']]
            original_calls+=gear['prefix_work']['calls']+gear['window_work']['calls']
            original_instructions+=gear['prefix_work']['instructions']+gear['window_work']['instructions']
            original_clocks+=gear['prefix_work']['clock_calls']+gear['window_work']['clock_calls']
            wanted_commands.append([gear_binary,*arguments])
            for phase in('prefix','window'):
                for field,value in gear[phase+'_work'].items():phase_work['gear_'+phase+'_'+field]+=value
            creating={}
            for tier in('native','interpreter'):
                pair=[];checkpoint=out/(stem+'-'+tier+'.pcec')
                for mode in('write','resume'):
                    label=stem+'-'+tier+'-'+mode;capture=out/(label+'-capture.json');actual=load(out/(label+'.stdout'))
                    require(actual['tier']==tier and actual['mode']==mode,'Requested process/actual tier or mode differs')
                    admission=validate_report(actual,case,cut,resume=mode=='resume');checks+=admission['admitted_values'];joins+=1
                    validate_capture(load(capture),actual,case,resume=mode=='resume')
                    require(actual['checkpoint_sha256']==sha(checkpoint),'Actual raw checkpoint file/hash association differs')
                    wanted_commands.append([binary,*arguments,mode,tier,str(checkpoint),str(capture)])
                    topologies += [dict(case=case['id'],cut=cut,tier=tier,mode=mode,**value)for value in admission['topology']]
                    if mode=='write':
                        validate_capture(load(str(capture)+'.prefix.json'),actual,case,prefix=True)
                        observed.update(full_hits(actual['prefix_hits'],actual['window_hits'],case))
                        phase_work[tier+'_creating_prefix']+=actual['prefix_work']['instructions']
                    count=actual['window_work']['instructions']+(actual['prefix_work']['instructions']if mode=='write'else 0)
                    if tier=='native':native+=count
                    else:interpreted+=count
                    phase_work[tier+('_creating_suffix'if mode=='write'else'_restored_suffix')]+=actual['window_work']['instructions']
                    phase_work[tier+'_blocks']+=actual['window_work']['blocks']+(actual['prefix_work']['blocks']if mode=='write'else 0)
                    phase_work[tier+'_block_bytes']+=actual['window_work']['block_bytes']+(actual['prefix_work']['block_bytes']if mode=='write'else 0)
                    pair.append(actual)
                keys={'dma_counter_role','vdc_counter_role','case','cut_id','tier','cut','final','window_work','window_hits','journal','ram','vram','window_provider_witnesses','prefix_native','prefix_interpreted','window_native','window_interpreted','origin_frame','checkpoint_sha256','final_sha256','prefix_blocks','prefix_block_bytes'}
                require(all(canonical(pair[0][key])==canonical(pair[1][key])for key in keys),'Fresh same-tier encoded-final/state/source/journal continuation differs')
                require(pair[1]['prefix_work']['instructions']==0 and not pair[1]['prefix_hits'],'Restoring process replayed imported setup')
                creating[tier]=pair[0];identity=(case['id'],tier)
                require(identity not in final_hashes or final_hashes[identity]==pair[0]['final_sha256'],'Same recipe/tier final encoded hash differs across natural cuts')
                final_hashes[identity]=pair[0]['final_sha256']
            a,other=creating['native'],creating['interpreter']
            keys=('cut','final','window_work','prefix_work','window_hits','prefix_hits','journal','prefix_journal','ram','vram','prefix_provider_witnesses','window_provider_witnesses')
            require(all(canonical(a[key])==canonical(other[key])for key in keys),'Internal native/separate interpreter actual state/source/work differs')
            differences+=raw_differences(gear,a,case,cut)
    require(r['commands']==compile_commands+[link,configure,build]+wanted_commands,'Complete actual build/guest command ledger differs')
    manifest=load(out/'fixture/module.json');plan=load(out/'fixture/fixture.json')
    require(plan['execution_evidence']is False and manifest['execution_evidence']is False and manifest['unsupported_observations']==0,'Emitted fixture source plan is not execution evidence')
    return dict(result='pass',recipes=len(selected),cuts=cuts,cases=len(selected)*len(cuts),complete_matrix=complete,
        actual_guest_processes=len(guest_labels),fresh_restores=2*len(selected)*len(cuts),
        native_steps=native,interpreter_steps=interpreted,gear_guest_cpu_calls=original_calls,
        gear_retired_instructions=original_instructions,gear_extra_continuation_calls=original_calls-original_instructions,
        gear_hardware_callbacks=original_clocks,admitted_values=checks,semantic_reports=joins,
        independent_adpcm_ram_values=65536*joins,independent_wram_values=8192*joins,independent_vram_words=32768*joins,
        phase_work=dict(phase_work),artifact_bindings=bound,original_git_blobs=len(required),
        compilation_joins=len(expected_compilations),original_dependency_compilations=original_compile_count,
        authored_reference_probe_compilations=1,compiled_sources=manifest['native_instructions_emitted'],
        actual_native_sources=len(observed),raw_difference_cases=len({(row['case'],row['cut'])for row in differences}),
        raw_differences=differences,topologies=topologies,tool=r['tool'],
        scope='Authored active-display IRQ priority, source acknowledgement and exact-build natural-boundary continuation; original phases remain raw, not hardware qualification')

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def validate_plan(plan):
    require(type(plan)is dict and set(plan)=={'cases','cuts','complete_matrix'},'Exact explicit execution plan required')
    known=cases();by_id={case['id']:case for case in known};names=plan['cases'];cuts=plan['cuts']
    require(type(names)is list and names and all(type(name)is str and name in by_id for name in names)and len(names)==len(set(names)),'Unique known selected recipes required')
    require(names==[case['id']for case in known if case['id']in names],'Selected recipes must preserve authored matrix order')
    require(type(cuts)is list and cuts and all(type(cut)is int and cut in(0,1,2)for cut in cuts)and cuts==sorted(set(cuts)),'Unique sorted natural cut IDs required')
    complete=len(names)==len(known)and cuts==[0,1,2]
    require(type(plan['complete_matrix'])is bool and plan['complete_matrix']==complete,'Partial/full matrix extent must be truthful')
    return [by_id[name]for name in names],cuts,complete

def full_hits(prefix,window,case):
    combined=Counter(validate_hits(prefix,case));combined.update(validate_hits(window,case));markers,_=authored(case)
    for row in program(case)[2]:
        count=combined.get(source_key(row),0);pc=row['pc']
        if pc==markers['done']:require(count==0,'Compiled terminal BRA falsely promoted to execution')
        elif pc>=markers['handler2']:require(count==int(case['policy']=='retain'),'Masked/retained IRQ2 handler source extent differs')
        elif pc>=markers['handler1']:require(count==1,'IRQ1 handler source extent differs')
        elif row['data'][0]in(0xad,0x29,0xc9,0xd0):require(count>0,'Required actual polling source missing')
        else:require(count==1,'Required one-shot authored setup/control source differs')
    for op,port,count in((0x8d,0x1801,6),(0xad,0x1801,2),(0x8d,0x180b,2)):
        require(sum(n for(_,_,_,raw),n in combined.items()if list(raw)==[op,port&255,port>>8])==count,'Autonomous READ/DMA protocol source extent differs')
    return combined

def negative_controls(path):
    value=load(path);out=Path(path).resolve().parent
    changes=[('result',lambda r:r.update(result='incomplete')),
        ('row-missing',lambda r:r['rows'].pop()),('case-missing',lambda r:r['plan']['cases'].pop()),
        ('claim-full',lambda r:r['plan'].update(complete_matrix=not r['plan']['complete_matrix'])),
        ('process-missing',lambda r:r['processes'].pop()),('process-bool',lambda r:r['processes'][0].update(returncode=False)),
        ('binding-missing',lambda r:r['bindings']['raw_outputs'].pop(next(iter(r['bindings']['raw_outputs'])))),
        ('source-missing',lambda r:r['bindings']['reference_raw_sources'].pop(next(iter(r['bindings']['reference_raw_sources'])))),
        ('build-command-missing',lambda r:r['commands'].pop(len(r['compilations'])+2)),
        ('compile-object-missing',lambda r:r['compilations'].pop()),
        ('oracle-blob',lambda r:r['gear_git_blobs'].update({next(iter(r['gear_git_blobs'])):'0'*40}))]
    refused=[]
    for name,mutate in changes:
        altered=copy.deepcopy(value);mutate(altered);target=out/('negative-'+name+'.json')
        require(not target.exists(),'New written negative receipt required');target.write_text(json.dumps(altered)+'\n',encoding='utf-8')
        try:qualify(target)
        except(ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError):refused.append(name)
        else:raise ValueError('Altered receipt admitted: '+name)
    return refused

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('result',type=Path);parser.add_argument('--negative-controls',action='store_true');args=parser.parse_args()
    try:
        result=qualify(args.result)
        if args.negative_controls:result['negative_controls_refused']=negative_controls(args.result)
        print(json.dumps(result,indent=2))
    except(ValueError,RuntimeError,OSError,KeyError,TypeError,subprocess.SubprocessError)as error:
        print(error,file=sys.stderr);raise SystemExit(1)
