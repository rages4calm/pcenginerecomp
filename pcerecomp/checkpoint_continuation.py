"""Explicit additive-module developer continuation under one audited SDK.

Permits are local reviewed capabilities, not signatures or untrusted-peer
authentication. Default checkpoint restore retains exact package binding.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time

from . import project, build_inputs
from .native_extension import compare_native_extensions
from .snapshots import SnapshotStore

FORMAT = 'pce-checkpoint-continuation-admission-1'
MAX_CHECKPOINT = 64*1024*1024
MAX_PROBE_JOURNAL = 8*1024*1024
MAX_PROBE_RESPONSE = 2*1024*1024


def _require(ok, message):
    if not ok:
        raise ValueError('Checkpoint continuation: '+message)


def _same(left,right):
    return _digest(left)==_digest(right)


def _strict_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate probe response field')
        result[key]=value
    return result


def _invalid_constant(token):
    raise ValueError('Non-finite probe response token: '+token)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _declaration_arguments(checked):
    if hasattr(project, 'declaration_arguments'):
        return project.declaration_arguments(checked)
    manifest=project._module_manifest(checked['files']['module_manifest'])
    kind=manifest.get('declared_roots_format')
    if kind=='pce-overlay-library-1':
        return dict(image_path=None,source_images=None)
    if kind=='pce-declared-cd-loads-1':
        return dict(image_path=None,source_images={key:checked['files'][key] for key in ('disc','toc','libchdr') if key in checked['files']})
    if kind=='pce-declared-source-set-1':
        from .source_sets import ASSETS
        return dict(image_path=None,source_images={key:checked['files'][key] for key in ASSETS if key in checked['files']})
    path,_=project._declared_boot_source(checked['config'],checked['files'])
    return dict(image_path=path,source_images=None)


def _catalogue_arguments(checked, observations):
    files=checked['files']
    if 'module_declared_roots' in files:
        _require(Path(observations).resolve()==files['module_declared_roots'].resolve(), 'declarations differ from package binding')
        return _declaration_arguments(checked)|dict(observation_history=files.get('module_observation_history'))
    for name in ('module_observation_history','module_observation_profile'):
        if name in files:
            _require(Path(observations).resolve()==files[name].resolve(), 'observations differ from package binding')
    return {}


def _reemit(checked, observations, arguments):
    """Prove artifacts equal this exact SDK's reviewed direct-operation emitter."""
    from . import emitter
    manifest=project._module_manifest(checked['files']['module_manifest'])
    options=dict(exclude_ranges=[(row['start'],row['length']) for row in manifest['excluded_physical_ranges']],
        partition_size=manifest['partition_size'],single_unit=not manifest['partitioned'],
        partition_layout=manifest.get('partition_layout','balanced'),
        native_span='native_span' in manifest,operand_sharing='operand_sharing' in manifest)
    with tempfile.TemporaryDirectory(prefix='pce-continuation-') as folder:
        output=Path(folder)/'module'
        if 'declared_roots_sha256' in manifest:
            emitter.emit_declarations(Path(observations),arguments.get('image_path'),output,
                observation_history=arguments.get('observation_history'),source_images=arguments.get('source_images'),**options)
        elif 'observation_history_sha256' in manifest:
            emitter.emit_history(Path(observations),output,**options)
        elif 'observation_profile_sha256' in manifest:
            from .observations import load_observation_profile
            value,digest=load_observation_profile(Path(observations))
            _require(digest==manifest['observation_profile_sha256'],'observation profile changed before re-emission')
            emitter.emit_observation_profile(value,output,digest,**options)
        else:
            from .capture import load_capture
            value,digest=load_capture(Path(observations))
            _require(digest==manifest['code_capture_sha256'],'capture changed before re-emission')
            emitter.emit_capture(value,output,digest,**options)
        regenerated=project._module_manifest(output/'module.json')
        for field in ('declared_roots_sha256','observation_history_sha256',
                      'observation_profile_sha256','code_capture_sha256'):
            if field in manifest:
                _require(regenerated.get(field)==manifest[field],'original source changed during re-emission')
        for field in ('translation_units','generated_headers'):
            _require(regenerated[field]==manifest[field], 'generated artifacts are not exact current-emitter output')
            for item in manifest[field]:
                _require(project.sha256(output/item['file'])==project.sha256(checked['files']['module_manifest'].parent/item['file']),
                         'generated source differs from current lowering')
    return dict(policy='exact-sdk-reemission-v1', manifest_sha256=project.sha256(checked['files']['module_manifest']))


def _audit(checked, built, build_dir):
    evidence=built.get('cache') or built.get('recovery')
    _require(type(evidence) is dict and type(evidence.get('input_contract')) is dict,
        'package lacks audited producer evidence; create a new baseline and extension with the verified cache or recoverable build producer')
    contract=evidence['input_contract']
    _require(contract.get('producer')=='windows-x64-llvm-mingw-ninja-v1', 'unsupported compiler producer')
    bundle=Path(contract['trees']['toolchain']['path'])
    roots=[Path(row['path']) for row in contract['trees']['dependencies']]
    options=tuple('-D'+key+'='+value for key,value in sorted(contract['options'].items()))
    context=build_inputs.prepare(checked,generator='Ninja',desktop=built['desktop'],cmake_args=options,
        toolchain_root=bundle,dependency_roots=roots,build_dir=Path(build_dir))
    current=build_inputs.verify_closure(context,Path(build_dir)/'build')
    expected=copy.deepcopy(contract)
    configured=expected.pop('configured',None)
    _require(expected==context['contract'], 'source/toolchain/dependency contract changed since build')
    recorded=evidence.get('input_audit')
    _require(type(recorded) is dict and recorded==current, 'compiled dependency/configuration closure changed since build')
    if configured is not None:
        _require(configured==current['configuration'], 'configured build contract differs')
    # Keep exact audited group flags/defines/includes/link policy. Source lists,
    # backtrace locations and module target names grow as coverage is added.
    module=str(checked['files']['module_manifest'].parent.resolve())
    def normalized(value):
        if type(value) is dict:
            return {key:normalized(item) for key,item in value.items() if key not in ('backtrace','sourceIndexes')}
        if type(value) is list:
            return [normalized(item) for item in value]
        if type(value) is str:
            return value.replace(module,'<MODULE>').replace(module.replace('\\','/'),'<MODULE>')
        return value
    policies=[]
    for target in current['configuration']['targets']:
        name=target['name']
        if name.startswith('pce-module-'):
            name='pce-module'
        policies.append(dict(name=name,type=target['type'],compile_groups=normalized(target['compile_groups']),link=normalized(target['link'])))
    shared=copy.deepcopy(context['contract'])
    shared.pop('module_inputs');shared['trees'].pop('module')
    return dict(producer=contract['producer'], shared=shared,
        effective_policy=sorted(policies,key=lambda row:row['name']),
        current_audit_sha256=_digest(current), revalidated=True)


def _checkpoint(path):
    from .declarations import _ordinary
    path=Path(path).absolute();_ordinary(path,MAX_CHECKPOINT)
    with path.open('rb') as stream:raw=stream.read(MAX_CHECKPOINT+1)
    _require(len(raw)<=MAX_CHECKPOINT,'source checkpoint grew beyond bound')
    _require(len(raw)>=24 and raw[:8]==b'PCEDEVCP', 'unsupported source checkpoint')
    schema,abi=struct.unpack_from('<II',raw,8)
    _require(schema==1 and abi==29, 'checkpoint schema/ABI unsupported')
    position=16
    values=[]
    for _ in range(2):
        _require(position+4<=len(raw), 'truncated checkpoint identity')
        length=struct.unpack_from('<I',raw,position)[0];position+=4
        _require(length==64 and position+length<=len(raw), 'invalid checkpoint identity length')
        value=raw[position:position+length].decode('ascii');position+=length
        _require(re.fullmatch('[0-9a-f]{64}',value) is not None, 'invalid checkpoint digest')
        values.append(value)
    _require(position+8<=len(raw), 'truncated checkpoint body length')
    length=struct.unpack_from('<Q',raw,position)[0];position+=8
    _require(length==len(raw)-position and hashlib.sha256(raw[position:]).hexdigest()==values[1], 'checkpoint body digest/length mismatch')
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),identity=values[0],body_sha256=values[1],bytes=len(raw))


def _probe(command, output, name):
    """Owned zero-retirement probe; source ordinary restore validates its envelope."""
    environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    log=output/(name+'.stderr');wire=[];wire_path=output/(name+'.wire.jsonl')
    with (output/(name+'.stdout')).open('xb') as stdout,log.open('xb') as stderr,wire_path.open('xb') as raw_wire:
        def retain(direction,identity,raw):
            record=dict(direction=direction,id=identity,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),raw_base64=base64.b64encode(raw).decode('ascii'))
            raw_wire.write((json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8'));raw_wire.flush();os.fsync(raw_wire.fileno())
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=environment,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            end=time.monotonic()+30
            while True:
                text=log.read_text(encoding='utf-8',errors='replace')
                match=re.search(r'PCE_DEV_PORT=(\d+)',text)
                if match:
                    break
                _require(child.poll() is None and time.monotonic()<end,'paused probe did not start: '+text[-1000:])
                time.sleep(.02)
            with socket.create_connection(('127.0.0.1',int(match[1])),timeout=30) as connection:
                reader=connection.makefile('rb')
                for identity,cmd in ((1,'status'),(2,'quit')):
                    request=dict(id=identity,cmd=cmd)
                    sent=json.dumps(request).encode()+b'\n';retain('request',identity,sent)
                    connection.sendall(sent)
                    raw=reader.readline(2*1024*1024)
                    _require(raw.endswith(b'\n'),'incomplete bounded probe response')
                    retain('response',identity,raw)
                    response=json.loads(raw,object_pairs_hook=_strict_object,parse_constant=_invalid_constant)
                    wire.append(dict(request=request,response=response))
                    _require(type(response) is dict and type(response.get('id')) is int and response.get('id')==identity and response.get('ok') is True,'probe command refused')
            _require(child.wait(timeout=15)==0,'paused probe did not exit cleanly')
            status=wire[0]['response'];host=status['host']
            _require(status.get('paused') is True,'probe guest was not paused')
            _require(re.fullmatch('[0-9a-f]{64}',host.get('checkpoint_identity','')) is not None,
                'host predates continuation identity reporting; perform one cold adoption with the current audited SDK')
            return dict(status=status,wire=wire,wire_sha256=project.sha256(wire_path),wire_file=wire_path.name,exit_code=0)
        finally:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill();child.wait(timeout=5)


def _admit(source_descriptor,source_build,destination_descriptor,destination_build,
           source_observations,destination_observations):
    old,old_build,_,old_receipt=project._verified_package(Path(source_descriptor),Path(source_build))
    new,new_build,_,new_receipt=project._verified_package(Path(destination_descriptor),Path(destination_build))
    _require(old['tool_identity']==new['tool_identity'] and old['tool_identity']==project.source_identity(Path(__file__).resolve().parent.parent),
        'requires identical current SDK/engine/lowering source; adopt one new cold baseline for older SDKs')
    def recipe(checked):
        config=checked['config']
        return dict(runtime=config['runtime'],boot=config.get('boot'),
            payload={key:value for key,value in config.get('payload',{}).items() if key not in ('path','sha256')},
            assets={key:value for key,value in checked['identities'].items() if not key.startswith('module_')})
    _require(recipe(old)==recipe(new),'media, firmware, providers, boot, runtime or input recipes differ')
    def sidecars(package):
        return {name:digest for name,digest in package['output_files'].items() if name!=Path(package['binary']).name}
    _require(sidecars(old_build)==sidecars(new_build),'non-executable package sidecars/DLLs differ')
    old_arguments=_catalogue_arguments(old,source_observations)
    new_arguments=_catalogue_arguments(new,destination_observations)
    comparison=compare_native_extensions(old['files']['module_manifest'],Path(source_observations),
        new['files']['module_manifest'],Path(destination_observations),
        source_options=old_arguments,destination_options=new_arguments)
    _require(comparison['source_is_subset'] and comparison['strict_additive'],'requires a strict additive native identity extension without removal')
    _require(comparison['policy_compatible'],'native emission/selection/exclusion policies changed')
    lowering=[_reemit(old,source_observations,old_arguments),_reemit(new,destination_observations,new_arguments)]
    audits=[_audit(old,old_build,source_build),_audit(new,new_build,destination_build)]
    _require(audits[0]['shared']==audits[1]['shared'] and audits[0]['effective_policy']==audits[1]['effective_policy'],
             'engine/compiler/dependency or effective compile/link policy differs')
    binding=dict(source=dict(descriptor=str(Path(source_descriptor).resolve()),build=str(Path(source_build).resolve()),
        receipt_sha256=old_receipt,binding=project._binding(old),package=old_build['output_files']),
        destination=dict(descriptor=str(Path(destination_descriptor).resolve()),build=str(Path(destination_build).resolve()),
        receipt_sha256=new_receipt,binding=project._binding(new),package=new_build['output_files']),
        comparison=comparison,lowering=lowering,audits=audits)
    return old,new,binding


def _create_continuation(source_descriptor,source_build,destination_descriptor,destination_build,
                        source_observations,destination_observations,checkpoint_dir,checkpoint_name,output,
                        *,reference_enabled=False):
    """Produce a reviewed startup permit after all admission and zero-work probes.

    Output is a new private directory. Both existing packages must retain audited
    producer inputs and ordinary source checkpoint restoration must succeed.
    This does not qualify the destination execution suffix.
    """
    _require(type(reference_enabled) is bool,'reference_enabled must be boolean')
    output=Path(output).absolute();_require(not output.exists() and not output.is_symlink(),'requires a new output directory')
    checkpoint_dir=Path(checkpoint_dir).resolve(strict=True)
    name=project._checkpoint_name(checkpoint_name)
    original=_checkpoint(checkpoint_dir/name)
    old,new,binding=_admit(source_descriptor,source_build,destination_descriptor,destination_build,source_observations,destination_observations)
    output.mkdir(parents=True)
    source_plan=project.prepare_launch(Path(source_descriptor),Path(source_build),dev_port=0,start_paused=True,
        checkpoint_dir=checkpoint_dir,checkpoint_load=name,reference_enabled=reference_enabled)
    destination_plan=project.prepare_launch(Path(destination_descriptor),Path(destination_build),dev_port=0,start_paused=True,
        checkpoint_dir=checkpoint_dir,reference_enabled=reference_enabled)
    source_probe=_probe(source_plan['command']+['--checkpoint-inspect','on'],output,'source')
    destination_probe=_probe(destination_plan['command']+['--checkpoint-inspect','on'],output,'destination')
    source_status=source_probe['status'];destination_status=destination_probe['status']
    imported=source_status['host']['checkpoint']
    _require(imported.get('resumed') is True and imported['origin']['sha256']==original['sha256'], 'source did not validate the exact original checkpoint')
    _require(all(value==0 for value in imported['window'].values()),'source probe executed guest instructions')
    _require(source_status['host']['checkpoint_identity']==original['identity'],'source package identity disagrees with checkpoint')
    _require(destination_status['host']['native_steps']==destination_status['host']['interpreter_steps']==0,'destination probe executed guest instructions')
    _,_,after=_admit(source_descriptor,source_build,destination_descriptor,destination_build,source_observations,destination_observations)
    _require(_same(after,binding) and _same(_checkpoint(checkpoint_dir/name),original),'inputs changed during continuation admission')
    receipt=dict(schema=1,format=FORMAT,migration_authorized=True,qualified=False,execution_evidence=False,
        binding=binding,source_observations=str(Path(source_observations).resolve()),destination_observations=str(Path(destination_observations).resolve()),
        source_checkpoint=original,reference_enabled=reference_enabled,
        source_probe=source_probe,destination_probe=destination_probe,
        destination_identity=destination_status['host']['checkpoint_identity'],
        scope='Explicit audited same-SDK additive-module developer continuation; imported prefix remains original evidence, fresh destination suffix qualification required')
    receipt_bytes=(json.dumps(receipt,indent=2)+'\n').encode('utf-8')
    permit=('PCE_CHECKPOINT_CONTINUATION 1\nsource_identity '+original['identity']+
        '\ndestination_identity '+receipt['destination_identity']+'\ncheckpoint_sha256 '+original['sha256']+
        '\nreceipt_sha256 '+hashlib.sha256(receipt_bytes).hexdigest()+'\n').encode('ascii')
    permit_created=False;receipt_created=False
    try:
        with (output/'permit.pcecp').open('xb') as stream:
            permit_created=True;stream.write(permit);stream.flush();os.fsync(stream.fileno())
        with (output/'receipt.json').open('xb') as stream:
            receipt_created=True;stream.write(receipt_bytes);stream.flush();os.fsync(stream.fileno())
    except Exception:
        # Only our newly reserved artifacts are retired; preserve failed receipt
        # bytes under an explicitly unissued name, never rewrite them to success.
        if permit_created:(output/'permit.pcecp').unlink()
        if receipt_created:(output/'receipt.json').rename(output/'unissued-receipt.json')
        raise
    return receipt


def create_continuation(source_descriptor,source_build,destination_descriptor,destination_build,
                        source_observations,destination_observations,checkpoint_dir,checkpoint_name,output,
                        *,reference_enabled=False):
    """Admit a new private continuation capability; failures issue no permit."""
    directory=Path(output).absolute();was_new=not directory.exists() and not directory.is_symlink()
    try:
        return _create_continuation(source_descriptor,source_build,destination_descriptor,destination_build,
            source_observations,destination_observations,checkpoint_dir,checkpoint_name,directory,reference_enabled=reference_enabled)
    except Exception as error:
        if was_new and directory.is_dir() and not directory.is_symlink() and not (directory/'receipt.json').exists():
            project._write_new(directory/'receipt.json',dict(schema=1,format=FORMAT,migration_authorized=False,
                qualified=False,execution_evidence=False,error=dict(type=type(error).__name__,message=str(error)),
                scope='Failed continuation admission; no permit was issued'))
        raise


def _receipt_shapes(receipt):
    """Validate nested containers before following any caller-supplied paths.

    Graph contents are still rederived by _admit; these checks do not grant
    authority to the retained comparison, lowering or probe JSON.
    """
    def path(value, label):
        _require(type(value) is str and bool(value) and '\x00' not in value, 'invalid '+label+' path')
    binding=project._table(receipt['binding'],{'source','destination','comparison','lowering','audits'},name='continuation binding')
    for side in ('source','destination'):
        entry=project._table(binding[side],{'descriptor','build','receipt_sha256','binding','package'},name='continuation '+side)
        for field in ('descriptor','build'):path(entry[field],side+' '+field)
        project._digest(entry['receipt_sha256'],side+' receipt')
        _require(type(entry['binding']) is dict and type(entry['package']) is dict and bool(entry['package']), 'invalid '+side+' package binding')
        for name,digest in entry['package'].items():
            _require(type(name) is str and bool(name),'invalid package output name')
            project._digest(digest,'package output')
    _require(type(binding['comparison']) is dict,'invalid retained comparison')
    for field in ('lowering','audits'):
        _require(type(binding[field]) is list and len(binding[field])==2 and all(type(row) is dict for row in binding[field]), 'invalid retained '+field)
    for field in ('source_observations','destination_observations'):path(receipt[field],field)
    checkpoint=project._table(receipt['source_checkpoint'],{'path','sha256','identity','body_sha256','bytes'},name='continuation source checkpoint')
    path(checkpoint['path'],'source checkpoint')
    for field in ('sha256','identity','body_sha256'):project._digest(checkpoint[field],field)
    project._integer(checkpoint['bytes'],1,MAX_CHECKPOINT,'checkpoint bytes')
    for side in ('source','destination'):
        probe=project._table(receipt[side+'_probe'],{'status','wire','wire_sha256','wire_file','exit_code'},name='continuation '+side+' probe')
        _require(type(probe['exit_code']) is int and probe['exit_code']==0,'invalid probe exit code')
        project._digest(probe['wire_sha256'],'probe wire')
        _require(probe['wire_file']==side+'.wire.jsonl','invalid probe wire filename')
        _require(type(probe['status']) is dict and type(probe['status'].get('host')) is dict,'invalid probe status')
        project._digest(probe['status']['host'].get('checkpoint_identity'),'probe checkpoint identity')
        _require(type(probe['wire']) is list and len(probe['wire'])==2,'invalid probe wire records')
        for identity,(record,cmd) in enumerate(zip(probe['wire'],('status','quit')),1):
            project._table(record,{'request','response'},name='probe wire record')
            request=project._table(record['request'],{'id','cmd'},name='probe request')
            response=record['response']
            _require(type(request['id']) is int and request['id']==identity and request['cmd']==cmd,'invalid retained probe request')
            _require(type(response) is dict and type(response.get('id')) is int and response['id']==identity and response.get('ok') is True,'invalid retained probe response')
        _require(_same(probe['status'],probe['wire'][0]['response']),'probe status differs from retained response')


def _probe_journal(directory, probe, store):
    """Reconstruct parsed evidence from the exact retained bounded wire file."""
    from .declarations import _ordinary
    path=directory/probe['wire_file']
    _ordinary(path,MAX_PROBE_JOURNAL)
    with path.open('rb') as stream:raw=stream.read(MAX_PROBE_JOURNAL+1)
    _require(len(raw)<=MAX_PROBE_JOURNAL and hashlib.sha256(raw).hexdigest()==probe['wire_sha256'],
             'probe journal changed or exceeds its byte bound')
    _require(raw.endswith(b'\n'),'probe journal lacks a complete final record')
    lines=raw.splitlines()
    _require(len(lines)==4,'probe journal requires exactly two request/reply pairs')
    def parse(raw):
        try:return json.loads(raw,object_pairs_hook=_strict_object,parse_constant=_invalid_constant)
        except (RecursionError,UnicodeError) as error:
            raise ValueError('Invalid bounded probe JSON') from error
    wire=[]
    for index,line in enumerate(lines):
        record=parse(line)
        project._table(record,{'direction','id','bytes','sha256','raw_base64'},name='raw probe journal record')
        identity=index//2+1;direction='response' if index%2 else 'request'
        _require(record['direction']==direction and type(record['id']) is int and record['id']==identity,
                 'probe journal direction/request sequence differs')
        project._integer(record['bytes'],1,MAX_PROBE_RESPONSE if index%2 else 8192,'raw probe bytes')
        project._digest(record['sha256'],'raw probe SHA256')
        _require(type(record['raw_base64']) is str,'raw probe requires base64 text')
        decoded=base64.b64decode(record['raw_base64'],validate=True)
        _require(len(decoded)==record['bytes'] and decoded.endswith(b'\n')
                 and hashlib.sha256(decoded).hexdigest()==record['sha256'],'raw probe bytes/hash disagree')
        value=parse(decoded)
        if direction=='request':wire.append(dict(request=value))
        else:wire[-1]['response']=value
    _require(_same(wire,probe['wire']) and _same(wire[0]['response'],probe['status']),
             'raw probe journal disagrees with retained parsed evidence')
    # Bind the actual original journal, not a JSON rendering of its contents.
    # Binary bindings stream bytes; the bounded buffer above supplies parsing.
    bound=store.bind(path,expected_sha256=probe['wire_sha256'])
    _require(bound.size_bytes==len(raw),'probe journal changed during binding')
    _ordinary(path,MAX_PROBE_JOURNAL)


def prepare_continuation_launch(receipt_path,*,dev_port=0,code_capture=None,capture_limit=None,capture_profile='legacy'):
    """Re-admit all producer/package inputs before returning the guarded argv."""
    receipt_path=Path(receipt_path).resolve(strict=True);store=SnapshotStore()
    snapshot=store.read_json(receipt_path,max_bytes=64*1024*1024);receipt=snapshot.value
    project._table(receipt,{'schema','format','migration_authorized','qualified','execution_evidence','binding',
        'source_observations','destination_observations','source_checkpoint','reference_enabled','source_probe',
        'destination_probe','destination_identity','scope'},name='continuation admission receipt')
    _require(receipt['format']==FORMAT and type(receipt['schema']) is int and receipt['schema']==1
        and receipt['migration_authorized'] is True and receipt['qualified'] is False and receipt['execution_evidence'] is False
        and type(receipt['reference_enabled']) is bool,'unsupported continuation admission receipt')
    project._digest(receipt['destination_identity'],'continuation destination identity')
    _require(type(receipt['scope']) is str and len(receipt['scope'])<=4096,'invalid continuation scope')
    _receipt_shapes(receipt)
    for side in ('source','destination'):_probe_journal(receipt_path.parent,receipt[side+'_probe'],store)
    source=receipt['binding']['source'];destination=receipt['binding']['destination']
    _,_,binding=_admit(source['descriptor'],source['build'],destination['descriptor'],destination['build'],
        receipt['source_observations'],receipt['destination_observations'])
    _require(_same(binding,receipt['binding']),'continuation packages changed since admission')
    original=_checkpoint(receipt['source_checkpoint']['path'])
    _require(_same(original,receipt['source_checkpoint']),'source checkpoint changed since admission')
    permit=receipt_path.parent/'permit.pcecp'
    expected=('PCE_CHECKPOINT_CONTINUATION 1\nsource_identity '+original['identity']+
        '\ndestination_identity '+receipt['destination_identity']+'\ncheckpoint_sha256 '+original['sha256']+
        '\nreceipt_sha256 '+snapshot.sha256+'\n').encode('ascii')
    from .declarations import _ordinary
    _ordinary(permit,512)
    with permit.open('rb') as stream:raw=stream.read(513)
    _require(len(raw)<=512 and raw==expected,'continuation permit changed or is unbound')
    plan=project.prepare_launch(Path(destination['descriptor']),Path(destination['build']),dev_port=dev_port,start_paused=True,
        checkpoint_dir=Path(original['path']).parent,checkpoint_load=Path(original['path']).name,
        reference_enabled=receipt['reference_enabled'],code_capture=code_capture,
        capture_limit=capture_limit,capture_profile=capture_profile)
    plan['command']+=['--checkpoint-continuation',str(permit),'--checkpoint-continuation-sha',hashlib.sha256(expected).hexdigest()]
    plan['continuation']=dict(receipt_sha256=snapshot.sha256,source_checkpoint_sha256=original['sha256'],qualified=False,
        descriptor=destination['descriptor'],build=destination['build'])
    store.revalidate()
    # Ordinary-file/byte bounds and raw-vs-parsed consistency remain true at
    # the return boundary as well as before package admission.
    for side in ('source','destination'):_probe_journal(receipt_path.parent,receipt[side+'_probe'],store)
    return plan


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('admit')
    for side in ('source','destination'):
        for name in ('descriptor','build','observations'):
            create.add_argument('--'+side+'-'+name,required=True,type=Path)
    create.add_argument('--checkpoint-dir',required=True,type=Path)
    create.add_argument('--checkpoint-name',required=True)
    create.add_argument('--out',required=True,type=Path)
    create.add_argument('--reference-enabled',action='store_true')
    launch=commands.add_parser('launch-plan');launch.add_argument('receipt',type=Path)
    launch.add_argument('--dev-port',type=int,default=0)
    launch.add_argument('--code-capture',type=Path)
    launch.add_argument('--capture-limit',type=int)
    launch.add_argument('--capture-profile',choices=('legacy','extended'),default='legacy')
    args=parser.parse_args(argv)
    if args.command=='admit':
        result=create_continuation(args.source_descriptor,args.source_build,args.destination_descriptor,args.destination_build,
            args.source_observations,args.destination_observations,args.checkpoint_dir,args.checkpoint_name,args.out,
            reference_enabled=args.reference_enabled)
        print(json.dumps(dict(migration_authorized=result['migration_authorized'],qualified=False),indent=2))
    else:
        print(json.dumps(prepare_continuation_launch(args.receipt,dev_port=args.dev_port,
            code_capture=args.code_capture,capture_limit=args.capture_limit,capture_profile=args.capture_profile),indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
