"""Managed stable-module rebuilds for the audited Windows LLVM-MinGW profile.

Each workspace belongs to this producer. It never updates a caller's module,
descriptor, installation or save. Failed/interrupted generations fail closed;
start a new workspace rather than repairing retained objects in place.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from . import project
from .build_inputs import (prepare, configuration_identity, verify_closure,
                           tree_identity, _linked)


def _plain(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            if _linked(item.lstat()):
                raise ValueError('Managed paths cannot contain links or reparse points')
    return path.resolve()


def _read(path):
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Managed metadata exceeds 64 MiB')
    return json.loads(path.read_text(encoding='utf-8'))


def _snapshot(root):
    """Bind bytes and mtimes, including objects and Ninja dependency records."""
    identity = tree_identity(root)
    times = {p.relative_to(root).as_posix(): p.stat().st_mtime_ns
             for p in root.rglob('*') if p.is_file()}
    return dict(identity=identity, mtimes=times)


def _module(checked):
    manifest = _read(checked['files']['module_manifest'])
    if (manifest.get('partition_layout') != 'stable'
            or manifest.get('partition_identity') != 'full_mpr_logical_pc_range_v1'
            or type(manifest.get('pc_bucket_size')) is not int
            or manifest['pc_bucket_size'] != 256 or manifest.get('partitioned') is not True):
        raise ValueError('Managed rebuild requires stable full-MPR/256-PC module layout')
    files = {p.name: p for k, p in checked['files'].items()
             if k.startswith(('module_unit:', 'module_header:'))}
    if (checked['files']['module_source'].name != 'module.cpp'
            or checked['files']['module_manifest'].name != 'module.json'
            or not files or 'module.cpp' not in files):
        raise ValueError('Managed rebuild requires complete emitted module artifacts')
    files['module.json'] = checked['files']['module_manifest']
    if 'module_declared_roots' in checked['files'] and 'module_discovery' not in checked['files']:
        name = 'declared-roots.json'
        if any(existing.casefold() == name for existing in files):
            raise ValueError('Managed declared roots filename collides with module artifact')
        _plain(checked['descriptor'].parent/checked['config']['module']['declared_roots']['path'])
        files[name] = checked['files']['module_declared_roots']
    if 'module_discovery' in checked['files']:
        if any(name.casefold() == 'discovery' or name.casefold().startswith('discovery/') for name in files):
            raise ValueError('Managed discovery namespace collides with module artifact')
        _plain(checked['descriptor'].parent/checked['config']['module']['discovery']['path'])
        _plain(checked['descriptor'].parent/checked['config']['module']['declared_roots']['path'])
        files.update({'discovery/'+name:path for name,path in _discovery_files(checked).items()})
    if 'module_observation_profile' in checked['files']:
        name = 'observation-profile.json'
        if any(existing.casefold() == name for existing in files):
            raise ValueError('Managed observation profile filename collides with module artifact')
        # Verification resolves input files. Check the declared spelling too,
        # so a linked original profile cannot disappear behind that resolution.
        declared = checked['config']['module']['observation_profile']['path']
        _plain(checked['descriptor'].parent / declared)
        files[name] = checked['files']['module_observation_profile']
    if 'module_observation_history' in checked['files']:
        declared = checked['config']['module']['observation_history']['path']
        _plain(checked['descriptor'].parent / declared)
        graph = {'history.json': checked['files']['module_observation_history']}
        graph.update({key.removeprefix('module_history:'): value
                      for key, value in checked['files'].items() if key.startswith('module_history:')})
        if any(name.casefold() == 'observation-history' for name in files):
            raise ValueError('Managed observation history namespace collides with module artifact')
        for relative, path in graph.items():
            if relative != 'history.json' and re.fullmatch(
                    r'(?:captures/[0-9a-f]{64}\.json|catalogue/[0-9a-f]{64}\.jsonl)', relative) is None:
                raise ValueError('Invalid managed observation history artifact name')
            files['observation-history/'+relative] = path
    if len(files) != len(set(n.casefold() for n in files)):
        raise ValueError('Managed module filenames collide')
    for path in files.values():
        _plain(path)
    return files


def _toml(config):
    """Encode the verified schema-1 subset, without editing arbitrary TOML."""
    lines = []
    def table(value, prefix=()):
        if prefix:
            lines.append('[' + '.'.join(prefix) + ']')
        for key, item in value.items():
            if not isinstance(item, dict):
                lines.append(key + ' = ' + json.dumps(item, ensure_ascii=False))
        lines.append('')
        for key, item in value.items():
            if isinstance(item, dict):
                table(item, (*prefix, key))
    table(config)
    return '\n'.join(lines)


def _config(checked, workspace, files):
    config = copy.deepcopy(checked['config'])
    config['tool']['path'] = str(checked['tool_root'])
    for key in project.ASSETS | {'payload'}:
        if key in config:
            config[key]['path'] = str(checked['files'][key])
    for key, name in (('source', 'module.cpp'), ('manifest', 'module.json')):
        config['module'][key] = dict(path=str(workspace/'module'/name),
                                    sha256=project.sha256(files[name]))
    if 'observation_profile' in config['module']:
        name = 'observation-profile.json'
        config['module']['observation_profile'] = dict(
            path=str(workspace/'module'/name), sha256=project.sha256(files[name]))
    if 'declared_roots' in config['module']:
        name = 'discovery/roots.json' if 'discovery' in config['module'] else 'declared-roots.json'
        config['module']['declared_roots'] = dict(
            path=str(workspace/'module'/name),sha256=project.sha256(files[name]))
    if 'discovery' in config['module']:
        name = 'discovery/discovery.json'
        config['module']['discovery'] = dict(
            path=str(workspace/'module'/name),sha256=project.sha256(files[name]))
    if 'observation_history' in config['module']:
        name = 'observation-history/history.json'
        config['module']['observation_history'] = dict(
            path=str(workspace/'module'/name), sha256=project.sha256(files[name]))
    return config


def _fixed_config(config):
    config = copy.deepcopy(config)
    del config['module']
    return config


def _fixed_contract(context):
    value = copy.deepcopy(context['contract'])
    del value['module_inputs']
    del value['trees']['module']
    return value


def _sync(files, target, *, old=None, newer_than=0):
    """Update owned module/history artifacts; identical bytes retain mtimes."""
    changed, unchanged, removed = [], [], []
    before = {} if old is None else old
    for name, source in sorted(files.items()):
        path = target/name
        _plain(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() == source.read_bytes():
            unchanged.append(name)
            continue
        data = source.read_bytes()
        with path.open('wb' if name in before else 'xb') as stream:
            stream.write(data)
        # Never trust a candidate's timestamps for dependency invalidation.
        os.utime(path, None)
        if path.stat().st_mtime_ns <= newer_than:
            raise ValueError('Clock resolution/regression prevents safe source invalidation')
        changed.append(name)
    for name in sorted(before.keys() - files.keys()):
        _plain(target/name).unlink()  # Only a previously verified owned artifact.
        removed.append(name)
    return dict(changed=changed, unchanged=unchanged, removed=removed)


def _history_state(checked):
    """Exact archive closure; paths are fixed, digest-derived history names."""
    if 'module_observation_history' not in checked['files']:
        return None
    files = _module(checked)
    return dict(file='observation-history/history.json',
        sha256=checked['identities']['module_observation_history'],
        artifacts=[dict(file=name, sha256=project.sha256(path), size_bytes=path.stat().st_size)
                   for name, path in sorted(files.items()) if name.startswith('observation-history/')])


def _check_declared_archive(root,binding,*,discovery=False):
    project._table(binding,{'file','sha256'},name='managed declared roots')
    if binding['file'] != ('discovery/roots.json' if discovery else 'declared-roots.json'):
        raise ValueError('Invalid managed declared roots filename')
    source = _plain(root/binding['file'])
    if project.sha256(source) != project._digest(binding['sha256'],'managed declared roots'):
        raise ValueError('Retained declared roots archive changed outside producer')


def _discovery_files(checked):
    from .discovery import REPORT_NAME, ROOTS_NAME, SEEDS_NAME
    graph = {REPORT_NAME:checked['files']['module_discovery']}
    graph.update({key.removeprefix('module_discovery:'):path
                  for key,path in checked['files'].items() if key.startswith('module_discovery:')})
    if set(graph) != {REPORT_NAME, ROOTS_NAME, SEEDS_NAME}:
        raise ValueError('Managed discovery requires its exact three-file closure')
    return graph


def _discovery_state(checked):
    if 'module_discovery' not in checked['files']:
        return None
    return dict(file='discovery/discovery.json',sha256=checked['identities']['module_discovery'],
        artifacts=[dict(file='discovery/'+name,sha256=project.sha256(path),size_bytes=path.stat().st_size)
                   for name,path in sorted(_discovery_files(checked).items())])


def _check_discovery_archive(root,binding,image):
    from .discovery import load_discovery
    project._table(binding,{'file','sha256','artifacts'},name='managed discovery')
    if binding['file'] != 'discovery/discovery.json':
        raise ValueError('Invalid managed discovery filename')
    admitted = load_discovery(_plain(root/binding['file']),image)
    if admitted.sha256 != project._digest(binding['sha256'],'managed discovery'):
        raise ValueError('Retained discovery changed outside producer')
    actual = [dict(file='discovery/'+name,sha256=item['sha256'],size_bytes=item['size_bytes'])
              for name,item in sorted(admitted.artifact_bindings.items()) if name != 'source_image']
    if binding['artifacts'] != actual:
        raise ValueError('Retained discovery graph changed outside producer')
    admitted.revalidate()
    return admitted


def _check_history_archive(root, binding):
    from .history import load_history
    project._table(binding, {'file', 'sha256', 'artifacts'}, name='managed observation history')
    if binding['file'] != 'observation-history/history.json':
        raise ValueError('Invalid managed observation history filename')
    admitted = load_history(_plain(root/binding['file']))
    if admitted.index_sha256 != project._digest(binding['sha256'], 'managed observation history'):
        raise ValueError('Retained observation history changed outside producer')
    actual = [dict(file='observation-history/'+relative, sha256=item['sha256'],
                   size_bytes=item['size_bytes'])
              for relative, item in sorted(admitted.artifact_bindings.items())]
    if binding['artifacts'] != actual:
        raise ValueError('Retained observation history graph changed outside producer')
    admitted.revalidate()
    return admitted


def _history_extension(previous_index, candidate):
    """Retain raw identities and the exact selection decisions already made."""
    old_inputs = {item['sha256'] for item in previous_index['inputs']}
    new_inputs = {item['sha256'] for item in candidate.index['inputs']}
    stages = previous_index['selection_stages']
    next_index = candidate.index
    old_version, new_version = previous_index.get('schema', 1), next_index['schema']
    capacity_preserved = (next_index['capacity'] == previous_index['capacity'] if new_version == 1
                          else next_index['capacity'] >= previous_index['capacity'])
    if (not old_inputs <= new_inputs
            or new_version < old_version
            or next_index['selection_stages'][:len(stages)] != stages
            or not capacity_preserved
            or next_index['selection_policy'] != previous_index['selection_policy']):
        raise ValueError('Managed observation history must retain prior inputs, selection stages, policy and capacity')


def _legacy_profile_lineage(workspace, state, binding):
    project._table(binding, {'generation', 'state_sha256', 'file', 'sha256'},
                   name='managed observation profile migration')
    generation = project._integer(binding['generation'], 0, state['generation']-1,
                                  'migrated profile generation')
    if binding['file'] != 'observation-profile.json':
        raise ValueError('Invalid migrated observation profile filename')
    root = workspace/'history'/f'{generation:06d}'
    prior_state = _plain(root/'state.json')
    if project.sha256(prior_state) != project._digest(binding['state_sha256'], 'migrated profile state'):
        raise ValueError('Migrated observation profile state changed outside producer')
    original = _read(prior_state)
    if original.get('observation_profile') != dict(file=binding['file'], sha256=binding['sha256']):
        raise ValueError('Migrated observation profile binding disagrees with original state')
    artifact = _plain(root/binding['file'])
    if project.sha256(artifact) != project._digest(binding['sha256'], 'migrated observation profile'):
        raise ValueError('Migrated observation profile changed outside producer')


@contextmanager
def _lock(workspace):
    path = workspace/'producer.lock'
    with path.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        path.unlink()


def _state(workspace):
    if (workspace/'in-progress.json').exists():
        raise ValueError('Incomplete generation; use a new workspace (no automatic repair)')
    pointer = _read(workspace/'current.json')
    if (set(pointer) != {'generation', 'sha256'}
            or type(pointer['generation']) is not int or not 0 <= pointer['generation'] <= 999999):
        raise ValueError('Invalid managed generation pointer')
    path = workspace/'history'/f"{pointer['generation']:06d}"/'state.json'
    if project.sha256(path) != pointer['sha256']:
        raise ValueError('Managed generation identity changed')
    state = _read(path)
    if state['generation'] != pointer['generation'] or state['schema'] != 1:
        raise ValueError('Invalid managed generation state')
    if 'observation_profile' in state:
        profile = project._table(state['observation_profile'], {'file', 'sha256'},
                                 name='managed observation profile')
        if profile['file'] != 'observation-profile.json':
            raise ValueError('Invalid managed observation profile filename')
        artifact = _plain(path.parent/profile['file'])
        expected = project._digest(profile['sha256'], 'managed observation profile')
        if not artifact.is_file() or project.sha256(artifact) != expected:
            raise ValueError('Retained observation profile history changed outside producer')
    if 'observation_history' in state:
        _check_history_archive(path.parent, state['observation_history'])
    if 'declared_roots' in state:
        _check_declared_archive(path.parent,state['declared_roots'],discovery='discovery' in state)
    if 'discovery' in state:
        fixed = state.get('fixed_config',{})
        if fixed.get('boot',{}).get('mode') != 'hucard-reset' or 'declared_roots' not in state:
            raise ValueError('Managed discovery requires archived declarations and HuCard source')
        image = project._file(workspace,fixed.get('cartridge',{}),'managed discovery cartridge')
        admitted = _check_discovery_archive(path.parent,state['discovery'],image)
        if admitted.declarations.sha256 != state['declared_roots']['sha256']:
            raise ValueError('Managed discovery differs from archived declarations')
    if 'observation_history_legacy_profile' in state:
        _legacy_profile_lineage(workspace, state, state['observation_history_legacy_profile'])
    if (_snapshot(workspace/'output') != state['build_tree']
            or _snapshot(workspace/'module') != state['module_tree']
            or project.sha256(workspace/'project.toml') != state['descriptor_sha256']):
        raise ValueError('Retained build, module or descriptor changed outside producer')
    return state


def validate_run(build_dir, receipt):
    """Reject stale or interrupted managed output through the official runner."""
    workspace = _plain(build_dir).parent
    metadata = receipt['incremental']
    if metadata.get('workspace') != str(workspace) or Path(build_dir).resolve() != workspace/'output':
        raise ValueError('Managed receipt belongs to a different workspace')
    state = _state(workspace)
    if metadata.get('generation') != state['generation']:
        raise ValueError('Managed build receipt generation is not current')


def rebuild(descriptor: Path, workspace: Path, *, create=False, desktop=False,
            toolchain_root=None, dependency_roots=(), cmake_args=(),
            allow_revision_override=False):
    workspace = _plain(workspace)
    candidate = project.verify(descriptor, allow_revision_override=allow_revision_override)
    files = _module(candidate)
    if (workspace == Path(workspace.anchor) or workspace.is_relative_to(candidate['tool_root'])
            and not workspace.is_relative_to(candidate['tool_root']/'.local')):
        raise ValueError('Workspace must be private and separate from toolkit source')
    input_paths = [candidate['descriptor'], *candidate['files'].values()]
    if any(p.is_relative_to(workspace) for p in input_paths):
        raise ValueError('Candidate input must be outside managed workspace')
    if type(create) is not bool or type(desktop) is not bool:
        raise ValueError('create and desktop must be boolean')
    if create:
        if workspace.exists():
            raise ValueError('Workspace exists; choose a new directory')
        if desktop and candidate['config']['runtime']['video'] != 'continuous':
            raise ValueError('Desktop requires continuous video')
        options = dict(desktop=desktop, toolchain_root=str(Path(toolchain_root).resolve())
                       if toolchain_root is not None else None,
                       dependency_roots=[str(Path(p).resolve()) for p in dependency_roots],
                       cmake_args=list(cmake_args))
        workspace.mkdir(parents=True)
    else:
        if any((desktop, toolchain_root is not None, dependency_roots, cmake_args)):
            raise ValueError('Update uses the original explicit build options')
        if not workspace.is_dir():
            raise ValueError('Managed workspace does not exist')
    started = time.monotonic()
    with _lock(workspace):
        previous = None if create else _state(workspace)
        if previous and 'declared_roots' in previous and 'module_declared_roots' not in candidate['files']:
            raise ValueError('Managed declared roots binding cannot be removed; use a new workspace')
        if previous and 'discovery' in previous and 'module_discovery' not in candidate['files']:
            raise ValueError('Managed discovery binding cannot be removed; use a new workspace')
        legacy_profile_lineage = previous.get('observation_history_legacy_profile') if previous else None
        if (previous and 'observation_profile' in previous
                and 'module_observation_profile' not in candidate['files']
                and 'module_observation_history' not in candidate['files']):
            raise ValueError('Managed observation profile binding cannot be removed; use a new workspace')
        if (previous and 'observation_profile' in previous
                and 'module_observation_history' in candidate['files']):
            from .history import load_history
            from .observations import SELECTION_POLICY, load_observation_profile_details
            prior_root = workspace/'history'/f"{previous['generation']:06d}"
            prior_path = _plain(prior_root/previous['observation_profile']['file'])
            profile, digest, _, _ = load_observation_profile_details(prior_path)
            if digest != previous['observation_profile']['sha256']:
                raise ValueError('Prior observation profile changed during migration')
            stages = (profile['selection_stages'] if profile['schema'] == 2
                      else [[item['sha256'] for item in profile['inputs']]])
            new_history = load_history(candidate['files']['module_observation_history'])
            _history_extension(dict(schema=1, inputs=profile['inputs'], selection_stages=stages,
                                    selection_policy=SELECTION_POLICY, capacity=profile['capacity']), new_history)
            new_history.revalidate()
            legacy_profile_lineage = dict(generation=previous['generation'],
                state_sha256=project.sha256(prior_root/'state.json'),
                file='observation-profile.json', sha256=digest)
        if (previous and 'observation_history' in previous
                and 'module_observation_history' not in candidate['files']):
            raise ValueError('Managed observation history binding cannot be removed; use a new workspace')
        if previous and 'observation_history' in previous:
            from .history import load_history
            old_history = _check_history_archive(workspace/'history'/f"{previous['generation']:06d}",
                                                 previous['observation_history'])
            new_history = load_history(candidate['files']['module_observation_history'])
            _history_extension(old_history.index, new_history)
            old_history.revalidate(); new_history.revalidate()
        if previous:
            options = previous['options']
        config = _config(candidate, workspace, files)
        if previous and _fixed_config(config) != previous['fixed_config']:
            raise ValueError('Only module may change; new toolkit/runtime/input/options require a new workspace')
        # Validate the full external build contract before touching retained inputs.
        # prepare needs the module root but not its contents on initial creation.
        if create:
            (workspace/'module').mkdir()
        prospective = dict(candidate, files=dict(candidate['files'],
            module_source=workspace/'module/module.cpp'))
        args = dict(generator='Ninja', desktop=options['desktop'],
                    cmake_args=options['cmake_args'], toolchain_root=options['toolchain_root'],
                    dependency_roots=options['dependency_roots'], build_dir=workspace/'output',
                    cache_root=workspace/'unused-package-cache')
        context = prepare(prospective, **args)
        fixed = _fixed_contract(context)
        if previous and fixed != previous['external_contract']:
            raise ValueError('Compiler, SDK, options or toolkit identity changed; use a new workspace')
        generation = 0 if previous is None else previous['generation'] + 1
        if generation > 999999:
            raise ValueError('Managed generation bound reached; use a new workspace')
        history = workspace/'history'/f'{generation:06d}'
        history.mkdir(parents=True)  # Retained failures are never overwritten.
        project._write_new(workspace/'in-progress.json', dict(generation=generation))
        newest = max(previous['build_tree']['mtimes'].values(), default=0) if previous else 0
        if newest >= time.time_ns():
            raise ValueError('Retained output is from the future; use a new workspace after clock recovery')
        old_names = previous['module_tree']['mtimes'] if previous else None
        changes = _sync(files, workspace/'module', old=old_names, newer_than=newest)
        descriptor_text = _toml(config)
        current_descriptor = workspace/'project.toml'
        if not current_descriptor.exists() or current_descriptor.read_text(encoding='utf-8') != descriptor_text:
            current_descriptor.write_text(descriptor_text, encoding='utf-8', newline='\n')
        checked = project.verify(current_descriptor, allow_revision_override=allow_revision_override)
        # Rehash the actual copied module (the earlier prospective entry is not a build binding).
        context = prepare(checked, **args)
        if _fixed_contract(context) != fixed:
            raise ValueError('External inputs changed during module update')
        if create:
            commands = project._configure_build(checked, workspace/'output', generator='Ninja',
                desktop=options['desktop'], cmake_args=options['cmake_args'], cache_context=context)
        else:
            commands = [previous['configure_command']]
            subprocess.run(commands[0], check=True, shell=False, env=context['environment'])
        configured = configuration_identity(context, workspace/'output/build')
        before_objects = {} if previous is None else {
            k: v for k, v in previous['build_tree']['mtimes'].items() if k.endswith(('.obj', '.o'))}
        receipt = project._compile_configured(checked, workspace/'output',
            allow_revision_override=allow_revision_override, desktop=options['desktop'],
            commands=commands, cache_context=context)
        audit = verify_closure(context, workspace/'output/build')
        if configuration_identity(context, workspace/'output/build') != configured:
            raise ValueError('Effective build configuration changed during compilation')
        if prepare(checked, **args)['contract'] != context['contract']:
            raise ValueError('Compiler, SDK or source inputs changed during compilation')
        if project._binding(project.verify(descriptor, allow_revision_override=allow_revision_override)) != project._binding(candidate):
            raise ValueError('Candidate changed during rebuild')
        object_files = {p.relative_to(workspace/'output').as_posix(): p.stat().st_mtime_ns
                        for p in (workspace/'output').rglob('*') if p.suffix in ('.obj', '.o')}
        object_work = dict(retained=sorted(k for k, v in object_files.items() if before_objects.get(k) == v),
                           rebuilt=sorted(k for k, v in object_files.items() if k in before_objects and before_objects[k] != v),
                           added=sorted(object_files.keys() - before_objects.keys()),
                           obsolete=sorted(before_objects.keys() - object_files.keys()))
        receipt['incremental'] = dict(schema=1, generation=generation, workspace=str(workspace), module_changes=changes,
            object_timestamps=object_work, input_audit=audit, elapsed_seconds=time.monotonic()-started,
            scope='Managed same-workspace rebuild; retained object bytes and mtimes verified before reconfiguration. No execution evidence.')
        # History is create-new. The live receipt/pointer are published only after all checks.
        project._write_new(history/'build-receipt.json', receipt)
        (history/'project.toml').write_text(descriptor_text, encoding='utf-8', newline='\n')
        (history/'module.json').write_bytes((workspace/'module/module.json').read_bytes())
        if 'module_observation_profile' in checked['files']:
            (history/'observation-profile.json').write_bytes(
                checked['files']['module_observation_profile'].read_bytes())
        discovery_binding = _discovery_state(checked)
        if discovery_binding is not None:
            for item in discovery_binding['artifacts']:
                source = workspace/'module'/item['file']
                raw = source.read_bytes()
                if project.sha256(source) != item['sha256'] or len(raw) != item['size_bytes']:
                    raise ValueError('Discovery changed while archiving generation')
                target = history/item['file']; target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(raw)
            _check_discovery_archive(history,discovery_binding,checked['files']['cartridge'])
        declared_binding = None
        if 'module_declared_roots' in checked['files']:
            declared_binding = dict(file='discovery/roots.json' if discovery_binding else 'declared-roots.json',
                                    sha256=checked['identities']['module_declared_roots'])
            if discovery_binding is None:
                with (history/declared_binding['file']).open('xb') as stream:
                    stream.write(checked['files']['module_declared_roots'].read_bytes())
            _check_declared_archive(history,declared_binding,discovery=discovery_binding is not None)
        history_binding = _history_state(checked)
        if history_binding is not None:
            for item in history_binding['artifacts']:
                source = workspace/'module'/item['file']
                raw = source.read_bytes()
                if project.sha256(source) != item['sha256'] or len(raw) != item['size_bytes']:
                    raise ValueError('Observation history changed while archiving generation')
                target = history/item['file']; target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(raw)
            _check_history_archive(history, history_binding)
        live_receipt = workspace/'output/build-receipt.json'
        temporary = live_receipt.with_suffix('.next')
        project._write_new(temporary, receipt)
        os.replace(temporary, live_receipt)
        state = dict(schema=1, generation=generation, options=options, fixed_config=_fixed_config(config),
            external_contract=fixed, configure_command=commands[0],
            descriptor_sha256=project.sha256(current_descriptor),
            module_tree=_snapshot(workspace/'module'), build_tree=_snapshot(workspace/'output'))
        if 'module_observation_profile' in checked['files']:
            state['observation_profile'] = dict(file='observation-profile.json',
                sha256=checked['identities']['module_observation_profile'])
        if history_binding is not None:
            state['observation_history'] = history_binding
        if declared_binding is not None:
            state['declared_roots'] = declared_binding
        if discovery_binding is not None:
            state['discovery'] = discovery_binding
        if legacy_profile_lineage is not None:
            state['observation_history_legacy_profile'] = legacy_profile_lineage
            _legacy_profile_lineage(workspace, state, legacy_profile_lineage)
        project._write_new(history/'state.json', state)
        pointer = workspace/'current.next'
        project._write_new(pointer, dict(generation=generation, sha256=project.sha256(history/'state.json')))
        os.replace(pointer, workspace/'current.json')
        (workspace/'in-progress.json').unlink()
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('create', 'update'):
        sub = commands.add_parser(name)
        sub.add_argument('descriptor', type=Path)
        sub.add_argument('--workspace', type=Path, required=True)
        sub.add_argument('--allow-revision-override', action='store_true')
        if name == 'create':
            sub.add_argument('--desktop', action='store_true')
            sub.add_argument('--toolchain-root', type=Path, required=True)
            sub.add_argument('--dependency-root', type=Path, action='append', default=[])
            sub.add_argument('--cmake-arg', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        result = rebuild(args.descriptor, args.workspace, create=args.command == 'create',
            allow_revision_override=args.allow_revision_override,
            **(dict(desktop=args.desktop, toolchain_root=args.toolchain_root,
                    dependency_roots=args.dependency_root, cmake_args=args.cmake_arg)
               if args.command == 'create' else {}))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'incremental: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
