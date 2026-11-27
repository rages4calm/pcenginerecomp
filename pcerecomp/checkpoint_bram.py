"""Source-bound offline developer checkpoint BRAM diagnostics, not player saves."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from . import project
from .declarations import _ordinary
from .snapshots import SnapshotStore

FORMAT = 'pce-checkpoint-bram-export-1'
RUNTIME_FORMAT = 'pce-checkpoint-bram-diagnostic-1'
MAX_CHECKPOINT = 64 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


def _directory(path):
    for candidate in (*reversed(path.parents), path):
        info = candidate.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('Diagnostic directories must be ordinary without links/reparse points')


def _path(value):
    return Path(os.path.abspath(os.fspath(value)))


def _owned_directory(path, identity):
    _directory(path)
    info=path.lstat()
    if (info.st_dev,info.st_ino)!=identity:
        raise ValueError('Diagnostic output directory was replaced; no further writes are allowed')


def _publish_receipt(output, identity, report):
    """Flush a complete JSON file, then atomically publish without replacement."""
    from .build_cache import _rename_new
    _owned_directory(output,identity)
    raw=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode('utf-8')
    fd,name=tempfile.mkstemp(prefix='receipt-',suffix='.pending',dir=output)
    temporary=Path(name);opened=os.fstat(fd);owned=(opened.st_dev,opened.st_ino)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        _owned_directory(output,identity)
        _rename_new(temporary,output/'receipt.json')
    finally:
        # Never recreate a vanished directory or remove another writer's name.
        try:
            _owned_directory(output,identity)
            info=temporary.lstat()
            if (info.st_dev,info.st_ino)==owned:temporary.unlink()
        except (OSError,ValueError):pass


def _source(descriptor, build_dir):
    checked, built, binary, receipt_sha = project._verified_package(descriptor, build_dir)
    if checked['tool_root'] != ROOT or checked['tool_identity'] != project.source_identity(ROOT):
        raise ValueError('Run the diagnostic from the exact producer SDK; no cross-SDK checkpoint rebinding')
    if 'title_adapter' in checked['config']:
        raise ValueError('Checkpoint BRAM diagnostics do not support adapter-bearing packages in v1')
    if checked['config'].get('boot', {}).get('mode') == 'hucard-reset':
        raise ValueError('Checkpoint BRAM diagnostics require CD backup memory, not HuCard boot')
    return checked, built, binary, receipt_sha


def _runtime_receipt(value, expected_sha, output_sha):
    project._table(value, {'schema','format','diagnostic_only','executed','restored','native_steps',
        'interpreter_steps','network_started','presentation_started','game_save_validated',
        'checkpoint_identity','checkpoint_sha256','core_sha256','bram_sha256','bytes',
        'physical_address','source_state'}, name='checkpoint BRAM runtime receipt')
    if type(value['schema']) is not int or value['schema'] != 1 or value['format'] != RUNTIME_FORMAT:
        raise ValueError('Unsupported checkpoint BRAM runtime receipt')
    for key in ('executed','restored','network_started','presentation_started','game_save_validated'):
        if value[key] is not False: raise ValueError('Diagnostic must not execute, restore or claim game SAVE validity')
    if value['diagnostic_only'] is not True:
        raise ValueError('Missing explicit diagnostic label')
    for key in ('native_steps','interpreter_steps'):
        project._integer(value[key], 0, 0, 'diagnostic '+key)
    for key in ('checkpoint_identity','checkpoint_sha256','core_sha256','bram_sha256'):
        project._digest(value[key], key)
    if value['checkpoint_sha256'] != expected_sha or value['bram_sha256'] != output_sha:
        raise ValueError('Diagnostic source/output hash differs')
    project._integer(value['bytes'], 2048, 2048, 'BRAM bytes')
    project._integer(value['physical_address'], 0x1EE000, 0x1EE000, 'BRAM address')
    state=project._table(value['source_state'], {'ticks','frame','raster_frames','native_steps',
        'interpreter_steps','pending_pcm_frames','source_wav_frames'}, name='imported source state')
    for key,item in state.items(): project._integer(item, 0, (1<<64)-1, 'source '+key)
    return value


def export_checkpoint_bram(descriptor, build_dir, checkpoint, output, *,
                           expected_checkpoint_sha256, reference_enabled=False):
    """Copy exactly 2048 diagnostic bytes without live restore or guest work.

    Output is a new directory under an existing ordinary parent. Its receipt is
    the success marker, written only after source/package/output revalidation.
    A failed operation retains its own partial diagnostics as explicitly failed.
    The caller owns the decision to use any image as a future developer seed.
    """
    project._digest(expected_checkpoint_sha256, 'expected checkpoint')
    if type(reference_enabled) is not bool: raise ValueError('reference_enabled must be boolean')
    descriptor=_path(descriptor);build_dir=_path(build_dir);checkpoint=_path(checkpoint);output=_path(output)
    name=project._checkpoint_name(checkpoint.name)
    _ordinary(checkpoint,MAX_CHECKPOINT);_directory(output.parent)
    if output.exists() or output.is_symlink(): raise ValueError('Diagnostic requires a new output directory')
    store=SnapshotStore();source_snapshot=store.bind(checkpoint,expected_sha256=expected_checkpoint_sha256)
    checked,built,binary,receipt_sha=_source(descriptor,build_dir)
    # Never write diagnostic output into a closed SDK, package or consumer graph.
    for protected in (checked['tool_root'],checked['files']['module_manifest'].parent,
                      build_dir,binary.parent,checkpoint):
        if output==protected or protected in output.parents:
            raise ValueError('Diagnostic output overlaps a protected source/build graph')
    command=project.command_for(checked,binary,dev_port=0,start_paused=True,
        checkpoint_dir=checkpoint.parent,reference_enabled=reference_enabled)
    command += ['--checkpoint-bram-export',name,'--checkpoint-bram-sha',expected_checkpoint_sha256,
                '--checkpoint-bram-output',str(output/'bram.bin')]
    # Reservation ownership is granted only by our successful mkdir; a racing
    # caller's existing directory can never receive our failure receipt.
    report=dict(schema=1,format=FORMAT,passed=False,diagnostic_only=True,
        executed=False,restored=False,execution_evidence=False,game_save_validated=False,
        source=dict(binding=project._binding(checked),build_receipt_sha256=receipt_sha,
                    binary=str(binary),binary_sha256=built['binary_sha256'],output_files=built['output_files']),
        checkpoint=dict(path=str(checkpoint),sha256=expected_checkpoint_sha256,bytes=source_snapshot.size_bytes),
        reference_enabled=reference_enabled,command=command,
        scope='Read-only source-bound developer diagnostic; not proof of game SAVE validity, qualification or portable player-save compatibility')
    output.mkdir();info=output.lstat();owned=(info.st_dev,info.st_ino)
    try:
        store.revalidate();_ordinary(checkpoint,MAX_CHECKPOINT);_owned_directory(output,owned)
        environment=os.environ.copy()
        # No host hardware is needed even for a source desktop executable.
        environment.update(SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy',SDL_RENDER_DRIVER='software')
        with (output/'runtime.json').open('xb') as stdout,(output/'stderr.log').open('xb') as stderr:
            done=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                env=environment,check=False,timeout=180,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        _owned_directory(output,owned)
        report['exit_code']=done.returncode
        if done.returncode!=0: raise ValueError('Offline consumer diagnostic refused; see retained stderr.log')
        metadata=store.read_json(output/'runtime.json',max_bytes=64*1024).value
        image=output/'bram.bin';_ordinary(image,2048,2048);image_snapshot=store.bind(image)
        _runtime_receipt(metadata,expected_checkpoint_sha256,image_snapshot.sha256)
        if (output/'stderr.log').read_bytes().find(b'PCE_DEV_PORT=')!=-1:
            raise ValueError('Offline diagnostic unexpectedly opened a development server')
        after,after_built,_,after_sha=_source(descriptor,build_dir)
        if (project._binding(after)!=project._binding(checked) or after_sha!=receipt_sha
                or after_built['output_files']!=built['output_files']):
            raise ValueError('Source package changed during diagnostic export')
        _ordinary(checkpoint,MAX_CHECKPOINT);_owned_directory(output,owned);store.revalidate()
        report.update(passed=True,runtime=metadata,output=dict(path=str(image),bytes=2048,sha256=image_snapshot.sha256),
                      runtime_receipt_sha256=project.sha256(output/'runtime.json'))
        _publish_receipt(output,owned,report)
        return report
    except BaseException as error:
        report.update(passed=False,error=dict(type=type(error).__name__,message=str(error)))
        try:
            _owned_directory(output,owned)
            if not (output/'receipt.json').exists():_publish_receipt(output,owned,report)
        except (OSError,ValueError):pass
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('descriptor',type=Path)
    parser.add_argument('--build',required=True,type=Path)
    parser.add_argument('--checkpoint',required=True,type=Path)
    parser.add_argument('--checkpoint-sha256',required=True)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--reference-enabled',action='store_true')
    args=parser.parse_args(argv)
    result=export_checkpoint_bram(args.descriptor,args.build,args.checkpoint,args.out,
        expected_checkpoint_sha256=args.checkpoint_sha256,reference_enabled=args.reference_enabled)
    print(json.dumps(dict(passed=result['passed'],diagnostic_only=True,output=result['output']),indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
