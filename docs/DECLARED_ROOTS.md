# Source-qualified declared instruction roots

A declared root is a numeric instruction-entry declaration recovered from an
exact source image. It is not a retired observation or execution trace. This
interface addresses [issue #13](https://github.com/rages4calm/pcenginerecomp/issues/13)
without inventing capture hits, retirement totals or checkpoint origins.

The original format described below supports explicit read-only HuCard ROM views (`base`, `sf2`,
`populous`). It does not reconstruct live RAM/CD overlays or infer a source view
from an address alone. Each row describes one independently decoded instruction;
routine closure and static reachability are **not inferred**. Unsupported flow
and semantics remain explicit diagnostics or runtime refusal.


## Live RAM overlay inputs

[Live overlay libraries](LIVE_OVERLAYS.md) now admit closed paused RAM/CD epochs
with independently rederived candidate graphs. Use `module.kind = "overlay"`
with the library manifest and an optional genuine `history_path`. The explicit
boot recipe and guest asset hashes must match. Every witness stays bound through
preparation, verification and managed archives; declarations do not become
retired observations. This is a separate source class from the older formats
below, with live fetch guards and unchanged ABI 29.

## Independently verified declaration members

[Declared source sets](SOURCE_SETS.md) combine exact numeric members from
compatible boot assets into one guarded native module. Each member retains its
own source role, raw-file hash and mapping contract; media stays external.
Preparation, descriptor checks and managed archives bind the complete numeric
graph. Optional observation history retains its original execution provenance.
Paused RAM source candidates are now available through [live overlays](LIVE_OVERLAYS.md);
loader attribution and general closure remain open. Runtime ABI 29 is unchanged.

## Declared RAM payload and firmware sources

The explicit [boot-source format](BOOT_SOURCE_DECLARATIONS.md) now admits standard
RAM payloads and Standard/Super System Card ROM through the same declaration,
emission, preparation and verification interfaces. Raw offsets, source-role and
load/profile bindings retain complete PC/MPR/physical/code identity. WRAM mirrors
and the Super RAM aperture are explicit; changed live RAM still meets dynamic
source guards. Old ROM declarations and ABI 29 remain unchanged. Automatic live
CD overlay recovery remains a separate gap; explicit composition is covered above.


## Portable numeric input

```json
{
  "format": "pce-declared-roots-1",
  "schema": 1,
  "kind": "declared",
  "execution_evidence": false,
  "image": {
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "profile": "base",
    "header": "none",
    "encoding": "linear"
  },
  "roots": [
    {"pc": 57408, "mpr": [0, 248, 0, 0, 0, 0, 0, 0], "selector": 0, "rom_offsets": [64, 65]}
  ]
}
```

Replace the example's zero hash with the exact lowercase SHA256 of the original
raw image and use offsets matching its contents. The image is supplied separately;
the declaration contains no filesystem paths or opcode bytes. `rom_offsets` lists
every fetched byte's offset in the **decoded** ROM, after the explicit optional
copier512 header removal and linear/bit-reversed conversion. The hash binds the
original raw file; derived source metadata also binds the decoded ROM.

Every row requires logical PC, all eight MPR bytes, an explicit selector and one
to seven offsets. The selected board map must produce precisely those offsets
and the decoder must agree with the instruction length. SF2 selector is its
four-bit address latch (0..15); other supported profiles require zero. RAM,
absent banks, Populous's RAM aperture, unknown profiles, malformed mappings,
truncated/mismatched offsets and duplicate identical declarations refuse.
Aliased selectors remain distinct declarations while identical full decoded
instruction identities can share one emitted body.

All top-level, image and root fields are exact. Captured hit counts, retirement
counters, origins, completeness flags, embedded code bytes and unknown fields
are not accepted. Limits are 64 MiB per numeric input, 1,048,576 roots and
1,048,576 total decoded identities across declarations plus optional history.
These are combined with existing image, manifest and source-artifact bounds;
no input is silently truncated. Files must be ordinary single-link files with
ordinary parents. Exact bytes/hashes are rebound at admission and use boundaries.

## Validate and emit

```sh
python -m pcerecomp declared-roots .local/roots.json --image .local/card.pce
python -m pcerecomp emit-roots .local/roots.json --image .local/card.pce --out .local/native-roots --partition-layout stable
python -m pcerecomp emit-roots .local/roots.json --image .local/card.pce --history .local/history/history.json --out .local/native-mixed --partition-layout stable
```

Validation output reports admitted membership and explicitly says emitted,
compiled and executed are false. Emission writes translated operations with
ordinary full-MPR, per-instruction source-byte and deadline guards. It never
executes the declarations. Existing observed-only generated C++ remains unchanged.
Output directories must be new; emission inside an input history graph refuses
before creating files.

The Python APIs are `declarations.load_declarations(path, image_path)`,
`declarations.load_compilation(path, image_path, observation_history=None)` and
`emitter.emit_declarations(path, image_path, output, observation_history=None, ...)`.
The returned admission has explicit revalidation. No old SDK or emitter is executed
just to reconstruct catalogue membership.

## Mixed provenance and consumer preparation

A mixed input is the exact source declaration plus an admitted history v1/v2.
Original capture bytes, stages, ABIs, origins and historical counters stay intact.
The image binding qualifies the declarations; it does not retrospectively attest
which whole source image produced every arbitrary historical capture.

Membership distinguishes observed, declared, overlapping, declared-only and
observed-only identities. Exclusions and unsupported declarations have their own
counts; excluded retirement costs come only from actual historical observations.
Declared-only entries have no hit fields. A later real capture can record their
first observed execution without rewriting the old declaration or history.
A generated module or catalogue alone proves neither compilation nor execution.

Use the generic preparation interface with a HuCard reset recipe and hashed
cartridge. In the module section:

```toml
[module]
kind = "declared"
path = "roots.json"
history_path = "history/history.json" # Optional; omit for pure declarations.
partition_layout = "stable"
```

Retain the complete required recipe from [consumer preparation](PREPARE_PROJECT.md).
History version/capacity options apply only when an actual `history_path` is
supplied. Pure declarations do not manufacture an empty capture or history.
Preparation copies exact roots into `declarations/roots.json`; media stays
read-only at its declared location. The source image/profile/header/encoding must
match the actual boot cartridge. Payload/System Card/CD source declarations are
not part of this first contract.

The resulting descriptor binds `[module.declared_roots]` with `path` and `sha256`
alongside an optional `[module.observation_history]`. Raw capture and inline-profile
bindings are not mixed with declarations: retain/import them as a history first.
Build, cache, recovery and execution contexts bind the numeric file, raw source
image, complete optional history and generated artifacts. Observer/runtime ABI 29
and guest checkpoint encoding remain unchanged; exact-build compatibility applies.

Managed stable builds copy/archive `declared-roots.json` and preserve observed
lineage. Annotation edits are explicit module-input changes; the boot cartridge
remains immutable. Dropping a retained declaration binding or historical provenance
requires a fresh workspace. Unchanged generated code can reuse objects, but changed
source/provenance bindings still require a new exact-build checkpoint context.

## Catalogue and gap reports

For automatic bounded expansion from a smaller set of entry declarations, use
[source-qualified static discovery](STATIC_DISCOVERY.md). Its separate closed
graph preserves seeds, code ranges and unresolved frontiers. The expanded
`roots.json` remains an ordinary declaration input: each row is one instruction,
with no execution counts or implicit derivation provenance in the consumer.

`load_native_catalog(manifest, declarations, image_path=image, observation_history=history)`
admits declared/mixed modules independently of build/execution proof. Its observed
set contains only history identities; its separate declared set retains static
membership. Emitted/excluded/unsupported partitions apply to their union.

The CLI accepts those explicit inputs too:

```sh
python -m pcerecomp native-gaps .local/native-mixed/module.json .local/actual-window.json --observations .local/roots.json --image .local/card.pce --history .local/history/history.json --out .local/gaps.json
```

Compiled membership not exercised by that real window remains unexercised,
including declared entries. Actual window costs come only from its retained
captures. Never insert fabricated zero/one-hit rows into a capture to make a
static entry pass an observation loader.

See the [complete authored example](../examples/declared-roots/README.md): it
separates an unexecuted routine from genuine discovery, then performs an actual
native call and a changed-source guard negative with independent literal CPU,
clock and whole-RAM expectations. Independent hardware/game qualification remains
separate from this compiler and provenance interface.

## Qualified scope

Frozen code `379db444` passes **1,988 Python tests without skips, 74 C++ suites
and 12 fresh-process audio cases** with all 734 tracked
inputs unchanged. The public authored workflow records a real 100-interpreted
prefix, compiles six additional declarations and qualifies a cold 100-native
prefix in which those six entries remain unexecuted. A separate compiled probe
then performs an explicit developer-assisted flag write and retires 110 native
instructions, reaching each additional entry once with zero fallback/guards.
All 8192 WRAM bytes and independently counted CPU/clocks match. An altered-source
negative refuses at 104 native with one guard and no extra retirement/clocks.

Only the genuine later capture extends history to 100 interpreted + 110 native;
declarations never manufacture work. A real managed update reuses all 31 object
files unchanged and preserves exact archives. Two private pure-declaration
SF2/Boxyboy reset-instruction smokes qualify only 1 native instruction each,
zero fallback/guards and literal 2 cycles/24 ticks against a bound interpreter
reference. These checks do not extend gameplay or independent hardware claims.
See [full evidence and source identity](STATUS.md).
