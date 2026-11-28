"""Authored last-track CDBs through native/reference TCP and own checkpoints."""
import argparse,copy,hashlib,importlib.util,json,os,subprocess,sys,time,tomllib,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('leadout_fixture',Path(__file__).with_name('fixture.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from pcerecomp import project,prepare
from pcerecomp.history import compose_history
from pcerecomp.capture import load_capture
from pcerecomp.checkpoint_inspection import _command,_runtime_receipt
from examples.widescreen.workflow import session

def require(value,message):
    if not value:raise ValueError(message)
def sha(path):return project.sha256(Path(path))
def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,indent=2);stream.write('\n')
def sources():return {p.relative_to(ROOT).as_posix():sha(p) for p in (Path(__file__),Path(__file__).with_name('fixture.py'),ROOT/'examples/live-overlays/fixture.py')}
ENV=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_RENDER_DRIVER='software')

def create(out):
    out.mkdir(parents=True,exist_ok=False);media=fixture.create_media(out)
    write(out/'seed.json',dict(format='pce-declared-boot-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(kind='system-card',profile='standard',sha256=sha(media['bios'])),
        roots=[dict(pc=0xE200,mpr=[0]*8,selector=0,source_offsets=[512])]))
    recipe=dict(schema=1,format=prepare.FORMAT,name='authored-cdda-leadout',module=dict(kind='declared',path='seed.json',partition_layout='shared',partition_size=1024),
        boot=dict(mode='system-card-reset',profile='standard'),bios=dict(path=media['bios'].name),disc=dict(path=media['disc'].name),toc=dict(path=media['toc'].name),
        runtime=dict(tier='hybrid',video='continuous',audio='on',audio_profile='raw',audio_rate=44100,audio_timing='gear',
            cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),limits=dict(steps=100000000,ticks=200000000,wall_seconds=90))
    (out/'bootstrap.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    files={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}
    receipt=dict(tool=project.source_identity(ROOT),sources=sources(),files=files,track_count=25,last_track_lba=50,leadout_lba=52)
    write(out/'creation.json',receipt);return receipt

def inputs(out):
    original=json.loads((out/'creation.json').read_text())
    require(original['tool']==project.source_identity(ROOT) and original['sources']==sources(),'SDK/example changed; use a new proof')
    require(all(sha(out/name)==value for name,value in original['files'].items()),'Original authored media/recipe changed')
    return original

def projection(status,*,restored=False):
    result=copy.deepcopy(status);result.pop('id');host=result['host'];host.pop('execution_policy',None);host.pop('checkpoint',None)
    host['retired_steps']=host.pop('native_steps')+host.pop('interpreter_steps')
    audio=host.get('audio_output',{});audio.pop('host',None)
    if restored:
        audio.pop('wav_frames',None)
        host.get('desktop',{}).get('presentation_effects',{}).pop('epoch',None)
    return result

def run(out,name,descriptor,build,mode,*,reference,restore=None):
    directory=out/name;directory.mkdir();checkpoints=directory/'checkpoints';checkpoints.mkdir();wav=directory/'audio.wav'
    if restore:
        original=restore[0]/restore[1];raw=original.read_bytes()
        (checkpoints/restore[1]).write_bytes(raw)
        require(sha(original)==sha(checkpoints/restore[1]),'Same-producer checkpoint copy changed')
    launch=project.prepare_launch(descriptor,build,dev_port=0,start_paused=True,memory_write=True,reference_enabled=True,
        checkpoint_dir=checkpoints,checkpoint_load=restore[1] if restore else None,
        code_capture=directory/'capture.jsonl',capture_limit=4096,capture_profile='extended')
    write(directory/'launch.json',launch)
    command=launch['command']+['--hidden','on','--unthrottled','on','--audio-out',str(wav)]
    receipt=dict(passed=False,mode=mode,reference=reference,restored=restore is not None,stages=[])
    def sample(client,label):
        state=client.call('status');ram=client.read_memory_block(0x1F0000,8192);meta,rgb=client.capture('guest')
        later=client.call('status');require(projection(state,restored=restore is not None)==projection(later,restored=restore is not None),'Paused observation advanced')
        row=dict(label=label,status=state,wram_sha256=hashlib.sha256(ram).hexdigest(),rgb_sha256=hashlib.sha256(rgb).hexdigest(),
                 extent=[meta['width'],meta['height']]);receipt['stages'].append(row)
        require(ram[2]==mode and ram[0] in (1,2),'Guest control/data marker differs')
        return state,ram
    def wait(client,phase):
        for _ in range(80):
            if client.read_memory(0x1F0000,1)[0]==phase:return
            client.advance(1,reference=reference)
        raise ValueError('Authored firmware did not reach phase '+str(phase))
    try:
        with session(command,directory,'host',ENV) as client:
            initial=client.call('status');receipt['initial']=initial
            if not restore:
                client.write_memory(0x1F0002,bytes((mode,)),b'\0');wait(client,1)
                queued,_=sample(client,'queued')
                audio=queued['host']['cd_audio'];require(audio['stop_lba']==51,'D9 leadout did not clamp to final sector')
                require(audio['stop_mode']==(1 if mode==1 else 2 if mode==2 else 0),'D9 stop mode differs')
                receipt['queued_checkpoint']=client.call('save_checkpoint',name='queued.pcec')['checkpoint']
            client.advance(30,reference=reference)
            played,ram=sample(client,'played')
            audio=played['host']['cd_audio'];require(audio['stop_lba']==51,'Retained leadout end differs')
            if mode==1:
                require(audio['state']==0 and audio['sectors_played']>=4,'Loop mode did not wrap within last track')
            else:
                require(audio['state']==3,'End mode did not stop at leadout')
                client.write_memory(0x1F0001,b'\1',b'\0');wait(client,2)
                _,ram=sample(client,'drained');require(ram[0x10:0x12]==bytes(2),'GOOD/status/message did not drain')
            receipt['end_checkpoint']=client.call('save_checkpoint',name='end.pcec')['checkpoint']
            final=client.call('status');receipt['final']=final
            receipt['work']=dict(native=final['host']['native_steps']-initial['host']['native_steps'],
                interpreted=final['host']['interpreter_steps']-initial['host']['interpreter_steps'])
            require(receipt['work']['native']==0 and receipt['work']['interpreted']>0 if reference else
                    receipt['work']['native']>0 and receipt['work']['interpreted']==0,'Unexpected execution tier')
        cap,digest=load_capture(directory/'capture.jsonl')
        require(cap['complete'] and not cap['dropped_instructions'] and not cap['unreadable_instructions'],'Lost authored code capture')
        with wave.open(str(wav)) as stream:
            require(stream.getnchannels()==2 and stream.getsampwidth()==2 and stream.getframerate()==44100,'PCM format differs')
            pcm=stream.readframes(stream.getnframes());frames=stream.getnframes()
        require(any(pcm),'No nonzero digital CD audio produced')
        receipt.update(passed=True,capture_sha256=digest,source_identities=len(cap['observations']),pcm_sha256=hashlib.sha256(pcm).hexdigest(),pcm_frames=frames)
        inputs(out)
    finally:write(directory/'receipt.json',receipt)
    return receipt

def compare_states(left,right,*,restored=False):
    require(len(left)==len(right),'Different boundary count')
    for a,b in zip(left,right):
        require(a['label']==b['label'] and a['wram_sha256']==b['wram_sha256'] and a['rgb_sha256']==b['rgb_sha256']
            and a['extent']==b['extent'] and projection(a['status'],restored=restored)==projection(b['status'],restored=restored),
            'Native/reference guest state differs')

def compare(left,right,*,restored=False):
    compare_states(left['stages'],right['stages'],restored=restored)
    require(left['pcm_sha256']==right['pcm_sha256'] and left['pcm_frames']==right['pcm_frames'],'Digital PCM differs')

def typed(descriptor,build,checkpoint,directory):
    directory.mkdir();checked,built,binary,receipt_sha=project._verified_package(descriptor,build)
    digest=sha(checkpoint);command=_command(checked,binary,checkpoint,digest,True,None);write(directory/'command.json',command)
    with (directory/'runtime.json').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=ENV,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=120)
    require(result.returncode==0,'Canonical checkpoint inspection refused')
    report=json.loads((directory/'runtime.json').read_text());_runtime_receipt(report,digest)
    require(sha(checkpoint)==digest and b'PCE_DEV_PORT=' not in (directory/'stderr.log').read_bytes(),'Diagnostic altered state or started network')
    later=project._verified_package(descriptor,build);require(later[1]==built and later[3]==receipt_sha,'Producer changed during inspection')
    return report

def qualify(out,generator,cmake_args):
    original=inputs(out);prepare.prepare_project(out/'bootstrap.toml',out/'bootstrap')
    project.build(out/'bootstrap/project.toml',out/'bootstrap-build',generator=generator,desktop=True,cmake_args=cmake_args)
    discovery=[run(out,f'discovery-{mode}',out/'bootstrap/project.toml',out/'bootstrap-build',mode,reference=True) for mode in (1,2,3)]
    compose_history([out/f'discovery-{mode}/capture.jsonl' for mode in (1,2,3)],out/'observed',history_version=2)
    recipe=tomllib.loads((out/'bootstrap.toml').read_text());recipe['module']=dict(kind='history',path='observed/history.json',partition_layout='shared',partition_size=1024)
    recipe['runtime']['tier']='native';(out/'native.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    prepare.prepare_project(out/'native.toml',out/'native');project.build(out/'native/project.toml',out/'native-build',generator=generator,desktop=True,cmake_args=cmake_args)
    results=[]
    for mode in (1,2,3):
        reference=run(out,f'reference-{mode}',out/'native/project.toml',out/'native-build',mode,reference=True)
        native=run(out,f'native-{mode}',out/'native/project.toml',out/'native-build',mode,reference=False);compare(reference,native)
        reports=[typed(out/'native/project.toml',out/'native-build',out/f'{role}-{mode}/checkpoints/end.pcec',out/f'typed-{role}-{mode}') for role in ('reference','native')]
        require(reports[0]['tier_neutral_core_sha256']==reports[1]['tier_neutral_core_sha256']
            and reports[0]['host_sha256']==reports[1]['host_sha256'],'Complete canonical HOST/CORE differs beyond four tier counters')
        forks=[run(out,f'fork-{role}-{mode}',out/'native/project.toml',out/'native-build',mode,reference=ref,
            restore=(out/f'native-{mode}/checkpoints','queued.pcec')) for role,ref in (('reference',True),('native',False))]
        compare(forks[0],forks[1],restored=True)
        compare_states(native['stages'][1:],forks[1]['stages'],restored=True)
        with wave.open(str(out/f'native-{mode}/audio.wav')) as a,wave.open(str(out/f'fork-native-{mode}/audio.wav')) as b:
            a.setpos(native['queued_checkpoint']['source_wav_frames']);require(a.readframes(a.getnframes()-a.tell())==b.readframes(b.getnframes()),'Restored PCM suffix differs')
        results.append(dict(mode=mode,native=native['work'],reference=reference['work'],forks=[r['work'] for r in forks],pcm_frames=native['pcm_frames'],
            core_tier_neutral_sha256=reports[0]['tier_neutral_core_sha256'],host_sha256=reports[0]['host_sha256']))
    inputs(out);result=dict(passed=True,tool=original['tool'],sources=sources(),modes=results,
        scope='Authored 25-track CUE, actual guest port/CDB/ACK/status commands, last-track end sentinel, loop/end modes; compiled native/reference TCP and own-build restores; guest RAM/RGB/digital PCM and canonical HOST/CORE comparison with four-tier-counter policy. Explicit paused mode/gate data writes. Dummy/software presentation, no hardware/physical-audio/retail/cross-build claim.')
    write(out/'qualification.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','qualify'));parser.add_argument('output',type=Path)
    parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[]);args=parser.parse_args();out=args.output.resolve()
    print(json.dumps(create(out) if args.command=='create' else qualify(out,args.generator,args.cmake_arg),indent=2))
if __name__=='__main__':main()
