"""Bounded authored digital CDDA samples and settled PSG phase versus Geargrafx.

Creates its own synthetic BIOS/BIN/CUE; never opens retail inputs. Raw CDDA
values are compared by reference LBA/sample identity, not by claiming aligned
resampling/seek phases. PSG checks waveform phase at safe mid-period points;
Gear's MCP does not expose raw PSG or ADPCM decoder PCM.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.reference_geargrafx import Mcp
from scripts.raster_reference import delay_program


def media(out):
    values=(-32768,-1,0,1,4660,32767,-4660)
    raw=b''.join(struct.pack('<h',values[(lba+i)%7]) for lba in range(90) for i in range(1176))
    setup=bytes.fromhex('78 D4 A9 FF 53 01 A9 F8 53 FE')
    bios=bytearray([0xea]*262144);bios[:len(setup)]=setup;bios[8190:8192]=bytes((0,0xe0))
    cue='FILE "pcm.bin" BINARY\n'
    for n,(frame,kind) in enumerate(((0,'MODE1/2352'),(10,'AUDIO'),(60,'MODE1/2352'),(70,'AUDIO')),1):
        cue+=f'  TRACK {n:02} {kind}\n    INDEX 01 00:{frame//75:02}:{frame%75:02}\n'
    files={'pcm.bin':raw,'pcm.cue':cue.encode('ascii'),'syscard.pce':bios}
    for name,data in files.items():
        target=out/name
        if target.exists():raise ValueError('Reference media output must be new')
        target.write_bytes(data)
    return out/'pcm.cue',out/'syscard.pce',{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}


def run(args):
    exe,probe,out=args.exe.resolve(),args.probe.resolve(),args.out.resolve()
    if not exe.is_relative_to(ROOT/'.deps') or not exe.is_file() or not probe.is_file():
        raise ValueError('Require an existing checkout-local portable Geargrafx and compiled PCM probe')
    config=exe.parent/'config.ini'
    if config.exists() or not (exe.parent/'portable.ini').exists():
        raise ValueError('Require unused portable instance with no existing config.ini')
    if out.exists():raise ValueError('Reference output must be a new directory')
    out.mkdir(parents=True)
    image,bios,identities=media(out)
    savedir=out/'isolated-saves';savedir.mkdir()
    report=dict(schema=1,result='incomplete',oracle_exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),authored_inputs=identities)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    started=time.monotonic();process=None
    try:
        config.write_text('[General]\nVersion=999\n[Debug]\nDebug=true\n[Emulator]\nStartPaused=true\nPauseWhenInactive=false\nBackupRAMDirOption=2\nBackupRAMPath='+str(savedir)+'\nSaveFilesDirOption=2\nSaveFilesPath='+str(savedir)+'\nSaveStatesDirOption=2\nSaveStatesPath='+str(savedir)+'\n[Rewind]\nEnabled=false\n')
        with (out/'process.log').open('wb') as log:
            process=subprocess.Popen([str(exe),'--headless','--portable','--mcp-http','--mcp-http-port',str(port)],
                cwd=exe.parent,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            report['pid']=process.pid;client=Mcp(port)
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('Reference exited during startup')
                try:
                    info=client.rpc('initialize',dict(protocolVersion='2025-11-25',capabilities={},clientInfo=dict(name='pcm-reference',version='1')));break
                except OSError:time.sleep(.05)
            else:raise RuntimeError('Reference startup timeout')
            client.headers['MCP-Protocol-Version']=info['protocolVersion'];client.rpc('notifications/initialized')
            client.call('load_bios',file_path=str(bios),type='syscard')
            client.call('load_media',file_path=str(image));client.call('debug_pause')
            client.call('write_huc6280_register',name='PC',value='E000')
            for _ in range(6):client.call('debug_step_into')
            areas={v['name']:v['id'] for v in client.call('list_memory_areas')['areas']}
            def guard():
                if time.monotonic()-started>180 or (out/'process.log').stat().st_size>1024*1024:
                    raise RuntimeError('PCM reference exceeded finite time/output bound')
            def code(data):
                guard()
                if not 0<len(data)<4096:raise ValueError('Authored helper exceeds scratch RAM')
                client.call('write_memory',area=areas['SYSTEM RAM'],offset='1000',bytes=data.hex(' '))
                client.call('write_huc6280_register',name='PC',value='3000')
                endpoint=f'{0x3000+len(data):04X}'
                client.call('debug_run_to_cursor',address=endpoint)
                for _ in range(100):
                    state=client.call('debug_get_status')
                    if state['paused'] and state['pc']==endpoint:return
                    time.sleep(.01)
                raise RuntimeError('Authored PCM helper did not reach its finite endpoint')
            def write(port,value,delay=0):
                code(bytes((0xa9,value,0x8d,port&255,port>>8))+delay_program(delay))
            def advance(ticks):code(delay_program(ticks))
            def begin(lba):
                write(0x1804,2);write(0x1804,0);write(0x1802,0)
                write(0x1800,255,75060)
                for value in (0xd8,1,0,0,0,lba,0,0,0,0):
                    write(0x1801,value);write(0x1802,128);write(0x1802,0,3060)
                for _ in range(16):
                    if client.call('get_cdrom_status')['scsi_phase']=='STATUS':break
                    advance(600000)
                else:raise RuntimeError('CDDA command did not complete seek/status')
                for _ in range(2):write(0x1802,128);write(0x1802,0,1560)
                # Drive command completion and actual PCM playback have
                # separate deadlines. Observe both; do not assume STATUS
                # means the playback-delay interval has elapsed.
                for _ in range(32):
                    status=client.call('get_cdrom_audio_status')
                    if not status['seek_cycles'] and not status['playback_delay_cycles']:break
                    advance(600000)
                else:raise RuntimeError('CDDA playback delay did not settle')
            def expected(kind,a,b):
                result=subprocess.run([str(probe),kind,str(a),str(b)],capture_output=True,text=True,check=True,timeout=5)
                return json.loads(result.stdout)
            samples=[]
            for start,count in ((10,20),(0,8),(70,20),(60,8)):
                begin(start)
                for _ in range(count):
                    advance(17280)
                    value=client.call('get_cdrom_audio_status')
                    if value['seek_cycles'] or value['playback_delay_cycles'] or value['state']!='PLAYING':
                        (out/'failure.json').write_text(json.dumps(dict(start=start,status=value),indent=2)+'\n')
                        raise RuntimeError('Reference CDDA sample was not settled playing')
                    # Status points at the NEXT frame; raw samples are the
                    # preceding generated stereo pair, including sector wrap.
                    frame=(value['current_sample']+587)%588
                    lba=value['current_lba']-(value['current_sample']==0)
                    actual=dict(left=value['left_sample'],right=value['right_sample'])
                    wanted=expected('cdda',lba,frame)
                    if actual!=wanted:
                        (out/'failure.json').write_text(json.dumps(dict(lba=lba,frame=frame,actual=actual,expected=wanted,status=value),indent=2)+'\n')
                        raise RuntimeError('Reference raw CDDA PCM differs from authored sector samples')
                    samples.append(dict(lba=lba,frame=frame,**actual))
            phases=[]
            for frequency in (64,127,512):
                for port,value in ((0x800,0),(0x802,frequency&255),(0x803,frequency>>8),
                                   (0x804,0xdf),(0x806,31),(0x804,0x9f)):
                    write(port,value)
                # A half-period margin avoids claiming bus-access-phase
                # equality. Later points remain one period apart.
                ticks=(frequency//2)*6
                for index in range(8):
                    advance(ticks if index==0 else frequency*6)
                    elapsed=ticks+index*frequency*6
                    actual=client.call('get_psg_status')['channels'][0]['wave_index']
                    wanted=expected('psg-phase',frequency,elapsed)['wave_index']
                    if actual!=wanted:raise RuntimeError('Reference settled PSG waveform phase differs')
                    phases.append(dict(frequency=frequency,elapsed=elapsed,wave_index=actual))
            report.update(result='pass',oracle=info['serverInfo'],cdda_samples=samples,psg_phases=phases,
                scope='Authored raw CDDA stereo samples selected by observed LBA/frame identity; data-track silence; settled PSG waveform phase',
                not_checked=['CHD compression in Gear (CUE reference)','exact sample-clock/seek alignment','raw PSG PCM','raw ADPCM decoder PCM','noise/LFO internals unavailable via MCP','analog filtering','mixed/resampled PCM','audio device','retail gameplay','hardware'])
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        config.unlink(missing_ok=True)
        report.update(config_restored=not config.exists(),child_stopped=process is None or process.poll() is not None,
                      elapsed_seconds=time.monotonic()-started)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cdda_samples','psg_phases')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    try:run(parser.parse_args())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
