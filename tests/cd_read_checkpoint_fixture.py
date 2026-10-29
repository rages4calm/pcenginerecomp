"""Independent authored media, bounded cuts and exact port-op hit counts."""
from collections import Counter
from pathlib import Path

MPR = (255,248,128,129,131,132,2,0)
SITES = [(0x2800+i*8,op,address) for i,(op,address) in enumerate(
    [(0x8d,a) for a in (0x1800,0x1801,0x1802,0x1804)]+[(0xad,a) for a in (0x1801,0x1808)])]
CUTS = ('partial-cdb','pending-first-load','mid-data-req','ack-edge','last-byte-next-buffer',
        'occupied-buffer-retry','reset-held','reselection-abort')

def cases():
    return [dict(id=f'{name}-ack{ack}-div{div}',cut=cut,automatic=ack,divisor=div)
            for div in (3,12) for ack in (0,1) for cut,name in enumerate(CUTS)]

def pattern(lba):
    return [(lba*29+i*17+(i>>8)*7+0x53)&255 for i in range(2048)]

def source_memory():
    return {0x1f0000+(pc&8191)+i:value for pc,op,address in SITES
            for i,value in enumerate((op,address&255,address>>8,0x80,0xfe))}

def authored_rom():
    image=bytearray([0xea]*262144);image[8190:8192]=b'\x00\xe0';return bytes(image)

def header():
    memory=source_memory()
    lines=['#pragma once','#include <array>','#include <cstdint>','#include <utility>',
        'inline constexpr std::array<std::uint8_t,8> checkpoint_mpr{'+','.join(map(str,MPR))+'};',
        'struct CheckpointSite {unsigned pc,op,address;};',
        f'inline constexpr std::array<CheckpointSite,{len(SITES)}> checkpoint_sites{{{{']
    lines+=['{'+','.join(map(str,row))+'},' for row in SITES]+['}};',
        f'inline constexpr std::array<std::pair<unsigned,std::uint8_t>,{len(memory)}> checkpoint_program{{{{']
    lines+=['{'+str(a)+','+str(v)+'},' for a,v in sorted(memory.items())]+['}};','']
    return '\n'.join(lines)

def expected_cut(case):
    cut,auto,div=case['cut'],case['automatic'],case['divisor'];slow_auto=auto and div==12
    rows=[[3,0x90,0,0,0,0,0,0],[4,0x88,0,0,0,0,2,1],
        [4,0xc8,0,2048,18,1,1,1],[4,0xc8 if slow_auto else 0x8a,0 if slow_auto else 1,2048,19 if slow_auto else 18,1,1,1],
        [4,0xc8,0,2048,0,2,0,1],[4,0xc8,0,2048,1,1,1,1],
        [0,0x100,0,0,0,0,0,0],[7,0xd8,0,8,0,1,1,0]]
    return rows[cut]

def expected_timing(case):
    cut,auto,div=case['cut'],case['automatic'],case['divisor']
    q=5*div+22 if auto else 15*div+2
    overrun=(-(3507953-(5*div+1)))%1000
    remaining=286363-overrun
    # event, residual event/auto/load, retained head/IRQ/CDB/data, retry/loads.
    rows=[[2,3000-(5*div+1),0,0,0,0,3,0,0,0],
          [0,0,0,3507953-(5*div+1),0,0,0,0,0,0],
          [0,0,0,remaining-17*q,1,64,0,pattern(0)[17],0,1],
          [0,0,max(0,21-(5*div+1)) if auto else 0,remaining-17*q-(5*div+1 if auto else 10*div+1),1,
              64 if auto and div==12 else 0,0,pattern(0)[18 if auto and div==12 else 17],0,1],
          [0,0,0,0,2,64,0,pattern(0)[2047],int(2047*q>remaining),2],
          [0,0,0,6228408-(300000+overrun-286363),1,64,0,pattern(0)[0],1,1],
          [0,0,0,0,0,0,0,0,0,1],
          [1,900000-5*div,0,remaining-17*q-5*div,1,96,0,0,0,1]]
    return rows[cut]

def validate_cut(actual,case):
    for key,wanted in (('cut',expected_cut(case)),('timing',expected_timing(case))):
        values=actual.get(key)
        if type(values) is not list or any(type(v) is not int or v<0 for v in values) or values!=wanted:
            raise ValueError(f'Literal {key} differs for {case["id"]}: {values}, expected {wanted}')
    cut,auto=case['cut'],case['automatic']
    pc=(0x281b if cut==6 else (0x2803 if cut==7 else (0x282b if auto and cut in (2,3,4) else 0x2813)))
    memory=source_memory();wanted=[pc,*MPR]
    for i in range(7):
        physical=(MPR[((pc+i)&65535)>>13]<<13)|((pc+i)&8191);wanted.extend((physical,memory.get(physical,0)))
    if actual.get('cut_source')!=wanted or any(type(v) is not int for v in actual['cut_source']):raise ValueError('Literal full cut-source identity differs')
    return len(expected_cut(case))+len(expected_timing(case))+len(wanted)

def validate_gear_cut(actual,case):
    cut=expected_cut(case);wanted=[cut[0],cut[1],cut[2],cut[5],cut[6],expected_timing(case)[4]]
    if actual.get('cut')!=wanted or any(type(v) is not int for v in actual['cut']):raise ValueError('Original Gear literal live cut differs')
    return len(wanted)

def expected(case):
    cut=case['cut']; count=2047 if cut==4 else (18 if cut==3 else (17 if cut in (2,6,7) else 0))
    whole=pattern(0)+pattern(1)
    return dict(prefix=whole[:count],reply=dict(data=pattern(1) if cut>=6 else whole[count:],status=[0],message=[0]))

def hits(case, prefix=False):
    cut,auto=case['cut'],case['automatic']; result=Counter()
    def add(op,address,count=1):
        pc=next(pc for pc,o,a in SITES if (o,a)==(op,address));result[pc]+=count
    def send(count): add(0x8d,0x1801,count);add(0x8d,0x1802,count*2)
    def data(count):
        if count:add(0xad,0x1808 if auto else 0x1801,count)
        if not auto:add(0x8d,0x1802,count*2)
    if prefix:
        add(0x8d,0x1800);send(3 if cut==0 else 6)
        count=2047 if cut==4 else (17 if cut in (2,3,6,7) else 0);data(count)
        if cut==3:
            add(0xad,0x1808 if auto else 0x1801)
            if not auto:add(0x8d,0x1802)
        if cut==6:add(0x8d,0x1804)
        if cut==7:add(0x8d,0x1800)
    else:
        if cut==0:send(3)
        if cut==3 and not auto:add(0x8d,0x1802)
        if cut==6:add(0x8d,0x1804);add(0x8d,0x1800);send(6)
        if cut==7:send(6)
        data(len(expected(case)['reply']['data']));add(0xad,0x1801,2);add(0x8d,0x1802,4)
    return +result

def fixtures(out):
    from pcerecomp.analysis import Snapshot,analyze
    from pcerecomp.emitter import emit
    out=Path(out);module=out/'fixture';module.mkdir()
    memory=source_memory()
    snapshot=Snapshot(MPR,memory,tuple(pc for pc,_,_ in SITES),'authored-cd-read-checkpoint-v1')
    emit(analyze(snapshot),module)
    (module/'cd_read_checkpoint_fixture.hpp').write_text(header())
    (out/'authored.pce').write_bytes(authored_rom())
    (out/'data.bin').write_bytes(b''.join(bytes(pattern(lba)) for lba in range(4)))
    (out/'data.cue').write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n',encoding='ascii')
    return module

def validate_payload(actual,case,resume=False):
    wanted=expected(case)
    if type(actual) is not dict or 'reply' not in actual:raise ValueError('Missing actual reply')
    def valid(value):
        if type(value) is list:return all(type(v) is int and 0<=v<=255 for v in value)
        return type(value) is dict and set(value)=={'data','status','message'} and all(valid(v) for v in value.values())
    if not valid(actual['reply']) or actual['reply']!=wanted['reply']:raise ValueError('Literal payload/status/message differs')
    prefix=[] if resume else wanted['prefix']
    if not valid(actual.get('prefix')) or actual['prefix']!=prefix:raise ValueError('Literal prefix payload differs')
    return len(prefix)+len(wanted['reply']['data'])+2
