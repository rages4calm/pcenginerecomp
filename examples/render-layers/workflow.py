"""Build or qualify immutable-scene rendering helpers using an authored HuCard."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from pcerecomp.project import ABI,sha256,source_identity
from examples.widescreen.workflow import session


def require(value,message):
    if not value:raise ValueError(message)


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def generate(output):
    spec=importlib.util.spec_from_file_location('render_layers_fixture',Path(__file__).with_name('fixture.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.emit_fixture(output)


def expected(width,sequence,*,enhanced):
    """Independent literal pixel expectation, not a call to C++ helpers."""
    result=bytearray();camera=-((width-256)//2)
    for y in range(240):
        for x in range(width):
            world=x+camera;opaque=(world%8)%2==(0 if y%8<4 else 1)
            color=(255,0,0) if opaque else (0,0,255)
            hero=80<=world<96 and 80<=y<96
            hidden=120<=world<136 and 80<=y<96
            visible=hero or (hidden and not opaque)
            if hero:color=(0,255,0)
            elif hidden and not opaque:color=(255,255,255)
            if enhanced:
                if not visible and opaque:color=(255,0,16+(sequence%4)*4)
                if hidden and 120<=world<124:color=(255,255,255)
            result.extend(color)
    return bytes(result)


def window_pixels(frame,width,height,window_width,window_height):
    # Tests deliberately select a 480-line target: all source scenes are 240
    # lines and use an exact nearest-neighbour scale of two, without rounding.
    require(window_height==480 and window_width>=2*width,'Invalid authored capture extent')
    result=bytearray(window_width*window_height*3);left=(window_width-2*width)//2
    for y in range(height):
        row=bytearray()
        for x in range(width):row.extend(frame[(y*width+x)*3:(y*width+x+1)*3]*2)
        start=((y*2)*window_width+left)*3
        result[start:start+len(row)]=row
        result[start+window_width*3:start+window_width*3+len(row)]=row
    return bytes(result)


def qualify(generated,binary,output):
    generated=Path(generated).resolve(strict=True);binary=Path(binary).resolve(strict=True)
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();tool=source_identity(ROOT)
    sources=[Path(__file__),Path(__file__).with_name('fixture.py'),Path(__file__).with_name('scene.cpp'),
             Path(__file__).with_name('CMakeLists.txt'),ROOT/'runtime/include/pce/port_render.hpp']
    inputs={str(path):sha256(path) for path in sources}
    inputs.update({str(path):sha256(path) for path in generated.rglob('*') if path.is_file()})
    inputs.update({str(path):sha256(path) for path in binary.parent.iterdir() if path.is_file() and path.suffix.lower() in ('.exe','.dll')})
    # This is the supported CMake PORT_RENDERER example, not a project.build
    # audited cache producer. Bind its explicit compiler and configure receipt.
    cache=binary.parent/'CMakeCache.txt'
    require(cache.is_file(),'Supply the CMake target from its build root')
    inputs[str(cache)]=sha256(cache)
    text=cache.read_text(encoding='utf-8')
    match=re.search(r'^CMAKE_CXX_COMPILER:[^=]+=(.+)$',text,re.M)
    require(match is not None,'CMake did not record its C++ compiler')
    compiler=Path(match[1].strip()).resolve(strict=True);inputs[str(compiler)]=sha256(compiler)
    identity=dict(schema=1,format='pce-authored-render-layer-context-1',tool=tool,files=inputs)
    context=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    write(output/'context.json',identity)
    checkpoints=output/'checkpoints';checkpoints.mkdir();runs=output/'runs';runs.mkdir()
    reports=output/'inspections';reports.mkdir()
    environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_RENDER_DRIVER='software')
    report=dict(schema=1,passed=False,tool=tool,context=context,input_bindings=inputs,
        producer='CMake PORT_RENDERER example; not an audited project.build/cache receipt',
        scope='Authored scene reconstruction, host-only layers and software presentation; no retail, hardware, GPU or physical-audio claim')
    card=generated/'authored-card.pce'

    def command(view,*,restore=None,writes=False):
        argv=[str(binary),'--hucard-reset','base',str(card),'50000000','100000000','native',
            '--rom-header','none','--rom-encoding','linear','--audio-output','on','--audio-profile','raw',
            '--audio-rate','44100','--audio-timing','gear','--video-output','continuous',
            '--dev-port','0','--dev-start-paused','on','--dev-reference','on',
            '--dev-memory-write','on' if writes else 'off','--checkpoint-dir',str(checkpoints),
            '--checkpoint-context',context,'--window-scale','2','--hidden','on','--unthrottled','on',
            '--port-view',view,'--display-mode','square','--display-filter','nearest','--display-shader','off',
            '--wall-seconds','90']
        if restore is not None:argv+=['--checkpoint-load',restore]
        return argv

    def inspect(cp,label):
        argv=command('guest')+['--checkpoint-report',cp.name,'--checkpoint-report-sha',sha256(cp)]
        result=subprocess.run(argv,env=environment,stdin=subprocess.DEVNULL,capture_output=True,timeout=30,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (reports/(label+'.stdout')).write_bytes(result.stdout);(reports/(label+'.stderr')).write_bytes(result.stderr)
        require(result.returncode==0 and b'PCE_DEV_PORT=' not in result.stderr,'Offline typed source inspection failed')
        value=json.loads(result.stdout)
        require(value['format']=='pce-checkpoint-inspection-1' and value['runtime_abi']==ABI
                and value['diagnostic_only'] is True,'Wrong typed inspection contract')
        require(value['native_steps']==value['interpreter_steps']==0 and all(value[key] is False
                for key in ('executed','restored','network_started','presentation_started')),
                'Inspection performed guest work or started a live host')
        require(value['checkpoint_sha256']==sha256(cp),'Inspection source differs')
        return value

    def state(client):
        status=client.call('status');meta,rgb=client.capture('guest');ram=client.read_memory_block(0x1F0000,8192)
        require(status['paused'] and meta['width']==256 and meta['height']==240,'Unexpected guest frame geometry')
        require(rgb==expected(256,status['frame'],enhanced=False),'Original VDC image differs from independent scene')
        audio=status['host']['audio_output']
        digital={key:audio[key] for key in ('enabled','sample_rate','channels','frames','psg_nonzero',
            'adpcm_nonzero','cdda_nonzero','mixed_nonzero','peak','pcm_hash','discarded_frames','wav_frames','wav_truncated')}
        return dict(frame=status['frame'],ticks=status['ticks'],rgb_sha256=hashlib.sha256(rgb).hexdigest(),
            ram_sha256=hashlib.sha256(ram).hexdigest(),audio=digital,
            pc=status['host']['pc'],cpu=status['host']['cpu'])

    def capture_present(client,width,*,fallback=False):
        metadata,rgb=client.capture('present');status=client.call('status')
        scene=expected(256 if fallback else width,status['frame'],enhanced=not fallback)
        wanted=window_pixels(scene,256 if fallback else width,240,metadata['width'],metadata['height'])
        require(rgb==wanted,'Software presentation differs from literal helper/effect expectation')
        return dict(size=[metadata['width'],metadata['height']],sha256=hashlib.sha256(rgb).hexdigest())

    def traces(role):
        text=(runs/(role+'.stderr')).read_text(encoding='utf-8')
        return [json.loads(line.partition('=')[2]) for line in text.splitlines() if line.startswith('PCE_RENDER_LAYER=')]

    try:
        report['runs']={};report['presentations']={};report['typed']={}
        # Independent cold native/repeat/reference runs all use the same binary
        # and recipe. The reference capability is enabled in every source.
        for role,reference in (('native',False),('repeat',False),('reference',True)):
            argv=command('4:3');write(runs/(role+'.launch.json'),argv)
            with session(argv,runs,role,environment) as client:
                client.advance(8,reference=reference);start=state(client)
                client.call('save_checkpoint',name=role+'-start.pcec')
                report['presentations'][role]=capture_present(client,256)
                client.advance(3,reference=reference);end=state(client)
                client.call('save_checkpoint',name=role+'-end.pcec')
            final=json.loads((runs/(role+'.stdout')).read_text())
            require(final['stop']=='dev_quit' and final['guard_misses']==0,'Authored host faulted or missed guards')
            require(final['native_steps']==0 if reference else final['interpreter_steps']==0,'Wrong execution tier')
            report['runs'][role]=dict(start=start,end=end,native=final['native_steps'],interpreted=final['interpreter_steps'],traces=traces(role))
            require(any(row['exact'] for row in report['runs'][role]['traces']),'No exact reconstruction was accepted')
            report['typed'][role]=inspect(checkpoints/(role+'-end.pcec'),role)
        require(report['runs']['native']['start']==report['runs']['repeat']['start'],'Cold repeat source state differs')
        require((checkpoints/'native-end.pcec').read_bytes()==(checkpoints/'repeat-end.pcec').read_bytes(),'Native repeat checkpoint bytes differ')
        require(report['typed']['native']['host_sha256']==report['typed']['reference']['host_sha256']
                and report['typed']['native']['tier_neutral_core_sha256']==report['typed']['reference']['tier_neutral_core_sha256'],
                'Native/reference complete typed state differs beyond four tier counters')
        require(report['typed']['native']['core_sha256']!=report['typed']['reference']['core_sha256'],'Reference accounting was hidden')
        baseline=report['runs']['native'];end_sha=sha256(checkpoints/'native-end.pcec')
        variants=(('narrow','4:3',256),('wide','16:9',426),('ultrawide','21:9',560),('adaptive','auto',420))
        for role,view,width in variants:
            argv=command(view,restore='native-start.pcec');write(runs/(role+'.launch.json'),argv)
            with session(argv,runs,role,environment) as client:
                require(state(client)==baseline['start'],'Own checkpoint restore changed original state')
                client.call('resize_window',width=width*2,height=480)
                before=state(client);first=capture_present(client,width);second=capture_present(client,width)
                require(first==second and state(client)==before,'Paused rendering changed image or guest state')
                if view=='auto':
                    client.call('resize_window',width=1280,height=480)
                    report['presentations'][role+'-resized']=capture_present(client,640)
                    require(state(client)==before,'Adaptive resize changed original guest state')
                    client.call('resize_window',width=width*2,height=480)
                report['presentations'][role]=capture_present(client,width)
                client.call('save_checkpoint',name=role+'-paused.pcec')
                require(sha256(checkpoints/(role+'-paused.pcec'))==sha256(checkpoints/'native-start.pcec'),'Paused rendering changed checkpoint bytes')
                client.advance(3);require(state(client)==baseline['end'],'Presentation changed forward guest execution')
                client.call('save_checkpoint',name=role+'-end.pcec')
            require(sha256(checkpoints/(role+'-end.pcec'))==end_sha,'Restored presentation changed complete ending state')
            rows=traces(role);require(any(row['epoch']>=1 and row['exact'] and not row['interpolation'] for row in rows),
                'Restored presentation did not invalidate temporal admission')
            report['runs'][role]=dict(traces=rows,checkpoint_sha256=end_sha)
        # Deliberately assisted consumer-only mismatch: no guest VRAM/palette is
        # changed. Test fallback, then clear the marker and recover exactness.
        role='fallback';argv=command('auto',restore='native-start.pcec',writes=True)
        with session(argv,runs,role,environment) as client:
            client.call('resize_window',width=840,height=480);before=state(client)
            client.write_memory(0x1F0042,b'\x01',b'\x00')
            client.call('resize_window',width=842,height=480)
            capture_present(client,421,fallback=True)
            require(client.capture('guest')[1]==expected(256,before['frame'],enhanced=False),'Fallback assist changed original RGB')
            client.write_memory(0x1F0042,b'\x00',b'\x01')
            client.call('resize_window',width=840,height=480);capture_present(client,420)
            after=state(client);require(after==before,'Cleared assisted marker changed original machine observations')
            client.call('save_checkpoint',name='fallback-assisted.pcec')
        rows=traces(role);require(any(not row['exact'] for row in rows) and any(row['exact'] and row['epoch']>=3 for row in rows),
            'Mismatch did not fail closed and recover after epoch invalidation')
        assisted=inspect(checkpoints/'fallback-assisted.pcec','fallback-assisted')
        start_inspection=inspect(checkpoints/'native-start.pcec','native-start')
        require(assisted['host_sha256']!=start_inspection['host_sha256'],'Assisted HOST counters were silently normalized')
        report['runs'][role]=dict(assisted=True,traces=rows,typed=assisted)
        require(source_identity(ROOT)==tool and all(sha256(Path(path))==digest for path,digest in inputs.items()),'Producer inputs changed')
        report.update(passed=True,elapsed_seconds=time.monotonic()-started,owned_hosts=0,
                      exact_reconstruction=True,presentation_changes_guest_state=False)
    except Exception as error:
        report['error']=dict(type=type(error).__name__,message=str(error));raise
    finally:write(output/'receipt.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('generate').add_argument('generated',type=Path)
    q=sub.add_parser('qualify');q.add_argument('generated',type=Path);q.add_argument('--binary',required=True,type=Path);q.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    if args.action=='generate':print(json.dumps(generate(args.generated),indent=2))
    else:print(json.dumps(dict(passed=qualify(args.generated,args.binary,args.out)['passed']),indent=2))
