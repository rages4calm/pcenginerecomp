# Compare native-module extensions

`pcerecomp.native_extension` compares two original, independently admitted
native module graphs. This is a read-only prerequisite for the continuation
workflow requested in [issue #43](https://github.com/rages4calm/pcenginerecomp/issues/43).
It does **not** transfer checkpoints or authorize a different package to load one.
Ordinary [developer checkpoint](DEVELOPER_CHECKPOINTS.md) restoration still
requires the exact original build and input recipe.

## Command line

```sh
python -m pcerecomp compare-native-extensions \
  --source-manifest OLD_MODULE/module.json --source-observations OLD_INPUT.json \
  --destination-manifest NEW_MODULE/module.json --destination-observations NEW_INPUT.json \
  --out NEW_PRIVATE_REPORT.json
```

For declared modules, each observations argument is its declarations file.
Supply `--source-image` and `--destination-image` for single-source modules, or
repeat `--source-asset ASSET=PATH` and
`--destination-asset ASSET=PATH` for source sets. Optional
`--source-history` and `--destination-history` retain associated execution
history. Existing output files are refused. A successfully written comparison
may report removals or policy differences; command success means the inputs
were admitted and compared, not that continuation is permitted.

For [offline CD loads](CD_LOADS.md), use `--source-cd-source disc=PATH` and
`--source-cd-source toc=PATH`, and the corresponding `--destination-cd-source`
arguments. CHD additionally requires `libchdr=PATH` on each side. These are
separate from boot source-set assets and retain complete media provenance.

## Python interface

```python
from pcerecomp.native_extension import compare_native_extensions

report = compare_native_extensions(
    old_module_manifest, old_observation_input,
    new_module_manifest, new_observation_input,
)
```

Every path refers to an original input, not a previously serialized comparison
report. Both sides pass through `load_native_catalog`, which authenticates the
explicit selection contract, reconstructs membership and verifies the original
source artifacts. The comparison binds the original manifest bytes to each
admitted catalogue and checks its manifest snapshots again before returning.
These checks establish content during admission, not a filesystem lock or
producer authentication.

For declarations, source sets, overlays or observation history, supply the
existing catalogue arguments independently for each side:

```python
report = compare_native_extensions(
    old_module_manifest, old_declarations,
    new_module_manifest, new_declarations,
    source_options={
        "producer_contract": "declared-overlay-abi29-v1",
        "source_images": old_source_images,
        "observation_history": old_history,
    },
    destination_options={
        "producer_contract": "declared-overlay-abi29-v1",
        "source_images": new_source_images,
        "observation_history": new_history,
    },
)
```

Source-image bindings retain the existing catalogue interface; this operation
does not infer media, loader addresses or declaration roots. Original captures,
generated source, manifests and checkpoints remain untouched.

## Read the report

The versioned report has kind `pce-native-extension-comparison` and classifies
**emitted membership** as `unchanged`, `strict-additive`, `replacement` or
`removal`. An unchanged set is a subset but is not a strict extension.

Each identity includes logical PC, **all eight MPRs**, every physical instruction
fetch address and exact source bytes. `retained`, `added` and `removed` expose
counts and SHA256 digests of canonically sorted complete identities. They do
not publish the code-bearing identity rows. Same-location variant diagnostics
group by PC, full mapping and the complete physical fetch tuple, then count
extended, replaced or removed source-byte sets. A changed mapping is a distinct
location even when the currently addressed bank remains unchanged.

Both sides retain their original catalogue provenance, manifest identity,
selection implementation, evidence classes and observed/declared/emitted/
excluded/unsupported set digests. Membership changes never create retirement
hits or turn declared candidates into executed code.

`policy_compatible` requires exact agreement on declared dispatch and guard
policies, ABI, emission/selection contracts, physical exclusions, code-fetch
observation, native spans, immediate-operand sharing and partition layout.
Presence and absence remain distinct. `manifest_policy_changes` identifies
changed manifest fields; `policy_changes` also includes catalogue contracts.
This deliberately conservative comparison does not infer semantic equivalence
between different layout or lowering policies. Counts that naturally grow with
the module, such as translated body count, are not policy settings.

An additive identity set with changed policies remains visibly additive, while
`policy_compatible` is false. Neither field is a migration approval:
`migration_authorized`, `qualified` and `execution_evidence` are always false.

## Separate continuation admission

The [supported continuation operation](CHECKPOINT_CONTINUATIONS.md) separately
verifies both linked packages, compiler/effective flags and compiled dependency closure, exact
lowering and generated source, and engine/checkpoint serialization compatibility.
Matching ABI numbers alone are insufficient. It must also bind media, firmware,
providers, boot/runtime/input/reference recipes and the untouched source
checkpoint. CPU/device state, clocks, pending PCM, host cursors and imported
counters must survive without edits. Fresh destination native, repeat and
interpreter-reference suffixes must then be qualified.

The comparison report lists these gates explicitly. Catalogue membership alone
proves neither translation semantics nor linked binary behavior. In particular,
this comparison alone does not make existing cross-build checkpoints portable
or waive ordinary restore constraints.

## Verification scope

Authored captures are emitted into real native modules and passed through
catalogue admission. Tests cover additive and unchanged membership, removals,
source-byte replacements and retained variants, full MPR identity, changed ABI,
exclusions/layout/native-span/operand-sharing policies, artifact tampering,
manifest-byte binding and original-input preservation. These are comparison
tests, not executed native routes or a retail-game continuation qualification.
