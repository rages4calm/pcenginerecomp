"""Bounded IRQ/RTI checks against isolated Geargrafx, using authored sources.

VDC VBlank, TEST UNIT READY status and a disabled expired timer establish
three real pending lines. The CPU matrix masks those lines independently.
No retail firmware, program, owner setting or save enters the experiment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
from generate_irq_fixture import make_fixture
from scripts.reference_geargrafx import Mcp, state
from scripts.cd_reference import prepare_media
from scripts.raster_reference import delay_program


def plans():
    result = []
    def add(name, entry, p, sp, divisor, mask, pulled=0):
        i = len(result)
        result.append(dict(id=name, seed=i & 255, a=(i*43+0x83)&255,
            x=(i*37+0x39)&255, y=(i*67+0xA7)&255, entry=entry, p=p,
            sp=sp, divisor=divisor, mask=mask, pulled=pulled, count=3))
    for divisor in (3, 12):
        for pulled in range(256):
            add(f'rti-{divisor}-{pulled:02x}', 0x2840, 0xE7,
                (0, 1, 254, 255)[pulled%4], divisor, 0, pulled)
        for mask in range(8):
            for sp in (0, 1, 254, 255):
                for p in (0, 0xFF, 0x55, 0xAA):
                    add(f'priority-{divisor}-{mask}-{sp}-{p:02x}', 0x2800, p, sp, divisor, mask)
        for name, entry, p, pulled in (('cli',0x2810,0xEF,0),
                ('sei',0x2820,0xEB,0),('plp-clear',0x2830,0xEF,0xEB),
                ('plp-set',0x2830,0xEB,0xEF)):
            for mask in (0, 1, 3, 7):
                for sp in (0, 255):
                    add(f'{name}-{divisor}-{mask}-{sp}',entry,p,sp,divisor,mask,pulled)
    return result


def initial_ram(plan):
    ram = bytearray((i*37+plan['seed']*17)&255 for i in range(8192))
    for pa,value in make_fixture().memory.items(): ram[pa-0x1F0000] = value
    for offset,target in ((0x1FF6,0x2900),(0x1FF8,0x2970),(0x1FFA,0x2980)):
        ram[offset:offset+2] = target.to_bytes(2,'little')
    for n,value in enumerate((plan['pulled'],0,0x28),1):
        ram[0x100+((plan['sp']+n)&255)] = value
    return ram


def write_plan(path,plan):
    keys=('seed','a','x','y','sp','p','divisor','mask','pulled','entry','count')
    path.write_text(' '.join(str(plan[k]) for k in keys)+'\n',encoding='ascii')


def measured_ticks(trace,pcs):
    if trace.get('overrun') or trace.get('count')!=len(pcs) or len(trace.get('lines',[]))!=len(pcs):
        raise RuntimeError('Missing or overwritten IRQ trace')
    stamps=[]
    for line,pc in zip(trace['lines'],pcs):
        match=re.match(r'^@(\d+)\s+.*?\b([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s',line)
        if not match or int(match[2],16)!=0xF8 or int(match[3],16)!=pc:
            raise RuntimeError('Unexpected IRQ trace bank/PC')
        stamps.append(int(match[1]))
    if any(b<=a for a,b in zip(stamps,stamps[1:])): raise RuntimeError('Nonmonotonic IRQ trace')
    return stamps[-1]-stamps[0]


def run(args):
    exe,probe,out=args.exe.resolve(),args.probe.resolve(),args.out.resolve()
    if not exe.is_relative_to(ROOT/'.deps') or not exe.is_file() or not probe.is_file():
        raise ValueError('Require existing .deps Geargrafx and compiled IRQ probe')
    if not 1<=args.shard_count<=32 or not 0<=args.shard_index<args.shard_count: raise ValueError('Invalid shard')
    selected=plans()[args.shard_index::args.shard_count]
    if not selected: raise ValueError('Empty shard')
    out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').write_text('{"result":"incomplete"}\n')
    setup=bytes.fromhex('78 D4 A9 FF 53 01 A9 F8 53 FE 80 FE')
    image,bios=prepare_media(out.parent/'irq-media',setup)
    (exe.parent/'portable.ini').touch(exist_ok=True)
    with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    started=time.monotonic()
    counts={tier:dict(states=0,ram=0,matching_tick_deltas=0,native_steps=0,interpreter_steps=0) for tier in ('native','interpreter')}
    with (out/'process.log').open('wb') as log:
        process=subprocess.Popen([str(exe),'--headless','--portable','--mcp-http','--mcp-http-port',str(port)],
            cwd=exe.parent,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        client=Mcp(port)
        try:
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('Reference exited')
                try:
                    info=client.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'pcenginerecomp-irq-reference','version':'0.1'}});break
                except OSError: time.sleep(.05)
            else: raise RuntimeError('Reference startup exceeded budget')
            client.headers['MCP-Protocol-Version']=info['protocolVersion'];client.rpc('notifications/initialized')
            client.call('load_bios',file_path=str(bios),type='syscard');client.call('load_media',file_path=str(image));client.call('debug_pause')
            client.call('write_huc6280_register',name='PC',value='E000')
            for _ in range(6): client.call('debug_step_into')
            area=next(a['id'] for a in client.call('list_memory_areas')['areas'] if a['name']=='SYSTEM RAM' and a['byte_size']==8192)
            def guard():
                if time.monotonic()-started>180 or (out/'process.log').stat().st_size>256*1024:
                    raise RuntimeError('IRQ reference exceeded time/diagnostic budget')
            def run_code(code):
                guard()
                if not 0<len(code)<4096: raise ValueError('Finite helper exceeds scratch RAM')
                client.call('write_memory',area=area,offset='1000',bytes=code.hex(' '));client.call('write_huc6280_register',name='PC',value='3000')
                endpoint=f'{0x3000+len(code):04X}';client.call('debug_run_to_cursor',address=endpoint)
                for _ in range(100):
                    position=client.call('debug_get_status')
                    if position['paused'] and position['pc']==endpoint: return
                    time.sleep(.01)
                raise RuntimeError('Finite IRQ helper failed to stop')
            def store(address,value): return bytes((0xA9,value,0x8D,address&255,address>>8))
            client.call('write_huc6280_register',name='P',value='04')
            run_code(store(0x1402,7)+store(0xC01,0)+store(0x1403,0)+store(0x1804,2)+store(0x1804,0)+store(0x1802,0x20)+store(0x1800,0)+delay_program(75060))
            command=b''
            for i in range(6):
                command+=store(0x1801,0)+store(0x1802,0xA0)+store(0x1802,0x20)+delay_program(450060 if i==5 else 3060)
            run_code(command)
            for index,value in ((5,8),(10,0x0202),(11,0x041F),(12,0x0F02),(13,239),(14,4)):
                client.call('write_huc6270_register',register=index,value=f'{value:04X}',vdc=1)
            run_code(delay_program(2*1365*262))
            run_code(store(0xC00,0)+store(0xC01,1)+delay_program(6144)+store(0xC01,0))
            source=client.call('get_huc6280_status')
            if not all(source[k] for k in ('IRQ1_asserted','IRQ2_asserted','TIQ_asserted')) or source['TIMER']:
                (out/'source-failure.json').write_text(json.dumps(source,indent=2)+'\n');raise RuntimeError('Authored pending source setup failed')
            for plan in selected:
                guard();client.call('write_huc6280_register',name='P',value='04')
                run_code(bytes((0xD4,))+store(0x1402,plan['mask'])+bytes((0x54 if plan['divisor']==12 else 0xD4,)))
                ram=initial_ram(plan);client.call('write_memory',area=area,offset='0000',bytes=ram.hex(' '))
                for name,key in (('PC','entry'),('A','a'),('X','x'),('Y','y'),('S','sp'),('P','p')):
                    client.call('write_huc6280_register',name=name,value=f'{plan[key]:X}')
                before=client.call('get_huc6280_status')
                if state(before)!=dict(pc=plan['entry'],a=plan['a'],x=plan['x'],y=plan['y'],sp=plan['sp'],p=plan['p'],mpr=[255]+[248]*7):
                    raise RuntimeError('Reference CPU setup differs')
                if not all(before[k] for k in ('IRQ1_asserted','IRQ2_asserted','TIQ_asserted')) or before['TIMER'] or before['SPEED']!=('7.16 MHz' if plan['divisor']==3 else '1.79 MHz'):
                    raise RuntimeError('Reference pending source/speed setup differs')
                client.call('set_trace_log',enabled=True,output='memory',memory_size='100K',filters=['cpu.instructions'])
                cursor=client.call('get_trace_log',start=-1,count=1)['next_sequence'];expected=[];pcs=[plan['entry']]
                for _ in range(3):
                    client.call('debug_step_into');row=state(client.call('get_huc6280_status'));expected.append(row);pcs.append(row['pc'])
                wanted_ram=bytes.fromhex(client.call('read_memory',area=area,offset='0000',size=8192)['data']).hex()
                client.call('write_memory',area=area,offset='0700',bytes='EA');client.call('write_huc6280_register',name='PC',value='2700');client.call('debug_step_into')
                trace=client.call('get_trace_log',start=cursor,count=4);client.call('set_trace_log',enabled=False)
                pcs[-1]=0x2700;ticks=measured_ticks(trace,pcs)
                write_plan(out/'plan.txt',plan)
                for tier in counts:
                    completed=subprocess.run([str(probe),str(out/'plan.txt'),tier],capture_output=True,text=True,check=True,timeout=5)
                    actual=json.loads(completed.stdout);wanted_counts=(3,0) if tier=='native' else (0,3)
                    if actual['states']!=expected or actual['ram']!=wanted_ram or (actual['native_steps'],actual['interpreter_steps'])!=wanted_counts or actual['ticks']!=ticks:
                        (out/'failure.json').write_text(json.dumps(dict(plan=plan,tier=tier,actual=actual,expected=dict(states=expected,ram=wanted_ram,ticks=ticks)),indent=2)+'\n')
                        raise RuntimeError(f'IRQ reference mismatch: {plan["id"]}, {tier}')
                    counts[tier]['states']+=3;counts[tier]['ram']+=1;counts[tier]['matching_tick_deltas']+=1
                    counts[tier]['native_steps']+=actual['native_steps'];counts[tier]['interpreter_steps']+=actual['interpreter_steps']
            report=dict(schema=1,result='pass',suite='irq-rti',oracle=info['serverInfo'],
                oracle_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
                shard=dict(index=args.shard_index,count=args.shard_count),checked_plans=[p['id'] for p in selected],comparisons=counts,
                scope='three CPU/MPR states, complete RAM including stack, complete-instruction clocks; actual VDC/CD/timer pending sources',
                not_checked=['IRQ line access phases','timer edge accuracy','source deassertion within instruction','hardware','gameplay'])
            (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='checked_plans'},indent=2))
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/irq-check/live')
    parser.add_argument('--shard-index',type=int,default=0);parser.add_argument('--shard-count',type=int,default=1)
    try: run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
