"""Bounded consumer-owned title contracts and deterministic initial settings.

This module describes source inputs, not game knowledge or execution evidence.
Only the caller's adapter implementation contains enhancement behavior.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

from .snapshots import SnapshotStore
from . import isa

FORMAT = 'pce-title-adapter-1'
MAX_BYTES = 4 * 1024 * 1024
MAX_GRAPH_BYTES = 16 * 1024 * 1024
MIN_INT = -(1 << 63)
MAX_INT = (1 << 63) - 1
BINDING_NAME = 'pce-title-adapter-binding.cpp'
MARKER = b'// pce-title-adapter-binding-1\n'


def _fields(value, required, optional=(), label='title adapter'):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('Invalid ' + label + ' fields')
    return value


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid ' + label + ' integer/range')
    return value


def _name(value, label):
    if type(value) is not str or re.fullmatch('[a-z][a-z0-9_-]{0,63}', value) is None:
        raise ValueError('Invalid ' + label + ' identifier')
    return value


def validate(value):
    _fields(value, {'format', 'schema', 'id', 'state_bytes', 'settings', 'events'})
    if value['format'] != FORMAT or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Unsupported title adapter manifest')
    _name(value['id'], 'adapter')
    _integer(value['state_bytes'], 0, 4096, 'adapter state size')
    settings = value['settings']
    if type(settings) is not list or len(settings) > 32:
        raise ValueError('Title settings require at most 32 declarations')
    names = set()
    for item in settings:
        _fields(item, {'name', 'min', 'max', 'default'}, label='title setting')
        name = _name(item['name'], 'setting')
        if name in names:
            raise ValueError('Duplicate title setting')
        names.add(name)
        low = _integer(item['min'], MIN_INT, MAX_INT, 'setting minimum')
        high = _integer(item['max'], low, MAX_INT, 'setting maximum')
        _integer(item['default'], low, high, 'setting default')
    events = value['events']
    if type(events) is not list or not 1 <= len(events) <= 256:
        raise ValueError('Title adapter requires 1..256 source events')
    names, identities = set(), set()
    for event in events:
        _fields(event, {'name', 'pc', 'mpr', 'selector', 'data'}, label='title event')
        name = _name(event['name'], 'event')
        if name in names:
            raise ValueError('Duplicate title event name')
        names.add(name)
        _integer(event['pc'], 0, 65535, 'event PC')
        _integer(event['selector'], 0, 15, 'event selector')
        if type(event['mpr']) is not list or len(event['mpr']) != 8:
            raise ValueError('Title event requires all eight MPR bytes')
        for byte in event['mpr']:
            _integer(byte, 0, 255, 'event MPR')
        data = event['data']
        if type(data) is not str or re.fullmatch('[0-9a-f]{2}(?:[0-9a-f]{2}){0,6}', data) is None:
            raise ValueError('Title event requires 1..7 lowercase hexadecimal bytes')
        raw = bytes.fromhex(data)
        mnemonic, mode = isa._ROWS[raw[0]].split('.')
        if mnemonic == 'ILL' or isa._LENGTH[mode] != len(raw):
            raise ValueError('Title event must identify exactly one legal instruction')
        key = (event['pc'], tuple(event['mpr']), event['selector'], data)
        if key in identities:
            raise ValueError('Duplicate title source event identity')
        identities.add(key)
    return value


def load(path, *, expected_sha256=None):
    store = SnapshotStore()
    snapshot = store.read_json(Path(path), expected_sha256=expected_sha256, max_bytes=MAX_BYTES)
    validate(snapshot.value)
    return snapshot, store


def settings(manifest, values=None, *, mode='pristine'):
    """Return a detached complete setting map and canonical launch string."""
    validate(manifest)
    if mode not in ('pristine', 'enhanced') or type(mode) is not str:
        raise ValueError('Title mode requires pristine or enhanced')
    if values is None:
        values = {}
    if type(values) is not dict or any(type(key) is not str for key in values):
        raise ValueError('Title settings require a structured integer mapping')
    declared = {item['name']: item for item in manifest['settings']}
    if set(values) - declared.keys():
        raise ValueError('Unknown title setting')
    result = {}
    for name, item in sorted(declared.items()):
        value = _integer(values.get(name, item['default']), item['min'], item['max'], 'title setting '+name)
        if mode == 'pristine' and value != item['default']:
            raise ValueError('Pristine title mode requires every default setting')
        result[name] = value
    return result, ','.join(name+'='+str(value) for name, value in result.items())


def parse_settings(items):
    result = {}
    for item in items:
        if type(item) is not str or item.count('=') != 1:
            raise ValueError('Title setting requires name=integer')
        name, text = item.split('=')
        _name(name, 'setting')
        if name in result or re.fullmatch('0|-?[1-9][0-9]*', text) is None:
            raise ValueError('Duplicate or noncanonical title setting')
        result[name] = _integer(int(text), MIN_INT, MAX_INT, 'title setting')
    return result


def _literal(value):
    return '(-INT64_C(9223372036854775807)-1)' if value == MIN_INT else 'INT64_C('+str(value)+')'


def binding_bytes(manifest, digest):
    validate(manifest)
    if type(digest) is not str or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise ValueError('Title manifest requires exact SHA256')
    setting_rows = ['{'+json.dumps(item['name'])+','+','.join(_literal(item[key]) for key in ('min','max','default'))+'}'
                    for item in manifest['settings']]
    event_rows = ['{'+json.dumps(item['name'])+','+str(item['pc'])+',{'+','.join(map(str,item['mpr']))+'},'+
                  str(item['selector'])+',{'+','.join(map(str,bytes.fromhex(item['data'])))+'}}'
                  for item in manifest['events']]
    text = MARKER.decode()+'''#include "pce/title_adapter.hpp"
#include <cstdint>
namespace pce::consumer { void title_adapter_after(pce::TitleAdapterContext&); }
namespace pce {
const TitleAdapterSpec* consumer_title_adapter() {
    static const TitleAdapterSpec spec{'''+','.join((json.dumps(manifest['id']),json.dumps(digest),str(manifest['state_bytes']),
        '{'+','.join(setting_rows)+'}', '{'+','.join(event_rows)+'}', '&consumer::title_adapter_after'))+'''};
    return &spec;
}
}
'''
    return text.encode('utf-8')


def generate(manifest_path, output):
    snapshot, store = load(manifest_path)
    data = binding_bytes(snapshot.value, snapshot.sha256)
    output = Path(output).absolute()
    if not output.parent.is_dir() or output.is_symlink():
        raise ValueError('Title binding requires an existing private output directory')
    if output.exists():
        old = _read(output)
        if old == data:
            store.revalidate()
            return output
        if not old.startswith(MARKER):
            raise ValueError('Refusing to replace a non-generated title binding')
    handle, name = tempfile.mkstemp(prefix='.pce-title-', suffix='.tmp', dir=output.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        store.revalidate()
        os.replace(name, output)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return output


def _read(path):
    path = Path(path).absolute()
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or parent.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Title source parents must be ordinary directories without links')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400 or before.st_size > MAX_BYTES:
        raise ValueError('Title source requires a bounded ordinary file')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(MAX_BYTES+1)
        after = os.fstat(stream.fileno())
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if len(data) > MAX_BYTES or signature(before) != signature(opened) or signature(opened) != signature(after) or signature(after) != signature(path.lstat()):
        raise ValueError('Title source changed while reading')
    return data


@dataclass
class SourceGraph:
    source: Path
    manifest: Path
    headers: list[Path]
    raw: dict[Path, bytes]
    snapshot: object
    store: SnapshotStore

    def revalidate(self):
        self.store.revalidate()
        for path, expected in self.raw.items():
            if _read(path) != expected:
                raise ValueError('Title adapter input changed')


def recipe_graph(base, entry):
    _fields(entry, {'source', 'manifest'}, {'headers'}, 'title adapter recipe')
    base = Path(base)
    def path(value):
        if type(value) is not str or not value or '\0' in value:
            raise ValueError('Invalid title adapter input path')
        return Path(os.path.abspath(base/value))
    source, manifest_path = path(entry['source']), path(entry['manifest'])
    if (source.suffix.lower() not in ('.cpp', '.cc', '.cxx')
            or re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]*',source.name) is None):
        raise ValueError('Title adapter source requires C++')
    root = source.parent
    header_values = entry.get('headers', [])
    if type(header_values) is not list or len(header_values) > 64:
        raise ValueError('Title adapter requires at most 64 explicit headers')
    if any(type(value) is not str or '..' in Path(value).parts for value in header_values):
        raise ValueError('Title header path cannot contain parent traversal')
    headers = [path(value) for value in header_values]
    names = {source.name.casefold(), 'manifest.json'}
    if source.name.casefold() == 'manifest.json':
        raise ValueError('Title source collides with manifest')
    for header in headers:
        if not header.is_relative_to(root) or header.suffix.lower() not in ('.h', '.hpp', '.hh', '.hxx', '.inc'):
            raise ValueError('Title header must be within the source directory')
        relative = header.relative_to(root)
        if any(part in ('.', '..') or re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]*', part) is None for part in relative.parts):
            raise ValueError('Title header requires a portable relative path')
        key = relative.as_posix().casefold()
        if key in names or any(key.startswith(item+'/') or item.startswith(key+'/') for item in names):
            raise ValueError('Duplicate/colliding title source path')
        names.add(key)
        for parent in (header.parent, *header.parents):
            if parent == root.parent:
                break
            if parent.is_symlink() or getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Title input graph cannot contain links')
    snapshot, store = load(manifest_path)
    if _read(manifest_path) != snapshot.raw:
        raise ValueError('Title manifest changed during admission')
    raw = {item: _read(item) for item in (source, *headers)}
    if sum(map(len, raw.values())) + len(snapshot.raw) > MAX_GRAPH_BYTES:
        raise ValueError('Title source graph exceeds 16 MiB')
    if manifest_path in raw:
        raise ValueError('Title source and manifest must be separate files')
    return SourceGraph(source, manifest_path, headers, raw, snapshot, store)


def copy_graph(graph, output):
    output = Path(output)
    output.mkdir(exist_ok=False)
    bindings = {}
    for path, raw in graph.raw.items():
        relative = path.relative_to(graph.source.parent)
        target = output/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        bindings[path] = dict(path=target, sha256=hashlib.sha256(raw).hexdigest())
    target = output/'manifest.json'
    with target.open('xb') as stream:
        stream.write(graph.snapshot.raw)
    graph.revalidate()
    return dict(source=bindings[graph.source], manifest=dict(path=target,sha256=graph.snapshot.sha256),
                headers={f'h{index:03d}':bindings[path] for index,path in enumerate(graph.headers)})


def verify_descriptor(base, entry, files):
    """Admit an explicitly closed source namespace, including unused headers."""
    from . import project
    _fields(entry, {'source', 'manifest'}, {'headers'}, 'title adapter binding')
    def bound(binding,label):
        _fields(binding,{'path','sha256'},label=label)
        value=binding['path']
        if type(value) is not str or not value or '\0' in value:
            raise ValueError('Invalid title source path')
        spelling=Path(os.path.abspath(Path(base)/value))
        for path in (spelling,*spelling.parents):
            info=path.lstat()
            if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('Title input graph cannot contain links or reparse points')
        _read(spelling)
        return project._file(base,binding,label)
    source = bound(entry['source'], 'title_adapter.source')
    manifest = bound(entry['manifest'], 'title_adapter.manifest')
    root = source.parent
    if source.suffix.lower() not in ('.cpp','.cc','.cxx') or manifest.parent != root:
        raise ValueError('Title adapter requires one dedicated closed source directory')
    _read(source); _read(manifest)
    snapshot, store = load(manifest, expected_sha256=entry['manifest']['sha256'])
    store.bind(source, expected_sha256=entry['source']['sha256'])
    files['title_adapter_source'] = source
    files['title_adapter_manifest'] = manifest
    declared = {source, manifest}
    headers = entry.get('headers', {})
    if type(headers) is not dict or len(headers) > 64 or set(headers) != {f'h{index:03d}' for index in range(len(headers))}:
        raise ValueError('Title headers require contiguous explicit h000..h063 bindings')
    names = {source.relative_to(root).as_posix().casefold(),manifest.relative_to(root).as_posix().casefold()}
    for name, binding in sorted(headers.items()):
        path = bound(binding, 'title_adapter.headers.'+name)
        if not path.is_relative_to(root) or path.suffix.lower() not in ('.h','.hpp','.hh','.hxx','.inc'):
            raise ValueError('Title header is outside its closed source directory')
        key = path.relative_to(root).as_posix().casefold()
        if key in names:
            raise ValueError('Duplicate/case-colliding title source path')
        names.add(key);declared.add(path)
        _read(path);store.bind(path, expected_sha256=binding['sha256'])
        files['title_adapter_header:'+name] = path
    actual = set()
    for path in root.rglob('*'):
        info = path.lstat()
        if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Title source graph cannot contain links or reparse points')
        if path.is_file():actual.add(path.resolve())
    if actual != declared or sum(path.stat().st_size for path in declared) > MAX_GRAPH_BYTES:
        raise ValueError('Title source directory must contain exactly its bound source, manifest and headers')
    store.revalidate()
    return snapshot, store


def binding_path(build_dir):
    return Path(build_dir).resolve()/'CMakeFiles/pce-consumer-title-adapter'/BINDING_NAME


def expected_binding(checked, build_dir):
    if 'title_adapter' not in checked['config']:
        return None
    entry = checked['config']['title_adapter']
    snapshot, store = load(checked['files']['title_adapter_manifest'],expected_sha256=entry['manifest']['sha256'])
    result = binding_path(build_dir), binding_bytes(snapshot.value,snapshot.sha256)
    store.revalidate()
    return result


def verify_producer(checked, built, build_dir, store):
    """Readmit producer/package origin without repeating toolchain-tree hashing."""
    from . import project, build_cache, build_recovery
    if 'title_adapter' not in checked['config']:
        return
    kinds = [name for name in ('cache','recovery') if name in built]
    if len(kinds) != 1:
        raise ValueError('Title adapter package requires one audited cache/recovery producer receipt')
    kind = kinds[0]; producer = built[kind]
    if type(producer) is not dict or type(producer.get('schema')) is not int or producer['schema'] != 1:
        raise ValueError('Invalid title adapter producer receipt')
    if kind == 'cache':
        contract = producer.get('input_contract')
        if producer.get('producer') != 'windows-x64-llvm-mingw-ninja-v1' or type(producer.get('hit')) is not bool:
            raise ValueError('Unsupported title adapter cache producer')
        if type(contract) is not dict or build_cache.contract_identity(contract) != producer.get('key_contract'):
            raise ValueError('Title adapter cache contract digest mismatch')
        key = hashlib.sha256(build_cache._canonical(producer['key_contract'])).hexdigest()
        if key != producer.get('key'):
            raise ValueError('Title adapter cache key mismatch')
        binding = producer.get('manifest')
        _fields(binding, {'path','sha256','bytes'}, label='cache manifest binding')
        if type(binding['path']) is not str or not binding['path']:
            raise ValueError('Invalid title adapter cache manifest path')
        manifest = store.read_json(Path(binding['path']),expected_sha256=binding['sha256'],max_bytes=build_cache.MAX_MANIFEST_BYTES)
        value = manifest.value
        _fields(value, {'schema','kind','key','contract','files'}, label='cache package manifest')
        if (type(value['schema']) is not int or value['schema'] != 1 or value['kind'] != 'pce-build-package'
                or value['key'] != key or value['contract'] != producer['key_contract']
                or type(binding['bytes']) is not int or binding['bytes'] != manifest.size_bytes
                or producer.get('manifest_sha256') != manifest.sha256):
            raise ValueError('Title adapter cache origin mismatch')
        if type(value['files']) is not list or not 1<=len(value['files'])<=build_cache.MAX_FILES:
            raise ValueError('Invalid title adapter cached package inventory')
        outputs = {}
        for row in value['files']:
            _fields(row,{'name','bytes','sha256','executable'},label='cache artifact')
            build_cache._name(row['name'])
            if row['name'] in outputs or type(row['bytes']) is not int or row['bytes']<0 or type(row['executable']) is not bool:
                raise ValueError('Invalid/duplicate title adapter cached artifact')
            snapshot = store.bind(Path(built['binary']).parent/row['name'],expected_sha256=row['sha256'])
            if snapshot.size_bytes != row['bytes']:
                raise ValueError('Title adapter cached artifact extent differs')
            outputs[row['name']] = row['sha256']
        if outputs != built.get('output_files'):
            raise ValueError('Title adapter cache package differs from its origin')
        if not producer['hit']:
            audit = producer.get('input_audit')
            if type(audit) is not dict or audit.get('cmake_file_api') is not True or audit.get('ninja_dependencies') is not True or type(audit.get('header_count')) is not int or audit['header_count']<1:
                raise ValueError('Title adapter cold package lacks actual dependency evidence')
    else:
        pre = producer.get('input_contract')
        if (type(pre) is not dict or type(pre.get('schema')) is not int or pre['schema']!=1
                or pre.get('kind')!='pce-recoverable-build-v1'):
            raise ValueError('Missing title adapter recovery input contract')
        original = store.read_json(Path(build_dir)/'.pce-recovery/contract.json',max_bytes=build_cache.MAX_COMPILED_INPUT_BYTES).value
        build_recovery._check_seal(original)
        if original != pre or build_recovery._digest(pre) != producer.get('contract_sha256') or pre.get('binding') != project._binding(checked):
            raise ValueError('Title adapter recovery origin mismatch')
        contract = pre.get('input_contract')
        audit = producer.get('input_audit')
        if type(audit) is not dict or audit.get('cmake_file_api') is not True or audit.get('ninja_dependencies') is not True or type(audit.get('header_count')) is not int or audit['header_count']<1:
            raise ValueError('Title adapter recovered package lacks actual dependency evidence')
    tool = contract.get('tool') if type(contract) is dict else None
    if (type(contract) is not dict or contract.get('producer') != 'windows-x64-llvm-mingw-ninja-v1'
            or type(tool) is not dict or tool.get('source_sha256') != checked['tool_identity']['source_sha256']):
        raise ValueError('Title adapter producer SDK/source mismatch')
    expected = {key:value for key,value in checked['identities'].items() if key.startswith('title_adapter_')}
    adapter = contract.get('title_adapter')
    item = checked['config']['title_adapter']['manifest']
    manifest, bound = load(checked['files']['title_adapter_manifest'],expected_sha256=item['sha256'])
    generated = hashlib.sha256(binding_bytes(manifest.value,manifest.sha256)).hexdigest()
    if (type(adapter) is not dict or adapter.get('inputs') != expected or adapter.get('binding_sha256') != generated
            or adapter.get('generator') != 'pce-title-adapter-binding-1'):
        raise ValueError('Title adapter producer source/manifest/generated binding differs')
    bound.revalidate()
    store.revalidate()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('verify', 'generate'):
        command = commands.add_parser(name)
        command.add_argument('manifest', type=Path)
        if name == 'generate': command.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        snapshot, store = load(args.manifest)
        if args.command == 'generate': generate(args.manifest, args.out)
        store.revalidate()
        print(json.dumps(dict(format=FORMAT, id=snapshot.value['id'], sha256=snapshot.sha256,
                              settings=len(snapshot.value['settings']), events=len(snapshot.value['events']))))
        return 0
    except (OSError, ValueError) as error:
        print('title adapter: '+str(error), file=__import__('sys').stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
