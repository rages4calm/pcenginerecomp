"""Read-only comparison of admitted native identity catalogues, never state migration."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json

from .native_catalog import NativeCatalog, MAX_MANIFEST_BYTES, load_native_catalog
from .snapshots import SnapshotStore


_POLICY_FIELDS = (
    'runtime_abi', 'dispatch_strategy', 'guards', 'unsupported_policy',
    'excluded_physical_ranges', 'bus_trace', 'native_span', 'operand_sharing',
    'partition_size', 'partitioned', 'partition_layout', 'pc_bucket_size',
    'partition_identity',
)
_REMAINING_GATES = [
    'Verify both exact linked packages and their original build receipts.',
    'Verify compiler, effective flags and complete compiled dependency closure.',
    'Verify reviewed lowering semantics and generated source, not only membership.',
    'Verify engine and checkpoint serialization compatibility independently of ABI.',
    'Verify exact media, firmware, providers, boot, runtime, input and reference recipes.',
    'Validate the untouched source checkpoint and preserve all machine, host, audio and imported counters.',
    'Qualify fresh destination native, repeat and interpreter-reference suffixes.',
]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def _identities(values):
    # Include every source byte, physical fetch address and all eight MPRs in
    # the digest without publishing code-bearing identities in the report.
    return dict(count=len(values), sha256=_digest(sorted(values)))


def _policies(catalog, manifest):
    return dict(manifest={key: dict(present=key in manifest, value=manifest.get(key))
                          for key in _POLICY_FIELDS},
                selection_contract=catalog.provenance['selection_contract'],
                declared_emission_contract=catalog.provenance['declared_emission_contract'],
                selection_source=catalog.provenance['selection_source'])


def _side(catalog, policies):
    provenance = catalog.provenance
    return dict(runtime_abi=catalog.runtime_abi,
                manifest=provenance['manifest'],
                catalogue_provenance_sha256=_digest(provenance),
                provenance=provenance,
                identities={name: _identities(getattr(catalog, name))
                            for name in ('emitted', 'observed', 'declared', 'excluded', 'unsupported')},
                policies=policies, policies_sha256=_digest(policies))


def report_native_extension(source_catalog, destination_catalog, *,
                            source_manifest, destination_manifest):
    """Compare admitted catalogues and their exact original manifest bytes.

    Callers should normally use ``compare_native_extensions``, which performs
    admission itself. This in-process helper requires NativeCatalog objects and
    binds raw manifest bytes to each admitted digest; JSON reports are not
    accepted as catalogue authority. The result never authorizes continuation.
    """
    catalogs = (source_catalog, destination_catalog)
    policies = []
    for catalog, raw in zip(catalogs, (source_manifest, destination_manifest)):
        if not isinstance(catalog, NativeCatalog) or type(raw) is not bytes:
            raise ValueError('Extension comparison requires admitted catalogues and original manifest bytes')
        if (len(raw) > MAX_MANIFEST_BYTES or
                hashlib.sha256(raw).hexdigest() != catalog.provenance['manifest']['sha256']):
            raise ValueError('Extension manifest differs from its admitted catalogue')
        policies.append(_policies(catalog, json.loads(raw)))
    source, destination = (catalog.emitted for catalog in catalogs)
    retained, added, removed = source & destination, destination-source, source-destination
    locations = defaultdict(lambda: [set(), set()])
    for side, values in enumerate((source, destination)):
        for pc, mpr, physical, data in values:
            locations[(pc, mpr, physical)][side].add(data)
    changes = {name: [] for name in ('extended', 'replaced', 'removed')}
    for location, (before, after) in sorted(locations.items()):
        if not before or before == after:
            continue
        kind = 'replaced' if before-after and after-before else 'removed' if before-after else 'extended'
        changes[kind].append((location, sorted(before), sorted(after)))
    policy_changes = [name for name in policies[0] if policies[0][name] != policies[1][name]]
    manifest_policy_changes = [name for name in _POLICY_FIELDS
                               if policies[0]['manifest'][name] != policies[1]['manifest'][name]]
    relation = ('unchanged' if not added and not removed else 'strict-additive' if not removed
                else 'replacement' if added else 'removal')
    return dict(schema=1, kind='pce-native-extension-comparison',
                source=_side(source_catalog, policies[0]),
                destination=_side(destination_catalog, policies[1]),
                relation=relation, source_is_subset=not removed,
                strict_additive=bool(added) and not removed,
                retained=_identities(retained), added=_identities(added), removed=_identities(removed),
                variant_changes={name: dict(locations=len(rows), sha256=_digest(rows))
                                 for name, rows in changes.items()},
                policy_compatible=not policy_changes,
                policy_changes=policy_changes, manifest_policy_changes=manifest_policy_changes,
                migration_authorized=False, qualified=False, execution_evidence=False,
                remaining_gates=list(_REMAINING_GATES),
                scope='Admitted emitted membership and exact declared policies only; no translation, linkage, checkpoint migration or execution qualification.')


def compare_native_extensions(source_manifest, source_observations,
                              destination_manifest, destination_observations, *,
                              source_options=None, destination_options=None):
    """Admit both original module graphs and return a read-only comparison.

    Options are explicit keyword arguments for ``load_native_catalog`` (source
    images, history and producer contract). No existing comparison JSON can
    replace admission. Original inputs and checkpoints are never rewritten.
    """
    store = SnapshotStore()
    snapshots = [store.read_json(path, max_bytes=MAX_MANIFEST_BYTES)
                 for path in (source_manifest, destination_manifest)]
    catalogs = [load_native_catalog(manifest, observations, **(options or {}))
                for manifest, observations, options in (
                    (source_manifest, source_observations, source_options),
                    (destination_manifest, destination_observations, destination_options))]
    # SnapshotStore retains original JSON bytes; bind them to admission rather
    # than reconstructing the original encoding from a parsed dictionary.
    raws = [snapshot.raw for snapshot in snapshots]
    result = report_native_extension(*catalogs, source_manifest=raws[0], destination_manifest=raws[1])
    store.revalidate()
    return result
