"""Content-addressed, private observation histories with complete raw provenance.

Histories transport the same staged selection as inline profiles without embedding
base64 originals or trusting cached catalogue facts. Admission replays originals.
This is offline catalogue evidence, never new execution or checkpoint migration.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from itertools import islice
import os
from pathlib import Path
import stat

from .capture import MAX_CAPTURE_BYTES, MAX_OBSERVATIONS, integer
from .observations import (MAX_CONTRIBUTIONS, MAX_INPUTS, MAX_PROFILE_BYTES,
    SELECTION_POLICY, _canonical, _decode_observation_rows, _derive_raw_observations,
    _digest, _embedded_sources, _json, _validate)

FORMAT = 'pce-observation-history-1'
SCHEMA = 1
FORMAT_V2 = 'pce-observation-history-2'
SCHEMA_V2 = 2
MAX_OBSERVATIONS_V2 = 1048576
MAX_CONTRIBUTIONS_V2 = 4194304
MAX_CAPTURE_BYTES_V2 = 512 * 1024 * 1024
MAX_INDEX_BYTES = 1024 * 1024
MAX_SHARD_BYTES = 4 * 1024 * 1024
MAX_SHARD_IDENTITIES = 4096
MAX_LINE_BYTES = 64 * 1024
# A transport graph bound, not an increase to any legacy profile/capture bound.
MAX_RAW_BYTES = MAX_INPUTS * MAX_CAPTURE_BYTES
MAX_RAW_BYTES_V2 = MAX_INPUTS * MAX_CAPTURE_BYTES_V2
INDEX_NAME = 'history.json'
_INDEX_FIELDS = {'format', 'schema', 'execution_evidence', 'capacity', 'inputs',
    'selection_stages', 'selection_policy', 'historical_totals',
    'selected_historical_totals', 'selection_counts', 'catalogue', 'catalogue_sha256'}


def history_limits(version):
    """Explicit versioned transport/identity bounds; legacy constants stay fixed."""
    integer(version, 2, 'history version', 1)
    if version == 1:
        return dict(format=FORMAT, schema=SCHEMA, union_limit=MAX_OBSERVATIONS,
                    contribution_limit=MAX_CONTRIBUTIONS, max_capture_bytes=MAX_CAPTURE_BYTES,
                    max_total_bytes=MAX_RAW_BYTES)
    return dict(format=FORMAT_V2, schema=SCHEMA_V2, union_limit=MAX_OBSERVATIONS_V2,
                contribution_limit=MAX_CONTRIBUTIONS_V2, max_capture_bytes=MAX_CAPTURE_BYTES_V2,
                max_total_bytes=MAX_RAW_BYTES_V2)


def _derivation_limits(limits):
    """Only v2 opts into the framed capture decoder and larger bounds."""
    options = {key: limits[key] for key in ('union_limit', 'contribution_limit',
                                          'max_capture_bytes', 'max_total_bytes')}
    if limits['schema'] == SCHEMA_V2:
        from .capture import parse_capture_bytes
        options['capture_decoder'] = lambda raw: parse_capture_bytes(raw, validate=False)
    return options


def _path(path):
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (ValueError, TypeError, OSError) as error:
        raise ValueError('History requires a valid file path') from error


def _plain(path, directory=False):
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError('History graph path is missing or unreadable') from error
    if (stat.S_ISLNK(info.st_mode) or
            getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
        raise ValueError('History graph links and reparse points are unsupported')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('History graph requires ordinary directories and regular files')
    if not directory and info.st_nlink != 1:
        raise ValueError('History graph hard-linked files are unsupported')
    return info


def _parents(path):
    for parent in reversed(path.parents):
        _plain(parent, directory=True)


@dataclass(frozen=True)
class _Binding:
    relative: str
    path: Path
    sha256: str
    size_bytes: int

    def view(self):
        return dict(relative=self.relative, path=self.path, sha256=self.sha256,
                    size_bytes=self.size_bytes)


def _read(path, maximum, *, relative='', expected=None, retain=True):
    path = _path(path)
    _parents(path)
    before = _plain(path)
    if before.st_size > maximum:
        raise ValueError('History graph file exceeds its byte bound')
    if expected is not None and before.st_size != expected['size_bytes']:
        raise ValueError('History graph file byte size disagrees')
    digest = hashlib.sha256()
    data = bytearray() if retain else None
    try:
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError('History graph path changed while opening')
            total = 0
            while True:
                chunk = stream.read(min(1024 * 1024, maximum + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise ValueError('History graph file exceeds its byte bound')
                digest.update(chunk)
                if retain:
                    data.extend(chunk)
            closed = os.fstat(stream.fileno())
    except OSError as error:
        raise ValueError('History graph file cannot be read') from error
    after = _plain(path)
    # Windows path-stat and CRT descriptor-stat expose different ctime meanings.
    # Identity/size/mtime detect replacement during this read; SHA256 remains
    # authoritative for content, including later same-timestamp changes.
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns)
    if identity(before) != identity(opened) or identity(before) != identity(closed) or identity(before) != identity(after):
        raise ValueError('History graph file changed while reading')
    value = digest.hexdigest()
    if total != before.st_size or (expected is not None and value != expected['sha256']):
        raise ValueError('History graph file SHA256 or size disagrees')
    return (bytes(data) if retain else None), _Binding(relative, path, value, total)


def _reference(value, *, shard=False, max_capture_bytes=MAX_CAPTURE_BYTES):
    fields = {'sha256', 'size_bytes'} | ({'identity_count'} if shard else set())
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('Invalid history content-addressed reference fields')
    _digest(value['sha256'])
    integer(value['size_bytes'], MAX_SHARD_BYTES if shard else max_capture_bytes,
            'history file byte size', 1)
    if shard:
        integer(value['identity_count'], MAX_SHARD_IDENTITIES, 'catalogue shard identities', 1)


def _index(value):
    if not isinstance(value, dict) or set(value) != _INDEX_FIELDS:
        raise ValueError('Invalid observation history index fields')
    if type(value['schema']) is not int or value['schema'] not in (SCHEMA, SCHEMA_V2):
        raise ValueError('Unsupported observation history format/schema/evidence')
    limits = history_limits(value['schema'])
    if value['format'] != limits['format'] or value['execution_evidence'] is not False:
        raise ValueError('Unsupported observation history format/schema/evidence')
    integer(value['capacity'], limits['union_limit'], 'history capacity', 1)
    if value['selection_policy'] != SELECTION_POLICY:
        raise ValueError('Unsupported observation history selection policy')
    if not isinstance(value['inputs'], list) or not 1 <= len(value['inputs']) <= MAX_INPUTS:
        raise ValueError('History requires bounded original inputs')
    for entry in value['inputs']:
        _reference(entry, max_capture_bytes=limits['max_capture_bytes'])
    digests = [entry['sha256'] for entry in value['inputs']]
    if digests != sorted(set(digests)):
        raise ValueError('History original inputs require canonical distinct SHA256 order')
    if not isinstance(value['catalogue'], list) or len(value['catalogue']) > limits['union_limit']:
        raise ValueError('History catalogue shard capacity exceeded')
    total = 0
    seen = set()
    for entry in value['catalogue']:
        _reference(entry, shard=True)
        if entry['sha256'] in seen:
            raise ValueError('Duplicate history catalogue shard')
        seen.add(entry['sha256'])
        total += entry['identity_count']
    if total > value['capacity']:
        raise ValueError('History catalogue identities exceed declared capacity')
    _digest(value['catalogue_sha256'])


def _closed_graph(root, relatives):
    _parents(root)
    _plain(root, directory=True)
    expected = set(relatives)
    actual = set()
    try:
        children = list(root.iterdir())
        for child in children:
            if child.name in ('captures', 'catalogue'):
                _plain(child, directory=True)
                for leaf in child.iterdir():
                    _plain(leaf)
                    actual.add(child.name + '/' + leaf.name)
            elif child.name == INDEX_NAME:
                _plain(child)
                actual.add(INDEX_NAME)
            else:
                raise ValueError('Unknown file or directory in closed history graph')
    except OSError as error:
        raise ValueError('History graph cannot be inspected') from error
    if actual != expected or {child.name for child in children} != {'captures', 'catalogue', INDEX_NAME}:
        raise ValueError('History graph has missing or unlisted content')


def _accounting(index):
    return dict(historical_totals=deepcopy(index['historical_totals']),
        historical_count_policy='sum of distinct raw inputs; overlapping execution windows are not deduplicated',
        selection_stages=deepcopy(index['selection_stages']),
        selected_historical_totals=deepcopy(index['selected_historical_totals']),
        selection_counts=deepcopy(index['selection_counts']), selection_policy=SELECTION_POLICY)


@dataclass(frozen=True)
class AdmittedHistory:
    index_path: Path
    index_sha256: str
    _index: dict
    _instructions: list
    _metadata: list
    _bindings: tuple[_Binding, ...]

    @property
    def index(self):
        return deepcopy(self._index)

    @property
    def instructions(self):
        return deepcopy(self._instructions)

    @property
    def input_metadata(self):
        return deepcopy(self._metadata)

    @property
    def per_input_metadata(self):
        return self.input_metadata

    @property
    def accounting(self):
        return _accounting(self._index)

    @property
    def artifact_bindings(self):
        return {entry.relative: entry.view() for entry in self._bindings}

    @property
    def artifacts(self):
        return tuple(entry.view() for entry in self._bindings)

    def revalidate(self):
        """Read every admitted path again; timestamps never substitute for SHA256."""
        _closed_graph(self.index_path.parent, [entry.relative for entry in self._bindings])
        for entry in self._bindings:
            _read(entry.path, entry.size_bytes, expected=entry.view(), retain=False)
        _closed_graph(self.index_path.parent, [entry.relative for entry in self._bindings])


def load_history(path):
    """Admit a closed portable history, recomputing every catalogue fact."""
    path = _path(path)
    if path.is_dir() and not path.is_symlink():
        path = path / INDEX_NAME
    if path.name != INDEX_NAME:
        raise ValueError('Observation history index must be named history.json')
    root = path.parent
    raw, binding = _read(path, MAX_INDEX_BYTES, relative=INDEX_NAME)
    try:
        text = raw.decode('utf-8')
    except UnicodeError as error:
        raise ValueError('History index requires UTF-8') from error
    index = _json(text)
    _index(index)
    limits = history_limits(index['schema'])
    if raw != _canonical(index) + b'\n':
        raise ValueError('History index requires canonical compact JSON and LF')
    bindings = [binding]
    expected = [INDEX_NAME]
    for entry in index['inputs']:
        expected.append('captures/' + entry['sha256'] + '.json')
    for entry in index['catalogue']:
        expected.append('catalogue/' + entry['sha256'] + '.jsonl')
    _closed_graph(root, expected)
    by_digest = {entry['sha256']: entry for entry in index['inputs']}

    def read_raw(digest):
        relative = 'captures/' + digest + '.json'
        data, source = _read(root / relative, limits['max_capture_bytes'], relative=relative,
                             expected=by_digest[digest])
        try:
            text = data.decode('utf-8')
        except UnicodeError as error:
            raise ValueError('History captures require original UTF-8 JSON') from error
        if text.startswith('\ufeff') or '\0' in text:
            raise ValueError('History captures require UTF-8 without a BOM')
        bindings.append(source)
        return data

    rows, totals, metadata, selected, counts = _derive_raw_observations(index['inputs'],
        index['capacity'], index['selection_stages'], read_raw, **_derivation_limits(limits))
    for field, value in (('historical_totals', totals), ('selected_historical_totals', selected),
                         ('selection_counts', counts)):
        if _canonical(index[field]) != _canonical(value):
            raise ValueError('History ' + field + ' disagrees with original captures')
    catalogue_digest = hashlib.sha256()
    offset = 0
    for entry in index['catalogue']:
        relative = 'catalogue/' + entry['sha256'] + '.jsonl'
        data, shard = _read(root / relative, MAX_SHARD_BYTES, relative=relative, expected=entry)
        bindings.append(shard)
        lines = data.splitlines(keepends=True)
        if len(lines) != entry['identity_count']:
            raise ValueError('History catalogue shard identity count disagrees')
        for line in lines:
            if len(line) > MAX_LINE_BYTES or not line.endswith(b'\n'):
                raise ValueError('History catalogue line exceeds bound or lacks LF')
            if offset >= len(rows) or line != _canonical(rows[offset]) + b'\n':
                raise ValueError('History catalogue rows disagree with original captures')
            catalogue_digest.update(line)
            offset += 1
    if offset != len(rows) or catalogue_digest.hexdigest() != index['catalogue_sha256']:
        raise ValueError('History catalogue digest or identity total disagrees')
    admitted = AdmittedHistory(path, binding.sha256, index, _decode_observation_rows(rows),
                               metadata, tuple(bindings))
    admitted.revalidate()
    return admitted


def _bounded_paths(paths):
    result = list(islice(iter(paths), MAX_INPUTS + 1))
    if len(result) > MAX_INPUTS:
        raise ValueError(f'At most {MAX_INPUTS} history input paths are accepted')
    return result


def _write_new(path, data):
    try:
        with path.open('xb') as stream:
            stream.write(data)
    except OSError as error:
        raise ValueError('History output must be a new exclusively created file') from error


def compose_history(input_paths, output, *, baseline_inputs=(), baseline_profile=None,
                    baseline_history=None, capacity=None, history_version=None):
    """Create a lossless history directory, publishing history.json last.

    No baseline means all distinct originals form stage zero. An explicit
    baseline retains all its stages; new raw inputs are the next additive stage,
    even when they contribute no novel identity. Originals are copied unchanged.
    Version defaults to 1 or the retained history version; explicit version 2
    promotes older histories/profiles without enlarging an inherited capacity.
    Version 2 histories cannot be downgraded.
    """
    additions, baseline = _bounded_paths(input_paths), _bounded_paths(baseline_inputs)
    if sum((bool(baseline), baseline_profile is not None, baseline_history is not None)) > 1:
        raise ValueError('Choose exactly one history baseline kind')
    if len(additions) + len(baseline) + int(baseline_profile is not None) + int(baseline_history is not None) > MAX_INPUTS:
        raise ValueError(f'At most {MAX_INPUTS} history input paths are accepted')
    output = _path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('History output directory already exists; choose a new destination')
    _parents(output)
    sources, readers, external = {}, {}, []
    prior = None
    prior_profile = None
    stages = None
    version = 1 if history_version is None else history_version
    limits = history_limits(version)
    selected_capacity = limits['union_limit'] if capacity is None else capacity
    if baseline_history is not None:
        prior = load_history(baseline_history)
        if output.is_relative_to(prior.index_path.parent):
            raise ValueError('History output cannot be inside its baseline history')
        index = prior.index
        if history_version is None:
            version = index['schema']
        elif version < index['schema']:
            raise ValueError('History version downgrade is unsupported')
        limits = history_limits(version)
        selected_capacity = index['capacity'] if capacity is None else capacity
        stages = deepcopy(index['selection_stages'])
        for entry in index['inputs']:
            digest = entry['sha256']
            sources[digest] = dict(entry)
            source = prior.artifact_bindings['captures/' + digest + '.json']
            readers[digest] = lambda source=source: _read(source['path'], limits['max_capture_bytes'], expected=source)[0]
    elif baseline_profile is not None:
        raw, pin = _read(baseline_profile, MAX_PROFILE_BYTES)
        external.append(pin)
        prior_profile = _json(raw)
        _validate(prior_profile)
        descriptions, reader = _embedded_sources(prior_profile['inputs'], canonical=True)
        selected_capacity = prior_profile['capacity'] if capacity is None else capacity
        stages = (deepcopy(prior_profile['selection_stages']) if prior_profile['schema'] == 2
                  else [[entry['sha256'] for entry in descriptions]])
        for entry in descriptions:
            digest = entry['sha256']
            sources[digest] = entry
            readers[digest] = lambda digest=digest: reader(digest)
        # Only the embedded original transport is needed after admission;
        # release the legacy profile's duplicated catalogue and JSON buffer.
        prior_profile = None
        del raw
    integer(selected_capacity, limits['union_limit'], 'history capacity', 1)

    def collect(paths):
        for path in paths:
            _, pin = _read(path, limits['max_capture_bytes'], retain=False)
            external.append(pin)
            digest = pin.sha256
            if digest in sources:
                continue
            if len(sources) >= MAX_INPUTS:
                raise ValueError('Observation input capacity exceeded')
            sources[digest] = dict(sha256=digest, size_bytes=pin.size_bytes)
            readers[digest] = lambda pin=pin: _read(pin.path, limits['max_capture_bytes'], expected=pin.view())[0]

    if baseline:
        collect(baseline)
        stages = [sorted(sources)]
    base_digests = set(sources)
    collect(additions)
    if stages is None:
        stages = [sorted(sources)]
    else:
        new = sorted(sources.keys() - base_digests)
        if new:
            stages.append(new)
    descriptions = [sources[digest] for digest in sorted(sources)]

    def read_source(digest):
        raw = readers[digest]()
        try:
            text = raw.decode('utf-8')
        except UnicodeError as error:
            raise ValueError('History captures require original UTF-8 JSON') from error
        if text.startswith('\ufeff') or '\0' in text:
            raise ValueError('History captures require UTF-8 without a BOM')
        return raw

    rows, totals, metadata, selected, counts = _derive_raw_observations(descriptions,
        selected_capacity, stages, read_source, **_derivation_limits(limits))
    # All semantic admission completes before creating even a partial output.
    index = dict(format=limits['format'], schema=limits['schema'], execution_evidence=False,
        capacity=selected_capacity, inputs=descriptions, selection_stages=stages,
        selection_policy=SELECTION_POLICY, historical_totals=totals,
        selected_historical_totals=selected, selection_counts=counts, catalogue=[],
        catalogue_sha256='')
    try:
        output.mkdir()
        (output / 'captures').mkdir()
        (output / 'catalogue').mkdir()
    except OSError as error:
        raise ValueError('History requires a new output in an existing ordinary parent') from error
    for entry in descriptions:
        _write_new(output / 'captures' / (entry['sha256'] + '.json'), read_source(entry['sha256']))
    digest = hashlib.sha256()
    buffer, identities = bytearray(), 0

    def flush():
        nonlocal buffer, identities
        if not buffer:
            return
        data = bytes(buffer)
        sha = hashlib.sha256(data).hexdigest()
        _write_new(output / 'catalogue' / (sha + '.jsonl'), data)
        index['catalogue'].append(dict(sha256=sha, size_bytes=len(data), identity_count=identities))
        buffer, identities = bytearray(), 0

    for row in rows:
        line = _canonical(row) + b'\n'
        if len(line) > MAX_LINE_BYTES:
            raise ValueError('History catalogue row exceeds its line bound')
        if identities == MAX_SHARD_IDENTITIES or len(buffer) + len(line) > MAX_SHARD_BYTES:
            flush()
        buffer.extend(line)
        identities += 1
        digest.update(line)
    flush()
    index['catalogue_sha256'] = digest.hexdigest()
    encoded = _canonical(index) + b'\n'
    if len(encoded) > MAX_INDEX_BYTES:
        raise ValueError('Observation history index exceeds 1 MiB')
    # Recheck every original spelling, including duplicate aliases and baselines.
    for pin in external:
        _read(pin.path, pin.size_bytes, expected=pin.view(), retain=False)
    if prior is not None:
        prior.revalidate()
    _write_new(output / INDEX_NAME, encoded)
    return load_history(output / INDEX_NAME)
