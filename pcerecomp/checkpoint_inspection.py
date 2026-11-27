"""Typed, exact-producer checkpoint diagnostics; never restore or qualify a game."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from . import project
from .checkpoint_bram import MAX_CHECKPOINT, _directory, _owned_directory, _path, _publish_receipt
from .declarations import _ordinary
from .snapshots import SnapshotStore

FORMAT = 'pce-checkpoint-inspection-receipt-1'
RUNTIME_FORMAT = 'pce-checkpoint-inspection-1'
COMPARISON_FORMAT = 'pce-checkpoint-comparison-1'
ROOT = Path(__file__).resolve().parents[1]
TIER_COUNTERS = ('native_steps', 'interpreter_steps', 'native_block_steps', 'interpreter_block_steps')
CPU_BYTES = ('a', 'x', 'y', 'sp', 'p', 'mpr_latch', 'irq_sampled')
CPU_WORDS = ('pc', 'irq_vector')
CPU_COUNTS = ('ticks', 'cycles', 'native_steps', 'interpreter_steps', 'guard_misses',
              'vdc_wait_ticks', 'native_block_steps', 'interpreter_block_steps',
              'block_bytes', 'irq_entries', 'rti_steps')
HOST_COUNTS = ('input_applied', 'memory_requests', 'memory_changes', 'source_wav_frames', 'next_poll')
SCOPE = ('Read-only exact-producer typed state inspection; not execution qualification, '
         'game SAVE validation, checkpoint portability or migration admission')


def _same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _array(value, length, maximum, name):
    if type(value) is not list or len(value) != length:
        raise ValueError(name+' requires an exact-length array')
    for item in value: project._integer(item, 0, maximum, name)


def _runtime_receipt(value, expected_sha):
    project._table(value, {'schema', 'format', 'runtime_abi', 'checkpoint_schema', 'diagnostic_only',
        'executed', 'restored', 'network_started', 'presentation_started', 'native_steps',
        'interpreter_steps', 'checkpoint_identity', 'checkpoint_sha256', 'core_sha256',
        'host_sha256', 'tier_neutral_core_sha256', 'cpu', 'host', 'frame', 'raster_frames',
        'pending_pcm_frames', 'guest_input', 'adapter'}, name='typed checkpoint inspection')
    project._integer(value['schema'], 1, 1, 'inspection schema')
    project._integer(value['runtime_abi'], project.ABI, project.ABI, 'inspection ABI')
    project._integer(value['checkpoint_schema'], 1, 2, 'checkpoint schema')
    if value['format'] != RUNTIME_FORMAT or value['diagnostic_only'] is not True:
        raise ValueError('Unsupported typed checkpoint inspection')
    for key in ('executed', 'restored', 'network_started', 'presentation_started'):
        if value[key] is not False: raise ValueError('Inspection must not execute, restore or initialize hosts')
    for key in ('native_steps', 'interpreter_steps'): project._integer(value[key], 0, 0, 'new '+key)
    for key in ('checkpoint_identity', 'checkpoint_sha256', 'core_sha256', 'host_sha256', 'tier_neutral_core_sha256'):
        project._digest(value[key], key)
    if value['checkpoint_sha256'] != expected_sha: raise ValueError('Inspection checkpoint hash differs')
    cpu = project._table(value['cpu'], {*CPU_BYTES, *CPU_WORDS, *CPU_COUNTS, 'mpr', 'clock_divisor'}, name='checkpoint CPU')
    for key in CPU_BYTES: project._integer(cpu[key], 0, 255, key)
    for key in CPU_WORDS: project._integer(cpu[key], 0, 65535, key)
    for key in CPU_COUNTS: project._integer(cpu[key], 0, (1 << 64)-1, key)
    _array(cpu['mpr'], 8, 255, 'MPR')
    project._integer(cpu['clock_divisor'], 3, 12, 'clock divisor')
    if cpu['clock_divisor'] not in (3, 12): raise ValueError('Unsupported clock divisor')
    host = project._table(value['host'], {*HOST_COUNTS, 'scripted', 'remote'}, name='checkpoint HOST')
    for key in ('scripted', 'remote'): _array(host[key], 5, 4095, key)
    for key in HOST_COUNTS: project._integer(host[key], 0, (1 << 64)-1, key)
    for key in ('frame', 'raster_frames', 'pending_pcm_frames'):
        project._integer(value[key], 0, (1 << 64)-1, key)
    guest = project._table(value['guest_input'], {'enabled', 'pressed'}, name='checkpoint guest input')
    if type(guest['enabled']) is not bool: raise ValueError('Guest input enabled must be boolean')
    _array(guest['pressed'], 5, 4095, 'guest input pressed')
    adapter = value['adapter']
    if adapter is not None:
        project._table(adapter, {'binding_sha256', 'state_sha256', 'state_bytes'}, name='checkpoint adapter')
        for key in ('binding_sha256', 'state_sha256'): project._digest(adapter[key], key)
        project._integer(adapter['state_bytes'], 0, 4160, 'adapter state bytes')
    if (value['checkpoint_schema'] == 2) != (adapter is not None):
        raise ValueError('Checkpoint schema and adapter state disagree')
    return value


def _source(descriptor, build_dir):
    checked, built, binary, receipt_sha = project._verified_package(descriptor, build_dir)
    if checked['tool_root'] != ROOT or checked['tool_identity'] != project.source_identity(ROOT):
        raise ValueError('Run inspection from the exact producer SDK; no legacy or cross-SDK rebinding')
    return checked, built, binary, receipt_sha


def _source_record(descriptor, build_dir, package):
    checked, built, binary, receipt_sha = package
    return dict(descriptor=str(descriptor), build_dir=str(build_dir), binding=project._binding(checked),
        build_receipt_sha256=receipt_sha, binary=str(binary), binary_sha256=built['binary_sha256'],
        output_files=built['output_files'])


def _protect(output, package, *paths):
    checked, _, binary, _ = package
    for protected in (checked['tool_root'], checked['files']['module_manifest'].parent,
                      binary.parent, *paths):
        if output == protected or protected in output.parents:
            raise ValueError('Diagnostic output overlaps a protected source/build/evidence graph')


def _command(checked, binary, checkpoint, expected_sha, reference_enabled, title_options):
    title_mode = 'pristine' if title_options is None else title_options['mode']
    settings = None if title_options is None else title_options['settings']
    command = project.command_for(checked, binary, dev_port=0, start_paused=True,
        checkpoint_dir=checkpoint.parent, reference_enabled=reference_enabled,
        title_mode=title_mode, title_settings=settings)
    return command + ['--checkpoint-report', project._checkpoint_name(checkpoint.name),
                      '--checkpoint-report-sha', expected_sha]


def _failed(output, owned, report, error):
    report.pop('equal', None)
    report.update(passed=False, error=dict(type=type(error).__name__, message=str(error)))
    try:
        _owned_directory(output, owned)
        if not (output/'receipt.json').exists(): _publish_receipt(output, owned, report)
    except (OSError, ValueError): pass


def inspect_checkpoint(descriptor, build_dir, checkpoint, output, *, expected_checkpoint_sha256,
                       reference_enabled=False, title_mode='pristine', title_settings=None):
    """Admit one checkpoint in its unchanged producer and publish a typed report.

    This starts an offline diagnostic process, never a guest or live TCP host.
    The output is a new directory; only a complete passed receipt is accepted.
    """
    project._digest(expected_checkpoint_sha256, 'expected checkpoint')
    if type(reference_enabled) is not bool: raise ValueError('reference_enabled must be boolean')
    descriptor, build_dir, checkpoint, output = map(_path, (descriptor, build_dir, checkpoint, output))
    project._checkpoint_name(checkpoint.name)
    _ordinary(checkpoint, MAX_CHECKPOINT); _directory(output.parent)
    if output.exists() or output.is_symlink(): raise ValueError('Inspection requires a new output directory')
    store = SnapshotStore(); source_snapshot = store.bind(checkpoint, expected_sha256=expected_checkpoint_sha256)
    package = _source(descriptor, build_dir)
    checked, _, binary, _ = package
    title_options = project._title_options(checked, title_mode, title_settings)
    _protect(output, package, build_dir, checkpoint)
    command = _command(checked, binary, checkpoint, expected_checkpoint_sha256, reference_enabled, title_options)
    report = dict(schema=1, format=FORMAT, passed=False, diagnostic_only=True, executed=False,
        restored=False, execution_evidence=False, migration_admitted=False, game_save_validated=False,
        source=_source_record(descriptor, build_dir, package),
        checkpoint=dict(path=str(checkpoint), sha256=expected_checkpoint_sha256, bytes=source_snapshot.size_bytes),
        reference_enabled=reference_enabled, title_options=title_options, command=command, scope=SCOPE)
    output.mkdir(); info = output.lstat(); owned = info.st_dev, info.st_ino
    try:
        store.revalidate(); _ordinary(checkpoint, MAX_CHECKPOINT); _owned_directory(output, owned)
        environment = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_RENDER_DRIVER='software')
        with (output/'runtime.json').open('xb') as stdout, (output/'stderr.log').open('xb') as stderr:
            done = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                env=environment, check=False, timeout=180,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        _owned_directory(output, owned)
        report['exit_code'] = done.returncode
        if done.returncode != 0: raise ValueError('Offline checkpoint inspection refused; see retained stderr.log')
        metadata = store.read_json(output/'runtime.json', max_bytes=64*1024).value
        _runtime_receipt(metadata, expected_checkpoint_sha256)
        stderr_snapshot = store.bind(output/'stderr.log')
        if b'PCE_DEV_PORT=' in (output/'stderr.log').read_bytes():
            raise ValueError('Offline inspection unexpectedly opened a development server')
        if (metadata['adapter'] is not None) != (title_options is not None and title_options['mode'] == 'enhanced'):
            raise ValueError('Inspection adapter differs from the selected source recipe')
        after = _source(descriptor, build_dir)
        if not _same(_source_record(descriptor, build_dir, after), report['source']):
            raise ValueError('Source package changed during checkpoint inspection')
        _ordinary(checkpoint, MAX_CHECKPOINT); _owned_directory(output, owned); store.revalidate()
        report.update(passed=True, runtime=metadata, runtime_receipt_sha256=project.sha256(output/'runtime.json'),
                      stderr_sha256=stderr_snapshot.sha256)
        _publish_receipt(output, owned, report)
        return report
    except BaseException as error:
        _failed(output, owned, report, error)
        raise


def _retained(directory, expected_sha, store):
    directory = _path(directory); _directory(directory)
    receipt_path = directory/'receipt.json'; _ordinary(receipt_path, 1024*1024)
    snapshot = store.read_json(receipt_path, expected_sha256=expected_sha, max_bytes=1024*1024)
    value = project._table(snapshot.value, {'schema', 'format', 'passed', 'diagnostic_only', 'executed',
        'restored', 'execution_evidence', 'migration_admitted', 'game_save_validated', 'source', 'checkpoint',
        'reference_enabled', 'title_options', 'command', 'scope', 'exit_code', 'runtime',
        'runtime_receipt_sha256', 'stderr_sha256'}, name='retained inspection receipt')
    project._integer(value['schema'], 1, 1, 'inspection receipt schema')
    project._integer(value['exit_code'], 0, 0, 'inspection exit code')
    if value['format'] != FORMAT or value['passed'] is not True or value['diagnostic_only'] is not True:
        raise ValueError('A completed typed inspection receipt is required')
    for key in ('executed', 'restored', 'execution_evidence', 'migration_admitted', 'game_save_validated'):
        if value[key] is not False: raise ValueError('Inspection must not claim execution, migration or SAVE validity')
    if type(value['reference_enabled']) is not bool or value['scope'] != SCOPE:
        raise ValueError('Invalid inspection capability or scope')
    source = project._table(value['source'], {'descriptor', 'build_dir', 'binding', 'build_receipt_sha256',
        'binary', 'binary_sha256', 'output_files'}, name='retained producer')
    for key in ('descriptor', 'build_dir', 'binary'):
        if type(source[key]) is not str or str(_path(source[key])) != source[key]:
            raise ValueError('Retained producer paths must be exact absolute paths')
    descriptor, build_dir = _path(source['descriptor']), _path(source['build_dir'])
    package = _source(descriptor, build_dir)
    if not _same(_source_record(descriptor, build_dir, package), source):
        raise ValueError('Retained inspection producer changed')
    cp = project._table(value['checkpoint'], {'path', 'sha256', 'bytes'}, name='retained checkpoint')
    if type(cp['path']) is not str or str(_path(cp['path'])) != cp['path']:
        raise ValueError('Retained checkpoint requires an exact absolute path')
    checkpoint = _path(cp['path']); _ordinary(checkpoint, MAX_CHECKPOINT)
    project._digest(cp['sha256'], 'retained checkpoint')
    project._integer(cp['bytes'], 1, MAX_CHECKPOINT, 'retained checkpoint size')
    bound = store.bind(checkpoint, expected_sha256=cp['sha256'])
    if bound.size_bytes != cp['bytes']: raise ValueError('Retained checkpoint size differs')
    title = value['title_options']
    if title is not None:
        project._table(title, {'format', 'id', 'manifest_sha256', 'mode', 'settings', 'canonical'}, name='title recipe')
    fresh_title = project._title_options(package[0], 'pristine' if title is None else title['mode'],
                                        None if title is None else title['settings'])
    if not _same(fresh_title, title): raise ValueError('Retained title recipe differs')
    command = _command(package[0], package[2], checkpoint, cp['sha256'], value['reference_enabled'], title)
    if not _same(command, value['command']): raise ValueError('Retained inspection command differs')
    for key in ('runtime_receipt_sha256', 'stderr_sha256'): project._digest(value[key], key)
    _ordinary(directory/'runtime.json', 64*1024); _ordinary(directory/'stderr.log', 1024*1024, 0)
    runtime = store.read_json(directory/'runtime.json', expected_sha256=value['runtime_receipt_sha256'], max_bytes=64*1024).value
    store.bind(directory/'stderr.log', expected_sha256=value['stderr_sha256'])
    _runtime_receipt(runtime, cp['sha256'])
    if not _same(runtime, value['runtime']): raise ValueError('Retained typed report differs from its bound file')
    if b'PCE_DEV_PORT=' in (directory/'stderr.log').read_bytes(): raise ValueError('Retained inspection announced a server')
    if (runtime['adapter'] is not None) != (title is not None and title['mode'] == 'enhanced'):
        raise ValueError('Retained adapter differs from source recipe')
    return value, package, dict(path=str(receipt_path), sha256=snapshot.sha256)


def compare_checkpoint_inspections(left_output, right_output, output, *,
        expected_left_receipt_sha256, expected_right_receipt_sha256, policy='exact'):
    """Re-admit two own-producer files, then compare exact or tier-neutral state.

    Matching state is not a continuation permit or execution qualification.
    ``passed`` means this comparison completed; inspect ``equal`` for agreement.
    Both retained reports are replayed through fresh offline typed inspections,
    so edited JSON claims alone never establish checkpoint equality.
    """
    project._digest(expected_left_receipt_sha256, 'left inspection receipt')
    project._digest(expected_right_receipt_sha256, 'right inspection receipt')
    project._choice(policy, ('exact', 'tier-counters'), 'checkpoint comparison policy')
    left_output, right_output, output = map(_path, (left_output, right_output, output))
    _directory(output.parent)
    if output.exists() or output.is_symlink(): raise ValueError('Comparison requires a new output directory')
    store = SnapshotStore()
    left, lp, lref = _retained(left_output, expected_left_receipt_sha256, store)
    right, rp, rref = _retained(right_output, expected_right_receipt_sha256, store)
    for item, package, path in ((left, lp, left_output), (right, rp, right_output)):
        _protect(output, package, _path(item['source']['build_dir']), _path(item['checkpoint']['path']), path)
        if output in path.parents: raise ValueError('Comparison cannot contain its retained input')
    if (not _same(left['source'], right['source']) or left['reference_enabled'] != right['reference_enabled']
            or not _same(left['title_options'], right['title_options'])
            or left['runtime']['checkpoint_identity'] != right['runtime']['checkpoint_identity']):
        raise ValueError('Comparison requires one exact producer, capability and title recipe')
    report = dict(schema=1, format=COMPARISON_FORMAT, passed=False, diagnostic_only=True,
        executed=False, restored=False, execution_evidence=False, migration_admitted=False,
        game_save_validated=False, policy=policy, projected_fields=list(TIER_COUNTERS) if policy == 'tier-counters' else [],
        left=lref, right=rref, scope=SCOPE)
    output.mkdir(); info = output.lstat(); owned = info.st_dev, info.st_ino
    try:
        store.revalidate(); _owned_directory(output, owned)
        fresh = []
        for name, item in (('left', left), ('right', right)):
            title = item['title_options']
            observed = inspect_checkpoint(item['source']['descriptor'], item['source']['build_dir'],
                item['checkpoint']['path'], output/name, expected_checkpoint_sha256=item['checkpoint']['sha256'],
                reference_enabled=item['reference_enabled'], title_mode='pristine' if title is None else title['mode'],
                title_settings=None if title is None else title['settings'])
            if not _same(observed['runtime'], item['runtime']):
                raise ValueError('Fresh typed inspection disagrees with retained '+name+' report')
            fresh.append(observed)
        core = 'core_sha256' if policy == 'exact' else 'tier_neutral_core_sha256'
        components = dict(core=fresh[0]['runtime'][core] == fresh[1]['runtime'][core],
                          host=fresh[0]['runtime']['host_sha256'] == fresh[1]['runtime']['host_sha256'])
        for item, package in ((left, lp), (right, rp)):
            current = _source(_path(item['source']['descriptor']), _path(item['source']['build_dir']))
            if not _same(_source_record(_path(item['source']['descriptor']), _path(item['source']['build_dir']), current), item['source']):
                raise ValueError('Producer changed before comparison sealing')
        # Seal the fresh child artifacts as well as the original evidence.
        fresh_refs = {}
        for name, item in zip(('left', 'right'), fresh):
            path = output/name
            receipt = store.read_json(path/'receipt.json', max_bytes=1024*1024)
            if not _same(receipt.value, item): raise ValueError('Fresh inspection receipt changed before sealing')
            runtime = store.read_json(path/'runtime.json', expected_sha256=item['runtime_receipt_sha256'], max_bytes=64*1024)
            if not _same(runtime.value, item['runtime']): raise ValueError('Fresh typed report changed before sealing')
            store.bind(path/'stderr.log', expected_sha256=item['stderr_sha256'])
            fresh_refs[name] = dict(path=str(path/'receipt.json'), sha256=receipt.sha256)
        store.revalidate(); _owned_directory(output, owned)
        report.update(passed=True, equal=all(components.values()), components=components,
            fresh_inspections=fresh_refs, counters={name: {key: item['runtime']['cpu'][key] for key in TIER_COUNTERS}
                for name, item in zip(('left', 'right'), fresh)})
        _publish_receipt(output, owned, report)
        return report
    except BaseException as error:
        _failed(output, owned, report, error)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    inspect = commands.add_parser('inspect', help='Produce an exact-source typed report')
    inspect.add_argument('descriptor', type=Path); inspect.add_argument('--build', required=True, type=Path)
    inspect.add_argument('--checkpoint', required=True, type=Path); inspect.add_argument('--checkpoint-sha256', required=True)
    inspect.add_argument('--out', required=True, type=Path); inspect.add_argument('--reference-enabled', action='store_true')
    inspect.add_argument('--title-mode', choices=('pristine', 'enhanced'), default='pristine')
    inspect.add_argument('--title-setting', action='append', default=[])
    compare = commands.add_parser('compare', help='Freshly re-admit and compare two retained inspections')
    compare.add_argument('--left', required=True, type=Path); compare.add_argument('--right', required=True, type=Path)
    compare.add_argument('--left-receipt-sha256', required=True); compare.add_argument('--right-receipt-sha256', required=True)
    compare.add_argument('--out', required=True, type=Path); compare.add_argument('--policy', choices=('exact', 'tier-counters'), default='exact')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'inspect':
            from .title_adapter import parse_settings
            report = inspect_checkpoint(args.descriptor, args.build, args.checkpoint, args.out,
                expected_checkpoint_sha256=args.checkpoint_sha256, reference_enabled=args.reference_enabled,
                title_mode=args.title_mode, title_settings=parse_settings(args.title_setting) if args.title_setting else None)
        else:
            report = compare_checkpoint_inspections(args.left, args.right, args.out,
                expected_left_receipt_sha256=args.left_receipt_sha256, expected_right_receipt_sha256=args.right_receipt_sha256,
                policy=args.policy)
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('Checkpoint diagnostic refused: '+str(error), file=sys.stderr)
        return 2
    print(json.dumps(dict(passed=report['passed'], **({'equal': report['equal']} if 'equal' in report else {})), indent=2))
    return 1 if report.get('equal') is False else 0


if __name__ == '__main__': raise SystemExit(main())
