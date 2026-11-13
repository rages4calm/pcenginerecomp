"""Actual CD-loaded RAM epochs -> rederived candidates -> guarded native routes."""
import argparse,copy,hashlib,importlib.util,json,os,re,subprocess,sys,time,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
f=load('live_overlay_fixture',Path(__file__).with_name('fixture.py'))
from pcerecomp import project,prepare
from pcerecomp.capture import load_capture
from pcerecomp.overlay_snapshot import package_binding,capture_snapshot,exact
from pcerecomp.overlays import discover_overlay,compose_overlays
from pcerecomp.native_catalog import load_native_catalog
from pcerecomp.native_gaps import report_native_gaps
from scripts.dev_client import DevClient

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,indent=2);stream.write('\n')
def identity():return project.source_identity(ROOT)
def sources():return {p.relative_to(ROOT).as_posix():digest(p) for p in (Path(__file__),Path(__file__).with_name('fixture.py'))}
def inputs(out):
    value=json.loads((out/'creation.json').read_text(encoding='utf-8'))
    if value['tool']!=identity() or value['sources']!=sources() or any(digest(out/name)!=sha for name,sha in value['originals'].items()):
        raise ValueError('Original source/SDK changed; create new proof rather than repin')
    return value

def create(output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'firmware.bin').write_bytes(f.firmware()[0]);(out/'disc.iso').write_bytes(f.disc())
    # One explicit unexecuted firmware entry bootstraps the normal consumer.
    # The discovery session selects the interpreter before any guest execution.
    write(out/'seed.json',dict(format='pce-declared-boot-roots-1',schema=1,kind='declared',execution_evidence=False,
        image=dict(kind='system-card',profile='standard',sha256=digest(out/'firmware.bin')),
        roots=[dict(pc=0xE200,mpr=[0]*8,selector=0,source_offsets=[512])]))
    recipe=dict(schema=1,format=prepare.FORMAT,name='authored-live-overlay',module=dict(kind='declared',path='seed.json',partition_layout='shared',partition_size=1024),
        boot=dict(mode='system-card-reset',profile='standard'),bios=dict(path='firmware.bin'),disc=dict(path='disc.iso'),
        runtime=dict(tier='hybrid',video='continuous',audio='off',cd_unknown_status='fault',joypad=2,region='usa',multitap='off'),
        limits=dict(steps=50000000,ticks=100000000,wall_seconds=60))
    (out/'bootstrap.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    value=dict(tool=identity(),sources=sources(),originals={name:digest(out/name) for name in ('firmware.bin','disc.iso','seed.json','bootstrap.toml')},compiled=False,executed=False)
    write(out/'creation.json',value);return value

def _projection(status):
    value=copy.deepcopy(status);value.pop('id');host=value['host'];host.pop('execution_policy',None)
    host['retired_steps']=host.pop('native_steps')+host.pop('interpreter_steps')
    checkpoint=host.get('checkpoint')
    if checkpoint and not checkpoint['resumed']:host.pop('checkpoint')
    elif checkpoint:
        window=checkpoint['window'];window['retired_steps']=window.pop('native_steps')+window.pop('interpreter_steps')
    return value

def _memory(client):
    return dict(wram=client.read_memory_block(0x1F0000,8192),cd=client.read_memory_block(0x100000,65536))

def session(out,name,descriptor,build,*,reference,variant=0,collect=False,checkpoint=None,fork=None,changed=False):
    directory=out/name;directory.mkdir(exist_ok=False);checkpoints=directory/'checkpoints';checkpoints.mkdir()
    capture=directory/'capture.jsonl'
    launch=project.prepare_launch(descriptor,build,dev_port=0,start_paused=True,memory_write=True,
        code_capture=capture,capture_limit=65536,capture_profile='extended',checkpoint_dir=fork[0] if fork else checkpoints,
        checkpoint_load=fork[1] if fork else None,reference_enabled=True)
    write(directory/'launch.json',launch)
    record=dict(tool=identity(),sources=sources(),name=name,variant=variant,reference=reference,closed=False,passed=False,
        producer=dict(binary_sha256=launch['binary_sha256'],build_receipt_sha256=launch['build_receipt']['sha256']),stages=[],snapshots=[],assistance=[])
    stdout=(directory/'stdout.log').open('xb');stderr=(directory/'stderr.log').open('xb')
    proc=subprocess.Popen(launch['command'],stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            text=(directory/'stderr.log').read_text(encoding='utf-8',errors='replace');match=re.search('PCE_DEV_PORT=(\\d+)',text)
            if match:port=int(match[1]);break
            if proc.poll() is not None:raise ValueError(text)
            time.sleep(.02)
        else:raise TimeoutError('Authored host did not announce TCP')
        with DevClient(port,journal=directory/'wire.jsonl') as client:
            initial=client.call('status');record['initial']=initial
            def wait_stage(wanted):
                for _ in range(50):
                    current=client.read_memory(0x1F0000,1)[0]
                    if current==wanted:return
                    if current>wanted:raise ValueError('Authored stage skipped its gate')
                    client.advance(1,reference=reference)
                raise ValueError('Authored CD loader did not reach stage '+str(wanted))
            def observe(label,phase,released=False,finished=False):
                before=client.call('status');ram=_memory(client);after=client.call('status')
                if not exact({k:v for k,v in before.items() if k!='id'},{k:v for k,v in after.items() if k!='id'}):raise ValueError('Authored paused sample advanced')
                if ram['wram']!=f.expected_wram(phase,variant,released=released,finished=finished):
                    (directory/(label+'-actual.wram')).write_bytes(ram['wram']);(directory/(label+'-expected.wram')).write_bytes(f.expected_wram(phase,variant,released=released,finished=finished));raise ValueError('Literal WRAM differs at '+label)
                if ram['cd']!=f.expected_cd(phase):raise ValueError('Literal full CD RAM differs at '+label)
                for region,data in ram.items():(directory/(label+'.'+region)).write_bytes(data)
                record['stages'].append(dict(label=label,status=before,memory={k:hashlib.sha256(v).hexdigest() for k,v in ram.items()}))
                return before
            if fork:
                client.advance(2,reference=reference);final=observe('fork',2,True,True)
            else:
                for phase in (1,2):
                    wait_stage(phase)
                    if phase==1 and variant:
                        client.write_memory(0x1F0010,bytes((variant,)),b'\0');record['assistance'].append(dict(kind='paused-data-control',address=0x1F0010,value=variant))
                    observe('ready-'+str(phase),phase)
                    if collect:
                        machine,origin=package_binding(descriptor,build)
                        snapshot=capture_snapshot(client,directory/f'snapshot-{phase}',machine=machine,origin=origin,regions=[(0x100000,65536),(0x1F0000,8192)])
                        epoch=discover_overlay(snapshot.path,directory/f'epoch-{phase}',code_ranges=[(0x100000,20)],entries=[0x4000])
                        record['snapshots'].append(dict(phase=phase,snapshot_sha256=snapshot.sha256,epoch_sha256=epoch.sha256,summary=epoch.report['summary']))
                    if changed and phase==1:
                        client.write_memory(0x100001,b'\x11',b'\x10');record['assistance'].append(dict(kind='paused-source-change',address=0x100001,before=16,after=17))
                    client.write_memory(0x1F0001,bytes((phase,)),bytes((phase-1,)))
                    record['assistance'].append(dict(kind='paused-data-gate',address=0x1F0001,value=phase))
                    if changed:break
                if changed:
                    try:client.advance(1,reference=reference)
                    except Exception as error:record['expected_refusal']=type(error).__name__
                    else:raise ValueError('Changed overlay executed without native guard refusal')
                    proc.wait(timeout=10);final=None
                else:
                    wait_stage(3);final=observe('finished',2,True,True)
                    expected=dict(a=3,x=0,y=0,sp=255,p=5)
                    if any(final['host']['cpu'][key]!=value for key,value in expected.items()):raise ValueError('Literal final CPU differs')
                    if checkpoint:record['checkpoint']=client.call('save_checkpoint',name=checkpoint)
            if final:
                record['final']=final
                record['work']=dict(native=final['host']['native_steps']-initial['host']['native_steps'],interpreted=final['host']['interpreter_steps']-initial['host']['interpreter_steps'])
                if (reference and (record['work']['native'] or record['work']['interpreted']<=0)
                        or not reference and (record['work']['interpreted'] or record['work']['native']<=0)):raise ValueError('Actual execution tier differs')
                client.call('quit')
        proc.wait(timeout=15);stdout.close();stderr.close()
        if changed:
            text=(directory/'stdout.log').read_text(encoding='utf-8');record['guard_result']=json.loads(text)
            if record['guard_result']['pc']!=0x4000 or record['guard_result']['guard_misses']!=1 or record['guard_result']['interpreter_steps']!=0:raise ValueError('Changed overlay refusal endpoint differs')
        elif proc.returncode!=0:raise ValueError('Authored host exit: '+(directory/'stderr.log').read_text(encoding='utf-8'))
        cap,sha=load_capture(capture)
        if not cap['complete'] or cap['dropped_instructions'] or cap['unreadable_instructions']:raise ValueError('Authored capture has losses')
        record.update(passed=True,closed=True,exit_code=proc.returncode,capture_sha256=sha,retired=cap['retired_instructions'],keys=len(cap['observations']))
        if identity()!=inputs(out)['tool']:raise ValueError('SDK changed during authored qualification')
    except BaseException as error:
        record['error']=repr(error);raise
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        stdout.close();stderr.close();record['process_closed']=proc.poll() is not None;write(directory/'receipt.json',record)
    return record

def qualify(output,generator=None,cmake_args=()):
    out=Path(output).resolve();created=inputs(out)
    prepare.prepare_project(out/'bootstrap.toml',out/'bootstrap');project.build(out/'bootstrap/project.toml',out/'bootstrap-build',generator=generator,cmake_args=cmake_args)
    baseline=session(out,'discovery',out/'bootstrap/project.toml',out/'bootstrap-build',reference=True,collect=True)
    library=compose_overlays([out/'discovery/epoch-1',out/'discovery/epoch-2'],out/'overlays')
    recipe=tomllib.loads((out/'bootstrap.toml').read_text(encoding='utf-8'));recipe['module']=dict(kind='overlay',path='overlays/library.json',history_path='observed/history.json',history_version=2,partition_layout='shared',partition_size=1024)
    from pcerecomp.history import compose_history
    compose_history([out/'discovery/capture.jsonl'],out/'observed',history_version=2)
    recipe['runtime']['tier']='native';(out/'native.toml').write_text(prepare._toml(recipe),encoding='utf-8',newline='\n')
    prepare.prepare_project(out/'native.toml',out/'native');project.build(out/'native/project.toml',out/'native-build',generator=generator,cmake_args=cmake_args)
    catalog=load_native_catalog(out/'native/module/module.json',out/'native/declarations/roots.json',observation_history=out/'native/observation-history/history.json')
    if len(catalog.declared-catalog.observed)!=3:raise ValueError('Unexecuted branch candidate count differs')
    routes=[]
    for variant in (0,1):
        ref=session(out,f'reference-{variant}',out/'native/project.toml',out/'native-build',reference=True,variant=variant)
        native=session(out,f'native-{variant}',out/'native/project.toml',out/'native-build',reference=False,variant=variant,checkpoint='final.pcec' if variant==0 else None)
        for a,b in zip(ref['stages'],native['stages']):
            if a['label']!=b['label'] or not exact(a['memory'],b['memory']) or not exact(_projection(a['status']),_projection(b['status'])):raise ValueError('Native/reference paused state differs')
        routes.append(dict(variant=variant,work=native['work'],keys=native['keys']))
    gaps=report_native_gaps(catalog,[out/f'native-{variant}/capture.jsonl' for variant in (0,1)],capture_profile='extended');write(out/'native-gaps.json',gaps)
    if gaps['summary']['declared_emitted_unexercised']!=0 or gaps['summary']['declared_emitted_exercised']!=11:raise ValueError('Overlay candidates not fully exercised')
    forks=[]
    for reference in (True,False):forks.append(session(out,'fork-reference' if reference else 'fork-native',out/'native/project.toml',out/'native-build',reference=reference,fork=(out/'native-0/checkpoints','final.pcec')))
    if not exact(_projection(forks[0]['final']),_projection(forks[1]['final'])) or not exact(forks[0]['stages'][0]['memory'],forks[1]['stages'][0]['memory']):raise ValueError('Same-build checkpoint fork differs')
    negative=session(out,'changed-source',out/'native/project.toml',out/'native-build',reference=False,changed=True)
    inputs(out);value=dict(passed=True,tool=created['tool'],sources=created['sources'],baseline=dict(work=baseline['work'],keys=baseline['keys'],capture_sha256=baseline['capture_sha256']),
        declared=len(catalog.declared),declared_only=len(catalog.declared-catalog.observed),epochs=library.source_metadata['epochs'],routes=routes,
        gaps=dict(sha256=digest(out/'native-gaps.json'),summary=gaps['summary']),forks=[v['work'] for v in forks],changed_guard=negative['guard_result'],
        scope='Authored real guest CD READ loads two sectors at the same RAM address. Paused snapshots precede executing each sector in discovery route. Three previously unexecuted branch keys derived without invented hits; two actual native routes exercise all11declared keys, zero interpreter fallback. Literal full WRAM/CDRAM/finalCPU plus same-build internal state/reference and checkpoint forks. Assisted data gates/branch choice and changed-code negative disclosed. Not retail/hardware or independent device-clock proof.')
    write(out/'qualification.json',value);return value

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','qualify'));parser.add_argument('output',type=Path);parser.add_argument('--generator');parser.add_argument('--cmake-arg',action='append',default=[]);args=parser.parse_args(argv)
    try:
        value=create(args.output) if args.command=='create' else qualify(args.output,args.generator,args.cmake_arg);print(json.dumps(value,indent=2));return 0
    except (ValueError,OSError,RuntimeError) as error:print(str(error),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
