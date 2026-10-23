"""Authored settled VCE palette and VDC DMA checks through isolated Geargrafx."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.reference_geargrafx import Mcp
from scripts.raster_reference import delay_program


def plans():
    cases=[('copy',0,0,0x100,0x400,17),('overlap',0,2,0x100,0x101,257),
        ('source-decrement',0,6,0x1000,0x2000,257),('destination-decrement',0,10,0x100,0x2000,257),
        ('both-decrement',0,14,0x512,0x768,257),('ignored-high-destination',0,2,0x100,0x7FF8,17),
        ('destination-wrap',0,2,0x200,0xFFFF,4),('one-word',0,2,0x321,0x321,1),
        ('satb-masked',1,0,0x1000,0,256),('satb-irq',1,1,0x2000,0,256),
        ('satb-repeat',1,17,0x3000,0,256),('palette-wrap',2,0,0,0,512)]
    return [dict(id=name,mode=mode,seed=(i*13+7)&255,dcr=dcr,source=source,destination=destination,length=length)
            for i,(name,mode,dcr,source,destination,length) in enumerate(cases)]


def write_plan(path,plan):
    path.write_text(' '.join(str(plan[k]) for k in ('mode','seed','dcr','source','destination','length'))+'\n',encoding='ascii')


def vram_bytes(seed):
    return b''.join(((i*73+seed*257)&65535).to_bytes(2,'little') for i in range(32768))


def register_program(index,value):
    return bytes((3,index,0x13,value&255,0x23,value>>8))


def store(address,value):return bytes((0xA9,value,0x8D,address&255,address>>8))


def run(args):
    exe,probe,out=args.exe.resolve(),args.probe.resolve(),args.out.resolve()
    if not exe.is_relative_to(ROOT/'.deps') or not exe.is_file() or not probe.is_file():raise ValueError('Require existing .deps Geargrafx and video probe')
    out.mkdir(parents=True,exist_ok=True);(out/'result.json').write_text('{"result":"incomplete"}\n')
    rom=bytearray([0xEA]*8192);setup=bytes.fromhex('78 D4 A9 FF 53 01 A9 F8 53 FE 80 FE');rom[:len(setup)]=setup;rom[-2:]=bytes((0,0xE0))
    image=out/'synthetic-video.pce';image.write_bytes(rom)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    started=time.monotonic();checked=[]
    with (out/'process.log').open('wb') as log:
        process=subprocess.Popen([str(exe),'--headless','--portable','--mcp-http','--mcp-http-port',str(port)],cwd=exe.parent,
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        client=Mcp(port)
        try:
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('Reference exited')
                try:
                    info=client.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'pcenginerecomp-video-reference','version':'0.1'}});break
                except OSError:time.sleep(.05)
            else:raise RuntimeError('Reference startup exceeded budget')
            client.headers['MCP-Protocol-Version']=info['protocolVersion'];client.rpc('notifications/initialized')
            def guard():
                if time.monotonic()-started>180 or (out/'process.log').stat().st_size>256*1024:raise RuntimeError('Video reference exceeded time/diagnostic budget')
            for plan in plans():
                guard();client.call('load_media',file_path=str(image));client.call('debug_pause');client.call('write_huc6280_register',name='PC',value='E000')
                for _ in range(6):client.call('debug_step_into')
                areas=client.call('list_memory_areas')['areas'];ids={a['name']:a['id'] for a in areas}
                def run_code(code):
                    guard()
                    if not 0<len(code)<4096:raise ValueError('Finite helper exceeds scratch RAM')
                    client.call('write_memory',area=ids['SYSTEM RAM'],offset='1000',bytes=code.hex(' '));client.call('write_huc6280_register',name='PC',value='3000')
                    endpoint=f'{0x3000+len(code):04X}';client.call('debug_run_to_cursor',address=endpoint)
                    for _ in range(100):
                        position=client.call('debug_get_status')
                        if position['paused'] and position['pc']==endpoint:return
                        time.sleep(.01)
                    raise RuntimeError('Finite video helper failed to stop')
                client.call('write_memory',area=ids['VRAM'],offset='0000',bytes=vram_bytes(plan['seed']).hex(' '))
                client.call('write_memory',area=ids['SAT'],offset='0000',bytes=bytes(512).hex(' '))
                client.call('write_memory',area=ids['PALETTES'],offset='0000',bytes=bytes(1024).hex(' '))
                # Keep raster IRQ sources disabled while allowing DMA-end lines.
                run_code(register_program(5,0))
                if plan['mode']==0:
                    run_code(register_program(15,plan['dcr'])+register_program(16,plan['source'])+
                        register_program(17,plan['destination'])+register_program(18,plan['length']-1))
                elif plan['mode']==1:
                    run_code(register_program(15,plan['dcr'])+register_program(19,plan['source']))
                else:
                    run_code(store(0x402,253)+store(0x403,1))
                    for start in range(0,512,64):
                        run_code(b''.join(store(0x404,(i*37+plan['seed']*17)&255)+store(0x405,(i*11+plan['seed'])&255) for i in range(start,start+64)))
                    run_code(store(0x402,253)+store(0x403,1))
                    for start in range(0,512,64):
                        code=b''
                        for i in range(start,start+64):
                            for port,dest in ((0x404,0x2000+i*2),(0x405,0x2001+i*2)):
                                code+=bytes((0xAD,port&255,port>>8,0x8D,dest&255,dest>>8))
                        run_code(code)
                run_code(delay_program(2*1365*262))
                registers=client.call('get_huc6270_registers',vdc=1)['registers']
                cpu=client.call('get_huc6280_status');vce=client.call('get_huc6260_status')
                actual=dict(vram=bytes.fromhex(client.call('read_memory',area=ids['VRAM'],offset='0000',size=65536)['data']).hex(),
                    sat=bytes.fromhex(client.call('read_memory',area=ids['SAT'],offset='0000',size=512)['data']).hex(),
                    palette=bytes.fromhex(client.call('read_memory',area=ids['PALETTES'],offset='0000',size=1024)['data']).hex(),
                    readback=bytes.fromhex(client.call('read_memory',area=ids['SYSTEM RAM'],offset='0000',size=1024)['data']).hex() if plan['mode']==2 else '',
                    address=int(vce['cta'],16),status=int(registers[-1][1],16)&63,irq1=cpu['IRQ1_asserted'],
                    dma_registers=[int(registers[i][1],16) for i in (16,17,18)])
                write_plan(out/'plan.txt',plan)
                completed=subprocess.run([str(probe),str(out/'plan.txt')],capture_output=True,text=True,check=True,timeout=5)
                expected=json.loads(completed.stdout)
                if actual!=expected:
                    mismatch={k:dict(actual=hashlib.sha256(actual[k].encode()).hexdigest(),expected=hashlib.sha256(expected[k].encode()).hexdigest())
                        if isinstance(actual[k],str) and len(actual[k])>4096 else dict(actual=actual[k],expected=expected[k]) for k in actual if actual[k]!=expected[k]}
                    (out/'failure.json').write_text(json.dumps(dict(plan=plan,mismatch=mismatch),indent=2)+'\n');raise RuntimeError(f'Video reference mismatch: {plan["id"]}')
                checked.append(dict(id=plan['id'],result_sha256=hashlib.sha256(completed.stdout.encode()).hexdigest()))
            report=dict(result='pass',suite='video-settled',plans=len(checked),checked=checked,
                oracle_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
                scope='authored full VRAM/SAT/palette, palette port readback, settled DMA terminal registers and status/IRQ',
                not_checked=['CPU execution tiers','access phases','exact DMA timing','rendered output','hardware','gameplay'])
            (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/video-check/live')
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:print(error,file=sys.stderr);raise SystemExit(1)
