"""Authored blanking palettes against separate unmodified full emulator cores.

This is an optional independent reference workflow, not hardware qualification.
Original CR frame/burst admission and a mid-frame CR change are distinct cases.
No game, BIOS, owner save, desktop capture or physical audio/GPU is used.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import beetle_reference
from scripts.reference_geargrafx import Mcp
from scripts.scanline_reference import decode_png


def require(value,message):
    if not value:raise ValueError(message)


def cases():
    return [dict(id=f'stable-{cr:02x}',cr=cr,midframe=False)for cr in (0,64,128,192)]+[
        dict(id='midframe-disable',cr=128,midframe=True)]


def authored_rom(case):
    require(type(case)is dict and set(case)=={'id','cr','midframe'} and
        type(case['id'])is str and type(case['cr'])is int and type(case['midframe'])is bool
        and case in cases(),'Canonical authored case required')
    code=bytearray.fromhex('78 D4 A9 FF 53 01 A9 F8 53 02 A2 FF 9A')
    def reg(index,value):code.extend((3,index,0x13,value&255,0x23,value>>8))
    def store(address,value):code.extend((0xA9,value,0x8D,address&255,address>>8))
    def color(index,value):
        for address,data in ((0x402,index&255),(0x403,index>>8),(0x404,value&255),(0x405,value>>8)):
            store(address,data)
    def wait(mask):
        at=len(code);code.extend((0xAD,0,0,0x29,mask,0xF0,0))
        code[-1]=(at-len(code))&255
    reg(5,0);reg(0,0);reg(2,0)
    # Explicitly clear every VRAM word through ordinary CPU/VDC instructions.
    code.extend((0xA0,128,0xA2,0));loop=len(code)
    code.extend((0x13,0,0x23,0,0xCA,0xD0,0));code[-1]=(loop-len(code))&255
    code.extend((0x88,0xD0,0));code[-1]=((loop-2)-len(code))&255
    if case['midframe']:
        store(0x2040,0);store(0x2041,0)
    for index,value in ((5,0x8C if case['midframe'] else case['cr']),(6,128),(7,0),(8,0),(9,0),
                        (10,0x0202),(11,0x041F),(12,0x0F02),(13,191),(14,64),(19,0)):
        reg(index,value)
    # Palette 0 = red; 0x100 = green; black is a third distinct outcome.
    for index,value in ((0,0x38),(256,0x1C0)):
        color(index,value)
    if case['midframe']:
        # VBlank/RCR status is gated by CR bits 3/2. Keep those enabled
        # while changing only the layer bits; counters prove both writes ran.
        cycle=len(code);wait(32);reg(5,0x8C);code.extend((0xE6,0x41))
        wait(4);reg(5,0x0C);code.extend((0xE6,0x40))
        code.extend((0x4C,(0xE000+cycle)&255,(0xE000+cycle)>>8))
    else:code.extend((0x80,0xFE))
    require(len(code)<1024,'Authored ROM code bound exceeded')
    rom=bytearray([0xEA])*262144;rom[:len(code)]=code;rom[8190:8192]=bytes((0,0xE0))
    return bytes(rom)


def admit_frame(case,frame,engine):
    """Literal palette probes inside active lines; viewport borders are separate."""
    require(engine in ('beetle','gear'),'Known independent engine required')
    if case['midframe']:
        markers=frame.get('markers')
        require(type(markers)is dict and set(markers)=={'disabled','reenabled'} and
            all(type(x)is int and 10<x<=255 for x in markers.values()),
            'Actual repeated mid-frame transitions were not observed')
    require(frame['width']==256 and frame['height']==(243 if engine=='beetle' else 242),
        'Independent viewport geometry changed')
    rows=frame['center_rows']
    require(type(rows)is list and len(rows)==frame['height'],'Complete center-column rows required')
    if engine=='beetle':
        require(all(type(x)is int and 0<=x<=65535 for x in rows),'RGB565 rows required')
        wanted=2016 if case['cr']in (0,64) else 63488
    else:
        require(all(type(x)is list and len(x)==3 and all(type(c)is int and 0<=c<=255 for c in x) for x in rows),
            'RGB888 rows required')
        wanted=[0,0,0] if case['cr']==0 else [255,0,0]
    required={y:wanted for y in (40,80,120,180)}
    require(all(rows[y]==value for y,value in required.items()),
        f'Independent {engine} active-row palette differs for '+case['id'])
    if engine=='beetle' and case['cr']==0 and not case['midframe']:
        require(all(x==2016 for x in rows),'Original latched burst is not uniformly border green')
    return dict(engine=engine,case=case['id'],active_probe_rows=required)


def compare_frames(beetle,gear):
    """Keep actual engine disagreement visible, rather than calling it parity."""
    require(len(beetle)==len(gear)==len(cases()),'Exact independent case extent required')
    differences=[]
    for case,b,g in zip(cases(),beetle,gear):
        require(b['case']==g['case']==case,'Canonical case order required')
        admit_frame(case,b['beetle'],'beetle');admit_frame(case,g['frame'],'gear')
        value=b['beetle']['center_rows'][80]
        color={2016:[0,255,0],63488:[255,0,0]}[value]
        actual=g['frame']['center_rows'][80]
        if color!=actual:differences.append(dict(case=case['id'],beetle=color,gear=actual))
    require([x['case']for x in differences]==['stable-00','stable-40'],
        'Independent engine discrepancy extent changed')
    return dict(all_cases_equal=False,active_probe_case_agreement=3,disagreements=differences,
        policy='Original engine outputs retained. Burst black versus palette256 and sprite-only transparent palette0 versus256 remain explicit; no hardware truth or per-dot timing claim.')


def gear_frames(executable,out,roms):
    """Run only an owned copied headless oracle with dummy software drivers."""
    host=out/'gear-host';host.mkdir()
    originals={}
    for name in ('Geargrafx.exe','SDL3.dll','gamecontrollerdb.txt'):
        source=executable.parent/name
        originals[str(source)]=beetle_reference.binding(source)
        shutil.copyfile(source,host/name)
        require(beetle_reference.binding(host/name)['sha256']==originals[str(source)]['sha256'],
            'Oracle package copy differs')
    # Empty portable marker selects only this new private directory. Do not
    # change the previous oracle's profile or discover an owner installation.
    (host/'portable.ini').write_text('',encoding='ascii')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    command=[str(host/'Geargrafx.exe'),'--headless','--portable','--mcp-http','--mcp-http-port',str(port)]
    log=(out/'gear-process.log').open('xb')
    process=subprocess.Popen(command,cwd=host,env=environment,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    client=Mcp(port);result=[]
    try:
        for _ in range(100):
            if process.poll()is not None:raise RuntimeError('Owned Gear oracle exited')
            try:initial=client.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'authored-blanking-reference','version':'1'}});break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('Owned Gear oracle startup deadline')
        client.rpc('notifications/initialized')
        for case,rom in roms:
            client.call('load_media',file_path=str(rom));client.call('debug_pause')
            client.call('debug_step_frame',frames=30,mode='sync')
            status=client.call('debug_get_status');require(status['paused'],'Original frame stepping did not settle')
            captured=client.rpc('tools/call',{'name':'get_screenshot','arguments':{}})
            blocks=[b for b in captured.get('content',[])if b.get('type')=='image']
            require(not captured.get('isError') and len(blocks)==1 and blocks[0]['mimeType']=='image/png','Original screenshot missing')
            raw=base64.b64decode(blocks[0]['data'],validate=True)
            folder=out/case['id'];folder.mkdir(exist_ok=True)
            (folder/'gear.png').write_bytes(raw)
            w,h,rgb=decode_png(raw)
            frame=dict(width=w,height=h,center_rows=[list(rgb[(y*w+w//2)*3:(y*w+w//2)*3+3])for y in range(h)])
            areas=client.call('list_memory_areas')['areas']
            area=next(a['id']for a in areas if a['name']=='SYSTEM RAM' and a['byte_size']==8192)
            markers=bytes.fromhex(client.call('read_memory',area=area,offset='0040',size=2)['data'])
            require(len(markers)==2,'Original SYSTEM RAM marker extent changed')
            frame['markers']=dict(disabled=markers[0],reenabled=markers[1])
            result.append(dict(case=case,frame=frame,admission=admit_frame(case,frame,'gear')))
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
        for name,bound in originals.items():require(beetle_reference.binding(Path(name))==bound,'Original Gear package changed')
    return dict(binary=originals[str(executable)],server=initial['serverInfo'],cases=result,
        command=command,source_package_unchanged=True,owned_hosts=0,
        scope='Owned copied software/headless Gear oracle; all RGB rows retained; no owner profile or GPU/audio')


def run(args):
    out=args.out.resolve();require(not out.exists() and out.is_relative_to(ROOT/'.local'),'New private output required')
    out.mkdir(parents=True);report=dict(schema=1,passed=False,cases=[],commands=[],scope=__doc__)
    try:
        built_path,built=beetle_reference.build(args,out,report['commands'],ROOT/'tests/beetle_blanking_probe.cpp')
        report['beetle_build']=beetle_reference.binding(built_path)
        roms=[]
        for case in cases():
            folder=out/case['id'];folder.mkdir();rom=folder/'authored.pce';rom.write_bytes(authored_rom(case))
            done=beetle_reference.run_command([built['binary']['path'],str(rom)],folder,'beetle',report['commands'])
            frame=json.loads(done.stdout)
            report['cases'].append(dict(case=case,rom=beetle_reference.binding(rom),beetle=frame,
                admission=admit_frame(case,frame,'beetle')));roms.append((case,rom))
        if args.gear_exe is not None:
            report['gear']=gear_frames(args.gear_exe.resolve(strict=True),out,roms)
            report['cross_engine']=compare_frames(report['cases'],report['gear']['cases'])
        beetle_reference.check_build(built_path)
        report['passed']=True
    finally:(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],cases=len(report['cases'])),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--beetle-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--compiler',required=True);p.add_argument('--cmake',required=True);p.add_argument('--ninja',required=True)
    p.add_argument('--gear-exe',type=Path)
    run(p.parse_args())
