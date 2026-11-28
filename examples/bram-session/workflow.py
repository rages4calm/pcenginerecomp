"""Qualify optional initial backup memory using authored reset firmware and TCP."""
import argparse,copy,hashlib,importlib.util,json,os,subprocess,sys,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('bram_fixture',Path(__file__).with_name('fixture.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from pcerecomp import project,prepare
from pcerecomp.saves import BramSession
from pcerecomp.history import compose_history
from pcerecomp.capture import load_capture
from pcerecomp.toc import Toc
from pcerecomp.checkpoint_inspection import _command,_runtime_receipt
from examples.widescreen.workflow import session
ENV=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_RENDER_DRIVER='software')
CONTRACT=hashlib.sha256(b'authored-bram-session-save-layout-v1').hexdigest()


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):return project.sha256(Path(path))


def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,indent=2);stream.write('\n')


def sources():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in (Path(__file__),Path(__file__).with_name('fixture.py'),
        ROOT/'examples/live-overlays/fixture.py',ROOT/'examples/widescreen/workflow.py',ROOT/'scripts/dev_client.py',ROOT/'scripts/dev_journal.py')}


def create(out):
    out.mkdir(parents=True,exist_ok=False);bios=out/'firmware.pce';bios.write_bytes(fixture.firmware())
    disc=out/'disc.iso';disc.write_bytes(bytes(2048*4));toc=out/'disc.toc';toc.write_text(Toc.from_image(disc).text(),encoding='ascii',newline='\n')
    write(out/'seed.json',dict(format='pce-declared-boot-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(kind='system-card',profile='standard',sha256=sha(bios)),
        roots=[dict(pc=0xE200,mpr=[0]*8,selector=0,source_offsets=[512])]))
    recipe=dict(schema=1,format=prepare.FORMAT,name='authored-bram-session',
        module=dict(kind='declared',path='seed.json',partition_layout='shared',partition_size=1024),
        boot=dict(mode='system-card-reset',profile='standard'),bios=dict(path=bios.name),disc=dict(path=disc.name),toc=dict(path=toc.name),
        runtime=dict(tier='hybrid',video='continuous',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
        limits=dict(steps=10000000,ticks=100000000,wall_seconds=60))
    (out/'bootstrap.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    record=dict(tool=project.source_identity(ROOT),sources=sources(),files={p.name:sha(p) for p in out.iterdir() if p.is_file()},
        scope='Authored reset firmware and four zero data sectors; no retail BIOS, image or save')
    write(out/'creation.json',record);return record


def inputs(out):
    original=json.loads((out/'creation.json').read_text(encoding='utf-8'))
    require(original['tool']==project.source_identity(ROOT) and original['sources']==sources(),'SDK/example changed during qualification')
    require(all(sha(out/name)==digest for name,digest in original['files'].items()),'Original authored input changed')
    return original


def projection(value):
    result=copy.deepcopy(value);result.pop('id',None);host=result['host']
    host.pop('execution_policy',None);host.pop('checkpoint',None)
    host['retired_steps']=host.pop('native_steps')+host.pop('interpreter_steps')
    return result


def run_case(out,name,descriptor,build,save_root,namespace,policy,expected,*,reference=False,restore=None,export=False,commit=False):
    require(not export or not reference and restore is None,'Only a cold native run may export persistence')
    require(not commit or export,'Publication requires a native export')
    directory=out/name;directory.mkdir();checkpoints=directory/'checkpoints';checkpoints.mkdir()
    checked=project.verify(descriptor);identity=project.save_identity(checked,CONTRACT)
    record=dict(passed=False,reference=reference,restore=restore is not None,export=export,commit=commit,stages=[])
    save=save_root/(namespace+'.bram.json');previous=save.read_bytes() if save.exists() else None
    with BramSession(save_root,namespace,identity,initial_bram=policy) as owned:
        try:
            actual=owned.seed_path.read_bytes() if owned.seed_path is not None else bytes(2048)
            require(actual==expected,'Session selected unexpected initial bytes')
            record['seed']=dict(policy=owned.initial_bram,origin=owned.seed_origin,sha256=owned.seed_payload_sha256,
                previous_payload_sha256=owned.previous_payload_sha256)
            if restore:
                source=restore/'ready.pcec';(checkpoints/'ready.pcec').write_bytes(source.read_bytes())
                require(sha(source)==sha(checkpoints/'ready.pcec'),'Original checkpoint copy differs')
                record['source_checkpoint_sha256']=sha(source)
            launch=project.prepare_launch(descriptor,build,dev_port=0,start_paused=True,memory_write=True,
                reference_enabled=not export,checkpoint_dir=checkpoints,checkpoint_load='ready.pcec' if restore else None,
                code_capture=directory/'capture.jsonl',capture_limit=4096,capture_profile='extended')
            command=launch['command']
            if owned.seed_path is not None:command+=['--bram',str(owned.seed_path)]
            if export:command+=['--bram-out',str(owned.output_path)]
            write(directory/'launch.json',launch|dict(command=command))
            with session(command,directory,'host',ENV) as client:
                initial=client.call('status');record['initial']=initial
                if not restore:client.advance(1,reference=reference)
                state=client.call('status');ram=client.read_memory_block(0x1F0000,8192);meta,rgb=client.capture('guest')
                require(ram[0]==1 and ram[1]==0 and ram[0x800:0x1000]==expected,'Guest did not read all original backup bytes')
                record['stages'].append(dict(label='ready',status=state,wram_sha256=hashlib.sha256(ram).hexdigest(),rgb_sha256=hashlib.sha256(rgb).hexdigest()))
                if not restore:record['ready_checkpoint']=client.call('save_checkpoint',name='ready.pcec')['checkpoint']
                client.write_memory(0x1F0001,b'\1',b'\0');client.advance(2,reference=reference)
                state=client.call('status');ram=client.read_memory_block(0x1F0000,8192);meta,rgb=client.capture('guest')
                require(ram[0]==2 and ram[2]==255,'Guest did not update and lock backup memory')
                require(ram[0x800:0x1000]==expected and ram[0x1000:0x1800]==fixture.expected_output(expected),'Guest readback differs from independent expected bytes')
                record['stages'].append(dict(label='updated',status=state,wram_sha256=hashlib.sha256(ram).hexdigest(),rgb_sha256=hashlib.sha256(rgb).hexdigest()))
                record['end_checkpoint']=client.call('save_checkpoint',name='end.pcec')['checkpoint']
                record['work']=dict(native=state['host']['native_steps']-initial['host']['native_steps'],
                    interpreted=state['host']['interpreter_steps']-initial['host']['interpreter_steps'])
                require(record['work']['native']==0 and record['work']['interpreted']>0 if reference else
                    record['work']['native']>0 and record['work']['interpreted']==0,'Unexpected execution tier')
            cap,digest=load_capture(directory/'capture.jsonl')
            require(cap['complete'] and not cap['dropped_instructions'] and not cap['unreadable_instructions'],'Incomplete source capture')
            final=json.loads((directory/'host.stdout').read_text(encoding='utf-8'))
            require(final['guard_misses']==0 or reference,'Unexpected native source guard miss')
            if export:
                require(owned.output_path.read_bytes()==fixture.expected_output(expected),'Raw backup export differs')
                record['export_sha256']=sha(owned.output_path)
            if commit:record['publication']=owned.commit()
            else:require((save.read_bytes() if save.exists() else None)==previous,'Non-publishing run changed saved envelope')
            record.update(passed=True,capture_sha256=digest,source_identities=len(cap['observations']))
        finally:write(directory/'receipt.json',record)
    if restore:
        require(sha(restore/'ready.pcec')==record['source_checkpoint_sha256'] and sha(checkpoints/'ready.pcec')==record['source_checkpoint_sha256'],'Original or imported checkpoint bytes changed')
    inputs(out);return record


def compare(left,right):
    require(len(left['stages'])==len(right['stages']),'Different paused boundaries')
    for a,b in zip(left['stages'],right['stages']):
        require(a['label']==b['label'] and a['wram_sha256']==b['wram_sha256'] and a['rgb_sha256']==b['rgb_sha256']
            and projection(a['status'])==projection(b['status']),'Native/reference state differs')


def typed(descriptor,build,checkpoint,directory,seed):
    directory.mkdir();checked,built,binary,receipt_sha=project._verified_package(descriptor,build)
    digest=sha(checkpoint);command=_command(checked,binary,checkpoint,digest,True,None)
    if seed is not None:
        initial=directory/'seed.bram';initial.write_bytes(seed);command += ['--bram',str(initial)]
    write(directory/'command.json',command)
    with (directory/'runtime.json').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=ENV,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=120)
    require(result.returncode==0,'Typed checkpoint inspection failed')
    report=json.loads((directory/'runtime.json').read_text(encoding='utf-8'));_runtime_receipt(report,digest)
    require(sha(checkpoint)==digest and b'PCE_DEV_PORT=' not in (directory/'stderr.log').read_bytes(),'Offline diagnostic changed state or opened network')
    later=project._verified_package(descriptor,build);require(later[1]==built and later[3]==receipt_sha,'Producer changed during inspection')
    return report


def install_authored_save(save_root,namespace,identity,payload):
    with BramSession(save_root,namespace,identity) as owned:
        require(owned.previous_payload_sha256 is None,'Authored saved fixture already exists')
        owned.output_path.write_bytes(payload);return owned.commit()


def failed_host(out,descriptor,build,save_root,namespace):
    directory=out/'failed-host';directory.mkdir();checked=project.verify(descriptor)
    identity=project.save_identity(checked,CONTRACT);save=save_root/(namespace+'.bram.json');original=save.read_bytes()
    with BramSession(save_root,namespace,identity,initial_bram='formatted') as owned:
        launch=project.prepare_launch(descriptor,build)['command']+['--bram',str(owned.seed_path),
            '--bram-out',str(owned.output_path),'--authored-invalid-option']
        result=subprocess.run(launch,stdin=subprocess.DEVNULL,capture_output=True,env=ENV,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
        (directory/'stdout.log').write_bytes(result.stdout);(directory/'stderr.log').write_bytes(result.stderr)
        require(result.returncode!=0 and not owned.output_path.exists() and not owned.committed,'Failed host published a save')
    require(save.read_bytes()==original,'Failed run changed existing save')
    record=dict(passed=True,exit_code=result.returncode,scope='Authored invalid-option host refusal before guest execution; no publication',save_sha256=sha(save))
    write(directory/'receipt.json',record);return record


def qualify(out,generator,cmake_args):
    original=inputs(out);save_root=out/'saves';save_root.mkdir()
    prepare.prepare_project(out/'bootstrap.toml',out/'bootstrap')
    project.build(out/'bootstrap/project.toml',out/'bootstrap-build',generator=generator,cmake_args=cmake_args)
    run_case(out,'discovery',out/'bootstrap/project.toml',out/'bootstrap-build',save_root,'discovery','formatted',fixture.FORMATTED,reference=True)
    compose_history([out/'discovery/capture.jsonl'],out/'observed',history_version=2)
    recipe=tomllib.loads((out/'bootstrap.toml').read_text(encoding='utf-8'));recipe['module']=dict(kind='history',path='observed/history.json',partition_layout='shared',partition_size=1024)
    recipe['runtime']['tier']='native';(out/'native.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    prepare.prepare_project(out/'native.toml',out/'native');descriptor=out/'native/project.toml';build=out/'native-build'
    project.build(descriptor,build,generator=generator,cmake_args=cmake_args)
    identity=project.save_identity(project.verify(descriptor),CONTRACT)
    install_authored_save(save_root,'saved-blank',identity,bytes(2048));install_authored_save(save_root,'saved-custom',identity,fixture.saved_pattern())
    results=[]
    for name,policy,expected in (('blank','blank',bytes(2048)),('formatted','formatted',fixture.FORMATTED),
        ('saved-blank','formatted',bytes(2048)),('saved-custom','formatted',fixture.saved_pattern())):
        native=run_case(out,'native-'+name,descriptor,build,save_root,name,policy,expected)
        reference=run_case(out,'reference-'+name,descriptor,build,save_root,name,policy,expected,reference=True);compare(native,reference)
        forks=[run_case(out,'fork-'+role+'-'+name,descriptor,build,save_root,name,policy,expected,reference=ref,
            restore=out/('native-'+name)/'checkpoints') for role,ref in (('native',False),('reference',True))]
        compare(forks[0],forks[1]);require(native['stages'][-1]['wram_sha256']==forks[0]['stages'][-1]['wram_sha256'],'Restored guest readback differs')
        reports=[typed(descriptor,build,out/(role+'-'+name)/'checkpoints/end.pcec',out/('typed-'+role+'-'+name),expected if native['seed']['origin']!='blank' else None) for role in ('native','reference')]
        require(reports[0]['tier_neutral_core_sha256']==reports[1]['tier_neutral_core_sha256'] and reports[0]['host_sha256']==reports[1]['host_sha256'],'Complete typed state differs beyond four tier counters')
        results.append(dict(case=name,seed=native['seed'],native=native['work'],reference=reference['work'],forks=[r['work'] for r in forks],
            tier_neutral_core_sha256=reports[0]['tier_neutral_core_sha256'],host_sha256=reports[0]['host_sha256']))
    primary=run_case(out,'publish-formatted',descriptor,build,save_root,'publication','formatted',fixture.FORMATTED,export=True,commit=True)
    reopened=run_case(out,'reopen-saved',descriptor,build,save_root,'publication','formatted',fixture.expected_output(fixture.FORMATTED),export=True,commit=True)
    require(primary['publication']['created'] and primary['publication']['previous_payload_sha256'] is None,'Initial seed was relabelled as old saved work')
    require(reopened['seed']['origin']=='saved' and not reopened['publication']['created'],'Existing save did not take precedence')
    failure=failed_host(out,descriptor,build,save_root,'publication');inputs(out)
    record=dict(passed=True,tool=original['tool'],sources=sources(),cases=results,publications=[primary['publication'],reopened['publication']],failed_host=failure,
        scope='Authored System Card reset, real guest BRAM reads/writes/lock, native/reference TCP, own-build checkpoints and explicit save-session commit/reopen. Expected2KiB developer seed follows Beetle/RetroRecomp, not factory hardware or exact Gear header parity; no retail/save-validity/campaign/GPU/audio claim.')
    write(out/'qualification.json',record);return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','qualify'));parser.add_argument('output',type=Path)
    parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[]);args=parser.parse_args();out=args.output.resolve()
    print(json.dumps(create(out) if args.command=='create' else qualify(out,args.generator,args.cmake_arg),indent=2))
if __name__=='__main__':main()
