"""Qualify typed offline inspection/comparison with authored guest execution."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pcerecomp import project
from examples.widescreen.workflow import session

_spec = importlib.util.spec_from_file_location('inspection_title_fixture',
    ROOT/'examples/title-adapter/fixture.py')
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def qualify(output, toolchain_root, cmake_args=(), *, desktop=True,
            dependency_roots=()):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(schema=1, passed=False, tool=project.source_identity(ROOT),
        scope='Authored typed checkpoint state agreement; no retail, hardware, migration authority or native whole-game claim')
    environment = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy',
                       SDL_RENDER_DRIVER='software')
    try:
        rows = fixture.create(output/'inputs')
        bundle = Path(toolchain_root).resolve(strict=True)
        runs = output/'runs'; runs.mkdir()
        checkpoints = output/'checkpoints'; checkpoints.mkdir()
        cache = output/'cache'; cache.mkdir()
        inspections = output/'inspections'; inspections.mkdir()
        comparisons = output/'comparisons'; comparisons.mkdir()
        report['builds'] = {}
        # The existing fixture also prepares an unused span descriptor. Only
        # these two actual audited packages belong to this proof.
        for name in ('original', 'adapted'):
            row = rows[name]; row['build'] = output/(name+'-build')
            built = project.build(row['descriptor'], row['build'], generator='Ninja',
                desktop=desktop, cache_root=cache, cache_toolchain_root=bundle,
                cache_dependency_roots=dependency_roots,
                cmake_args=['-DCMAKE_CXX_COMPILER='+str(bundle/'bin/clang++.exe'),
                            '-DCMAKE_MAKE_PROGRAM='+str(bundle/'bin/ninja.exe'), *cmake_args])
            require(built['cache']['hit'] is False, 'Proof requires audited cache-MISS compilation')
            report['builds'][name] = dict(binary_sha256=built['binary_sha256'],
                receipt_sha256=project.sha256(row['build']/'build-receipt.json'))
        variants = dict(
            original=dict(package='original', title_mode='pristine', title_settings=None,
                          expected=dict(exp=1, gold=1, protection=0)),
            pristine=dict(package='adapted', title_mode='pristine', title_settings=None,
                          expected=dict(exp=1, gold=1, protection=0)),
            enhanced=dict(package='adapted', title_mode='enhanced',
                          title_settings=dict(exp=2, gold=3, protection=1),
                          expected=dict(exp=2, gold=3, protection=1)))
        labels = json.loads((output/'inputs/fixture.json').read_text(encoding='utf-8'))['labels']
        report['runs'] = {}; report['inspections'] = {}; report['comparisons'] = {}
        cp_paths = {}; inspection_paths = {}

        def options(variant):
            return dict(reference_enabled=True, title_mode=variant['title_mode'],
                        title_settings=variant['title_settings'])

        def execute(name, kind, *, reference=False, resume=None):
            variant = variants[name]; row = rows[variant['package']]
            role = name+'-'+kind
            plan = project.prepare_launch(row['descriptor'], row['build'], dev_port=0,
                start_paused=True, checkpoint_dir=checkpoints, checkpoint_load=resume,
                **options(variant))
            write(runs/(role+'.launch.json'), plan)
            command = list(plan['command'])
            if desktop:
                command += ['--hidden', 'on', '--window-scale', '1', '--unthrottled', 'on']
            with session(command, runs, role, environment) as client:
                initial = client.call('status')
                if resume is None:
                    ready = client.run_until(labels['game_ready'], fixture.MPR,
                        instructions=2000000, ticks=10000000, reference=reference)
                    require(client.read_memory_block(0x1F0009, 1)==b'\xA5',
                            'Original guest did not complete its warmup')
                    client.advance(1, reference=reference)
                    origin = client.call('status')['frame']
                    require(origin==ready['frame']+1, 'Missing completed alignment frame')
                    client.advance(2, reference=reference)
                else:
                    window = initial['host']['checkpoint']['window']
                    require(window['native_steps']==window['interpreter_steps']==0,
                            'Exact restore retired new instructions')
                status = client.call('status')
                ram = client.read_memory_block(0x1F0000, 8192)
                actual = dict(exp=int.from_bytes(ram[0:2], 'little'),
                    gold=int.from_bytes(ram[2:4], 'little'), timer=ram[4],
                    vblanks=ram[5], health=ram[8])
                require(actual==fixture.expected(2, **variant['expected']),
                        'Independent authored guest values differ: '+role)
                picture, rgb = client.capture('guest')
                require(picture['width']>0 and picture['height']>0 and any(rgb),
                        'Missing completed nonzero guest RGB')
                metadata = client.call('save_checkpoint', name=role+'.pcec')['checkpoint']
            final = json.loads((runs/(role+'.stdout')).read_text(encoding='utf-8'))
            require(final['stop']=='dev_quit' and final['guard_misses']==0,
                    'Guest fault or guard miss in '+role)
            if resume is None:
                require(final['native_steps']==0 if reference else final['interpreter_steps']==0,
                        'Unexpected execution tier in '+role)
                require(final['interpreter_steps']>0 if reference else final['native_steps']>0,
                        'No genuine guest work in '+role)
            require(metadata['pending_pcm_frames']>0, 'No pending PCM in '+role)
            path = checkpoints/(role+'.pcec'); cp_paths[role] = path
            report['runs'][role] = dict(status=status, initial=initial, checkpoint=metadata,
                native=final['native_steps'], interpreted=final['interpreter_steps'],
                checkpoint_sha256=project.sha256(path), ram_sha256=digest(ram),
                rgb_sha256=digest(rgb), guest_values=actual)
            destination = inspections/role
            inspected = project.inspect_checkpoint(row['descriptor'], row['build'], path,
                destination, expected_checkpoint_sha256=project.sha256(path), **options(variant))
            require(inspected['runtime']['cpu']['pc']==status['host']['pc']
                    and inspected['runtime']['cpu']['mpr']==status['host']['cpu']['mpr'],
                    'Typed CPU/MPR differs from TCP status')
            require(inspected['runtime']['pending_pcm_frames']==metadata['pending_pcm_frames'],
                    'Typed inspection lost pending PCM metadata')
            require(inspected['runtime']['frame']==status['frame'], 'Typed frame metadata differs')
            require(inspected['runtime']['checkpoint_schema']==(2 if name=='enhanced' else 1),
                    'Wrong typed checkpoint envelope schema')
            report['inspections'][role] = dict(path=str(destination),
                receipt_sha256=project.sha256(destination/'receipt.json'), runtime=inspected['runtime'])
            inspection_paths[role] = destination
            return path

        def compare(label, left, right, *, policy, expected):
            left_dir = inspection_paths[left]; right_dir = inspection_paths[right]
            result = project.compare_checkpoint_inspections(left_dir, right_dir,
                comparisons/label, expected_left_receipt_sha256=project.sha256(left_dir/'receipt.json'),
                expected_right_receipt_sha256=project.sha256(right_dir/'receipt.json'), policy=policy)
            require(result['passed'] is True and result['equal'] is expected,
                    'Typed comparison has unexpected result: '+label)
            report['comparisons'][label] = dict(policy=policy, equal=result['equal'],
                components=result['components'], receipt_sha256=project.sha256(comparisons/label/'receipt.json'))
            return result

        for name in variants:
            native = execute(name, 'native')
            execute(name, 'repeat')
            execute(name, 'reference', reference=True)
            restored = execute(name, 'restored', resume=native.name)
            require(native.read_bytes()==restored.read_bytes(), 'Exact restore changed checkpoint bytes')
            require(native.read_bytes()==cp_paths[name+'-repeat'].read_bytes(), 'Native repeat bytes differ')
            compare(name+'-repeat-exact', name+'-native', name+'-repeat', policy='exact', expected=True)
            compare(name+'-restore-exact', name+'-native', name+'-restored', policy='exact', expected=True)
            compare(name+'-reference-exact', name+'-native', name+'-reference', policy='exact', expected=False)
            compare(name+'-reference-tiers', name+'-native', name+'-reference', policy='tier-counters', expected=True)
            for kind in ('repeat', 'reference', 'restored'):
                for key in ('ram_sha256', 'rgb_sha256'):
                    require(report['runs'][name+'-'+kind][key]==report['runs'][name+'-native'][key],
                            'Observed guest data differs: '+name+'-'+kind+' '+key)

        negatives = []

        def reject(label, action, *, message_contains=None):
            try:
                action()
            except (ValueError, OSError, RuntimeError) as error:
                if message_contains is not None:
                    require(message_contains in str(error),
                            'Negative failed before its intended gate: '+label+': '+str(error))
                negatives.append(dict(name=label, error=str(error)))
            else:
                raise ValueError('Invalid inspection/comparison admitted: '+label)

        enhanced = variants['enhanced']; adapted = rows['adapted']
        cp = cp_paths['enhanced-native']; cp_sha = project.sha256(cp)
        reject('wrong-checkpoint-sha', lambda: project.inspect_checkpoint(adapted['descriptor'],
            adapted['build'], cp, output/'refused-wrong-sha', expected_checkpoint_sha256='0'*64,
            **options(enhanced)))
        reject('wrong-mode', lambda: project.inspect_checkpoint(adapted['descriptor'], adapted['build'],
            cp, output/'refused-wrong-mode', expected_checkpoint_sha256=cp_sha,
            reference_enabled=True, title_mode='pristine'))
        reject('wrong-settings', lambda: project.inspect_checkpoint(adapted['descriptor'], adapted['build'],
            cp, output/'refused-wrong-settings', expected_checkpoint_sha256=cp_sha,
            reference_enabled=True, title_mode='enhanced', title_settings=dict(exp=2, gold=4, protection=1)))
        reject('cross-recipe-comparison', lambda: project.compare_checkpoint_inspections(
            inspection_paths['pristine-native'], inspection_paths['enhanced-native'],
            output/'refused-cross-recipe', expected_left_receipt_sha256=project.sha256(
                inspection_paths['pristine-native']/'receipt.json'), expected_right_receipt_sha256=
                project.sha256(inspection_paths['enhanced-native']/'receipt.json'), policy='tier-counters'))
        original_inspection = inspection_paths['enhanced-native']
        forged = output/'forged-inspection-input'
        shutil.copytree(original_inspection, forged)
        forged_runtime = json.loads((forged/'runtime.json').read_text(encoding='utf-8'))
        forged_runtime['tier_neutral_core_sha256'] = '0'*64
        write(forged/'runtime.json', forged_runtime)
        forged_receipt = json.loads((forged/'receipt.json').read_text(encoding='utf-8'))
        forged_receipt['runtime'] = forged_runtime
        forged_receipt['runtime_receipt_sha256'] = project.sha256(forged/'runtime.json')
        write(forged/'receipt.json', forged_receipt)
        reject('self-consistent-forged-projection', lambda: project.compare_checkpoint_inspections(
            forged, inspection_paths['enhanced-reference'], output/'refused-forged-projection',
            expected_left_receipt_sha256=project.sha256(forged/'receipt.json'),
            expected_right_receipt_sha256=project.sha256(inspection_paths['enhanced-reference']/'receipt.json'),
            policy='tier-counters'), message_contains='Fresh typed inspection disagrees')
        # A new reference must not silently accept a changed owned source graph.
        checked = project.verify(adapted['descriptor']); source = checked['files']['title_adapter_source']
        original = source.read_bytes(); info = source.stat()
        try:
            source.write_bytes(original+b'\n')
            reject('changed-source', lambda: project.inspect_checkpoint(adapted['descriptor'], adapted['build'],
                cp, output/'refused-changed-source', expected_checkpoint_sha256=cp_sha, **options(enhanced)))
        finally:
            source.write_bytes(original); os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
        require(source.read_bytes()==original, 'Owned authored source was not restored')
        # Direct offline argv must succeed without usable SDL drivers. No guest
        # execution/restore, host audio/video initialization or listener is needed.
        inspection_receipt = json.loads((original_inspection/'receipt.json').read_text(encoding='utf-8'))
        invalid_environment = dict(environment, SDL_VIDEODRIVER='pce-invalid-video',
            SDL_AUDIODRIVER='pce-invalid-audio', SDL_RENDER_DRIVER='pce-invalid-renderer')
        driver_free = subprocess.run(inspection_receipt['command'], env=invalid_environment,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (runs/'driver-free.stdout').write_bytes(driver_free.stdout)
        (runs/'driver-free.stderr').write_bytes(driver_free.stderr)
        require(driver_free.returncode==0 and b'PCE_DEV_PORT=' not in driver_free.stderr,
                'Offline inspection tried to initialize a device or listener')
        runtime = json.loads(driver_free.stdout)
        require(runtime==inspection_receipt['runtime'], 'Driver-free typed state differs')
        require(runtime['native_steps']==runtime['interpreter_steps']==0
                and all(runtime[key] is False for key in
                    ('executed','restored','network_started','presentation_started')),
                'Offline inspection reported new work or live initialization')
        report['driver_free'] = dict(runtime=runtime, exit_code=driver_free.returncode)
        for name, row in report['runs'].items():
            require(project.sha256(cp_paths[name])==row['checkpoint_sha256'], 'Source checkpoint changed')
        require(project.source_identity(ROOT)==report['tool'], 'SDK changed during qualification')
        report.update(passed=True, negative_checks=negatives, elapsed_seconds=time.monotonic()-started,
            imported_work_claimed_as_fresh=False, owned_hosts=0,
            comparison_policy='Exact HOST; original CORE or typed four-tier-counter projection only')
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        write(output/'receipt.json', report)
    return report


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--toolchain-root', required=True, type=Path)
    parser.add_argument('--cmake-arg', action='append', default=[])
    parser.add_argument('--dependency-root', action='append', default=[], type=Path)
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    result = qualify(args.out, args.toolchain_root, args.cmake_arg,
                     desktop=not args.headless, dependency_roots=args.dependency_root)
    print(json.dumps(dict(passed=result['passed'], elapsed_seconds=result['elapsed_seconds']), indent=2))
