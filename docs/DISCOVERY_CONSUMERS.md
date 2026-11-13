# Discovery provenance in consumer projects

Use preparation `module.kind = "discovery"` when a consumer needs the complete
[static-discovery derivation](STATIC_DISCOVERY.md), rather than only its expanded
numeric roots. This keeps the original seeds, roots and report together through
verification, builds, package-cache/recovery contracts, execution receipts and
[managed generations](INCREMENTAL_BUILDS.md).

This is host-side provenance. Runtime ABI **29**, guest execution/device semantics
and checkpoint encoding are unchanged. A copied or verified derivation is not
observed guest work, compilation, execution, hardware qualification or proof that
every possible path was recovered.

## Immutable data derivations

The opt-in [ROM data policy](ROM_DATA.md) is also admitted with its exact original
three-file graph. Data witnesses and composed call/vector/table options are
rederived against the bound image, with no fabricated observations. Older readers
refuse its new policy identifier. Generated loads still read live memory.

## Prepare a discovery consumer

Start with an admitted default, ROM-vector, synchronous-call or opt-in
[unknown-X ROM table discovery](ROM_TABLES.md). Table candidates retain the same
exact three-file closure and independent rederivation, with no execution claims.
Older readers refuse its new policy identifiers. In the normal
[HuCard preparation recipe](PREPARE_PROJECT.md), select:

```toml
[module]
kind = "discovery"
path = "../discovery/discovery.json"
partition_layout = "stable"
# Optional real observation history remains a separate provenance class:
# history_path = "../history/history.json"
# history_version = 2
# capacity = 131072
```

The input path can name the report or its directory. All ordinary explicit boot,
cartridge, runtime and limits fields remain required. The exact raw image and
profile/header/encoding must agree with the graph. Capacity/history-version options
still require an actual history; a pure discovery does not create an empty one.

Preparation recomputes the derivation, copies the exact three artifact files into
`consumer/discovery/`, then emits normal guarded translated operations from the
copied `roots.json`. It does not copy the ROM. Expanded roots are stored once:
there is no second `declarations/roots.json` for this input kind. Original input
bytes remain unchanged. Preparation output cannot be inside its original closed
graph, and existing destinations refuse.

The descriptor contains both typed bindings:

```toml
[module.declared_roots]
path = "discovery/roots.json"
sha256 = "FULL_EXPANDED_ROOTS_SHA256"

[module.discovery]
path = "discovery/discovery.json"
sha256 = "FULL_REPORT_SHA256"
```

The preparation receipt separately retains `original_declarations` and
`original_discovery`, including the original report path/hash and analysis policy.
Original paths are historical provenance, not ongoing dependencies: subsequent
consumer verification uses its owned graph and the independently bound cartridge.
The ordinary optional observation history preserves its exact originals, historical
ABIs, selection stages and actual counters. Declarations never acquire invented hits.

## What verification and build contracts bind

Verification rederives the graph from its exact retained seeds, policy, ranges and
cartridge, then requires its expanded-roots digest to equal the compiled declaration
binding. Rehashing edited graph metadata cannot replace that derivation. A valid
graph with different roots also refuses, even if its source image is the same.

The checked input map contains `module_discovery` for the report and
`module_discovery:seed-roots.json` / `module_discovery:roots.json` for the other
files. These participate in the existing module-input identities for build cache,
interrupted-build recovery and build/run receipts. The cartridge remains a fixed
asset; it is never classified as mutable module data or copied into these graphs.
Graph directories are not implicitly authorized as compiler/include roots.

Changing derivation metadata requires a new build binding even if roots and emitted
C++ remain identical. An old execution receipt or checkpoint does not become a new
qualification. The module manifest and standalone native catalogue still describe
ordinary declared/observed membership; they do not independently authenticate a
discovery merely because they share its roots. The optional descriptor binding is
what admits and carries this additional provenance.

Existing `kind = "declared"` preparation still accepts an ordinary roots file and
binds only those declarations. It does not infer a discovery graph from neighboring
files or paths. Existing descriptors without discovery remain supported unchanged.

## Managed generation retention

The managed workspace owns exactly three files under `module/discovery/`. Its
`module.declared_roots` references the same `discovery/roots.json`; no standalone
`declared-roots.json` duplicate is written. Each completed generation retains its
own exact three-file graph under `history/NNNNNN/discovery/`, with report and artifact
hashes/sizes in the state record. The declared-roots state binding points to that
same archived roots file.

Active-generation archive admission recomputes the derivation against the fixed
cartridge and cross-checks the archived declarations. Missing, modified, extra or
misbound artifacts refuse reuse/run. Archive bindings must agree with the owned
descriptor and fixed configuration, every owned graph file must match its archived
bytes, and managed graph paths must stay inside their owned namespace. A different
valid archive plus recomputed state hashes cannot bypass those cross-checks. Live module/build-tree protection remains in
force. Admission does not recursively re-audit every older generation; verify a
historical graph separately before using its evidence.

An update may supply a new admitted derivation under the same fixed machine/media/
SDK contract. Previous generation bytes remain intact. A graph-only change with
identical roots and translated code can preserve compiled object bytes and mtimes;
it still publishes a new provenance/build binding. Once a workspace retains
discovery, silently removing that binding refuses before compilation. Use a new
workspace for an explicitly declaration-only contract.

## Python copying and example

`copy_discovery` provides the same separate-directory graph-copy boundary:

```python
from pcerecomp.discovery import copy_discovery

copied = copy_discovery(original_report, exact_image, new_directory)
copied.revalidate()
```

It recomputes input/output admission, preserves exact bytes, refuses existing or
nested destinations, revalidates originals, and publishes the report last. Physical
parent identity is checked too, including Windows extended-path aliases, before
copy or preparation can allocate an output inside the original closed graph. A failed
partial output is diagnostic material; it does not admit as a complete graph.

The [authored ROM-vector example](../examples/rom-vectors/README.md) supports
`prepare --retain-discovery`. Its normal qualification separately checks actual
native/reference work, full RAM, literal clocks and guard negatives. The managed
native integration fixture additionally exercises a graph-only update, actual
object retention and separate original-generation derivations. Those bounded
authored checks do not qualify game progression or independent hardware behavior.

## Qualified scope

Frozen `63daf485` passes **2,073 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases** with all 750 tracked inputs unchanged.
The discovery-backed authored example qualifies nine actual native retirements,
separate native/reference whole-RAM and literal-clock probes, and two source/target
negatives. A real managed integration preserves all object/code bytes and mtimes
across a graph-only change, separately rederives both generation archives and
executes the same nine-native route again. The old build refuses a separately
verified graph-only candidate; checkpoint context hashes differ without any
cross-build state-load claim. Exact producers and boundaries are in
[current status](STATUS.md).
