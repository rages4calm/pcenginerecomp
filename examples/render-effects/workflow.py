"""Qualify completed-frame timing and CPU display effects without GPU hardware."""
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


def layers_module():
    source=ROOT/'examples/render-layers/workflow.py'
    spec=importlib.util.spec_from_file_location('authored_render_layer_workflow',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def row(width,sequence):
    colors=((240,0,0),(0,160,0),(0,0,80),(0,0,0))
    return bytes(c for x in range(width) for c in colors[(x+sequence)%4])


def effected_row(width,sequences,softness,persistence,initial=None):
    """Independent literal integer oracle over documented diagnostic swatches."""
    previous=initial
    require(initial is None or len(initial)==width*3,'Wrong bounded oracle history')
    for sequence in sequences:
        source=row(width,sequence);result=bytearray(len(source))
        for x in range(width):
            for c in range(3):
                at=x*3+c;center=source[at]
                left=source[max(x-1,0)*3+c];right=source[min(x+1,width-1)*3+c]
                blur=(left+2*center+right+2)//4
                value=(center*(100-softness)+blur*softness+50)//100
                if previous is not None:value=max(value,previous[at]*persistence//100)
                result[at]=value
        previous=bytes(result)
    require(previous is not None,'At least one completed sequence required')
    return previous


def qualify(generated,binary,output):
    generated=Path(generated).resolve(strict=True);binary=Path(binary).resolve(strict=True)
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();tool=source_identity(ROOT);layers=layers_module()
    sources=[Path(__file__),Path(__file__).with_name('scene.cpp'),Path(__file__).with_name('CMakeLists.txt'),
        ROOT/'examples/render-layers/workflow.py',ROOT/'examples/render-layers/fixture.py',
        ROOT/'examples/widescreen/workflow.py',ROOT/'scripts/dev_client.py',ROOT/'scripts/dev_journal.py']
    inputs={str(path):sha256(path) for path in sources}
    inputs.update({str(path):sha256(path) for path in generated.rglob('*') if path.is_file()})
    inputs.update({str(path):sha256(path) for path in binary.parent.iterdir() if path.is_file() and path.suffix.lower() in ('.exe','.dll')})
    cache=binary.parent/'CMakeCache.txt';require(cache.is_file(),'Supply the CMake build-root binary')
    inputs[str(cache)]=sha256(cache)
    match=re.search(r'^CMAKE_CXX_COMPILER:[^=]+=(.+)$',cache.read_text(encoding='utf-8'),re.M)
    require(match is not None,'Compiler missing from CMake cache')
    compiler=Path(match[1].strip()).resolve(strict=True);inputs[str(compiler)]=sha256(compiler)
    context_source=dict(schema=1,format='pce-authored-render-effects-context-1',tool=tool,files=inputs)
    context=hashlib.sha256(json.dumps(context_source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    write(output/'context.json',context_source)
    checkpoints=output/'checkpoints';checkpoints.mkdir();runs=output/'runs';runs.mkdir()
    inspections=output/'inspections';inspections.mkdir()
    environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_RENDER_DRIVER='software')
    report=dict(schema=1,passed=False,tool=tool,context=context,input_bindings=inputs,
        producer='Authored CMake PORT_RENDERER; not a Python audited-cache package',
        scope='Software effects, completed-frame timing and authored native/reference/checkpoint routes. No retail, hardware, physical GPU/audio or historical layer-recovery claim.')
    card=generated/'authored-card.pce';rom=card.read_bytes()

    def command(*,restore=None,pristine=False):
        argv=[str(binary),'--hucard-reset','base',str(card),'50000000','100000000','native',
            '--rom-header','none','--rom-encoding','linear','--audio-output','on','--audio-profile','raw',
            '--audio-rate','44100','--audio-timing','gear','--video-output','continuous',
            '--dev-port','0','--dev-start-paused','on','--dev-reference','on',
            '--checkpoint-dir',str(checkpoints),'--checkpoint-context',context,
            '--window-scale','2','--hidden','on','--unthrottled','on','--port-view','auto',
            '--display-mode','square','--display-filter','nearest','--display-shader','off',
            '--display-softness','0' if pristine else '50','--display-persistence','0' if pristine else '50',
            '--wall-seconds','90']
        if restore is not None:argv+=['--checkpoint-load',restore]
        return argv

    def inspect(name,label):
        cp=checkpoints/name
        result=subprocess.run(command()+['--checkpoint-report',name,'--checkpoint-report-sha',sha256(cp)],
            env=dict(environment,SDL_VIDEODRIVER='deliberately-invalid',SDL_AUDIODRIVER='deliberately-invalid'),
            stdin=subprocess.DEVNULL,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (inspections/(label+'.stdout')).write_bytes(result.stdout);(inspections/(label+'.stderr')).write_bytes(result.stderr)
        require(result.returncode==0 and b'PCE_DEV_PORT=' not in result.stderr,'Offline typed report failed')
        value=json.loads(result.stdout)
        require(value['format']=='pce-checkpoint-inspection-1' and value['runtime_abi']==ABI
            and value['diagnostic_only'] is True and value['checkpoint_sha256']==sha256(cp),'Wrong typed report')
        require(value['native_steps']==value['interpreter_steps']==0 and not any(value[k] for k in
            ('executed','restored','network_started','presentation_started')),'Offline report performed work')
        return value

    def state(client):
        status=client.call('status');metadata,rgb=client.capture('guest')
        ram=client.read_memory_block(0x1F0000,8192)
        require(status['paused'] and (metadata['width'],metadata['height'])==(256,240),'Wrong paused guest image')
        require(rgb==layers.expected(256,status['frame'],enhanced=False),'Guest image differs from authored VDC expectation')
        audio=status['host']['audio_output']
        return dict(frame=status['frame'],ticks=status['ticks'],frame_ticks=metadata['frame_ticks'],
            cpu=status['host']['cpu'],ram_sha256=hashlib.sha256(ram).hexdigest(),
            rgb_sha256=hashlib.sha256(rgb).hexdigest(),audio={k:audio[k] for k in
            ('enabled','sample_rate','channels','frames','psg_nonzero','adpcm_nonzero','cdda_nonzero',
             'mixed_nonzero','peak','pcm_hash','discarded_frames','wav_frames','wav_truncated')})

    def effect_status(client):
        return client.call('status')['host']['desktop']['presentation_effects']

    def capture(client,width,sequences,*,pristine=False):
        metadata,pixels=client.capture('present')
        expected_row=effected_row(width,sequences,0 if pristine else 50,0 if pristine else 50)
        expected=layers.window_pixels(expected_row*240,width,240,metadata['width'],metadata['height'])
        require(pixels==expected,'CPU effect RGB differs from independent integer expectation')
        return dict(width=width,size=[metadata['width'],metadata['height']],sha256=hashlib.sha256(pixels).hexdigest(),
            sequences=list(sequences),settings=[0,0] if pristine else [50,50],effect=effect_status(client))

    def scalar(client,reference):
        before=state(client);cpu=before['cpu'];pc=cpu['pc'];offset=pc-0xE000
        require(0<=offset<len(rom)-2,'CPU left authored loop bank')
        opcode=rom[offset]
        # Exact successors for the fixture's five wait-loop instruction forms.
        # Conditional direction is known from pre-instruction CPU P, not guessed.
        if opcode==0xAD:target=pc+3
        elif opcode in (0x29,0xE6):target=pc+2
        elif opcode in (0xF0,0x80):
            relative=rom[offset+1];relative-=256 if relative>=128 else 0
            target=pc+2+(relative if opcode==0x80 or cpu['p']&2 else 0)
        else:raise ValueError('Unexpected authored wait-loop opcode')
        status=client.run_until(target,cpu['mpr'],instructions=1,ticks=1000,reference=reference)
        require(status['instruction_window']['state']=='reached','Scalar successor was not reached')
        after=state(client)
        require(after['frame']==before['frame'] and after['frame_ticks']==before['frame_ticks']
            and after['ticks']>before['ticks'] and after['ticks']>after['frame_ticks'],
            'Scalar instruction did not establish distinct CPU/completed-frame time')
        work=sum(after['cpu'][k]-before['cpu'][k] for k in ('native_steps','interpreter_steps'))
        require(work==1,'Instruction-boundary control did not retire exactly one instruction')
        return dict(before=before,after=after,window=status['instruction_window'])

    def traces(role):
        return [json.loads(line.partition('=')[2]) for line in (runs/(role+'.stderr')).read_text(encoding='utf-8').splitlines()
            if line.startswith('PCE_RENDER_EFFECT=')]

    def paused_checks(client,role,start,*,pristine=False,restored=False):
        sequence=start['frame'];soft=0 if pristine else 50;persist=0 if pristine else 50
        # Bound unknown initial RGB by0..255 and independently prove nine
        # exact swatch frames erase it. Then prove this periodic source's
        # four-frame suffix agrees with that complete bounded calculation.
        if not pristine:
            four=effected_row(256,range(sequence-3,sequence+1),soft,persist)
            known=range(sequence-8,sequence+1)
            lower=effected_row(256,known,soft,persist,bytes(256*3))
            upper=effected_row(256,known,soft,persist,bytes([255])*(256*3))
            require(four==lower==upper,'Authored bounded convergence proof failed')
        first=capture(client,256,[sequence] if restored else range(sequence-8,sequence+1),pristine=pristine)
        require(capture(client,256,[sequence] if restored else range(sequence-8,sequence+1),pristine=pristine)==first,
            'Repeated screenshot advanced effect history')
        client.call('resize_window',width=840,height=480)
        wide=capture(client,420,[sequence],pristine=pristine)
        require(capture(client,420,[sequence],pristine=pristine)==wide,'Paused wide redraw changed pixels')
        status=effect_status(client)
        require(status['sequence']==sequence and status['completed_ticks']==start['frame_ticks'],
            'Resize substituted current CPU time for completed-frame time')
        client.call('resize_window',width=512,height=480)
        reset=capture(client,256,[sequence],pristine=pristine)
        require(state(client)==start,'Paused screenshots/resize changed guest state')
        name=role+'-paused.pcec';client.call('save_checkpoint',name=name)
        require((checkpoints/name).read_bytes()==(checkpoints/(role+'-start.pcec')).read_bytes(),
            'Paused redraw/resize changed complete checkpoint bytes')
        return dict(first=first,wide=wide,reset=reset)

    try:
        report['runs']={};report['typed']={}
        require(effected_row(4,[0],50,0)==bytes([210,20,0,30,120,10,0,20,60,0,0,10]),
            'Independent four-pixel softness oracle changed')
        require(effected_row(4,[0,1],50,50)==bytes([105,140,10,15,60,60,30,10,30,210,0,5]),
            'Independent four-pixel persistence oracle changed')
        report['literal_four_pixel_oracles']=2
        for role,reference,pristine in (('native',False,False),('repeat',False,False),('reference',True,False),('pristine',False,True)):
            argv=command(pristine=pristine);write(runs/(role+'.launch.json'),argv)
            with session(argv,runs,role,environment) as client:
                client.advance(12,reference=reference);step=scalar(client,reference);start=step['after']
                client.call('save_checkpoint',name=role+'-start.pcec')
                presentations=paused_checks(client,role,start,pristine=pristine)
                client.advance(1,reference=reference)
                presentations['next']=capture(client,256,[start['frame'],start['frame']+1],pristine=pristine)
                client.advance(2,reference=reference);end=state(client)
                require(effected_row(256,range(start['frame'],end['frame']+1),50,50)==
                    effected_row(256,range(end['frame']-8,end['frame']+1),50,50),
                    'Calculated three-frame suffix did not converge to known prior history')
                presentations['end']=capture(client,256,range(start['frame'],end['frame']+1),pristine=pristine)
                client.call('save_checkpoint',name=role+'-end.pcec')
            final=json.loads((runs/(role+'.stdout')).read_text());rows=traces(role)
            require(final['stop']=='dev_quit' and final['guard_misses']==0,'Host fault or source guard miss')
            require(final['native_steps']==0 if reference else final['interpreter_steps']==0,'Wrong execution tier')
            require(any(r['exact'] and r['guest_ticks']==start['ticks'] and r['completed_ticks']==start['frame_ticks']
                for r in rows),'Callback did not expose frozen completed time after partial-frame CPU work')
            require(all(any(r['frame']==frame and r['exact'] for r in rows) for frame in range(4,13)),
                'Swatch history lacks independently reconstructed source frames')
            report['runs'][role]=dict(start=start,end=end,scalar=step,presentations=presentations,traces=rows,
                native=final['native_steps'],interpreted=final['interpreter_steps'])
            report['typed'][role]=inspect(role+'-end.pcec',role)
        for role in ('repeat','pristine'):
            for boundary in ('start','end'):
                require((checkpoints/f'{role}-{boundary}.pcec').read_bytes()==(checkpoints/f'native-{boundary}.pcec').read_bytes(),
                    'Default/effected native complete checkpoints differ')
        native=report['typed']['native'];reference=report['typed']['reference']
        require(native['host_sha256']==reference['host_sha256'] and
            native['tier_neutral_core_sha256']==reference['tier_neutral_core_sha256'] and
            native['core_sha256']!=reference['core_sha256'],'Complete native/reference tier projection differs')
        for role in ('restored','restored-repeat'):
            argv=command(restore='native-start.pcec');write(runs/(role+'.launch.json'),argv)
            with session(argv,runs,role,environment) as client:
                start=state(client);require(start==report['runs']['native']['start'],'Own restore changed original state')
                client.call('save_checkpoint',name=role+'-start.pcec')
                presentations=paused_checks(client,role,start,restored=True)
                require(presentations['first']['sha256']!=report['runs']['native']['presentations']['first']['sha256'],
                    'Expected transient history loss was hidden at restore')
                client.advance(1);presentations['next']=capture(client,256,[start['frame'],start['frame']+1])
                client.advance(2);end=state(client)
                presentations['end']=capture(client,256,range(start['frame'],end['frame']+1))
                client.call('save_checkpoint',name=role+'-end.pcec')
            require(end==report['runs']['native']['end'],'Restored suffix guest state differs')
            require((checkpoints/(role+'-end.pcec')).read_bytes()==(checkpoints/'native-end.pcec').read_bytes(),
                'Restored suffix complete checkpoint differs')
            require(presentations['end']['sha256']==report['runs']['native']['presentations']['end']['sha256'],
                'Independently calculated restored visual convergence differs')
            rows=traces(role);require(any(r['epoch']>=1 and r['exact'] and not r['interpolation'] for r in rows),
                'Restored callback failed to invalidate history')
            report['runs'][role]=dict(start=start,end=end,presentations=presentations,traces=rows)
        require(source_identity(ROOT)==tool and all(sha256(Path(p))==h for p,h in inputs.items()),'Frozen producer changed')
        report.update(passed=True,elapsed_seconds=time.monotonic()-started,owned_hosts=0,
            guest_unchanged_by_effects=True,transient_restore_loss_expected=True,
            complete_suffix_checkpoints_identical=True,software_pixel_oracle=True)
    except Exception as error:
        report['error']=dict(type=type(error).__name__,message=str(error));raise
    finally:write(output/'receipt.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('generate').add_argument('generated',type=Path)
    q=sub.add_parser('qualify');q.add_argument('generated',type=Path);q.add_argument('--binary',required=True,type=Path);q.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    if args.action=='generate':print(json.dumps(layers_module().generate(args.generated),indent=2))
    else:print(json.dumps(dict(passed=qualify(args.generated,args.binary,args.out)['passed']),indent=2))
