"""Qualify offline diagnostic extraction with authored guest BRAM and fresh seeds."""
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pcerecomp import project
from examples.widescreen.workflow import session
from scripts.dev_client import DevError

_spec = importlib.util.spec_from_file_location('bram_fixture', Path(__file__).with_name('fixture.py'))
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def checkpoint_body(path, *, tiers=False):
    # This comparison does not extract BRAM or admit a checkpoint. The production
    # typed loader does that separately; compare the whole explicit HOST/CORE.
    data = path.read_bytes()
    require(data[:8] == b'PCEDEVCP' and len(data) >= 228, 'Invalid checkpoint envelope')
    require(struct.unpack_from('<II', data, 8) == (1, 29), 'Expected pristine schema1 ABI29')
    require(struct.unpack_from('<Q', data, 152)[0] == len(data)-160, 'Wrong payload size')
    body = bytearray(data[160:])
    require(hashlib.sha256(body).hexdigest() == data[88:152].decode('ascii'), 'Wrong payload digest')
    require(body[60:68] == b'PCECORE\0', 'Missing typed CORE')
    if tiers:
        for offset in (44, 52, 76, 84):
            body[60+offset:60+offset+8] = bytes(8)
    return bytes(body)


def qualify(output, toolchain_root, cmake_args=(), *, desktop=False,
            dependency_roots=(), exporter=None):
    """The exporter is the supported project diagnostic API, never raw offsets."""
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(schema=1, passed=False, tool=project.source_identity(ROOT),
                  scope='Authored offline diagnostic BRAM; no player-save validity, retail media, hardware or campaign claim')
    environment = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software',
                       SDL_AUDIODRIVER='dummy')
    try:
        if exporter is None:
            exporter = project.export_checkpoint_bram
        bundle = Path(toolchain_root).resolve(strict=True)
        checkpoints = output/'checkpoints'
        checkpoints.mkdir()
        runs = output/'runs'
        runs.mkdir()
        cache = output/'cache'
        cache.mkdir()
        builds = {}
        report['builds'] = {}

        def build(name, seed=None):
            row = fixture.create(output/(name+'-inputs'), seed=seed, name='bram-'+name)
            row['build'] = output/(name+'-build')
            receipt = project.build(row['descriptor'], row['build'], generator='Ninja',
                desktop=desktop, cache_root=cache, cache_toolchain_root=bundle,
                cache_dependency_roots=dependency_roots,
                cmake_args=['-DCMAKE_CXX_COMPILER='+str(bundle/'bin/clang++.exe'),
                            '-DCMAKE_MAKE_PROGRAM='+str(bundle/'bin/ninja.exe'), *cmake_args])
            require(receipt['cache']['hit'] is False, 'Qualification requires audited cache-MISS builds')
            report['builds'][name] = dict(receipt_sha256=project.sha256(row['build']/'build-receipt.json'),
                binary_sha256=receipt['binary_sha256'], initial_sha256=row['initial_sha256'])
            builds[name] = row
            return row

        def launch(row, role, *, resume=None):
            plan = project.prepare_launch(row['descriptor'], row['build'], dev_port=0,
                start_paused=True, reference_enabled=True, checkpoint_dir=checkpoints,
                checkpoint_load=resume)
            write(runs/(role+'.launch.json'), plan)
            command = list(plan['command'])
            if desktop:
                command += ['--hidden', 'on', '--window-scale', '1', '--unthrottled', 'on']
            return command

        report['runs'] = {}

        def execute(row, role, expected_seed, *, reference=False, resume=None):
            command = launch(row, role, resume=resume)
            with session(command, runs, role, environment) as client:
                before = client.call('status')
                if resume is None:
                    client.run_until(row['ready'], fixture.MPR, instructions=100000,
                                     ticks=10000000, reference=reference)
                else:
                    require(before['host']['checkpoint']['window']['native_steps'] == 0
                            and before['host']['checkpoint']['window']['interpreter_steps'] == 0,
                            'Restore unexpectedly retired guest instructions')
                status = client.call('status')
                require(client.read_memory_block(fixture.READBACK, 2048) == expected_seed,
                        'Complete original BRAM seed differs in guest readback')
                require(client.read_memory_block(0x1F0000, 1) == b'\xa5', 'Guest did not finish BRAM write')
                try:
                    client.read_memory_block(0x1EE000, 1)
                except DevError:
                    pass
                else:
                    raise ValueError('TCP incorrectly allowed BRAM reads')
                saved = client.call('save_checkpoint', name=role+'.pcec')['checkpoint']
            final = json.loads((runs/(role+'.stdout')).read_text(encoding='utf-8'))
            require(final['stop'] == 'dev_quit' and final['guard_misses'] == 0, 'Run faulted or missed source guards')
            if resume is None:
                require(final['native_steps'] == 0 if reference else final['interpreter_steps'] == 0,
                        'Wrong execution tier')
                require(final['interpreter_steps'] > 0 if reference else final['native_steps'] > 0,
                        'No genuine guest instructions')
            cp = checkpoints/(role+'.pcec')
            report['runs'][role] = dict(status=status, checkpoint=saved,
                checkpoint_sha256=project.sha256(cp), native=final['native_steps'],
                interpreted=final['interpreter_steps'], guard_misses=final['guard_misses'])
            return cp

        original = build('original')
        native = execute(original, 'native', bytes(2048))
        repeat = execute(original, 'repeat', bytes(2048))
        reference = execute(original, 'reference', bytes(2048), reference=True)
        restored = execute(original, 'restored', bytes(2048), resume=native.name)
        require(native.read_bytes() == repeat.read_bytes(), 'Native checkpoints are not byte-identical')
        require(checkpoint_body(native, tiers=True) == checkpoint_body(reference, tiers=True),
                'Complete native/reference HOST/CORE differs beyond four tier counters')
        require(checkpoint_body(native) == checkpoint_body(restored), 'Exact restore changed complete state')
        source_sha = project.sha256(native)
        export_directory = output/'diagnostic-export'
        export = exporter(original['descriptor'], original['build'], native, export_directory,
                          expected_checkpoint_sha256=source_sha, reference_enabled=True)
        extracted = export_directory/'bram.bin'
        require(extracted.read_bytes() == fixture.expected(), 'Typed export differs from independent 2048B pattern')
        require(project.sha256(native) == source_sha, 'Offline extraction changed its source checkpoint')
        report['export'] = export
        # The direct diagnostic must exit before SDL initialization, even when
        # the source package is desktop and no valid host driver is available.
        # The supported Python wrapper deliberately supplies dummy drivers, so
        # this separate direct probe uses its exact admitted argv with only the
        # new output destination changed.
        no_sdl_output = output/'no-sdl-bram.bin'
        no_sdl_command = list(export['command'])
        no_sdl_command[no_sdl_command.index('--checkpoint-bram-output')+1] = str(no_sdl_output)
        no_sdl_environment = dict(environment, SDL_VIDEODRIVER='pce-deliberately-invalid-video',
                                  SDL_AUDIODRIVER='pce-deliberately-invalid-audio',
                                  SDL_RENDER_DRIVER='pce-deliberately-invalid-renderer')
        no_sdl = subprocess.run(no_sdl_command, env=no_sdl_environment,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (runs/'no-sdl.stdout').write_bytes(no_sdl.stdout)
        (runs/'no-sdl.stderr').write_bytes(no_sdl.stderr)
        require(no_sdl.returncode == 0, 'Offline diagnostic initialized unavailable SDL drivers')
        require(b'PCE_DEV_PORT=' not in no_sdl.stderr, 'Offline diagnostic announced a listening server')
        require(no_sdl_output.read_bytes() == fixture.expected(), 'Driver-free diagnostic bytes differ')
        no_sdl_metadata = json.loads(no_sdl.stdout)
        require(no_sdl_metadata['executed'] is False and no_sdl_metadata['restored'] is False,
                'Driver-free diagnostic executed or restored a live guest')
        require(no_sdl_metadata['network_started'] is False
                and no_sdl_metadata['presentation_started'] is False
                and no_sdl_metadata['native_steps'] == no_sdl_metadata['interpreter_steps'] == 0,
                'Driver-free diagnostic started a host surface or retired instructions')
        report['driver_free_export'] = dict(desktop_source=desktop, command=no_sdl_command,
            exit_code=no_sdl.returncode, runtime=no_sdl_metadata,
            output_sha256=project.sha256(no_sdl_output),
            deliberately_invalid_drivers=True, development_server_announced=False)
        require(project.sha256(native) == source_sha, 'Driver-free probe changed source checkpoint')
        seeded = build('seeded', extracted)
        seeded_native = execute(seeded, 'seeded-native', fixture.expected())
        seeded_reference = execute(seeded, 'seeded-reference', fixture.expected(), reference=True)
        require(checkpoint_body(seeded_native, tiers=True) == checkpoint_body(seeded_reference, tiers=True),
                'Fresh seed native/reference complete state differs')
        seeded_export_directory = output/'seeded-diagnostic-export'
        report['seeded_export'] = exporter(seeded['descriptor'], seeded['build'], seeded_native,
            seeded_export_directory, expected_checkpoint_sha256=project.sha256(seeded_native),
            reference_enabled=True)
        seeded_export = seeded_export_directory/'bram.bin'
        require(seeded_export.read_bytes() == extracted.read_bytes(), 'New cold consumer changed diagnostic bytes')
        require(report['builds']['original']['initial_sha256'] != report['builds']['seeded']['initial_sha256'],
                'Cold seed did not create a distinct asset identity')
        require(export['runtime']['checkpoint_identity'] !=
                report['seeded_export']['runtime']['checkpoint_identity'],
                'Fresh seeded consumer unexpectedly reused the blank-seed checkpoint identity')
        negatives = []

        def reject(label, source=native, *, expected_sha=None, destination=None):
            destination = destination or output/('refused-'+label)
            try:
                exporter(original['descriptor'], original['build'], source, destination,
                    expected_checkpoint_sha256=expected_sha or project.sha256(source),
                    reference_enabled=True)
            except (ValueError, OSError, RuntimeError) as error:
                require(not (destination/'bram.bin').exists(), 'Rejected diagnostic published BRAM')
                negatives.append(dict(name=label, error=str(error)))
            else:
                raise ValueError('Invalid diagnostic was accepted: '+label)

        reject('wrong-sha', expected_sha='0'*64)
        # Existing output is independently protected, including its valid bytes.
        try:
            exporter(original['descriptor'], original['build'], native, export_directory,
                expected_checkpoint_sha256=source_sha, reference_enabled=True)
        except (ValueError, OSError, RuntimeError) as error:
            negatives.append(dict(name='existing-output', error=str(error)))
        else:
            raise ValueError('Existing diagnostic directory was overwritten')
        require(extracted.read_bytes() == fixture.expected(), 'Existing diagnostic bytes changed')
        for label, data in (('truncated', native.read_bytes()[:-1]),
                            ('same-length-corrupt', native.read_bytes()[:-1]+bytes([native.read_bytes()[-1]^1]))):
            bad = output/(label+'.pcec')
            bad.write_bytes(data)
            reject(label, bad)
        admitted = project.verify(original['descriptor'])
        payload = admitted['files']['payload']
        old = payload.read_bytes()
        info = payload.stat()
        try:
            payload.write_bytes(bytes([old[0]^1])+old[1:])
            reject('same-length-source-tamper')
        finally:
            payload.write_bytes(old)
            os.utime(payload, ns=(info.st_atime_ns, info.st_mtime_ns))
        require(payload.read_bytes() == old, 'Owned authored input was not restored exactly')
        # Preserve normal export exclusions rather than broadening the live host.
        for label, resume, disable_reference in (('normal-reference-export', None, False),
                                                 ('normal-checkpoint-export', native.name, True)):
            command = launch(original, label, resume=resume)
            if disable_reference:
                index = command.index('--dev-reference')
                del command[index:index+2]
            forbidden = output/(label+'.bin')
            command += ['--bram-out', str(forbidden)]
            result = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=15)
            (runs/(label+'.stdout')).write_bytes(result.stdout)
            (runs/(label+'.stderr')).write_bytes(result.stderr)
            require(result.returncode != 0 and not forbidden.exists(), 'Normal BRAM export guard was weakened')
            require(b'excludes BRAM export' in result.stderr, 'Normal export failed at an unrelated gate')
            negatives.append(dict(name=label, returncode=result.returncode))
        require(project.sha256(native) == source_sha, 'Negative probes changed original checkpoint')
        report['negative_checks'] = negatives
        require(project.source_identity(ROOT) == report['tool'], 'SDK changed during qualification')
        report.update(passed=True, bram_sha256=project.sha256(extracted), bram_bytes=2048,
                      imported_work_claimed_as_fresh=False, elapsed_seconds=time.monotonic()-started)
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        write(output/'receipt.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--toolchain-root', required=True, type=Path)
    parser.add_argument('--cmake-arg', action='append', default=[])
    parser.add_argument('--dependency-root', action='append', default=[], type=Path)
    parser.add_argument('--desktop', action='store_true', help='Use SDL dummy desktop in addition to canonical guest execution')
    args = parser.parse_args()
    result = qualify(args.out, args.toolchain_root, args.cmake_arg,
                     desktop=args.desktop, dependency_roots=args.dependency_root)
    print(json.dumps(dict(passed=result['passed'], elapsed_seconds=result['elapsed_seconds']), indent=2))
