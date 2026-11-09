# Source-qualified declared instruction roots

A declared root is a numeric instruction-entry declaration recovered from an
exact source image. It is not a retired observation or execution trace. This
interface addresses [issue #13](https://github.com/rages4calm/pcenginerecomp/issues/13)
without inventing capture hits, retirement totals or checkpoint origins.

The first format supports explicit read-only HuCard ROM views (`base`, `sf2`,
`populous`). It does not reconstruct live RAM/CD overlays or infer a source view
from an address alone. Each row describes one independently decoded instruction;
routine closure and static reachability are **not inferred**. Unsupported flow
and semantics remain explicit diagnostics or runtime refusal.

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
