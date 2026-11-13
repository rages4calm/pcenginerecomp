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
        {'capacity', 'history_version', 'history_path', 'partition_size', 'partition_layout', 'native_span', 'exclude_ranges'}, name='module')
    project._choice(module['kind'], ('capture', 'profile', 'history', 'declared', 'discovery', 'overlay'), 'module.kind')
    if module['kind'] not in ('declared', 'discovery', 'overlay') and 'history_path' in module:
        raise ValueError('module.history_path requires declared roots or discovery')
    if module['kind'] in ('declared', 'discovery', 'overlay'):
        from .cartridge import PROFILES, HEADERS, ENCODINGS
        boot = spec.get('boot',{})
        if type(boot) is not dict:raise ValueError('Declared boot requires a table')
        if module['kind']=='discovery' or boot.get('mode')=='hucard-reset':
            project._table(boot,{'mode','profile','header','encoding'},name='declared boot')
            project._choice(boot['mode'],('hucard-reset',),'declared boot mode')
            for key,choices in (('profile',PROFILES),('header',HEADERS),('encoding',ENCODINGS)):
                project._choice(boot[key],choices,'declared boot '+key)
            if 'cartridge' not in spec or {'bios','bram','toc','disc','libchdr'} & spec.keys():
                raise ValueError('Declared ROM roots require a HuCard cartridge and exclude CD assets')
        elif 'boot' in spec:
            project._table(boot,{'mode','profile'},{'arcade_card'},name='declared System Card boot')
            project._choice(boot['mode'],('system-card-reset',),'declared boot mode')
            project._choice(boot['profile'],('standard','super'),'declared System Card profile')
            if 'bios' not in spec or 'cartridge' in spec:
                raise ValueError('System Card declarations require BIOS and exclude cartridge')
            if 'arcade_card' in boot and (boot['arcade_card']!='duo' or boot['profile']!='super'):
                raise ValueError('Arcade Card Duo requires Super System Card reset')
        elif 'cartridge' in spec:
            raise ValueError('Payload declarations exclude HuCard cartridges')
        if 'history_path' not in module and {'capacity','history_version'} & module.keys():
            raise ValueError('Declared capacity/history_version require an optional history_path')
    if 'history_version' in module:
        project._integer(module['history_version'], 1, 2, 'history_version')
    maximum_capacity = 1048576 if module.get('history_version') == 2 else 65536
    project._integer(module.get('capacity', 65536), 1, maximum_capacity, 'capacity')
    project._integer(module.get('partition_size', 256), 1, 4096, 'partition_size')
    project._choice(module.get('partition_layout', 'stable'), ('balanced', 'stable', 'shared'), 'partition_layout')
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
    from .emitter import emit_history, emit_declarations
    from .history import compose_history, load_history
    from .observations import load_observation_profile

    spec_path, raw_spec, spec = _recipe(spec_path)
    base = spec_path.parent
    output = Path(os.path.abspath(output))
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('Preparation requires a new directory in an existing parent')
    kind = spec['module']['kind']
    declared = kind in ('declared', 'discovery', 'overlay')
    source = _path(base, spec['module']['path'], 'module input', directory=kind in ('history', 'discovery'))
    if source.resolve().is_relative_to(output.resolve()):
        raise ValueError('Preparation cannot contain its original input')
    # Admit the selected format before allocating a destination. A profile or
    # history cannot masquerade as a raw capture by changing its extension.
    assets = {name: _asset(base, spec[name], name) for name in sorted(project.ASSETS & spec.keys())}
    original_history = None
    original_compilation = None
    original_discovery = None
    source_images=None
    original_overlay=None
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
    if declared:
        from .declarations import load_compilation
        if kind == 'discovery':
            from .discovery import load_discovery
            original_discovery = load_discovery(source, assets['cartridge'][0])
            source = original_discovery.roots_path
        history_path = (_path(base,spec['module']['history_path'],'optional observation history',directory=True)
                        if 'history_path' in spec['module'] else None)
        source_files={name:value[0] for name,value in assets.items()}
        if payload:source_files['payload']=payload[0]
        from .source_sets import is_source_set,ASSETS
        from .overlays import is_library
        source_set=is_source_set(source)
        overlay=is_library(source)
        if kind=='overlay' and not overlay:raise ValueError('Overlay preparation requires a closed overlay library')
        declaration_image,expected_source=(None,None) if overlay else project._declared_boot_source(spec,source_files)
        if source_set:source_images={k:v for k,v in source_files.items() if k in ASSETS};declaration_image=None
        original_compilation = load_compilation(source,declaration_image,observation_history=history_path,source_images=source_images)
        source_sha = original_compilation.declarations.sha256
        original_history = original_compilation.history
        if overlay:
            original_overlay=original_compilation.declarations
            hashes={k:v[1] for k,v in assets.items()}
            if payload:hashes['payload']=payload[1]
            project._overlay_machine(spec,hashes,original_overlay)
        elif source_set:project._declared_source_set(spec,source_files,original_compilation.declarations)
        elif original_compilation.declarations.source_metadata != expected_source:
            raise ValueError('Declared roots source contract disagrees with explicit boot')
    elif kind == 'capture':
        original_capture, source_sha = load_capture(source)
        if original_capture['schema'] == 2 and spec['module'].get('history_version') != 2:
            raise ValueError('Extended capture preparation requires explicit history_version = 2')
        del original_capture  # The authenticated history admission rereads the original bytes.
    elif kind == 'profile':
        _, source_sha = load_observation_profile(source)
    else:
        original_history = load_history(source)
        source = original_history.index_path
        source_sha = original_history.index_sha256
    if original_history is not None:
        if original_history.index['schema'] == 2 and spec['module'].get('history_version') == 1:
            raise ValueError('Preparation cannot downgrade observation history version')
        if output.resolve().is_relative_to(original_history.index_path.parent.resolve()):
            raise ValueError('Preparation output cannot modify its original history graph')
    if original_discovery is not None and (output.is_relative_to(original_discovery.report_path.parent)
            or output.parent.samefile(original_discovery.report_path.parent)):
        raise ValueError('Preparation output cannot modify its original discovery graph')
    if source_images is not None:
        from .source_sets import MEMBER_DIR
        if output.is_relative_to(source.parent/MEMBER_DIR):raise ValueError('Preparation cannot modify its original source member namespace')
    if original_overlay is not None and output.is_relative_to(source.parent/'epochs'):
        raise ValueError('Preparation cannot modify its original overlay epochs')
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
    history = None
    if not declared or original_history is not None:
        history = compose_history([source] if kind == 'capture' else [], output/'observation-history',
            baseline_profile=source if kind == 'profile' else None,
            baseline_history=original_history.index_path if original_history is not None else None,
            capacity=options.get('capacity'), history_version=options.get('history_version'))
    emission = dict(partition_size=options.get('partition_size',256),
                    partition_layout=options.get('partition_layout','stable'),
                    native_span=options.get('native_span',False),
                    exclude_ranges=tuple(tuple(pair) for pair in options.get('exclude_ranges',[])))
    if declared:
        roots_relative = 'declarations/roots.json'
        if original_discovery is not None:
            from .discovery import copy_discovery
            copied_discovery = copy_discovery(original_discovery.report_path, assets['cartridge'][0], output/'discovery')
            if copied_discovery.sha256 != original_discovery.sha256:
                raise ValueError('Original discovery changed during preparation')
            roots_relative = 'discovery/roots.json'
        elif original_overlay is not None:
            from .overlays import copy_library
            copy_library(source,output/'declarations')
        elif source_images is not None:
            from .source_sets import copy_source_set
            copy_source_set(source,output/'declarations',source_images)
        else:
            (output/'declarations').mkdir()
            with (output/roots_relative).open('xb') as stream:
                stream.write(source.read_bytes())
        manifest = emit_declarations(output/roots_relative,declaration_image,output/'module',
                                     observation_history=history.index_path if history is not None else None,source_images=source_images,**emission)
    else:
        manifest = emit_history(history.index_path,output/'module',**emission)
    config = dict(schema=1, name=spec['name'], tool=dict(path=_relative(TOOL_ROOT, output),
        revision=revision, source_sha256=identity['source_sha256'], runtime_abi=ABI),
        module=dict(source=dict(path='module/module.cpp', sha256=project.sha256(output/'module/module.cpp')),
                    manifest=dict(path='module/module.json', sha256=project.sha256(output/'module/module.json'))))
    if history is not None:
        config['module']['observation_history'] = dict(path='observation-history/history.json',sha256=history.index_sha256)
    if declared:
        config['module']['declared_roots'] = dict(path=roots_relative,sha256=project.sha256(output/roots_relative))
    if original_discovery is not None:
        config['module']['discovery'] = dict(path='discovery/discovery.json',sha256=original_discovery.sha256)
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
    if history is not None:
        history.revalidate()
    if original_history is not None:
        original_history.revalidate()
    if original_compilation is not None:
        original_compilation.revalidate()
    if original_discovery is not None:
        original_discovery.revalidate()
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
        tool=identity, binding=project._binding(verified),
        descriptor=str(descriptor), descriptor_sha256=project.sha256(descriptor),
        native_instructions_emitted=manifest['native_instructions_emitted'],
        limits=['Preparation verifies declared inputs; native execution requires a separate build/run',
                'Original captures preserve their historical ABI/origin/counters',
                'Media remains read-only and is not copied or installed'])
    if declared:
        receipt['original_declarations'] = dict(path=str(source),sha256=source_sha,
            source=original_compilation.declarations.source_metadata)
        receipt['declared_roots_sha256'] = source_sha
        if original_history is not None:
            receipt['original_observations'] = dict(kind='history',path=str(original_history.index_path),
                                                    sha256=original_history.index_sha256)
        if original_discovery is not None:
            receipt['original_discovery'] = dict(path=str(original_discovery.report_path),
                sha256=original_discovery.sha256, analysis_policy=original_discovery.report['analysis_policy'])
    else:
        receipt['original_observations'] = dict(kind=kind,path=str(source),sha256=source_sha)
    if history is not None:
        receipt['history_sha256'] = history.index_sha256
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
