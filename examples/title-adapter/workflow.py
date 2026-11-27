"""Qualify a consumer-owned gameplay adapter with an authored native program."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from examples.widescreen.workflow import session
from pcerecomp import project

_spec=importlib.util.spec_from_file_location('title_fixture',Path(__file__).with_name('fixture.py'))
fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(fixture)


def require(condition,message):
    if not condition:raise ValueError(message)


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def digest(data):return hashlib.sha256(data).hexdigest()


def checkpoint(path):
    """Decode both explicitly versioned HOST envelopes without hiding fields."""
    data=path.read_bytes()
    require(data[:8]==b'PCEDEVCP' and len(data)>=228,'Invalid authored checkpoint envelope')
    schema,abi=struct.unpack_from('<II',data,8)
    require(schema in (1,2) and abi==29,'Unsupported authored checkpoint schema/ABI')
    require(struct.unpack_from('<I',data,16)[0]==64 and struct.unpack_from('<I',data,84)[0]==64,'Invalid envelope strings')
    require(struct.unpack_from('<Q',data,152)[0]==len(data)-160,'Invalid envelope body length')
    body=data[160:]
    require(digest(body)==data[88:152].decode('ascii'),'Invalid envelope body digest')
    host=body[:60];position=60;extension=b'';adapter_state=b''
    if schema==2:
        require(body[position:position+8]==b'PCETITLE','Missing explicit adapter extension')
        require(struct.unpack_from('<II',body,position+8)==(1,64),'Unknown adapter extension contract')
        state_size=struct.unpack_from('<I',body,position+80)[0]
        require(state_size<=4160,'Unbounded adapter state')
        position+=84+state_size;extension=body[60:position];adapter_state=extension[84:]
    core=body[position:]
    require(core[:8]==b'PCECORE\0','Missing canonical CORE')
    return dict(schema=schema,raw=data,host=host,extension=extension,adapter_state=adapter_state,core=core)


def projected(row,*,tiers=False,wav=False):
    host=bytearray(row['host']);core=bytearray(row['core'])
    if wav:host[44:52]=bytes(8)
    if tiers:
        for offset in (44,52,76,84):core[offset:offset+8]=bytes(8)
    return bytes(host),row['extension'],bytes(core)


def guest(client,frame,settings,*,origin_frame=0):
    status=client.call('status');ram=client.read_memory_block(0x1F0000,8192)
    wanted=fixture.expected(frame,**settings)
    actual=dict(exp=int.from_bytes(ram[0:2],'little'),gold=int.from_bytes(ram[2:4],'little'),
                timer=ram[4],vblanks=ram[5],health=ram[8])
    require(status['paused'] and status['frame']==origin_frame+frame,'Guest cut is not the requested paused frame')
    require(actual==wanted,f'Independent toy-game expectation differs at frame {frame}: {actual} != {wanted}')
    return dict(status=status,values=actual,ram_sha256=digest(ram))


def audit(path,*,fresh_events,checkpoint_sha256=None,initial_adapter=None):
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    require(rows and rows[0].get('format')=='pce-title-adapter-audit-1','Missing typed enhancement audit header')
    require(rows[-1].get('end') is True and rows[-1].get('complete') is True,'Incomplete enhancement audit')
    origins=[row for row in rows if 'checkpoint_origin' in row]
    if checkpoint_sha256 is None:
        require(not origins,'Cold execution unexpectedly imports checkpoint provenance')
    else:
        require(len(origins)==1 and origins[0].get('validated_before_commit') is True
                and origins[0]['checkpoint_origin']['sha256']==checkpoint_sha256
                and origins[0]['adapter']==initial_adapter,
                'Audit does not bind its exact restored source checkpoint and persistent adapter state')
    events=[row for row in rows if 'event' in row]
    require(len(events)==fresh_events,'Audit records do not match fresh adapter events')
    code,labels=fixture.program()
    for row in events:
        name=row['event'];require(name in ('earned_exp','earned_gold','hit','vblank'),'Unexpected enhancement event')
        pc=labels[name];data=code[pc-fixture.PC:pc-fixture.PC+2]
        require(row['execution']=='enhanced' and row['pc']==pc and row['mpr']==fixture.MPR
                and row['selector']==0 and row['source_sha256']==digest(data)
                and row['physical']==[(fixture.MPR[((pc+i)&65535)>>13]<<13)|((pc+i)&8191) for i in range(2)],
                'Audit event lost its complete original source identity')
    return events


def qualify(output,toolchain_root,cmake_args=(),*,desktop=True,dependency_roots=()):
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    producers=('examples/title-adapter/workflow.py','examples/title-adapter/fixture.py',
               'examples/title-adapter/fixture.cpp','examples/widescreen/workflow.py',
               'scripts/dev_client.py','scripts/dev_journal.py')
    report=dict(schema=1,passed=False,tool=project.source_identity(ROOT),
        producer_sources={name:project.sha256(ROOT/name) for name in producers},
        scope='Authored consumer gameplay-adapter integration; no retail addresses, owner saves, physical audio/GPU or campaign claim')
    start=time.monotonic()
    environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    try:
        fixtures=fixture.create(output/'inputs');bundle=Path(toolchain_root).resolve(strict=True)
        cache=output/'cache';cache.mkdir();checkpoints=output/'checkpoints';checkpoints.mkdir()
        runs=output/'runs';runs.mkdir();report['builds']={}
        for name,row in fixtures.items():
            row['build']=output/(name+'-build')
            receipt=project.build(row['descriptor'],row['build'],generator='Ninja',desktop=desktop,
                cache_root=cache,cache_toolchain_root=bundle,
                cache_dependency_roots=dependency_roots,
                cmake_args=['-DCMAKE_CXX_COMPILER='+str(bundle/'bin/clang++.exe'),
                            '-DCMAKE_MAKE_PROGRAM='+str(bundle/'bin/ninja.exe'),*cmake_args])
            require(receipt['cache']['hit'] is False,'Qualification needs real audited compilation, not a cache hit')
            report['builds'][name]=dict(receipt_sha256=project.sha256(row['build']/'build-receipt.json'),
                                       binary_sha256=receipt.get('binary_sha256'),cache=receipt['cache'])
        report['build_seconds']=time.monotonic()-start
        variants={
            'original':dict(package='original',mode=None,settings=dict(exp=1,gold=1,protection=0)),
            'pristine':dict(package='adapted',mode='pristine',settings=dict(exp=1,gold=1,protection=0)),
            'off':dict(package='adapted',mode='enhanced',settings=dict(exp=1,gold=1,protection=0)),
            'enhanced':dict(package='adapted',mode='enhanced',settings=dict(exp=2,gold=8,protection=1)),
            'independent':dict(package='adapted',mode='enhanced',settings=dict(exp=8,gold=2,protection=0)),
            'span':dict(package='span',mode='enhanced',settings=dict(exp=2,gold=8,protection=1))}

        def launch(variant,role,*,resume=None,paced=False,audit=False,wav=True):
            recipe=fixtures[variant['package']]
            options=dict(dev_port=0,start_paused=True,reference_enabled=True,
                         checkpoint_dir=checkpoints,checkpoint_load=resume)
            if variant['mode'] is not None:
                options.update(title_mode=variant['mode'],title_settings=variant['settings'])
                if audit:options['title_audit']=runs/(role+'.adapter.jsonl')
            plan=project.prepare_launch(recipe['descriptor'],recipe['build'],**options)
            write(runs/(role+'.launch.json'),plan)
            command=plan['command']
            if desktop:command+=['--hidden','on','--window-scale','1','--unthrottled','off' if paced else 'on']
            if wav:command+=['--audio-out',str(runs/(role+'.wav'))]
            return command

        # Separate genuine own-package seeds: no cross-mode/header rebinding.
        report['seeds']={};seed_files={};origins={}
        for name,variant in variants.items():
            role=name+'-seed';before=time.monotonic()
            with session(launch(variant,role,audit=variant['mode']=='enhanced',wav=False),runs,role,environment) as client:
                labels=json.loads((output/'inputs/fixture.json').read_text(encoding='utf-8'))['labels']
                ready=client.run_until(labels['game_ready'],fixture.MPR,instructions=2000000,ticks=10000000)
                require(client.read_memory_block(0x1F0009,1)==b'\xA5','Original guest did not finish its own warmup')
                client.advance(1);origins[name]=client.call('status')['frame']
                require(origins[name]==ready['frame']+1,'Warmup cut did not reach its next genuine guest frame')
                guest(client,0,variant['settings'],origin_frame=origins[name])
                cuts=[]
                for frame in (1,2):
                    client.advance(1);cuts.append(guest(client,frame,variant['settings'],origin_frame=origins[name]))
                seed_name=role+'.pcec';metadata=client.call('save_checkpoint',name=seed_name)['checkpoint']
            final=json.loads((runs/(role+'.stdout')).read_text(encoding='utf-8'))
            require(final['guard_misses']==0 and final['interpreter_steps']==0,'Seed has fallback or guard misses')
            require(metadata['pending_pcm_frames']>0,'Seed must preserve actual pending PCM')
            seed_files[name]=seed_name
            report['seeds'][name]=dict(metadata=metadata,cuts=cuts,elapsed_seconds=time.monotonic()-before,
                guest_frame_origin=origins[name],
                source_checkpoint_sha256=project.sha256(checkpoints/seed_name))
            if variant['mode']=='enhanced':
                seed_events=audit(runs/(role+'.adapter.jsonl'),fresh_events=final['title_adapter']['matched_events'])
                require([row['event'] for row in seed_events]==
                        ['earned_exp','earned_gold','hit','vblank','vblank'],
                        'Cold seed must multiply each earned input exactly once before its guest countdown')
                report['seeds'][name]['qualified_source_events']=[row['event'] for row in seed_events]
        require(checkpoint(checkpoints/seed_files['original'])['core']==checkpoint(checkpoints/seed_files['pristine'])['core'],
                'Compiled pristine adapter changes the original guest machine')
        require(checkpoint(checkpoints/seed_files['original'])['core']==checkpoint(checkpoints/seed_files['off'])['core'],
                'Explicit 1x/off settings change the original guest machine')

        report['rows']={};decoded={};audit_rows={}
        cases=[('original','native',False,False,(1,1,1,1)),('pristine','native',False,False,(1,1,1,1)),
               ('pristine','reference',True,False,(1,1,1,1)),('off','native',False,False,(1,1,1,1)),
               ('enhanced','native',False,False,(1,1,1,1)),('enhanced','repeat',False,False,(1,1,1,1)),
               ('enhanced','reference',True,False,(1,1,1,1)),('enhanced','chunked',False,False,(2,2)),
               ('independent','native',False,False,(1,1,1,1)),('independent','reference',True,False,(1,1,1,1)),
               ('span','native',False,False,(1,1,1,1)),('span','reference',True,False,(1,1,1,1))]
        if desktop:cases.append(('enhanced','paced',False,True,(1,1,1,1)))
        for name,kind,reference,paced,chunks in cases:
            variant=variants[name];role=name+'-'+kind;before=time.monotonic()
            with session(launch(variant,role,resume=seed_files[name],paced=paced,
                                audit=variant['mode']=='enhanced'),runs,role,environment) as client:
                initial=client.call('status');cuts=[];frame=2
                for chunk in chunks:
                    client.advance(chunk,reference=reference);frame+=chunk
                    cuts.append(guest(client,frame,variant['settings'],origin_frame=origins[name]))
                status=client.call('status');_,rgb=client.capture('guest')
                require(any(rgb),'Fixture should retain nonzero guest RGB')
                metadata=client.call('save_checkpoint',name=role+'.pcec')['checkpoint']
            final=json.loads((runs/(role+'.stdout')).read_text(encoding='utf-8'))
            require(final['stop']=='dev_quit' and final['guard_misses']==0,'Suffix fault or guard miss')
            window=status['host']['checkpoint']['window']
            require(window['native_steps']==0 if reference else window['interpreter_steps']==0,'Wrong retirement tier')
            require(window['interpreter_steps']>0 if reference else window['native_steps']>0,'No fresh guest retirement')
            with wave.open(str(runs/(role+'.wav')),'rb') as stream:
                require((stream.getnchannels(),stream.getsampwidth(),stream.getframerate())==(2,2,44100),'Unexpected WAV format')
                pcm=stream.readframes(stream.getnframes());samples=list(struct.iter_unpack('<hh',pcm))
            require(samples and all(pair==(1761,0) for pair in samples),'Literal nonzero authored PCM differs')
            decoded[role]=checkpoint(checkpoints/(role+'.pcec'))
            report['rows'][role]=dict(initial=initial,cuts=cuts,status=status,checkpoint=metadata,
                fresh_work=window,guard_misses=final['guard_misses'],ram_sha256=cuts[-1]['ram_sha256'],
                rgb_sha256=digest(rgb),pcm_sha256=digest(pcm),pcm_frames=len(samples),
                checkpoint_sha256=project.sha256(checkpoints/(role+'.pcec')),elapsed_seconds=time.monotonic()-before)
            if name=='span' and not reference:
                dispatch=final['native_dispatch']
                require(dispatch['supported'] is True and dispatch['limit']==8 and dispatch['native_completed']>0
                        and dispatch['interpreted_completed']==0 and 1<dispatch['max_completed']<=8
                        and dispatch['local_continuations']>0,'Actual native span/local-continuation work was not exercised')
                report['rows'][role]['native_dispatch']=dispatch
            if variant['mode']=='enhanced':
                initial_adapter=initial['host']['title_adapter'];ending_adapter=status['host']['title_adapter']
                fresh_events=ending_adapter['matched_events']-initial_adapter['matched_events']
                events=audit(runs/(role+'.adapter.jsonl'),fresh_events=fresh_events,
                    checkpoint_sha256=report['seeds'][name]['source_checkpoint_sha256'],
                    initial_adapter=initial_adapter)
                require(not any(row['event'].startswith('earned_') for row in events),
                        'A restored suffix re-awarded its imported earned reward')
                require(sum(row['event']=='vblank' for row in events)==4,'Suffix did not observe exactly four guest VBlanks')
                expected_new_hits=1 if variant['settings']['protection'] else 2
                require(sum(row['event']=='hit' for row in events)==expected_new_hits,'Wrong source-qualified suffix hit count')
                blob=decoded[role]['adapter_state']
                require(len(blob)==104 and blob[:8]==b'PCETITLE','Unexpected opaque fixture state version')
                words=struct.unpack_from('<6Q',blob,56)
                origin=origins[name]
                wanted=(1,1,2,origin+9,origin+5,6) if variant['settings']['protection'] else (1,1,3,origin+8,origin+5,6)
                require(words==wanted,'Persistent consumer frame/reward state differs from literal expectations')
                audit_rows[role]=events
                report['rows'][role].update(fresh_adapter_events=fresh_events,consumer_state_words=list(words),
                    source_event_audit_sha256=digest(json.dumps(events,sort_keys=True,separators=(',',':')).encode()))

        for prefix,kinds in (('pristine',('native','reference')),('enhanced',('native','repeat','reference','chunked',*(('paced',) if desktop else ()))),
                             ('independent',('native','reference')),('span',('native','reference'))):
            baseline=prefix+'-native'
            for kind in kinds:
                role=prefix+'-'+kind
                require(projected(decoded[role],tiers=True)==projected(decoded[baseline],tiers=True),
                        'Complete HOST/adapter/CORE differs beyond four tier counters: '+role)
                for key in ('ram_sha256','rgb_sha256','pcm_sha256','pcm_frames'):
                    require(report['rows'][role][key]==report['rows'][baseline][key],role+' differs: '+key)
                if baseline in audit_rows:
                    require(audit_rows[role]==audit_rows[baseline],'Enhanced source/event transactions differ: '+role)
        require(decoded['enhanced-native']['raw']==decoded['enhanced-repeat']['raw'],'Native repeat checkpoint bytes differ')
        require(projected(decoded['span-native'])==projected(decoded['enhanced-native']),
                'Actual scalar/span native execution changes complete HOST/adapter/CORE')
        require(audit_rows['span-native']==audit_rows['enhanced-native'],'Scalar/span qualified source transactions differ')
        require(report['rows']['span-native']['fresh_work']==report['rows']['enhanced-native']['fresh_work'],
                'Scalar/span original retirement or tick counts differ')
        for role in ('pristine-native','off-native'):
            require(decoded[role]['core']==decoded['original-native']['core'],'Original guest differs in '+role)
        require(decoded['pristine-native']['schema']==1 and decoded['enhanced-native']['schema']==2,'Mode envelope versions lost')
        require(decoded['enhanced-native']['adapter_state'] and any(decoded['enhanced-native']['adapter_state']),
                'Enhanced state was not persisted')
        for name,seed in report['seeds'].items():
            require(project.sha256(checkpoints/seed_files[name])==seed['source_checkpoint_sha256'],'Original seed changed')
        # Preflight must reject these before creating a host or output file.
        negatives=[]
        adapted=fixtures['adapted']
        for title_options in (dict(title_mode='pristine',title_settings={'exp':2}),
                dict(title_mode='enhanced',title_settings={'exp':9}),
                dict(title_mode='enhanced',title_settings={'gold':0}),
                dict(title_mode='enhanced',title_settings={'unknown':1}),
                dict(title_mode='enhanced',title_settings={'protection':True}),
                dict(title_mode='enhanced',code_capture=runs/'forbidden-original.json')):
            try:project.prepare_launch(adapted['descriptor'],adapted['build'],**title_options)
            except ValueError as error:negatives.append(dict(options=str(title_options),error=str(error)))
            else:raise ValueError('Invalid adapter launch settings unexpectedly admitted')
        require(not (runs/'forbidden-original.json').exists(),'Rejected capture created output')
        # A valid new launch recipe must still refuse an old checkpoint from a
        # different mode/settings binding. No RPC or live guest mutation occurs.
        mismatch_runs=[]
        for role,bad_variant in (
            ('wrong-settings',dict(variants['enhanced'],settings=dict(exp=2,gold=4,protection=1))),
            ('wrong-mode',dict(variants['pristine']))):
            command=launch(bad_variant,role,resume=seed_files['enhanced'],wav=False)
            result=subprocess.run(command,env=environment,capture_output=True,timeout=15,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (runs/(role+'.stdout')).write_bytes(result.stdout);(runs/(role+'.stderr')).write_bytes(result.stderr)
            message=result.stderr.decode('utf-8',errors='replace').lower()
            require(result.returncode!=0 and 'checkpoint' in message
                    and any(word in message for word in ('mismatch','refus','requires')),
                    'Mismatched adapter checkpoint did not fail at its restore gate: '+role)
            mismatch_runs.append(dict(name=role,returncode=result.returncode,
                stderr_sha256=digest(result.stderr),checkpoint_unchanged=
                project.sha256(checkpoints/seed_files['enhanced'])==report['seeds']['enhanced']['source_checkpoint_sha256']))
        # Source and manifest changes are rejected even before a host starts.
        checked=project.verify(adapted['descriptor']);tamper=[]
        for key in ('title_adapter_source','title_adapter_manifest'):
            path=checked['files'][key];original=path.read_bytes();info=path.stat()
            try:
                path.write_bytes(original+b'\n')
                try:project.prepare_launch(adapted['descriptor'],adapted['build'])
                except ValueError as error:tamper.append(dict(input=key,error=str(error)))
                else:raise ValueError('Changed adapter input was admitted: '+key)
            finally:
                path.write_bytes(original);os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
            require(path.read_bytes()==original,'Failed to restore owned authored input')
        require(project.source_identity(ROOT)==report['tool'],'SDK source changed during qualification')
        for name,digest_before in report['producer_sources'].items():
            require(project.sha256(ROOT/name)==digest_before,'Example producer changed during qualification')
        report.update(passed=True,negative_preflights=negatives,mismatched_restore_runs=mismatch_runs,
            changed_input_refusals=tamper,elapsed_seconds=time.monotonic()-start,
            imported_prefix_is_new_work=False,checkpoint_projections=['four execution-tier counters within each mode'],
            pristine_guest_equivalence=True,enhanced_1x_off_guest_equivalence=True,
            actual_protection_scope='Authored VBlank timer2->4 only; no retail title timing claim')
    except Exception as error:
        report['error']=dict(type=type(error).__name__,message=str(error));raise
    finally:write(output/'receipt.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--toolchain-root',required=True,type=Path)
    parser.add_argument('--cmake-arg',action='append',default=[])
    parser.add_argument('--dependency-root',action='append',default=[],type=Path,
                        help='explicit hashed dependency SDK root, including SDL for desktop builds')
    parser.add_argument('--headless',action='store_true',help='omit optional paced desktop comparison')
    args=parser.parse_args();result=qualify(args.out,args.toolchain_root,args.cmake_arg,
        desktop=not args.headless,dependency_roots=args.dependency_root)
    print(json.dumps(dict(passed=result['passed'],elapsed_seconds=result['elapsed_seconds']),indent=2))
