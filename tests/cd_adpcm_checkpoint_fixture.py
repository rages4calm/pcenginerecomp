"""Authored CD→ADPCM DMA dataflow and independent finite cut expectations."""
from collections import Counter
from pathlib import Path
MPR=(255,248,128,129,131,132,2,0)
SITES=[(0x2800+i*8,op,address) for i,(op,address) in enumerate([(0x8d,a) for a in (0x1800,0x1801,0x1802,0x1804,0x1808,0x1809,0x180b,0x180d)]+[(0xad,0x1801)])]
CUTS=('waiting-req','pending-beat','sampled-write','committed-ack','paused-dma','sector-gap','adpcm-reset','cd-reset')
WRITE_DELAY=(9,8,7,6,5,4,3,2,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,19,18,17,16,15,14,13,12,11,10)
def cases():return [dict(id=f'{name}-mode{mode}-div{div}',cut=cut,mode=mode,divisor=div) for div in (3,12) for mode in (1,2) for cut,name in enumerate(CUTS)]
def pattern(lba):return [(lba*29+i*17+(i>>8)*7+0x53)&255 for i in range(2048)]
def source_memory():return {0x1f0000+(pc&8191)+i:v for pc,op,address in SITES for i,v in enumerate((op,address&255,address>>8,0x80,0xfe))}
def authored_rom():
 value=bytearray([0xea]*262144);value[8190:8192]=b'\x00\xe0';return bytes(value)
def header():
 memory=source_memory();lines=['#pragma once','#include <array>','#include <cstdint>','#include <utility>',
  'inline constexpr std::array<std::uint8_t,8> checkpoint_mpr{'+','.join(map(str,MPR))+'};','struct CheckpointSite {unsigned pc,op,address;};',f'inline constexpr std::array<CheckpointSite,{len(SITES)}> checkpoint_sites{{{{']
 lines+=['{'+','.join(map(str,row))+'},' for row in SITES]+['}};',f'inline constexpr std::array<std::pair<unsigned,std::uint8_t>,{len(memory)}> checkpoint_program{{{{']
 lines+=['{'+str(a)+','+str(v)+'},' for a,v in sorted(memory.items())]+['}};',''];return '\n'.join(lines)
def fixtures(out):
 from pcerecomp.analysis import Snapshot,analyze
 from pcerecomp.emitter import emit
 out=Path(out);module=out/'fixture';module.mkdir();emit(analyze(Snapshot(MPR,source_memory(),tuple(pc for pc,_,_ in SITES),'authored-cd-adpcm-checkpoint-v1')),module)
 (module/'cd_adpcm_checkpoint_fixture.hpp').write_text(header());(out/'authored.pce').write_bytes(authored_rom());(out/'data.bin').write_bytes(b''.join(bytes(pattern(lba)) for lba in range(4)))
 (out/'data.cue').write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n',encoding='ascii');return module

def expected(case):
 payload=pattern(0)+pattern(1) if case['cut']==5 else pattern(1) if case['cut']>=6 else pattern(0)
 ram=[0]*65536
 for i,v in enumerate(payload):ram[(0xfffe+i)&65535]=v
 return dict(prefix=[],reply=dict(ram=ram,status=[0],message=[0],flags=[len(payload),(0xfffe+len(payload))&65535,1,1,1,0,1,1,1,0,1,1,0,0,0]))
def validate_payload(actual,case,resume=False):
 if type(actual) is not dict or type(actual.get('reply')) is not dict:raise ValueError('DMA reply missing')
 wanted=expected(case)
 if actual.get('prefix')!=[]:raise ValueError('DMA prefix is observation only')
 if set(actual['reply'])!=set(wanted['reply']):raise ValueError('DMA reply fields differ')
 for key,values in wanted['reply'].items():
  got=actual['reply'][key]
  if type(got) is not list or any(type(v) is not int or v<0 for v in got) or got!=values:raise ValueError('Independent DMA '+key+' differs')
 return sum(map(len,wanted['reply'].values()))

def hits(case,prefix=False):
 result=Counter()
 def add(address,n=1,op=0x8d):result[next(pc for pc,o,a in SITES if (o,a)==(op,address))]+=n
 def setup():add(0x180d,4);add(0x1808);add(0x1809);add(0x1802)
 def send():add(0x1800);add(0x1801,6);add(0x1802,12)
 if prefix:
  setup();send();add(0x180b)
  if case['cut']==4:add(0x180b)
  if case['cut']==6:add(0x180d)
  if case['cut']==7:add(0x1804)
 else:
  if (case['cut'] in (0,5) and case['mode']==1) or case['cut']==4:add(0x180b)
  if case['cut']>=6:
   add(0x180b);add(0x180d);add(0x1804,2);setup();send();add(0x180b)
  add(0x180b);add(0x1801,2,0xad);add(0x1802,6);add(0x180d,2)
 return +result

def validate_cut(actual,case,gear=False):
 row=actual.get('cut')
 if type(row) is not list or len(row)!=13 or any(type(v) is not int or v<0 for v in row):raise ValueError('Typed DMA cut observation required')
 tick,signals,dma,remain,write,address,length,half,end,irq,active,enabled,ack=row
 if remain>36 or write>19 or ack>21 or enabled!=12 or any(v not in (0,1) for v in (half,end,irq)):raise ValueError('DMA cut bounds differ')
 if (active&12)!=((4 if half else 0)|(8 if end else 0)) or irq!=int(bool(active&enabled)):raise ValueError('ADPCM source/enable IRQ relation differs')
 cut,mode,slow=case['cut'],case['mode'],case['divisor']==12
 n=(1 if slow else 0)
 if cut==0:
  if [signals,dma,remain,write,address,length,half,end,irq,ack]!=[0x88,mode if mode==2 else 0,0,0,0xfffe,0,0,0,0,0]:raise ValueError('Waiting DMA cut differs')
 elif cut in (1,4):
  if not (1<=remain<=36 and write==0 and length==n and address==(0xfffe+n)&65535 and half==end==irq==int(n>0) and dma==(0 if cut==4 else mode)):raise ValueError('Pending/paused DMA cut differs')
 elif cut==2:
  if not(write==WRITE_DELAY[tick%36] and write>0 and ack==21 and length==n and address==(0xfffe+n)&65535 and signals==(0xca if gear else 0x8a) and dma==mode):raise ValueError('Sampled pending-write DMA cut differs')
 elif cut==3:
  if not(write==0 and 1<=ack<=20 and length==n+1 and address==(0xfffe+n+1)&65535 and half==end==irq==1 and signals==0x8a):raise ValueError('Committed/ACK DMA cut differs')
 elif cut==5:
  if not(length==2048 and address==2046 and not write and not remain and not ack and dma==(2 if mode==2 else 0) and half==end==irq==1):raise ValueError('Sector-gap DMA cut differs')
 elif cut==6:
  if not(length==address==write==half==end==irq==0 and dma==mode and remain>0):raise ValueError('ADPCM reset-held DMA cut differs')
 elif cut==7:
  count=2 if slow else 0
  if not(signals==0x100 and length==count and address==(0xfffe+count)&65535 and not ack and half==end==irq==int(slow) and dma==(mode if not slow or mode==2 else 0)):raise ValueError('CD reset cut differs')
 if not gear:
  address=0x180d if cut==6 else 0x1804 if cut==7 else 0x180b
  pc=next(pc for pc,op,a in SITES if op==0x8d and a==address)+3;memory=source_memory();wanted=[pc,*MPR]
  for i in range(7):
   physical=(MPR[((pc+i)&65535)>>13]<<13)|((pc+i)&8191);wanted.extend((physical,memory.get(physical,0)))
  if actual.get('cut_source')!=wanted or any(type(v) is not int for v in actual['cut_source']):raise ValueError('Full paused DMA source differs')
 return len(row)
def validate_gear_cut(actual,case):
 checks=validate_cut(actual,case,True)
 for key in ('single_clock_calls','single_clock_ticks','coarse_clock_calls','coarse_clock_ticks'):
  if type(actual.get(key)) is not int or actual[key]<0:raise ValueError('Original clock count type differs')
 if not actual['single_clock_calls'] or actual['single_clock_calls']!=actual['single_clock_ticks']:raise ValueError('Original active DMA must use one-tick calls')
 if type(actual.get('final_ticks')) is not int or actual['final_ticks']!=actual['single_clock_ticks']+actual['coarse_clock_ticks']:raise ValueError('Original total callback clock association differs')
 return checks+4

CUT_FIELDS=('ticks','signals','dma','dma_remaining','write_remaining','write_address','length','half','end','irq2','active_irqs','enabled_irqs','auto_ack_remaining')
def raw_differences(original,tool,case):
 return [dict(case=case['id'],field=name,original=g,tool=t) for name,g,t in zip(CUT_FIELDS,original['cut'],tool['cut']) if g!=t]
def validate_journal(actual,case,resume=False,gear=False):
 journal=actual.get('journal')
 if type(journal) is not list:raise ValueError('Raw named clock observations required')
 expected_labels=[] if resume else (['waiting-first-req'] if case['cut']==0 else ['arm-end','cut'])
 expected_labels+=(['after-reset-hold'] if case['cut']>=6 else [])+['payload-committed','acknowledged-end']
 if [row.get('label') for row in journal if type(row) is dict]!=expected_labels:raise ValueError('Raw named observation sequence differs')
 for row in journal:
  if set(row)!={'label','values'} or type(row['values']) is not list or len(row['values'])!=13 or any(type(v) is not int or v<0 for v in row['values']):raise ValueError('Raw observation field/type differs')
 if gear:
  if journal[-1]['values'][0]!=actual['final_ticks']:raise ValueError('Original final clock observation differs')
 else:
  for key in ('advance_calls','advanced_ticks','origin_ticks','final_ticks'):
   if type(actual.get(key)) is not int or actual[key]<0:raise ValueError('Actual toolkit clock count type differs')
  instructions=sum(hits(case).values())+(0 if resume else sum(hits(case,True).values()))
  wanted=(actual['origin_ticks'] if resume else 0)+actual['advanced_ticks']+instructions*5*case['divisor']
  if actual['final_ticks']!=wanted:raise ValueError('Independent port-op/host-wait clock ledger differs')
 return len(journal)*13
