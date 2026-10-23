"""Bounded live pixel comparison with the pinned portable Geargrafx MCP.

Authored graphics only. Direct debugger writes intentionally isolate rendering
from CPU port-access timing. A full 256 by 192 VDC active viewport is compared,
including palette changes within a line and horizontal scroll changes between
line latches. No game media, firmware, screenshot UI, or owner save is used.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import zlib

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.reference_geargrafx import Mcp
from scripts.raster_reference import delay_program

FRAME=1365*262


def plans():
    return [dict(id=name,seed=seed,mwr=mwr,bxr=bxr,byr=byr,cr=cr) for name,seed,mwr,bxr,byr,cr in (
        ('background-32',1,0,0,0,128),('sprites-and-scroll-64',2,16,253,255,192),
        ('vertical-wrap-64',3,64,7,507,192),('two-bit-sprites-64',4,84,511,253,192))]


def fixture(plan):
    """Complete little-endian synthetic VRAM, SATB and standard-RGB palette."""
    seed,mwr=plan['seed'],plan['mwr'];vram=[0]*32768;sat=[0]*256
    width=(32,64,128,128)[(mwr>>4)&3];height=64 if mwr&64 else 32
    for y in range(height):
        for x in range(width):vram[y*width+x]=(0x200+(x*3+y*5+seed)%64)|(((x+y+seed)%16)<<12)
    for tile in range(64):
        for y in range(8):
            for x in range(8):
                color=1+(x+y*3+tile+seed)%15;base=(0x200+tile)*16+y
                for plane in range(4):vram[base+(8 if plane>=2 else 0)]|=((color>>plane)&1)<<(7-x+8*(plane%2))
    for address in range(0x4000,0x6000):vram[address]=(address*109+seed*997)&65535
    for i in range(8):sat[i*4:i*4+4]=[64+24+i*19,32+8+i*29,0x200+i*8+(seed&1),
        (i&3)|(128 if i&1 else 0)|(256 if i&2 else 0)|(0x8800 if i&4 else 0)]
    pack=lambda words:b''.join(x.to_bytes(2,'little') for x in words)
    return pack(vram),pack(sat),palette(plan,0)


def palette(plan,phase):
    return b''.join(((i*29+plan['seed']*17+3+phase*183)&511).to_bytes(2,'little') for i in range(512))


def decode_png(data):
    """Bounded 8-bit RGB/RGBA noninterlaced PNG decoder; discard alpha only."""
    if len(data)>2*1024*1024 or data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid bounded PNG')
    position=8;compressed=bytearray();header=None;ended=False
    while position<len(data):
        if position+12>len(data):raise ValueError('Truncated PNG chunk')
        size=struct.unpack_from('>I',data,position)[0];kind=data[position+4:position+8]
        if size>2*1024*1024 or position+12+size>len(data):raise ValueError('Invalid PNG chunk extent')
        payload=data[position+8:position+8+size];crc=struct.unpack_from('>I',data,position+8+size)[0]
        if zlib.crc32(kind+payload)&0xFFFFFFFF!=crc:raise ValueError('PNG CRC mismatch')
        if kind==b'IHDR':
            if header is not None or size!=13:raise ValueError('Invalid PNG header')
            header=struct.unpack('>IIBBBBB',payload)
        elif kind==b'IDAT':compressed.extend(payload)
        elif kind==b'IEND':ended=True;position+=12;break
        position+=size+12
    if not ended or position!=len(data) or header is None:raise ValueError('Incomplete PNG')
    width,height,depth,color,compression,filter_method,interlace=header
    if not 1<=width<=1024 or not 1<=height<=512 or depth!=8 or color not in (2,6) or any((compression,filter_method,interlace)):
        raise ValueError('Unsupported PNG format')
    channels=3 if color==2 else 4;stride=width*channels;limit=(stride+1)*height
    inflater=zlib.decompressobj();raw=inflater.decompress(bytes(compressed),limit+1)
    if len(raw)!=limit or not inflater.eof or inflater.unused_data:raise ValueError('PNG raster extent mismatch')
    previous=bytearray(stride);rgb=bytearray()
    for y in range(height):
        start=y*(stride+1);method=raw[start];row=bytearray(raw[start+1:start+1+stride])
        if method>4:raise ValueError('Unknown PNG filter')
        for x in range(stride):
            left=row[x-channels] if x>=channels else 0;up=previous[x];upper_left=previous[x-channels] if x>=channels else 0
            if method==1:value=left
            elif method==2:value=up
            elif method==3:value=(left+up)//2
            elif method==4:
                p=left+up-upper_left;distances=(abs(p-left),abs(p-up),abs(p-upper_left));value=(left,up,upper_left)[distances.index(min(distances))]
            else:value=0
            row[x]=(row[x]+value)&255
        if channels==3:rgb.extend(row)
        else:
            for x in range(width):rgb.extend(row[x*4:x*4+3])
        previous=row
    return width,height,bytes(rgb)


def run(args):
    exe,probe,out=args.exe.resolve(),args.probe.resolve(),args.out.resolve()
    if not exe.is_relative_to(ROOT/'.deps') or not exe.is_file() or not probe.is_file():raise ValueError('Require existing project-local Geargrafx and probe')
    if not out.is_relative_to(ROOT/'.local'):raise ValueError('Reference outputs must remain private in .local')
    out.mkdir(parents=True,exist_ok=True);(out/'result.json').write_text('{"result":"incomplete"}\n')
    rom=bytearray([0xEA]*8192);rom[:3]=bytes((0xD4,0x53,1));rom[-2:]=bytes((0,0xE0));image=out/'synthetic-scanline.pce';image.write_bytes(rom)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    started=time.monotonic();checked=[]
    with (out/'process.log').open('wb') as log:
        process=subprocess.Popen([str(exe),'--headless','--portable','--mcp-http','--mcp-http-port',str(port)],cwd=exe.parent,
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        client=Mcp(port)
        try:
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('Reference exited')
                try:info=client.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'pcerecomp-scanline-reference','version':'1'}});break
                except OSError:time.sleep(.05)
            else:raise RuntimeError('Reference startup exceeded budget')
            client.headers['MCP-Protocol-Version']=info['protocolVersion'];client.rpc('notifications/initialized')
            def guard():
                if time.monotonic()-started>180 or (out/'process.log').stat().st_size>1024*1024:raise RuntimeError('Scanline reference exceeded work budget')
            for plan in plans():
                guard();directory=out/plan['id'];directory.mkdir(exist_ok=True)
                client.call('load_media',file_path=str(image));client.call('debug_pause')
                initial=client.call('get_huc6260_status')
                if initial['x'] or initial['y'] or initial['control_reg']!='00':raise RuntimeError('Reference did not reset VCE phase/control')
                ids={a['name']:a['id'] for a in client.call('list_memory_areas')['areas']}
                regs=[0]*20
                for index,value in ((5,plan['cr']),(7,plan['bxr']),(8,plan['byr']),(9,plan['mwr']),(10,0x0202),(11,0x041F),(12,0x0F02),(13,191),(14,64)):regs[index]=value
                for index,value in enumerate(regs):client.call('write_huc6270_register',register=index,value=f'{value:04X}',vdc=1)
                for area,data in zip(('VRAM','SAT','PALETTES'),fixture(plan)):client.call('write_memory',area=ids[area],offset='0000',bytes=data.hex(' '))
                client.call('write_huc6280_register',name='P',value='04');client.call('write_huc6280_register',name='PC',value='E000');client.call('debug_step_into')
                client.call('write_huc6280_register',name='A',value='FF');client.call('debug_step_into');elapsed=24
                def advance(target):
                    nonlocal elapsed
                    guard();code=delay_program(target-elapsed)
                    client.call('write_memory',area=ids['ROM'],offset='0100',bytes=code.hex(' '));client.call('write_huc6280_register',name='PC',value='E100')
                    end=f'{0xE100+len(code):04X}';client.call('debug_run_to_cursor',address=end)
                    for _ in range(100):
                        position=client.call('debug_get_status')
                        if position['paused'] and position['pc']==end:break
                        time.sleep(.01)
                    else:raise RuntimeError('Finite raster delay failed to stop')
                    state=client.call('get_huc6260_status')
                    if state['x']!=target%1365 or state['y']!=(target//1365)%262:raise RuntimeError('Delay/master phase mismatch')
                    elapsed=target
                def capture(n):
                    result=client.rpc('tools/call',{'name':'get_screenshot','arguments':{}})
                    blocks=[b for b in result.get('content',[]) if b.get('type')=='image']
                    if result.get('isError') or len(blocks)!=1 or blocks[0]['mimeType']!='image/png':raise RuntimeError('Missing reference PNG')
                    data=base64.b64decode(blocks[0]['data'],validate=True);(directory/f'gear-{n}.png').write_bytes(data)
                    width,height,rgb=decode_png(data)
                    if (width,height)!=(256,242):raise RuntimeError('Reference viewport changed; require standard unfiltered RGB, 256x242')
                    return rgb[3*256*3:(3+192)*256*3]
                advance(2*FRAME+24);expected=[capture(0)]
                advance(2*FRAME+96*1365+600);client.call('write_memory',area=ids['PALETTES'],offset='0000',bytes=palette(plan,1).hex(' '))
                advance(3*FRAME+24);expected.append(capture(1))
                advance(3*FRAME+80*1365+498);client.call('write_huc6270_register',register=7,value=f'{(plan["bxr"]+13)&1023:04X}',vdc=1)
                advance(4*FRAME+24);expected.append(capture(2))
                advance(4*FRAME+120*1365+600)
                pattern=fixture(plan)[0][0x4000:0x4800]
                client.call('write_memory',area=ids['VRAM'],offset='2000',bytes=bytes(value^255 for value in pattern).hex(' '))
                advance(5*FRAME+24);expected.append(capture(3))
                path=directory/'plan.txt';path.write_text(' '.join(str(plan[k]) for k in ('seed','mwr','bxr','byr','cr'))+'\n',encoding='ascii')
                completed=subprocess.run([str(probe),str(path),str(directory)],capture_output=True,text=True,check=True,timeout=10)
                probe_metadata=json.loads(completed.stdout)
                for n,wanted in enumerate(expected):
                    ppm=(directory/f'local-{n}.ppm').read_bytes();header,shape,maximum,actual=ppm.split(b'\n',3)
                    if (header,shape,maximum)!=(b'P6',b'256 192',b'255') or len(actual)!=len(wanted):raise RuntimeError('Local framebuffer shape mismatch')
                    if actual!=wanted:
                        differences=[i//3 for i in range(0,len(actual),3) if actual[i:i+3]!=wanted[i:i+3]]
                        (out/'failure.json').write_text(json.dumps(dict(plan=plan['id'],frame=n,pixels=len(differences),first=[dict(x=i%256,y=i//256,actual=list(actual[i*3:i*3+3]),expected=list(wanted[i*3:i*3+3])) for i in differences[:16]]),indent=2)+'\n')
                        raise RuntimeError(f'Continuous pixel mismatch: {plan["id"]} frame {n}')
                    if len(set(wanted[i:i+3] for i in range(0,len(wanted),3)))<8:raise RuntimeError('Empty/trivial reference framebuffer')
                if len(set(expected))!=4:raise RuntimeError('Temporal plan did not produce four distinct frames')
                checked.append(dict(id=plan['id'],frames=[hashlib.sha256(x).hexdigest() for x in expected],probe=probe_metadata))
            report=dict(schema=1,result='pass',suite='continuous-video',plans=len(checked),frames=4*len(checked),pixels=256*192*4*len(checked),checked=checked,
                oracle_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
                profile='single VDC, divider4, 262lines, standard RGB, full256x192 active crop of raw256x242 Gear viewport at(0,3)',
                scope='authored background/sprites, map and scroll wrap, 2-bit sprite mode, four distinct frames per plan, midline palette, line-latched BXR and decoded-line VRAM history',
                not_checked=['CPU execution tiers','CPU port-access phases','all timings/modes','collision/overflow IRQ','hardware','retail frames','audio','gameplay'])
            (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/desktop-check/reference/live')
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:print(error,file=sys.stderr);raise SystemExit(1)
