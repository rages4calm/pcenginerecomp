"""Explicit consumer-owned guest loader probes and source-qualified RAM sweeps.

Inspired by RondoRecomp's independent/cumulative loader passes, adapted with
permission. Numeric loader knowledge stays in consumer plans, not this module.
Every CPU/stack edit is disclosed assistance; target reachability is not a claim
of natural gameplay, loader completeness or hardware/sector attribution.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib,json,os,re,subprocess,time
from .capture import integer,load_capture
from .declarations import _fields,_ordinary,_path
from .discovery import _canonical
from .overlay_snapshot import package_binding,capture_snapshot,status,ram_ranges,exact,canonical
from .overlays import discover_overlay,compose_overlays
from .snapshots import SnapshotStore
from . import project
from scripts.dev_client import DevClient

FORMAT='pce-loader-sweep-1'
def write(path,value):
    with path.open('xb') as stream:stream.write(_canonical(value,64*1024*1024))

def seed(status_reply):
    pc,mapping=status(status_reply);cpu=status_reply['host']['cpu']
    return pc.to_bytes(2,'little')+bytes(cpu[k] for k in ('a','x','y','sp','p'))+bytes(mapping)

def plan(value):
    value=deepcopy(value)
    _fields(value,{'format','schema','groups','passes','loader','snapshot','limits'},'loader plan')
    if value['format']!=FORMAT or type(value['schema']) is not int or value['schema']!=1:raise ValueError('Unsupported loader plan')
    groups=value['groups']
    if type(groups) is not list or not 1<=len(groups)<=256:raise ValueError('Loader plan requires1..256groups')
    for group in groups:integer(group,255,'loader group')
    if len(set(groups))!=len(groups):raise ValueError('Duplicate loader groups')
    if type(value['passes']) is not list or not value['passes'] or len(value['passes'])>2 or any(type(p) is not str or p not in ('independent','cumulative') for p in value['passes']) or len(set(value['passes']))!=len(value['passes']):raise ValueError('Choose independent and/or cumulative loader passes')
    loader=value['loader'];_fields(loader,{'pc','mpr','a','x','y','p','return_pc','return_mpr_mask'},'loader call')
    for k in ('pc','return_pc'):integer(loader[k],65535,k)
    for k in ('p','return_mpr_mask'):integer(loader[k],255,k)
    for k in ('a','x','y'):
        if loader[k]!='group':integer(loader[k],255,'loader '+k)
    if type(loader['mpr']) is not list or len(loader['mpr'])!=8:raise ValueError('Loader needs8explicit-or-preserved MPR bytes')
    for bank in loader['mpr']:
        if bank is not None:integer(bank,255,'loader MPR')
    if not loader['return_mpr_mask']&(1<<(loader['return_pc']>>13)):raise ValueError('Loader return must bind its source window')
    snapshot=value['snapshot'];_fields(snapshot,{'ranges','code_ranges','entries'},'loader snapshot')
    if type(snapshot['entries']) is not list or not 1<=len(snapshot['entries'])<=256:raise ValueError('Loader requires explicit code entries')
    for entry in snapshot['entries']:integer(entry,65535,'loader source entry')
    limits=value['limits'];_fields(limits,{'instructions','ticks','seconds','states','contexts'},'loader limits')
    for k,n in (('instructions',100000000),('ticks',10000000000),('seconds',3600),('states',100000),('contexts',4096)):integer(limits[k],n,k,1)
    if len(groups)*len(value['passes'])>256:raise ValueError('Loader sweep exceeds256explicit epochs')
    return value

@contextmanager
def consumer_session(descriptor,build,output,checkpoint_dir,checkpoint,*,capture_limit=1048576):
    output.mkdir();capture=output/'capture.jsonl';wire=output/'wire.jsonl'
    launch=project.prepare_launch(descriptor,build,dev_port=0,start_paused=True,memory_write=True,reference_enabled=True,
        checkpoint_dir=checkpoint_dir,checkpoint_load=checkpoint,code_capture=capture,capture_profile='extended',capture_limit=capture_limit)
    write(output/'launch.json',launch);record=dict(passed=False,closed=False,tool=project.source_identity(project.verify(descriptor)['tool_root']),binary_sha256=launch['binary_sha256'])
    with (output/'stdout.log').open('xb') as stdout,(output/'stderr.log').open('xb') as stderr:
        process=subprocess.Popen(launch['command'],stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                with (output/'stderr.log').open('rb') as stream:diagnostic=stream.read(65536).decode('utf-8',errors='replace')
                match=re.search(r'PCE_DEV_PORT=(\d+)',diagnostic)
                if match:port=int(match[1]);break
                if process.poll() is not None:raise ValueError('Owned loader consumer exited: '+diagnostic)
                time.sleep(.02)
            else:raise TimeoutError('Owned loader consumer did not announce TCP')
            with DevClient(port,journal=wire) as client:
                record['initial']=client.call('status');yield client,record
                record['final']=client.call('status');client.call('quit')
            process.wait(timeout=15)
            if process.returncode!=0:raise ValueError('Loader consumer failed')
            cap,sha=load_capture(capture)
            if not cap['complete'] or cap['dropped_instructions'] or cap['unreadable_instructions']:raise ValueError('Loader source capture has losses')
            record.update(passed=True,closed=True,capture_sha256=sha,retired=cap['retired_instructions'],keys=len(cap['observations']))
        except BaseException as error:record['error']=repr(error);raise
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
            record['process_closed']=True;record['exit_code']=process.returncode;write(output/'receipt.json',record)

def probe(client,group,options):
    before=client.call('status');old=seed(before);loader=options['loader'];mapping=[a if b is None else b for a,b in zip(old[7:],loader['mpr'])]
    target=(loader['return_pc']-1)&65535
    # A real RTS consumes this explicit developer-created frame. No helper ROM
    # or firmware service is invented. Stack backing must be supported RAM.
    machine=options['_machine'];addresses=[(mapping[1]<<13)|offset for offset in (0x1FE,0x1FF)]
    ram_ranges(machine,[(canonical(addresses[0]),2)])
    expected=client.read_memory(addresses[0],2);replacement=target.to_bytes(2,'little')
    registers=[group if loader[k]=='group' else loader[k] for k in ('a','x','y')]
    new=loader['pc'].to_bytes(2,'little')+bytes((*registers,0xFD,loader['p']))+bytes(mapping)
    client.write_memory(addresses[0],replacement,expected);client.write_cpu(old,new)
    try:
        after=client.run_until(loader['return_pc'],mapping,instructions=options['limits']['instructions'],ticks=options['limits']['ticks'],
            mpr_mask=loader['return_mpr_mask'],reference=options['_reference'],timeout=options['limits']['seconds'])
    except BaseException:
        # A bound/fault leaves authentic partial work in the original journal.
        # Never restore counters or turn it into a successful loader response.
        raise
    if after['host']['cpu']['sp']!=255:raise ValueError('Loader reached target without consuming the prescribed return frame')
    return dict(group=group,before=before,after=after,assistance=dict(cpu_before=old.hex(),cpu_seed=new.hex(),stack_address=addresses[0],stack_before=expected.hex(),stack_seed=replacement.hex()))

def sweep(descriptor,build,checkpoint_dir,checkpoint,plan_path,output,*,reference=True):
    descriptor=_path(descriptor);build=_path(build);checkpoint_dir=_path(checkpoint_dir);output=_path(output)
    if output.is_relative_to(build) or output.is_relative_to(descriptor.parent):raise ValueError('Loader output must be outside the consumer/build input namespace')
    if output.exists() or output.is_symlink() or not output.parent.is_dir():raise ValueError('Loader sweep requires a new output directory')
    plan_path=_path(plan_path);_ordinary(plan_path,1048576);store=SnapshotStore();bound=store.read_json(plan_path,max_bytes=1048576);options=plan(bound.value)
    if type(reference) is not bool:raise ValueError('Loader reference selection requires a boolean')
    machine,origin=package_binding(descriptor,build)
    ram_ranges(machine,options['snapshot']['ranges']);ram_ranges(machine,options['snapshot']['code_ranges'])
    store.revalidate();output.mkdir();write(output/'plan.json',options);options['_machine']=machine;options['_reference']=reference
    epochs=[];members={};sessions=[];calls=[];receipt=dict(format='pce-loader-sweep-receipt-1',schema=1,passed=False,origin=origin,machine=machine,plan_sha256=bound.sha256,
        execution='reference' if reference else 'configured-native',scope='Developer-assisted actual guest loader windows; explicit selectors, stack/CPU seeds and target boundaries. Static RAM candidates remain separate from retired source captures. No natural gameplay, all-loader completeness, disc-sector attribution or hardware claim.')
    def call(client,record,group):
        result=probe(client,group,options);number=len(calls);snapshot=capture_snapshot(client,output/f'snapshot-{number:04d}',machine=machine,origin=origin,regions=options['snapshot']['ranges'])
        epoch=discover_overlay(snapshot.path,output/f'epoch-{number:04d}',code_ranges=options['snapshot']['code_ranges'],entries=options['snapshot']['entries'],instruction_limit=options['limits']['states'],context_limit=options['limits']['contexts'])
        # Identical closed source graphs are one compiler input. Keep every
        # original call, snapshot and epoch on disk, with an explicit member
        # reference; never drop genuine work or manufacture a distinct source.
        if epoch.sha256 not in members:members[epoch.sha256]=len(epochs);epochs.append(epoch.path)
        result.update(snapshot_sha256=snapshot.sha256,epoch_sha256=epoch.sha256,library_epoch=members[epoch.sha256],summary=epoch.report['summary']);calls.append(result);record.setdefault('calls',[]).append(result)
    try:
        for mode in options['passes']:
            if mode=='cumulative':
                directory=output/'cumulative'
                with consumer_session(descriptor,build,directory,checkpoint_dir,checkpoint) as (client,record):
                    for group in options['groups']:call(client,record,group)
                sessions.append(directory.name)
            else:
                for i,group in enumerate(options['groups']):
                    directory=output/f'independent-{i:04d}'
                    with consumer_session(descriptor,build,directory,checkpoint_dir,checkpoint) as (client,record):call(client,record,group)
                    sessions.append(directory.name)
        library=compose_overlays(epochs,output/'library');store.revalidate()
        later=package_binding(descriptor,build)
        if not exact([machine,origin],list(later)):raise ValueError('Loader package changed during sweep')
        receipt.update(passed=True,library_sha256=library.sha256,identities=len(library.instructions),epochs=len(calls),library_epochs=len(epochs),sessions=sessions,calls=calls)
    except BaseException as error:receipt.update(error=repr(error),sessions=sessions,calls=calls);raise
    finally:write(output/'receipt.json',receipt)
    return receipt
