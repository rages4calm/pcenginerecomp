# Finding native coverage gaps efficiently

Work from larger coherent execution windows on a stable package, then batch
the actual missing identities. Replaying an already admitted prefix or building
every new observed byte variant separately is not required merely to discover
more candidates. Keep execution evidence, compiled membership and static
reachability distinct.

The shared [native gap report](NATIVE_GAPS.md) now implements the membership
join, identity union and per-input missing-cost ranking below. It authenticates
the declared observed-module selection and artifact bytes; build/execution
qualification remains separate.

## Supported bounded ROM discovery

[Static discovery](STATIC_DISCOVERY.md) now expands numeric seeds from an exact
read-only HuCard source, explicit decoded-ROM code ranges and full mapping context.
Direct branches/jumps/callees and proven TAM mappings are supported; unknown
returns, unknown indirect flow, mapper-write effects, overlaps and limits remain explicit.
The opt-in ROM-vector policy can follow separately authorized immutable pointers,
including indexed JMP with a known X, while retaining both pointer source reads.
The expanded roots go through ordinary declared preparation/emission, with no
fabricated observations. For integrated seed/analysis provenance, use
[discovery-backed preparation](DISCOVERY_CONSUMERS.md); it owns and rederives the
closed graph. Ordinary declared-only preparation does not infer that extra binding.
General interprocedural return recovery and live RAM/CD snapshots remain separate.

## What exists today

The toolkit already provides:

- [Retired-code captures](CODE_CAPTURE.md) with logical PC, all eight MPRs,
  every mapped physical fetch address, exact bytes and native/interpreted hits.
- [Observation composition](OBSERVATION_PROFILES.md) that preserves input
  producer ABI/source/origin metadata and full byte/mapping variants.
- `Snapshot.load` and `analyze` in [analysis.py](../pcerecomp/analysis.py):
  hash-bound physical segments, explicit entries/MPRs and bounded CFG recovery.
  `follow_mappings=True` enables conservative mapping-context analysis,
  including known accumulator values propagated into TAM.
- [Direct native emission](../pcerecomp/emitter.py), source/MPR guards and
  manifest-bound consumer builds, plus exact-build developer checkpoints.

The existing analyzer reports missing bytes, limits and unresolved flow. It
does not infer an entire CD overlay layout from a finite trace. A snapshot
content hash proves which supplied bytes were analyzed; by itself it does not
prove when those bytes were present in a running consumer.

## Declared code is not retired execution

A consumer may recover candidate instruction bytes from numeric PC/MPR/source
rows and its own hash-verified image. Those declarations must not acquire invented
`native_hits`, `interpreted_hits`, retirement totals, completeness or checkpoint
origin fields. Capture admission checks structure, mapping and counter consistency;
it does not independently attest that an arbitrary producer executed the rows.
Source guards protect dispatch. A parity check qualifies the window actually run,
not every declared or emitted instruction.

The existing `Snapshot.load` → `analyze` → `emit` route accepts declared entries
and hash-bound byte segments with static provenance and explicit unresolved flow.
Keep each full MPR/source view explicit; ROM offset alone is insufficient for a
banked or latch-dependent mapping. Its snapshot manifest remains distinct from an
observed capture/history. It is not a portable numeric-root-plus-history importer.

[Declared roots](DECLARED_ROOTS.md) now implement the portable numeric-input and
observed-history composition interface requested in
[issue #13](https://github.com/rages4calm/pcenginerecomp/issues/13). The exact image,
explicit board/header/encoding, mapper selector, full PC/MPR context and every
decoded-ROM byte offset are validated. Entries compile through guarded translated
operations; declaration, observation, emission and execution stay separate.
Each row lists one instruction entry, with no inferred routine/CFG closure.
General interprocedural discovery and source-qualified live overlay export remain
future work. Keep original observed histories intact.

## A safe discovery workflow

1. Retain a complete closed capture, its actual execution-window origin and
   the exact compiled package/profile/manifest. Decode the full source keys;
   do not join live TCP row numbers, physical banks or logical PCs alone.
2. Reconstruct actual emitted supported identities from the pinned inputs and
   manifest, respecting exclusions and unsupported records. A profile may
   retain provenance rows that were not emitted. Do not label every profile
   row compiled without checking that distinction.
3. Report observed compiled keys, compiled keys not exercised in this window,
   and observed keys absent from the compiled set separately. Rank absent
   keys by actual interpreted retirement counts and group related mapping/
   byte variants for a coherent next batch. Imported work and overlapping
   captures must not inflate newly executed totals.
4. Decode individual recorded byte variants independently where useful. For
   larger static reachability, acquire an authenticated contemporaneous
   physical snapshot with its complete MPR context, source/build identity,
   capture/checkpoint epoch and allowed code/data regions. Preserve alias and
   memory-generation evidence where it applies.
5. Run the existing bounded analyzer from declared entries. Keep unresolved
   indirect/return/dynamic mapping edges and unmapped bytes explicit. New
   static instruction boundaries are candidates; compiling them does not
   establish execution or campaign completion.
6. Emit/rebuild a candidate when the accumulated additions justify it. Qualify
   that candidate through its own startup and checkpoints before selecting it.
   An unchanged selected package can continue discovery without an SDK migration.

Never construct a bank snapshot by filling historical gaps with current RAM,
combining captures from different epochs, flattening MPR contexts or scanning
all disc payload as code. Two authentic instruction records are insufficient
evidence for all bytes between them. Keep original captures, snapshots and
generated retail source private.

## Independent decoding and remaining interfaces

The source-reviewed [RomAtlas PCE frontend](https://github.com/weisserw/romatlas/blob/3d0d1393149491777626f5a8e4461f7c49b2d6df/docs/pce.md)
supports HuCard analysis. That is not a qualified PC Engine CD image frontend.
Its [instruction decoder](https://github.com/weisserw/romatlas/blob/3d0d1393149491777626f5a8e4461f7c49b2d6df/crates/romatlas-pce/src/decode.rs)
accepts explicit bytes and an MPR context. The new
[isolated original-source comparison](ROMATLAS_REFERENCE.md) actually checks
25,221 authored records, preserving exact BRK frontend disagreements and a
separate narrow original-core fetch scope. It uses no CD image or fake HuCard.
It does not qualify a CD frontend, complete core semantics or physical hardware.

The remaining missing interface is a provenance-bound, paused physical
source-snapshot exporter. It is planned contributor tooling, not a new runtime
blocker or currently shipped API.
The snapshot exporter must establish the epoch/source relation above; an
unlabelled memory dump is insufficient. The useful lesson from static-closure
work on other recomp projects is to expand declared reachable code while
preserving failed roots, data boundaries and unresolved edges, rather than
turning a static boundary count into a completion percentage.
