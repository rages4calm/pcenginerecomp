"""Prepare an explicitly configured, pinned native consumer without launching it.

Inputs stay read-only. Observations become a self-contained history; media stays
at its declared location. Preparation is not compilation or execution evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib

from . import project
from .abi import ABI

FORMAT = 'pce-consumer-prepare-1'
MAX_SPEC_BYTES = 1024 * 1024
TOOL_ROOT = Path(__file__).resolve().parent.parent


def _path(base, value, label, *, directory=False):
    if type(value) is not str or not value or '\0' in value:
        raise ValueError('Invalid '+label+' path')
    path = Path(os.path.abspath(base/value))
    if not path.is_file() and not (directory and path.is_dir()):
        raise ValueError('Missing '+label+' file')
    return path


def _relative(path, base):
    # Absolute paths remain explicit on Windows when assets use another drive.
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:
        return path.as_posix()


def _value(value):
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    if type(value) is list:
        return '['+', '.join(_value(item) for item in value)+']'
    raise ValueError('Unsupported recipe value')


def _toml(value):
    lines = []

    def table(data, prefix=()):
        if prefix:
            lines.append('['+'.'.join(prefix)+']')
        for key, item in data.items():
            if type(item) is not dict:
                lines.append(key+' = '+_value(item))
        for key, item in data.items():
            if type(item) is dict:
                lines.append('')
                table(item, prefix+(key,))

    table(value)
    return '\n'.join(lines)+'\n'


def _asset(base, entry, label):
    project._table(entry, {'path'}, {'sha256'}, name=label)
    path = _path(base, entry['path'], label)
    cue = None
    if label == 'disc' and path.suffix.lower() == '.cue':
        from .cue import Cue
        cue = Cue(path)
        digest = cue.image_sha256()
    else:
        digest = project.sha256(path)
    if 'sha256' in entry and project._digest(entry['sha256'], label) != digest:
        raise ValueError(label+' SHA256 mismatch')
    return path, digest, cue


def _recipe(path):
    path = Path(path).absolute()
    if not path.is_file() or path.stat().st_size > MAX_SPEC_BYTES:
        raise ValueError('Preparation recipe requires a bounded TOML file')
    raw = path.read_bytes()
    try:
        spec = tomllib.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError('Invalid preparation TOML') from error
    project._table(spec, {'schema', 'format', 'name', 'module', 'runtime', 'limits'},
                   {'sdk', 'boot', 'payload'} | project.ASSETS, name='preparation')
    if type(spec['schema']) is not int or spec['schema'] != 1 or spec['format'] != FORMAT:
        raise ValueError('Unsupported preparation recipe schema/format')
    if type(spec['name']) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', spec['name']) is None:
        raise ValueError('Invalid consumer name')
    if ('boot' in spec) == ('payload' in spec):
        raise ValueError('Choose exactly one explicit boot or payload recipe')
    module = project._table(spec['module'], {'kind', 'path'},
        {'capacity', 'partition_size', 'partition_layout', 'native_span', 'exclude_ranges'}, name='module')
    project._choice(module['kind'], ('capture', 'profile', 'history'), 'module.kind')
    project._integer(module.get('capacity', 65536), 1, 65536, 'capacity')
    project._integer(module.get('partition_size', 256), 1, 4096, 'partition_size')
    project._choice(module.get('partition_layout', 'stable'), ('balanced', 'stable'), 'partition_layout')
    if module.get('partition_layout', 'stable') == 'stable' and module.get('partition_size', 256) != 256:
        raise ValueError('Stable partition layout requires partition_size = 256')
    if type(module.get('native_span', False)) is not bool:
        raise ValueError('native_span requires a boolean')
    if module.get('native_span') and module.get('partition_layout', 'stable') != 'stable':
        raise ValueError('Native span requires stable partition layout')
    exclusions = module.get('exclude_ranges', [])
    if type(exclusions) is not list or len(exclusions) > 256:
        raise ValueError('exclude_ranges requires at most 256 physical ranges')
    for pair in exclusions:
        if type(pair) is not list or len(pair) != 2:
            raise ValueError('Each exclusion requires physical start and byte length')
        project._integer(pair[0], 0, 0x1FFFFF, 'exclusion start')
        project._integer(pair[1], 1, 0x200000-pair[0], 'exclusion length')
    runtime = project._table(spec['runtime'],
        {'tier', 'video', 'cd_unknown_status', 'joypad', 'region', 'multitap'},
        {'audio', 'audio_profile', 'audio_rate', 'audio_timing', 'vdc_access',
         'native_span', 'cd_timing', 'cd_subchannel'}, name='runtime')
    project._choice(runtime['tier'], ('native', 'hybrid'), 'runtime.tier')
    project._choice(runtime['video'], ('snapshot', 'continuous'), 'runtime.video')
    limits = project._table(spec['limits'], {'steps', 'ticks', 'wall_seconds'}, name='limits')
    project._integer(limits['steps'], 1, 20000000000, 'steps')
    project._integer(limits['ticks'], 1, (1 << 64)-1, 'ticks')
    project._integer(limits['wall_seconds'], 1, project.MAX_WALL_SECONDS, 'wall_seconds')
    return path, raw, spec


def prepare_project(spec_path, output):
    """Create a new consumer from an explicit recipe and authentic observations.

    Successful output has a verified descriptor and preparation receipt. Neither
    reports compiled or executed native work. Failures may retain a new partial
    output for diagnosis; existing destinations and all original inputs survive.
    """
    from .capture import load_capture
    from .emitter import emit_history
    from .history import compose_history, load_history
    from .observations import load_observation_profile

    spec_path, raw_spec, spec = _recipe(spec_path)
    base = spec_path.parent
    output = Path(os.path.abspath(output))
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('Preparation requires a new directory in an existing parent')
    kind = spec['module']['kind']
    source = _path(base, spec['module']['path'], 'observation input', directory=kind == 'history')
    if source.resolve().is_relative_to(output.resolve()):
        raise ValueError('Preparation cannot contain its original input')
    # Admit the selected format before allocating a destination. A profile or
    # history cannot masquerade as a raw capture by changing its extension.
    original_history = None
    if kind == 'capture':
        _, source_sha = load_capture(source)
    elif kind == 'profile':
        _, source_sha = load_observation_profile(source)
    else:
        original_history = load_history(source)
        source = original_history.index_path
        source_sha = original_history.index_sha256
        if output.resolve().is_relative_to(source.parent.resolve()):
            raise ValueError('Preparation output cannot modify its original history graph')
    assets = {name: _asset(base, spec[name], name) for name in sorted(project.ASSETS & spec.keys())}
    payload = None
    if 'payload' in spec:
        p = project._table(spec['payload'], {'path', 'physical_load', 'pc', 'mpr'}, {'sha256'}, name='payload')
        project._integer(p['physical_load'], 0, 0x1FFFFF, 'physical_load')
        project._integer(p['pc'], 0, 65535, 'pc')
        if type(p['mpr']) is not list or len(p['mpr']) != 8:
            raise ValueError('Payload requires all eight MPR bytes')
        for byte in p['mpr']:
            project._integer(byte, 0, 255, 'MPR byte')
        payload = _asset(base, {k: p[k] for k in ('path', 'sha256') if k in p}, 'payload')
    sdk = project._table(spec.get('sdk', {}), set(), {'revision', 'allow_revision_override'}, name='sdk')
    allow_override = sdk.get('allow_revision_override', False)
    if type(allow_override) is not bool:
        raise ValueError('allow_revision_override requires a boolean')
    identity = project.source_identity(TOOL_ROOT)
    revision = sdk.get('revision', identity['revision'])
    if type(revision) is not str or re.fullmatch('[0-9a-f]{40}', revision) is None:
        raise ValueError('Preparation requires a Git revision or an explicit vendored SDK revision')
    if identity['revision'] != revision and not allow_override:
        raise ValueError('SDK revision mismatch requires explicit allow_revision_override')
    spec_sha = hashlib.sha256(raw_spec).hexdigest()
    if spec_path.read_bytes() != raw_spec or project.sha256(source) != source_sha:
        raise ValueError('Recipe or observation input changed during admission')
    output.mkdir(exist_ok=False)
    options = spec['module']
    history = compose_history([source] if kind == 'capture' else [], output/'observation-history',
        baseline_profile=source if kind == 'profile' else None,
        baseline_history=source if kind == 'history' else None,
        capacity=options.get('capacity'))
    manifest = emit_history(history.index_path, output/'module',
        partition_size=options.get('partition_size', 256),
        partition_layout=options.get('partition_layout', 'stable'),
        native_span=options.get('native_span', False),
        exclude_ranges=tuple(tuple(pair) for pair in options.get('exclude_ranges', [])))
    config = dict(schema=1, name=spec['name'], tool=dict(path=_relative(TOOL_ROOT, output),
        revision=revision, source_sha256=identity['source_sha256'], runtime_abi=ABI),
        module=dict(source=dict(path='module/module.cpp', sha256=project.sha256(output/'module/module.cpp')),
                    manifest=dict(path='module/module.json', sha256=project.sha256(output/'module/module.json')),
                    observation_history=dict(path='observation-history/history.json', sha256=history.index_sha256)))
    if 'boot' in spec:
        config['boot'] = spec['boot']
    if payload:
        config['payload'] = dict(path=_relative(payload[0], output), sha256=payload[1],
            **{k: spec['payload'][k] for k in ('physical_load', 'pc', 'mpr')})
    for name, (path, digest, _) in assets.items():
        config[name] = dict(path=_relative(path, output), sha256=digest)
    config['runtime'] = spec['runtime']
    config['limits'] = spec['limits']
    descriptor = output/'project.toml'
    with descriptor.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(_toml(config))
    verified = project.verify(descriptor, allow_revision_override=allow_override)
    history.revalidate()
    if original_history is not None:
        original_history.revalidate()
    for name, (path, digest, cue) in assets.items():
        if cue:
            cue.check_unchanged()
            current = cue.image_sha256()
        else:
            current = project.sha256(path)
        if current != digest:
            raise ValueError(name+' changed during preparation')
    if payload and project.sha256(payload[0]) != payload[1]:
        raise ValueError('Payload changed during preparation')
    if project.sha256(source) != source_sha or project.sha256(spec_path) != spec_sha:
        raise ValueError('Preparation input changed')
    if project.source_identity(TOOL_ROOT) != identity:
        raise ValueError('Toolkit source changed during preparation')
    receipt = dict(schema=1, kind='pce-consumer-preparation', prepared=True,
        execution_evidence=False, compiled=False, executed=False,
        recipe=dict(path=str(spec_path), sha256=spec_sha),
        original_observations=dict(kind=kind, path=str(source), sha256=source_sha),
        tool=identity, binding=project._binding(verified),
        descriptor=str(descriptor), descriptor_sha256=project.sha256(descriptor),
        history_sha256=history.index_sha256,
        native_instructions_emitted=manifest['native_instructions_emitted'],
        limits=['Preparation verifies declared inputs; native execution requires a separate build/run',
                'Original captures preserve their historical ABI/origin/counters',
                'Media remains read-only and is not copied or installed'])
    with (output/'prepare-receipt.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_project(args.spec, args.out), indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError) as error:
        print('Preparation: '+' '.join(str(error).split())[:300], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
