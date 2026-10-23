"""Bounded authored settled ADPCM/PSG port checks through isolated Geargrafx."""
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
from scripts.cd_reference import prepare_media
from scripts.raster_reference import delay_program


def plans():
    result=[]
    for i,address in enumerate((0,1,0xFFDF,0xFFFF)):
        seed=7+i*23
        # Alternate both rising-edge address modes; the minus-one variant
        # deliberately wraps zero to FFFF in the final case.
        pointer=(address+(i&1))&65535
        ops=[(0x180D,128),(0x180D,0),(0x1808,pointer&255),(0x1809,pointer>>8),(0x180D,2 if i&1 else 3)]
        ops += [(0x180A,(j*37+seed)&255) for j in range(64)]
        ops += [(0x180D,0),(0x1808,pointer&255),(0x1809,pointer>>8),(0x180D,8 if i&1 else 12)]
        ops += [(0x180A,-1)]*65
        ops += [(0x180C,-1),(0x180D,-1),(0x180E,255),(0x180E,-1),
                (0x180D,128),(0x180D,0),(0x180C,-1),(0x180D,-1)]
        result.append(dict(id=f'adpcm-{address:04x}',operations=ops))
    for selected in (0,3,4,7):
        ops=[(0x800,selected),(0x801,0xE7),(0x802,0x34),(0x803,0xF2),(0x804,0x1F),(0x805,0xA5)]
        ops += [(0x806,(i*11+selected*17)&255) for i in range(40)]
        ops += [(0x806,-1),(0x804,0x40),(0x806,0xA5),(0x800,-1),(0x804,0),
                (0x806,0x1B),(0x807,0xE7),(0x808,0x7F),(0x809,0x80),(0xBFF,-1)]
        if selected==3:ops += [(0x804,0x40)]
        result.append(dict(id=f'psg-disabled-{selected}',operations=ops))
    return result


def write_plan(path,plan):
    ops=plan['operations']
    path.write_text(str(len(ops))+'\n'+''.join(f'{address} {value}\n' for address,value in ops),encoding='ascii')


def normalize_adpcm(value):
    return dict(address=int(value['address'],16),read_address=int(value['read_address'],16),
        write_address=int(value['write_address'],16),length=value['length'],control=int(value['control'],16),
        dma=int(value['dma'],16),playing=value['playing'])


def normalize_psg(value):
    return dict(selected=value['channel_select'],main_volume=int(value['main_amplitude'],16),
        lfo_frequency=int(value['lfo_frequency'],16),lfo_control=int(value['lfo_control'],16),
        channels=[dict(frequency=c['frequency'],
            balance=(int(c['vol_left'],16)<<4)|int(c['vol_right'],16),wave_index=c['wave_index'],
            dda_mode=c['dda'],enabled=c['enabled'],noise_enabled=c['noise']) for c in value['channels']])


def run(args):
    exe,probe,out=args.exe.resolve(),args.probe.resolve(),args.out.resolve()
    if not exe.is_relative_to(ROOT/'.deps') or not exe.is_file() or not probe.is_file():raise ValueError('Require existing .deps Geargrafx and audio probe')
    out.mkdir(parents=True,exist_ok=True);(out/'result.json').write_text('{"result":"incomplete"}\n')
    image,bios=prepare_media(out.parent/'audio-media',bytes.fromhex('78 D4 A9 FF 53 01 A9 F8 53 FE 80 FE'))
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
                    info=client.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'pcenginerecomp-audio-reference','version':'0.1'}});break
                except OSError:time.sleep(.05)
            else:raise RuntimeError('Reference startup exceeded budget')
            client.headers['MCP-Protocol-Version']=info['protocolVersion'];client.rpc('notifications/initialized')
            client.call('load_bios',file_path=str(bios),type='syscard')
            def guard():
                if time.monotonic()-started>180 or (out/'process.log').stat().st_size>256*1024:raise RuntimeError('Audio reference exceeded time/diagnostic budget')
            for plan in plans():
                guard();client.call('load_media',file_path=str(image));client.call('debug_pause');client.call('write_huc6280_register',name='PC',value='E000')
                for _ in range(6):client.call('debug_step_into')
                ids={a['name']:a['id'] for a in client.call('list_memory_areas')['areas']}
                client.call('write_memory',area=ids['ADPCM'],offset='0000',bytes=bytes(65536).hex(' '))
                def run_code(code):
                    guard()
                    if not 0<len(code)<4096:raise ValueError('Finite helper exceeds scratch RAM')
                    client.call('write_memory',area=ids['SYSTEM RAM'],offset='1000',bytes=code.hex(' '));client.call('write_huc6280_register',name='PC',value='3000')
                    endpoint=f'{0x3000+len(code):04X}';client.call('debug_run_to_cursor',address=endpoint)
                    for _ in range(100):
                        position=client.call('debug_get_status')
                        if position['paused'] and position['pc']==endpoint:return
                        time.sleep(.01)
                    raise RuntimeError('Finite audio helper failed to stop')
                read_count=0
                for start in range(0,len(plan['operations']),32):
                    code=b''
                    for address,value in plan['operations'][start:start+32]:
                        if value<0:
                            target=0x2000+read_count;read_count+=1
                            code+=bytes((0xAD,address&255,address>>8,0x8D,target&255,target>>8))
                        else:code+=bytes((0xA9,value,0x8D,address&255,address>>8))
                        code+=delay_program(120)
                    run_code(code)
                actual=dict(reads=bytes.fromhex(client.call('read_memory',area=ids['SYSTEM RAM'],offset='0000',size=read_count)['data']).hex(),
                    ram=bytes.fromhex(client.call('read_memory',area=ids['ADPCM'],offset='0000',size=65536)['data']).hex(),
                    adpcm=normalize_adpcm(client.call('get_adpcm_status')),psg=normalize_psg(client.call('get_psg_status')))
                write_plan(out/'plan.txt',plan)
                completed=subprocess.run([str(probe),str(out/'plan.txt')],capture_output=True,text=True,check=True,timeout=5)
                expected=json.loads(completed.stdout)
                if actual!=expected:
                    mismatch={k:dict(actual=hashlib.sha256(actual[k].encode()).hexdigest(),expected=hashlib.sha256(expected[k].encode()).hexdigest())
                        if isinstance(actual[k],str) and len(actual[k])>4096 else dict(actual=actual[k],expected=expected[k]) for k in actual if actual[k]!=expected[k]}
                    (out/'failure.json').write_text(json.dumps(dict(plan=plan,mismatch=mismatch),indent=2)+'\n');raise RuntimeError(f'Audio reference mismatch: {plan["id"]}')
                checked.append(dict(id=plan['id'],read_bytes=read_count,result_sha256=hashlib.sha256(completed.stdout.encode()).hexdigest()))
            report=dict(result='pass',suite='audio-settled',plans=len(checked),checked=checked,
                oracle_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
                scope='settled manual ADPCM RAM/port reads/reset; disabled PSG register/index/DDA-mode and I/O latch',
                not_checked=['CPU execution tiers','access phases','exact memory slot timing','ADPCM DMA/playback','PSG waveform memory','oscillators','mixed PCM','hardware','gameplay'])
            (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/audio-check/live')
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:print(error,file=sys.stderr);raise SystemExit(1)
