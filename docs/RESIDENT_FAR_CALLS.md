# Resident sources and proven stack transfers

RAM/CD analysis supports two additional opt-ins: explicit resident bytes from
one closed RAM snapshot, and the `bounded-ram-cd-stack-values-v1` analysis
policy. They can be used together or independently. ABI 29, runtime execution
and the older analysis policies remain unchanged.

## Compose a resident source with CD overlays

Some games keep shared routines in RAM while loading other code into separate
banks. A CD group's fetch may cross into those shared routines only when their
bytes are explicitly supplied and authenticated:

```sh
python -m pcerecomp declare-cd-loads load-map.json --disc game.iso --toc game.toc --analysis-policy bounded-ram-cd-stack-values-v1 --resident-snapshot .local/resident-snapshot --resident-range 0x104000:64 --call-depth 8 --out .local/composed
python -m pcerecomp verify-cd-loads .local/composed/roots.json --disc game.iso --toc game.toc
```

The numbers are an authored example. Repeat `--resident-range` for separate
canonical physical start/length pairs. Every selected byte must exist in the
same closed System Card snapshot. Supported ranges are standard CD RAM
`$100000..$10FFFF` and canonical WRAM `$1F0000..$1F1FFF`.

The declaration copies a closed `resident/` bundle with the original snapshot,
selected ranges, segment hashes and numeric residency contract. Admission
rederives that bundle and the full analysis graph. Every fetched byte records
either its CD load/disc offset or its resident snapshot/region/offset. Current
logical PC and all eight MPRs still identify the instruction; the snapshot's
original mapping and package provenance remain in the copied evidence.

Each alternative CD group must be disjoint from every resident span. Even an
overlap containing identical bytes is refused. Excluded data stays nonexecutable;
missing resident bytes remain a fetch frontier. This does not splice several
historical snapshots into one assumed memory image or infer ordered overlays.

The snapshot must bind the same complete disc identity and any recorded TOC.
Prepared consumers additionally require the exact snapshot boot mode, profile,
firmware and asset contract, including BRAM selection. Capture from a consumer
with the intended explicit TOC before composition; adding a TOC later changes
that machine contract. Wrong firmware, profile or assets fail before preparation.
The complete copied resident graph counts toward the CD declaration's 64 MiB
bound and remains pinned through emission, consumer preparation and managed
module/history archives.

Residency is an explicit consumer assertion about a selected source range.
A snapshot proves reported bytes at its original paused epoch, not that those
bytes remain installed during a later CD load. Runtime source guards remain
mandatory. Composition creates static candidates, not an executed checkpoint,
retired instructions or evidence of a natural loader route.

Python callers use:

```python
cd_loads.declare(map_path, output, disc=disc, toc=toc,
    analysis_policy="bounded-ram-cd-stack-values-v1",
    resident_snapshot=snapshot_path,
    resident_ranges=[(0x104000, 64)], call_depth_limit=8)
```

`resident_sources.admit`, `copy_resident` and `load_resident` expose the same
closed source selection for tooling. The original snapshot namespace and copied
resident bundle are protected from nested declaration/preparation outputs.

## Analyze supported far transfers

Select `--analysis-policy bounded-ram-cd-stack-values-v1` on
`discover-overlay`, `discover-origin-overlay` or `declare-cd-loads`. Loader
sweep plans may select the same policy in their existing `analysis` object.
No resident source is required when the allowed snapshot/load bytes already
contain every target. Both the policy and exact options are rederived on load;
older readers refuse them rather than silently using different analysis.

The new policy tracks byte values and source origins produced by analyzed
JSR/BSR and register pushes. Supported pulls and register transfers preserve
those origins. RTS follows a destination only when both consumed bytes are
known, computing the actual 16-bit word plus one using the current MPR mapping.
An original balanced call word produces a matched `return` edge. A synthesized
or transformed word produces a `reconstructed_return` edge with both byte
values and their generating instruction identities. This is a proven transfer,
not proof of a conventional call or complete routine.

The analyzer executes these abstract operations individually. It does not
accept caller-trusted summaries that skip a thunk or invent its effects.
Replacing a byte with the same numeric value still records its new origin.
Unknown status bytes stay unknown. Known stack loads require a real analyzed
TXS establishing SP and a cell written on that path; ordinary snapshot RAM and
initial stack contents are never treated as constants. Absolute indexed reads
retain normal page-crossing behavior before physical alias lookup.

Code writes, direct or aliased stack stores, uncertain indirect writes,
block/device effects, incompatible stack mappings and SP replacement with live
stack state remain barriers. Depth, mapping/state limits and a fixed aggregate
symbolic-cell bound stop with explicit diagnostics. The older policy retains
its original conservative saved-word-pop barrier and exact graph shape.

This does **not** yet recover arbitrary far-call conventions. Thunks that read
inline targets through RAM pointers, update a RAM bank stack, or require broader
mutable-memory flow still stop at those unsupported effects. In particular,
source inspection of the retained Ys III thunk shows saved-return *reads*,
inline target lookup and bank-stack state; these operations need further work.
That observation does not establish a rewritten caller return or qualify that
whole thunk under the new policy.

## Qualification

The [authored example](../examples/resident-far-calls/README.md) copies shared
resident code through real guest firmware TII, loads alternative sectors with
actual CD READ commands, and compares whole-snapshot analysis with resident/CD
composition. It compiles both source types and checks native/reference routes
and same-build checkpoint suffixes using dummy/software drivers. It supplies
bounded internal evidence, with disclosed data gates and no proprietary inputs,
physical GPU, hardware timing or whole-title claim.
