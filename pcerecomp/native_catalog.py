"""Read-only reconstruction of observed and explicitly declared membership.

This checks an explicit selection contract, original observation provenance and
every manifest-listed source artifact. It neither executes an old SDK/emitter
nor proves C++ semantics, linkage, execution, coverage completeness or producer
authorship. Untyped static-CFG manifests have no admitted identity catalogue here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import groupby
import json
import os
from pathlib import Path
import re
import stat

from .capture import MAX_CAPTURE_BYTES, MAX_EXTENDED_CAPTURE_BYTES, U64, parse_capture_bytes, validate_capture
from .isa import NATIVE
from .observations import MAX_PROFILE_BYTES, _profile_accounting, _validate


Identity = tuple[int, tuple[int, ...], tuple[int, ...], tuple[int, ...]]
PRODUCER_CONTRACT = 'observed-abi28-29-v1'
DECLARED_PRODUCER_CONTRACT = 'declared-rom-abi29-v1'
SOURCE_SET_PRODUCER_CONTRACT = 'declared-source-set-abi29-v1'
OVERLAY_PRODUCER_CONTRACT = 'declared-overlay-abi29-v1'
_OVERLAY_EMITTER_CONTRACT = 'observed-and-declared-overlay-abi29-v1'
_SOURCE_SET_EMITTER_CONTRACT = 'observed-and-declared-source-set-abi29-v1'
_DECLARED_EMITTER_CONTRACT = 'observed-and-declared-rom-abi29-v1'
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 512 * 1024 * 1024
_ISA_SHA = '8f1b4454029d442313b93ea162311f0cf4d46a965cdd562b1341f72c2d6ba9ea'
# These exact reviewed implementations retain the same observed identity
# membership rules. The second additionally separates real operand fetches
# from data callbacks; that observation contract is not backdated into ABI28.
_EMITTER_SOURCES = {
    '8ba31b588355b9528a8379bd6d0e31f3502df7938faa9309c23e68f6fbf5daa0': 'observed-abi28-29-policy-v1',
    'f477c78b1ca5650136708966e21c25ee0feec74ceb2c6c87b737121c4ee84b4f': 'observed-abi29-separated-fetch-v1',
    # The history transport adds no opcode/identity membership changes.
    '02dafd62a94ecc46216c687b28bc960f72f7631ddc898fccb5ef7217aeaa4a22': 'observed-abi29-separated-fetch-v1',
    # Explicit format-2 capture provenance does not alter identity membership.
    '94810d6f4ebe0fd71f864244b1ea53173c91b12938b0f809344d4a60679fe04d': 'observed-abi29-separated-fetch-v1',
    # Explicit declarations preserve observed selection and add a separate,
    # source-bound unexecuted identity class under the contract below.
    '960a008181325bf7eeab6694d2921aad03898c7b391f44b37d499c1a24401aa7': 'observed-abi29-separated-fetch-v1',
    # Shared layout reuses only identical complete guarded parts; observed
    # membership and declared-source identity remain unchanged.
    '116cbb793b412017ddd3ada8578157a7bdfcca65b4abd035a5886d6d6c9242ef': 'observed-abi29-separated-fetch-v1',
    '939ea1b55eb6d6ed9ecf02a91b1b37597de415d205c6d57ccae1b828e3952d0d': 'observed-abi29-separated-fetch-v1',
    # Explicit multi-source composition preserves observed/single-source
    # selection. Source sets add the separate reviewed contract below.
    '90fe212ffb2547a50a84bfe90162c7bbcd4ed4a1edd77db053eb1aca0341f9a3': 'observed-abi29-separated-fetch-v1',
    # Overlay inputs add a separately rederived source class, leaving existing
    # observed/single-source/source-set emission selection unchanged.
    '13b577eb3a40d9a74b1aac05e4f0fb5da5ada7e2c223b7fde8901768e2acc546': 'observed-abi29-separated-fetch-v1',
}
_DECLARED_EMITTER_SOURCES = frozenset({
    '960a008181325bf7eeab6694d2921aad03898c7b391f44b37d499c1a24401aa7',
    '116cbb793b412017ddd3ada8578157a7bdfcca65b4abd035a5886d6d6c9242ef',
    '939ea1b55eb6d6ed9ecf02a91b1b37597de415d205c6d57ccae1b828e3952d0d',
    '90fe212ffb2547a50a84bfe90162c7bbcd4ed4a1edd77db053eb1aca0341f9a3',
    '13b577eb3a40d9a74b1aac05e4f0fb5da5ada7e2c223b7fde8901768e2acc546',
})
_SOURCE_SET_EMITTER_SOURCES=frozenset({'90fe212ffb2547a50a84bfe90162c7bbcd4ed4a1edd77db053eb1aca0341f9a3','13b577eb3a40d9a74b1aac05e4f0fb5da5ada7e2c223b7fde8901768e2acc546'})
_OVERLAY_EMITTER_SOURCES=frozenset({'13b577eb3a40d9a74b1aac05e4f0fb5da5ada7e2c223b7fde8901768e2acc546'})
_BUS_TRACE_CONTRACT = dict(schema=1, profile='software-access-callback-v1', code_fetch='separate-v1')
_NATIVE_SHA = '6951ccf25b9c079dad86a31f937af81afadae0e28add5e7635da58ca9934e6fd'
_GUARDS = ['full_mpr_snapshot', 'exact_source_bytes_per_instruction', 'instruction_deadline']
_POLICY = 'return to dispatcher, then bounded interpreter or explicit trap'


@dataclass(frozen=True)
class NativeCatalog:
    runtime_abi: int
    observed: frozenset[Identity]
    emitted: frozenset[Identity]
    excluded: frozenset[Identity]
    unsupported: frozenset[Identity]
    counts: dict
    provenance: dict
    declared: frozenset[Identity] = frozenset()


def _integer(value, maximum, label, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} requires an integer in {minimum}..{maximum}')
    return value


def _digest(value, label):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError(label+' requires a lowercase SHA256')
    return value


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON field in native catalogue input')
            value[key] = item
        return value

    def no_float(_):
        raise ValueError('Native catalogue inputs require finite integer numeric tokens')
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_float=no_float, parse_constant=no_float)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Invalid native catalogue JSON encoding or nesting') from error


def _exact(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_exact(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_exact(a, b) for a, b in zip(left, right))
    return left == right


def _expect(manifest, field, value):
    if field not in manifest or not _exact(manifest[field], value):
        raise ValueError('Module manifest disagrees with '+field)


def _stamp(value):
    # Windows Path.stat and fstat expose different legacy ctime meanings on
    # supported Python versions. File ID/size/mtime and whole-call hashes agree.
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


class _Files:
    """Whole-call content/stability epoch; never put resolved paths in reports."""
    def __init__(self):
        self.pins = {}

    def read(self, path, maximum, *, expected=None, retain=True):
        path = Path(path).absolute()
        if path.is_symlink():
            raise ValueError('Native catalogue inputs cannot be symbolic links')
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ValueError('Native catalogue input is not a bounded nonempty regular file')
        digest = hashlib.sha256()
        chunks = []
        size = 0
        with path.open('rb') as stream:
            if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                raise ValueError('Native catalogue input changed before read')
            for chunk in iter(lambda: stream.read(65536), b''):
                size += len(chunk)
                if size > maximum:
                    raise ValueError('Native catalogue input exceeds its byte bound')
                digest.update(chunk)
                if retain:
                    chunks.append(chunk)
            if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                raise ValueError('Native catalogue input changed during read')
        after = path.stat()
        if path.is_symlink() or _stamp(after) != _stamp(before) or size != before.st_size:
            raise ValueError('Native catalogue input changed after read')
        actual = digest.hexdigest()
        if expected is not None and actual != _digest(expected, 'Expected file hash'):
            raise ValueError('Native catalogue input SHA256 mismatch')
        key = str(path.resolve())
        pin = _stamp(after), actual, maximum
        if key in self.pins and self.pins[key] != pin:
            raise ValueError('Native catalogue input changed within admission')
        self.pins[key] = pin
        public = dict(basename=path.name, sha256=actual, size_bytes=size)
        return b''.join(chunks) if retain else None, public

    def finish(self):
        for name, (stamp, digest, maximum) in list(self.pins.items()):
            path = Path(name)
            if _stamp(path.stat()) != stamp:
                raise ValueError('Native catalogue input epoch changed')
            self.read(path, maximum, expected=digest, retain=False)


def _selection_contract(files, producer_contract):
    if producer_contract not in (PRODUCER_CONTRACT, DECLARED_PRODUCER_CONTRACT,SOURCE_SET_PRODUCER_CONTRACT,OVERLAY_PRODUCER_CONTRACT) or type(producer_contract) is not str:
        raise ValueError('Unsupported native catalogue producer selection contract')
    base = Path(__file__).resolve().parent
    files.read(base/'isa.py', MAX_ARTIFACT_BYTES, expected=_ISA_SHA, retain=False)
    _, emitter = files.read(base/'emitter.py', MAX_ARTIFACT_BYTES, retain=False)
    if emitter['sha256'] not in _EMITTER_SOURCES:
        raise ValueError('Native catalogue emitter SHA256 has no reviewed selection contract')
    if (producer_contract in (DECLARED_PRODUCER_CONTRACT,SOURCE_SET_PRODUCER_CONTRACT,OVERLAY_PRODUCER_CONTRACT) and
            emitter['sha256'] not in _DECLARED_EMITTER_SOURCES):
        raise ValueError('Declared ROM roots require the reviewed declared selection contract')
    native = frozenset(NATIVE)
    if any(type(op) is not int or not 0 <= op <= 255 for op in native):
        raise ValueError('Native opcode selection contract changed')
    digest = hashlib.sha256(json.dumps(sorted(native), separators=(',', ':')).encode()).hexdigest()
    if digest != _NATIVE_SHA:
        raise ValueError('Native opcode selection contract changed')
    return native, dict(isa_sha256=_ISA_SHA, emitter_sha256=emitter['sha256'],
                        emitter_contract=(_DECLARED_EMITTER_CONTRACT if producer_contract == DECLARED_PRODUCER_CONTRACT
                                          else _EMITTER_SOURCES[emitter['sha256']]),
                        native_opcodes_sha256=digest, native_opcode_count=len(native))


def _artifacts(files, manifest_path, manifest):
    base = Path(manifest_path).resolve().parent
    seen, result, total = set(), {}, 0
    maximum_units = 1048577 if ('declared_roots_sha256' in manifest
                               or manifest.get('observation_history_schema') == 2
                               or manifest.get('capture_schema') == 2) else 65537
    for field, suffix, low, high in (('translation_units', '.cpp', 1, maximum_units),
                                    ('generated_headers', '.hpp', 0, 256)):
        entries = manifest.get(field)
        if type(entries) is not list or not low <= len(entries) <= high:
            raise ValueError('Observed module requires bounded '+field+' artifact list')
        output = []
        for item in entries:
            if type(item) is not dict or set(item) != {'file', 'sha256'}:
                raise ValueError('Invalid module artifact fields')
            name = item['file']
            if (type(name) is not str or not 1 <= len(name) <= 128
                    or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', name) is None
                    or not name.endswith(suffix)
                    or name.split('.', 1)[0].upper() in {
                        'CON', 'PRN', 'AUX', 'NUL',
                        *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
                raise ValueError('Module artifact requires a portable '+suffix+' basename')
            if name.casefold() in seen:
                raise ValueError('Duplicate module artifact basename, case insensitive')
            seen.add(name.casefold())
            path = base/name
            if path.is_symlink() or path.resolve().parent != base:
                raise ValueError('Module artifact escapes manifest directory')
            _, binding = files.read(path, MAX_ARTIFACT_BYTES,
                                    expected=_digest(item['sha256'], 'Artifact'), retain=False)
            total += binding['size_bytes']
            if total > MAX_TOTAL_ARTIFACT_BYTES:
                raise ValueError('Total module artifact bytes exceed catalogue bound')
            output.append(binding)
        result[field] = output
    if not result['translation_units'] or result['translation_units'][0]['basename'] != 'module.cpp':
        raise ValueError('Observed module requires module.cpp as its first translation unit')
    return result


def _shared_layout_contract(manifest):
    """Admit the additive layout metadata; input membership is checked below."""
    shared = manifest.get('partition_layout') == 'shared'
    if not shared:
        if {'unshared_partition_count', 'shared_part_count'} & manifest.keys():
            raise ValueError('Shared partition counts require shared layout')
        return False
    _expect(manifest, 'runtime_abi', 29)
    _expect(manifest, 'partitioned', True)
    _expect(manifest, 'partition_identity', 'exact_guarded_pc_ranges_v1')
    _expect(manifest, 'pc_bucket_size', 64)
    unshared = _integer(manifest.get('unshared_partition_count'), 1048576, 'Unshared partition count')
    count = _integer(manifest.get('shared_part_count'), 65536, 'Shared part count')
    if count > unshared:
        raise ValueError('Shared part count exceeds unshared partition count')
    if {'native_span', 'native_span_translated_body_count'} & manifest.keys():
        raise ValueError('Shared layout does not support native spans')
    return True


def _layout(manifest, supported, artifacts):
    size = _integer(manifest.get('partition_size'), 4096, 'Module partition size', 1)
    partitioned = manifest.get('partitioned')
    if type(partitioned) is not bool:
        raise ValueError('Module partitioned must be boolean')
    shared = _shared_layout_contract(manifest)
    stable = 'partition_layout' in manifest and not shared
    if stable:
        _expect(manifest, 'partition_layout', 'stable')
        _expect(manifest, 'pc_bucket_size', 256)
        _expect(manifest, 'partition_identity', 'full_mpr_logical_pc_range_v1')
        if size != 256 or not partitioned:
            raise ValueError('Invalid stable module partition contract')
    elif not shared and {'pc_bucket_size', 'partition_identity'} & manifest.keys():
        raise ValueError('Stable partition metadata requires stable layout')
    elif not shared and partitioned and len(supported) <= size:
        raise ValueError('Balanced partitioning disagrees with emitted instruction count')
    parts, names = [], []
    for mpr, entries in groupby(supported, key=lambda row: row['mpr']):
        entries = list(entries)
        if stable or shared:
            mapping = sum(value << (8*i) for i, value in enumerate(mpr))
            bucket_size = 256 if stable else 64
            for page, rows in groupby(entries, key=lambda row: row['pc'] // bucket_size):
                parts.append(list(rows))
                if stable:
                    names.append(f'module_m{mapping:016x}_p{page << 8:04x}.cpp')
        else:
            current = []
            for _, variants in groupby(entries, key=lambda row: row['pc']):
                variants = list(variants)
                if current and len(current)+len(variants) > size:
                    parts.append(current);current = []
                current.extend(variants)
            if current:
                parts.append(current)
    if shared:
        _expect(manifest, 'unshared_partition_count', len(parts))
        unique, retained = set(), []
        for part in parts:
            signature = tuple((row['pc'], tuple(row['physical']), tuple(row['data'])) for row in part)
            if signature not in unique:
                unique.add(signature)
                retained.append(part)
        parts = retained
        _expect(manifest, 'shared_part_count', len(parts))
    unit_sizes = [len(part) for part in parts]
    if shared:
        unit_sizes, count = [], 0
        for part in parts:
            if count and count + len(part) > size:
                unit_sizes.append(count)
                count = 0
            count += len(part)
        if count:
            unit_sizes.append(count)
    if not stable:
        names = [f'module_part_{i:04d}.cpp' for i in range(len(unit_sizes))]
    expected_units = ['module.cpp']+sorted(names) if partitioned else ['module.cpp']
    expected_headers = ['module_parts.hpp'] if partitioned else []
    if ([row['basename'] for row in artifacts['translation_units']] != expected_units
            or [row['basename'] for row in artifacts['generated_headers']] != expected_headers):
        raise ValueError('Module artifact membership disagrees with declared selection layout')
    largest = max(unit_sizes, default=0) if partitioned else len(supported)
    _expect(manifest, 'largest_partition_instructions', largest)
    bodies = _integer(manifest.get('translated_body_count'), len(supported), 'Translated body count')
    if bool(bodies) != bool(supported):
        raise ValueError('Translated body count disagrees with empty/nonempty selection')
    if 'native_span' in manifest:
        if not stable:
            raise ValueError('Native spans require stable observed module layout')
        _expect(manifest, 'native_span', dict(schema=1, protocol='per_instruction_v1'))
        _expect(manifest, 'native_span_translated_body_count', bodies)
    elif 'native_span_translated_body_count' in manifest:
        raise ValueError('Native span count requires explicit native span protocol')


def _key(row):
    return row['pc'], tuple(row['mpr']), tuple(row['physical']), tuple(row['data'])


def load_native_catalog(manifest_path, observations_path, *, image_path=None,
                        observation_history=None, producer_contract=PRODUCER_CONTRACT,source_images=None):
    """Admit declared emission membership, preserving distinct evidence classes.

    The named contract supports the unchanged identity-membership selection of
    the reviewed ABI28/29 emitters. Additive observation semantics are declared
    separately and never backdated into ABI28. Build/producer/execution proof remains
    separate. Paths never enter returned provenance beyond explicit basenames.
    Original capture/profile files and generated source are never modified.
    For a declared-roots module, observations_path is its exact declarations
    file; image_path (single source) or source_images (source set) is mandatory,
    and observation_history is separately explicit. Source-set catalogues use
    their own versioned selection/provenance contract and closed member graph.
    Only actual history contributes to the returned observed identity set.
    """
    files = _Files()
    native, selection_source = _selection_contract(files, producer_contract)
    raw, manifest_binding = files.read(manifest_path, MAX_MANIFEST_BYTES)
    manifest = _json(raw)
    if type(manifest) is not dict:
        raise ValueError('Module manifest must be an object')
    _expect(manifest, 'schema', 1)
    abi = _integer(manifest.get('runtime_abi'), 29, 'Observed module runtime ABI', 28)
    emission_contract = dict(name='observed-abi28-29-policy-v1')
    if 'bus_trace' in manifest:
        if abi != 29:
            raise ValueError('Separated code-fetch observation requires module producer ABI29')
        _expect(manifest, 'bus_trace', _BUS_TRACE_CONTRACT)
        emission_contract = dict(name='observed-abi29-separated-fetch-v1',
                                 bus_trace=dict(_BUS_TRACE_CONTRACT))
    _expect(manifest, 'execution_evidence', False)
    _expect(manifest, 'dispatch_strategy', 'full_mpr_pc_opcode_operand_key')
    _expect(manifest, 'guards', _GUARDS)
    _expect(manifest, 'unsupported_policy', _POLICY)
    if 'declared_roots_sha256' in manifest:
        return _load_declared_catalog(files, native, selection_source, manifest_path,
            manifest, manifest_binding, observations_path, image_path,
            observation_history, abi,source_images,producer_contract)
    if image_path is not None or source_images is not None or observation_history is not None or producer_contract in (DECLARED_PRODUCER_CONTRACT,SOURCE_SET_PRODUCER_CONTRACT,OVERLAY_PRODUCER_CONTRACT):
        raise ValueError('Declaration source/history arguments require a declared-roots module')
    capture_input = 'code_capture_sha256' in manifest
    profile_input = 'observation_profile_sha256' in manifest
    history_input = 'observation_history_sha256' in manifest
    if sum((capture_input, profile_input, history_input)) != 1:
        raise ValueError('Native membership unavailable: require exactly one observed capture/profile/history provenance')
    field = ('code_capture_sha256' if capture_input else
             'observation_profile_sha256' if profile_input else 'observation_history_sha256')
    maximum = ((MAX_EXTENDED_CAPTURE_BYTES if manifest.get('capture_schema') == 2 else MAX_CAPTURE_BYTES)
               if capture_input else MAX_PROFILE_BYTES)
    if history_input:
        from .history import MAX_INDEX_BYTES
        maximum = MAX_INDEX_BYTES
    raw, input_binding = files.read(observations_path, maximum,
                                    expected=_digest(manifest[field], 'Observation input'))
    value = parse_capture_bytes(raw) if capture_input else _json(raw)
    admitted_history = None
    history_artifacts = []
    if capture_input:
        if any(key.startswith('observation_') for key in manifest):
            raise ValueError('Capture manifest cannot declare observation-profile provenance')
        instructions = validate_capture(value)
        provenance = [{key: item for key, item in value.items() if key != 'observations'}]
        accounting = dict(capture_runtime_abi=value['runtime_abi'],
            capture_complete=value['complete'], capture_retired_instructions=value['retired_instructions'],
            capture_dropped_instructions=value['dropped_instructions'],
            capture_unreadable_instructions=value['unreadable_instructions'],
            captured_native_hits=sum(row['native_hits'] for row in instructions),
            captured_interpreted_hits=sum(row['interpreted_hits'] for row in instructions))
        if value['schema'] == 2:
            if abi != 29:
                raise ValueError('Extended capture requires module producer ABI29')
            accounting.update(capture_schema=2, capture_format=value['format'])
        if 'checkpoint_origin' in value:
            accounting.update(capture_checkpoint_origin=value['checkpoint_origin'],
                              capture_execution_window='resumed-checkpoint-suffix')
        elif {'capture_checkpoint_origin', 'capture_execution_window'} & manifest.keys():
            raise ValueError('Module invented capture checkpoint origin')
        if 'execution_policy' in value:
            accounting['capture_execution_policy'] = value['execution_policy']
        elif 'capture_execution_policy' in manifest:
            raise ValueError('Module invented capture execution policy')
    elif profile_input:
        if any(key.startswith(('capture_', 'captured_')) for key in manifest):
            raise ValueError('Profile manifest cannot declare singular capture provenance')
        instructions, provenance = _validate(value)
        accounting = dict(observation_profile_format=value['format'],
            observation_profile_schema=value['schema'], observation_inputs=provenance,
            **_profile_accounting(value))
        if value['schema'] == 1 and {'selection_stages', 'selected_historical_totals',
                                    'selection_counts', 'selection_policy'} & manifest.keys():
            raise ValueError('Version1 profile cannot declare additive selection metadata')
    else:
        from .history import load_history
        if abi != 29:
            raise ValueError('Observation history requires module producer ABI29')
        if any(key.startswith(('capture_', 'captured_', 'observation_profile_')) for key in manifest):
            raise ValueError('History manifest cannot declare singular capture/profile provenance')
        admitted_history = load_history(observations_path)
        if admitted_history.index_sha256 != input_binding['sha256']:
            raise ValueError('Observation history index changed during catalogue admission')
        instructions = admitted_history.instructions
        provenance = admitted_history.input_metadata
        accounting = dict(observation_history_format=admitted_history.index['format'],
            observation_history_schema=admitted_history.index['schema'],
            observation_inputs=provenance, **admitted_history.accounting)
        for relative, artifact in sorted(admitted_history.artifact_bindings.items()):
            if relative == 'history.json':
                bound = input_binding  # Already pinned under the index's fixed byte bound.
            else:
                _, bound = files.read(artifact['path'], artifact['size_bytes'],
                                      expected=artifact['sha256'], retain=False)
            history_artifacts.append(dict(relative=relative, sha256=bound['sha256'],
                                          size_bytes=bound['size_bytes']))
    for key, expected in accounting.items():
        _expect(manifest, key, expected)
    # A later diagnostic can decode an older module's retained inputs, but
    # cannot backdate a newer capture producer into that historical emitter.
    if any(item['runtime_abi'] > abi for item in provenance):
        raise ValueError('Observation producer ABI exceeds declared module producer contract')
    base_fields = {'schema', 'runtime_abi', 'translation_units', 'generated_headers',
        'partition_size', 'partitioned', 'dispatch_strategy', 'translated_body_count',
        'largest_partition_instructions', 'native_instructions_emitted', 'native_contexts',
        'observed_instructions', 'execution_evidence', 'excluded_physical_ranges',
        'excluded_observations', 'excluded_retired_hits', 'unsupported_observations',
        'guards', 'unsupported_policy', 'scope'}
    optional = {'partition_layout', 'pc_bucket_size', 'partition_identity', 'unshared_partition_count', 'shared_part_count',
                'native_span', 'native_span_translated_body_count', 'bus_trace'}
    if set(manifest) - base_fields - optional - {field} - accounting.keys():
        raise ValueError('Unsupported observed module manifest fields')
    if type(manifest.get('scope')) is not str or len(manifest['scope']) > 4096:
        raise ValueError('Module scope requires a bounded string')
    spans = manifest.get('excluded_physical_ranges')
    if type(spans) is not list or len(spans) > 256:
        raise ValueError('Module exclusions require at most256 physical spans')
    exclusions = []
    for span in spans:
        if type(span) is not dict or set(span) != {'start', 'length'}:
            raise ValueError('Invalid physical exclusion fields')
        start = _integer(span['start'], 0x1fffff, 'Excluded physical start')
        length = _integer(span['length'], 0x200000-start, 'Excluded physical length', 1)
        exclusions.append((start, length))
    if exclusions != sorted(set(exclusions)):
        raise ValueError('Module exclusions must be canonical sorted unique spans')
    excluded, unsupported, emitted = [], [], []
    for row in instructions:
        if any(start <= address < start+length
               for address in row['physical'] for start, length in exclusions):
            excluded.append(row)
        elif row['data'][0] not in native:
            unsupported.append(row)
        else:
            emitted.append(row)
    counts = dict(observed_instructions=len(instructions), native_instructions_emitted=len(emitted),
        native_contexts=len({tuple(row['mpr']) for row in emitted}), excluded_observations=len(excluded),
        excluded_retired_hits=sum(row['native_hits']+row['interpreted_hits'] for row in excluded),
        unsupported_observations=len(unsupported))
    for key, expected in counts.items():
        _integer(manifest.get(key), U64, 'Module '+key)
        _expect(manifest, key, expected)
    artifacts = _artifacts(files, manifest_path, manifest)
    _layout(manifest, emitted, artifacts)
    files.finish()
    if admitted_history is not None:
        admitted_history.revalidate()
    if capture_input:
        provenance[0].update(sha256=input_binding['sha256'], size_bytes=input_binding['size_bytes'],
            native_hits=accounting['captured_native_hits'],
            interpreted_hits=accounting['captured_interpreted_hits'], observation_count=len(instructions))
    return NativeCatalog(abi, frozenset(map(_key, instructions)), frozenset(map(_key, emitted)),
        frozenset(map(_key, excluded)), frozenset(map(_key, unsupported)), counts,
        dict(format='pce-native-catalog-1', selection_contract=producer_contract,
             declared_emission_contract=emission_contract,
             membership_claim='reconstructed-declared-emission', runtime_abi=abi,
             manifest=manifest_binding, observations=dict(kind='capture' if capture_input else 'profile' if profile_input else 'history',
                **input_binding), artifacts=artifacts, original_inputs=provenance,
             **(dict(history_artifacts=history_artifacts) if history_input else {}),
             excluded_physical_ranges=[dict(start=start, length=length) for start, length in exclusions],
             selection_source=selection_source, execution_evidence=False, linked_binary_verified=False,
             scope='Declared emitted identity membership under the named selection contract and exact input/artifact hashes; not producer authorship, generated-code semantics, linked-binary or execution qualification.'))


def _load_declared_catalog(files, native, selection_source, manifest_path, manifest,
                           manifest_binding, declarations_path, image_path,
                           observation_history, abi,source_images,producer_contract):
    """Reconstruct the typed source union without assigning execution to roots."""
    from .declarations import load_compilation

    from .overlays import LIBRARY_FORMAT
    overlay=manifest.get('declared_roots_format')==LIBRARY_FORMAT
    if abi != 29 or image_path is None and source_images is None and not overlay:
        raise ValueError('Declared roots require ABI29 and an explicit source image')
    _expect(manifest, 'bus_trace', _BUS_TRACE_CONTRACT)
    if selection_source['emitter_sha256'] not in _DECLARED_EMITTER_SOURCES:
        raise ValueError('Declared roots require the reviewed declared emitter selection')
    selection_source = selection_source | {'emitter_contract': _DECLARED_EMITTER_CONTRACT}
    if any(key.startswith(('code_capture_', 'capture_', 'captured_', 'observation_profile_')) for key in manifest):
        raise ValueError('Declared roots cannot invent capture or inline-profile provenance')
    if ('observation_history_sha256' in manifest) != (observation_history is not None):
        raise ValueError('Declared module requires its exact optional history binding')
    compilation = load_compilation(declarations_path, image_path,
                                   observation_history=observation_history,source_images=source_images)
    _, declarations_binding = files.read(declarations_path, MAX_MANIFEST_BYTES,
        expected=manifest['declared_roots_sha256'], retain=False)
    source = compilation.provenance['declared_roots_source']
    from .source_sets import FORMAT as SET_FORMAT
    source_set=compilation.declarations.format==SET_FORMAT
    if (source_set or overlay) and selection_source['emitter_sha256'] not in _SOURCE_SET_EMITTER_SOURCES:
        raise ValueError('Source sets require the reviewed source-set emitter selection')
    if overlay and selection_source['emitter_sha256'] not in _OVERLAY_EMITTER_SOURCES:
        raise ValueError('Overlays require the reviewed overlay emitter selection')
    if (source_set and producer_contract in (DECLARED_PRODUCER_CONTRACT,OVERLAY_PRODUCER_CONTRACT)
            or overlay and producer_contract in (DECLARED_PRODUCER_CONTRACT,SOURCE_SET_PRODUCER_CONTRACT)
            or not source_set and producer_contract==SOURCE_SET_PRODUCER_CONTRACT
            or not overlay and producer_contract==OVERLAY_PRODUCER_CONTRACT):
        raise ValueError('Source-set and single-source producer contracts cannot be interchanged')
    source_bindings={}
    if source_set or overlay:
        members=[];images={}
        for name,item in sorted(compilation.declarations.artifact_bindings.items()):
            if name=='declarations':continue
            _,bound=files.read(item['path'],item['size_bytes'],expected=item['sha256'],retain=False)
            if name.startswith('member:'):members.append(dict(relative=name.removeprefix('member:'),sha256=bound['sha256'],size_bytes=bound['size_bytes']))
            elif name.startswith('source_image:'):images[name.removeprefix('source_image:')]=bound
        source_bindings=dict(overlay_artifacts=members) if overlay else dict(declaration_members=members,source_images=images)
        selection_source=selection_source|dict(emitter_contract=_OVERLAY_EMITTER_CONTRACT if overlay else _SOURCE_SET_EMITTER_CONTRACT)
    else:
        _,image_binding=files.read(image_path,source['file_bytes'],expected=source['image_sha256'],retain=False)
        source_bindings=dict(source_image=image_binding)
    for key, expected in (compilation.provenance | compilation.accounting).items():
        _expect(manifest, key, expected)
    history_artifacts = []
    if compilation.history is not None:
        for relative, item in sorted(compilation.history.artifact_bindings.items()):
            _, binding = files.read(item['path'], item['size_bytes'], expected=item['sha256'], retain=False)
            history_artifacts.append(dict(relative=relative, sha256=binding['sha256'],
                                          size_bytes=binding['size_bytes']))
    spans = manifest.get('excluded_physical_ranges')
    if type(spans) is not list or len(spans) > 256:
        raise ValueError('Module exclusions require at most256 physical spans')
    exclusions = []
    for span in spans:
        if type(span) is not dict or set(span) != {'start', 'length'}:
            raise ValueError('Invalid physical exclusion fields')
        start = _integer(span['start'], 0x1fffff, 'Excluded physical start')
        length = _integer(span['length'], 0x200000-start, 'Excluded physical length', 1)
        exclusions.append((start, length))
    if exclusions != sorted(set(exclusions)):
        raise ValueError('Module exclusions must be canonical sorted unique spans')
    instructions = compilation.instructions
    emitted, excluded, unsupported = [], [], []
    for row in instructions:
        if any(start <= address < start+length for address in row['physical'] for start, length in exclusions):
            excluded.append(row)
        elif row['data'][0] not in native:
            unsupported.append(row)
        else:
            emitted.append(row)
    observed = compilation.observed_keys
    declared = compilation.declared_keys
    known = observed | declared
    if frozenset(map(_key, instructions)) != known:
        raise ValueError('Declared/observed union disagrees with admitted source rows')
    counts = compilation.counts(exclude_ranges=exclusions)
    independent = dict(observed_instructions=len(observed), declared_instructions=len(declared),
        source_identity_count=len(known), declared_only=len(declared-observed),
        observed_only=len(observed-declared), declared_observed_overlap=len(declared & observed),
        native_instructions_emitted=len(emitted), native_contexts=len({tuple(r['mpr']) for r in emitted}),
        excluded_observations=sum(_key(r) in observed for r in excluded),
        excluded_declarations=sum(_key(r) in declared for r in excluded),
        excluded_retired_hits=sum(r['native_hits']+r['interpreted_hits'] for r in excluded if _key(r) in observed),
        unsupported_observations=sum(_key(r) in observed for r in unsupported),
        unsupported_declarations=sum(_key(r) in declared for r in unsupported),
        emitted_instructions=len(emitted))
    for key, value in independent.items():
        if key in counts and counts[key] != value:
            raise ValueError('Declared selection count disagrees with source union '+key)
    counts = counts | {key: value for key, value in independent.items()
                       if key in {'native_instructions_emitted', 'native_contexts'}}
    for key, expected in counts.items():
        _integer(manifest.get(key), U64, 'Module '+key)
        _expect(manifest, key, expected)
    base_fields = {'schema', 'runtime_abi', 'translation_units', 'generated_headers',
        'partition_size', 'partitioned', 'dispatch_strategy', 'translated_body_count',
        'largest_partition_instructions', 'native_instructions_emitted', 'native_contexts',
        'observed_instructions', 'execution_evidence', 'excluded_physical_ranges',
        'excluded_observations', 'excluded_retired_hits', 'unsupported_observations',
        'guards', 'unsupported_policy', 'scope'}
    optional = {'partition_layout', 'pc_bucket_size', 'partition_identity', 'unshared_partition_count', 'shared_part_count',
                'native_span', 'native_span_translated_body_count', 'bus_trace'}
    allowed = base_fields | optional | set(compilation.provenance) | set(compilation.accounting) | set(counts)
    if set(manifest)-allowed:
        raise ValueError('Unsupported declared module manifest fields')
    if type(manifest.get('scope')) is not str or len(manifest['scope']) > 4096:
        raise ValueError('Module scope requires a bounded string')
    artifacts = _artifacts(files, manifest_path, manifest)
    _layout(manifest, emitted, artifacts)
    compilation.revalidate()
    files.finish()
    compilation.revalidate()
    provenance = dict(format='pce-native-catalog-4' if overlay else 'pce-native-catalog-3' if source_set else 'pce-native-catalog-2', selection_contract=OVERLAY_PRODUCER_CONTRACT if overlay else SOURCE_SET_PRODUCER_CONTRACT if source_set else DECLARED_PRODUCER_CONTRACT,
        declared_emission_contract=dict(name=_OVERLAY_EMITTER_CONTRACT if overlay else _SOURCE_SET_EMITTER_CONTRACT if source_set else _DECLARED_EMITTER_CONTRACT,
                                       bus_trace=dict(_BUS_TRACE_CONTRACT)),
        membership_claim='reconstructed-declared-and-observed-emission', runtime_abi=abi,
        manifest=manifest_binding, declarations=declarations_binding, **source_bindings,
        source_metadata=source, artifacts=artifacts, excluded_physical_ranges=spans,
        selection_source=selection_source, execution_evidence=False, linked_binary_verified=False,
        scope='Declared source roots and historical observations remain separate evidence classes; declared membership is not execution, generated-code semantics or linked-binary qualification.')
    if compilation.history is not None:
        provenance.update(original_inputs=compilation.history.input_metadata, history_artifacts=history_artifacts,
                          observation_history_sha256=compilation.history.index_sha256)
    return NativeCatalog(abi, observed, frozenset(map(_key, emitted)), frozenset(map(_key, excluded)),
                         frozenset(map(_key, unsupported)), counts, provenance, declared)
