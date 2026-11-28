"""Reproduce an audited additive-module continuation without retail media or GPU."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from examples.widescreen.workflow import session
from pcerecomp import checkpoint_continuation as continuation, project
from pcerecomp.capture import load_capture

fixture_spec=importlib.util.spec_from_file_location('continuation_fixture',Path(__file__).with_name('fixture.py'))
fixture=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixture)


def require(ok,message):
    if not ok:raise ValueError(message)


def qualify(output,toolchain_root,*,source_producer='cache',destination_producer='cache'):
    require(source_producer in ('cache','recovery') and destination_producer in ('cache','recovery'),
            'Unsupported build producer')
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    producers=('examples/checkpoint-continuation/workflow.py','examples/checkpoint-continuation/fixture.py',
               'examples/widescreen/workflow.py','scripts/dev_client.py','scripts/dev_journal.py')
    report=dict(schema=1,passed=False,tool=project.source_identity(ROOT),
        producer_sources={name:project.sha256(ROOT/name) for name in producers},
        build_producers=dict(source=source_producer,destination=destination_producer),
        scope='Authored same-SDK additive-module checkpoint continuation; no retail, hardware or campaign claim')
    started=time.monotonic()
    try:
        fixtures=fixture.prepare_fixture(output/'inputs')
        bundle=Path(toolchain_root).resolve(strict=True);cache=output/'cache';cache.mkdir()
        for name,row in fixtures.items():
            row['build']=output/(name+'-build')
            producer=report['build_producers'][name]
            arguments=dict(cache_root=cache,cache_toolchain_root=bundle) if producer=='cache' else dict(
                recoverable=True,recovery_toolchain_root=bundle)
            row['build_receipt']=project.build(row['descriptor'],row['build'],generator='Ninja',
                cmake_args=['-DCMAKE_CXX_COMPILER='+str(bundle/'bin/clang++.exe'),
                            '-DCMAKE_MAKE_PROGRAM='+str(bundle/'bin/ninja.exe')],**arguments)
            if producer=='cache':
                require(row['build_receipt']['cache']['hit'] is False,'Expected newly compiled audited cache miss')
            else:
                require(type(row['build_receipt']['recovery']['resumed']) is bool,'Expected audited recovery receipt')
            row['build_receipt_sha256']=project.sha256(row['build']/'build-receipt.json')
        report['build_receipts']={name:row['build_receipt_sha256'] for name,row in fixtures.items()}
        old,new=fixtures['source'],fixtures['destination']
        report['build_seconds']=time.monotonic()-started
        checkpoints=output/'checkpoints';checkpoints.mkdir()
        runs=output/'runs';runs.mkdir()
        environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
        seed_argv=project.prepare_launch(old['descriptor'],old['build'],dev_port=0,start_paused=True,
            checkpoint_dir=checkpoints,reference_enabled=True)['command']
        with session(seed_argv+['--audio-out',str(runs/'prefix.wav')],runs,'seed',environment) as client:
            client.advance(1)
            report['seed']=client.call('save_checkpoint',name='seed.pcec')['checkpoint']
        require(report['seed']['pending_pcm_frames']>0 and report['seed']['source_wav_frames']>0,
                'Expected nonempty imported PCM and WAV history')
        admission_started=time.monotonic()
        admission=continuation.create_continuation(old['descriptor'],old['build'],new['descriptor'],new['build'],
            old['observations'],new['observations'],checkpoints,'seed.pcec',output/'admission',reference_enabled=True)
        report['admission_seconds']=time.monotonic()-admission_started
        report['admission_receipt_sha256']=project.sha256(output/'admission/receipt.json')
        rows={};source_counts={}
        for role in ('source','native','repeat','reference'):
            launch_started=time.monotonic()
            capture_path=runs/(role+'.capture.json')
            if role=='source':
                argv=project.prepare_launch(old['descriptor'],old['build'],dev_port=0,start_paused=True,
                    checkpoint_dir=checkpoints,checkpoint_load='seed.pcec',reference_enabled=True,
                    code_capture=capture_path,capture_limit=128)['command']
            else:
                argv=continuation.prepare_continuation_launch(output/'admission/receipt.json',
                    code_capture=capture_path,capture_limit=128)['command']
            launch_seconds=time.monotonic()-launch_started
            argv+=['--audio-out',str(runs/(role+'.wav'))]
            execution_started=time.monotonic()
            with session(argv,runs,role,environment) as client:
                before=client.call('status')
                client.advance(12,reference=role=='reference')
                status=client.call('status')
                ram=client.read_memory_block(0x1f0000,8192);_,rgb=client.capture('guest')
                saved=client.call('save_checkpoint',name=role+'.pcec')['checkpoint']
            capture,_=load_capture(capture_path)
            window=status['host']['checkpoint']['window']
            require(capture['complete'] is True and capture['dropped_instructions']==0
                    and capture['unreadable_instructions']==0,'Incomplete source capture')
            for key,hits in (('native_steps','native_hits'),('interpreter_steps','interpreted_hits')):
                require(sum(row[hits] for row in capture['observations'])==window[key],
                        'Source capture differs from newly retired '+key)
            final=json.loads((runs/(role+'.stdout')).read_text(encoding='utf-8'))
            require(type(final.get('guard_misses')) is int and final['guard_misses']==(1 if role=='source' else 0),
                    'Unexpected guard history before comparison projection')
            source_counts[role]=sorted((row['pc'],row['mpr'],row['physical'],row['data'],
                row['native_hits']+row['interpreted_hits']) for row in capture['observations'])
            rows[role]=dict(before=before,status=status,checkpoint=saved,
                final_report_sha256=project.sha256(runs/(role+'.stdout')),guard_misses=final['guard_misses'],
                launch_reaudit_seconds=launch_seconds,execution_seconds=time.monotonic()-execution_started,
                ram_sha256=hashlib.sha256(ram).hexdigest(),rgb_sha256=hashlib.sha256(rgb).hexdigest(),
                wav_sha256=project.sha256(runs/(role+'.wav')),marker=ram[2],
                source_retirements_sha256=hashlib.sha256(json.dumps(source_counts[role],separators=(',',':')).encode()).hexdigest())
            require(ram[2]==0x77,'Guest did not execute its late marker write')
        # PCEDEVCP v1 has a 160-byte envelope and a 60-byte encoded HOST.
        # CORE fields are canonical, with four tier counters explicitly projected.
        def comparable(role):
            raw=(checkpoints/(role+'.pcec')).read_bytes();require(raw[:8]==b'PCEDEVCP','Unexpected checkpoint encoding')
            body=bytearray(raw[160:]);require(body[60:68]==b'PCECORE\0','Unexpected CORE encoding')
            for offset in (44,52,76,84):body[60+offset:60+offset+8]=bytes(8)
            if role=='source':body[120:128]=bytes(8)  # One expected old dispatch miss.
            return body
        for role in rows:
            for key in ('ram_sha256','rgb_sha256','wav_sha256','source_retirements_sha256'):
                require(rows[role][key]==rows['native'][key],role+' differs: '+key)
            require(comparable(role)==comparable('native'),'Complete encoded HOST/CORE differs: '+role)
        require(project.sha256(checkpoints/'native.pcec')==project.sha256(checkpoints/'repeat.pcec'),'Native repeat checkpoint differs')
        require(rows['source']['status']['host']['checkpoint']['window']['interpreter_steps']==1,'Expected exactly one old fallback')
        for role in ('native','repeat'):
            require(rows[role]['status']['host']['checkpoint']['window']['interpreter_steps']==0,'Unexpected new fallback')
        require(rows['reference']['status']['host']['checkpoint']['window']['native_steps']==0,'Reference retired native code')
        require(project.sha256(checkpoints/'seed.pcec')==admission['source_checkpoint']['sha256'],'Original checkpoint changed')
        report['tool_after']=project.source_identity(ROOT)
        require(report['tool_after']==report['tool'],'SDK changed during qualification')
        require(report['producer_sources']=={name:project.sha256(ROOT/name) for name in producers},
                'Workflow source changed during qualification')
        require(report['build_receipts']=={name:project.sha256(row['build']/'build-receipt.json')
                    for name,row in fixtures.items()},'Producer receipt changed during qualification')
        report.update(passed=True,rows=rows,elapsed_seconds=time.monotonic()-started,
            projections=['four execution-tier counters','source package expected guard miss: one'],
            imported_prefix_is_new_work=False)
    except Exception as error:
        report['error']=dict(type=type(error).__name__,message=str(error))
        raise
    finally:
        (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--toolchain-root',required=True,type=Path)
    parser.add_argument('--source-producer',choices=('cache','recovery'),default='cache')
    parser.add_argument('--destination-producer',choices=('cache','recovery'),default='cache')
    args=parser.parse_args();result=qualify(args.out,args.toolchain_root,
        source_producer=args.source_producer,destination_producer=args.destination_producer)
    print(json.dumps(dict(passed=result['passed'],elapsed_seconds=result['elapsed_seconds']),indent=2))
