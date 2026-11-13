# Source-qualified unknown-X ROM tables

Opt-in table analysis expands an indexed indirect jump when X is unknown by
examining its complete eight-bit domain. It removes one discovery frontier
without treating candidate code as observed execution.

```sh
python -m pcerecomp discover-roots seeds.json --image card.pce --rom-range 0:7 --rom-range 64:10 --rom-range 80:10 --rom-range 224:10 --rom-range 4320:10 --rom-vector-range 256:257 --rom-table-limit 1 --out new-table-graph
```

The ranges above belong to the [authored example](../examples/rom-tables/README.md),
not a generic game recipe. Use explicit decoded-ROM code and vector-data ranges
for your own image. Python callers pass `rom_table_limit=1` to `discover_roots`.
Omission preserves existing policies and byte-identical artifacts. The option
requires ROM-vector permissions and accepts an integer in 1..256; booleans,
fractional values and missing permissions refuse before output publication.

## Candidate derivation

For `JMP (abs,X)` with unknown X, the analyzer considers all values 0..255.
It does not assume even indices, word alignment, hot values or observed player
paths. Each candidate pointer reads `(base + X) & 65535` and the following
16-bit-wrapped address, with each byte's current MPR mapping and mapper selector.
The two bytes must independently resolve to driven immutable ROM inside explicit
vector-data permissions. RAM, I/O, undriven and Populous apertures refuse.
An ordinary data/code-range permission does not implicitly authorize vector reads.

Every successful pair yields a candidate target and its conditional X value.
The target still needs its own code-range/source/context/instruction admission.
Facts from multiple incoming edges join conservatively; conflicting X values
become unknown. The generated indirect jump continues to read the actual live
pointer. It never substitutes a predicted target, and ordinary target source
guards remain required. Runtime timing and instruction semantics do not change.

Known X retains the existing one-vector path and consumes no table-site budget.
`JMP (abs)` also retains its existing path. A complete eight-bit index domain
spans 257 possible source bytes, before any mapping boundaries or aliases.
Partial permissions can derive fewer pairs, with an explicit frontier for each
blocked index. That is a partial candidate graph, not a claim of complete routing.

The new policy is `bounded-source-qualified-rom-tables-v1`. Adding the existing
`call_depth_limit`/`--call-depth` selects
`bounded-source-qualified-rom-table-calls-v1`; ordinary synchronous stack/call
restrictions remain. Interrupt recovery, writable vectors, RAM/CD-loaded code
views and general routine closure are separate capabilities.

## Bounds and provenance

`rom_table_limit` counts distinct unknown-index source views: mapper selector,
all eight MPRs and logical PC under the exact bound image. Immutable pointer
evidence is cached for that view. Different calling frames can reuse its source
reads while retaining separate analysis states and conditional edges.

A separate fixed bound admits at most 256 table-expanded analysis states across
calling frames, or 65,536 index decisions. Reprocessing an existing state does
not spend another slot. Exceeding either bound stops the complete next table;
no arbitrary numeric prefix is silently retained. The diagnostics are
`rom_table_limit` and `rom_table_state_limit`, and `limit_reached` remains true.
Counts include explored views/states even if a later conservative join retracts
an optimistic path. Existing instruction/context/depth and serialized-byte bounds
also remain. This is bounded candidate analysis, not an automatic whole-ROM scan.

The existing three-file graph and source hashes are retained:

- `seed-roots.json`: exact original numeric entries.
- `roots.json`: source-qualified candidate declarations, with no hit counts.
- `discovery.json`: separate policy/options, pointer evidence, graph and frontiers.

An enumerated node records `rom_vector_table`: base, `index_domain: [0,255]`,
`source_complete` and entries containing index, both logical pointer reads, both
decoded-ROM offsets and target. `source_complete` means all pointer pairs were
read; it does not mean every target was admitted, emitted or executed.
Successful `rom_vector` edges retain `vector_index`. Rejected reads/targets retain
that index in their frontier. Known-X nodes retain the prior `rom_vector` record.

Summary counts separate `enumerated_vector_sites` (retained analysis states),
`explored_vector_tables` (distinct cached source views),
`explored_vector_table_states` and `resolved_vector_entries` (retained pointer pairs,
including known single-vector pairs). `resolved_vectors` counts retained nodes
with at least one pointer pair. Compilation and actual retirement counts remain
separate from all of these candidate counts.

Admission rederives every read, target, conditional edge, count and bound from
the immutable image and original seeds. Recomputed hashes alone cannot legitimize
an edited graph. Existing copy/preparation/consumer/managed archive interfaces
retain the exact graph; no ROM copy or fabricated capture is added. Older
readers refuse the new policy strings. Pin an updated toolkit before using them.
ABI 29 and guest/checkpoint payloads are unchanged; exact-build checkpoint
contexts still require fresh checkpoints after a source/package/build change.

## Verification

Frozen `1b8081de4a18457247685585493f41c14ff78424` passes 2,156 Python tests
without skips, 74 C++ suites and 12 fresh-process audio cases. All 763 tracked
inputs stay unchanged during the required check. SDK SHA256
`14b3255b32fed8e334122ab0e32b9655b1fceb34f74e8d4167b6d16b2d109260`
covers 95 source files; later publication edits are Markdown only.

Unit checks cover the complete domain, partial permissions, full 16-bit pointer
wrap, independent source mappings/selectors, known-X behavior, conflicting joins,
instruction/site/call-state limits, call/return composition, exact copying,
malformed types, tampered evidence and consumer preparation. Eight old default,
vector and call-policy graphs are byte-identical to the previous committed
implementation. That old reader separately rejects the new table policy.

The authored [native workflow](../examples/rom-tables/README.md) goes from three
candidates under the old policy to 19 with table analysis. An official cold native
consumer executes seven instructions. A separate all-index matrix executes
1792 native/zero interpreted/zero guards; an interpreter-only matrix executes
1792 interpreted/zero native. Both reach all 19 exact source identities and match
the literal hit plan, CPU state, 30 cycles/360 ticks per case and every WRAM byte.
Host X presets/resets are declared matrix preconditions, not guest work or one
continuous route. Changed-vector and changed-source probes each stop after three
native retirements with one guard miss and no added clocks, retirements or memory
changes. Original inputs remain unchanged.

Fresh Geargrafx 1.8.4 also passes all 256 authored seven-instruction cases against
the same separate CPU/flags/PC/MPR/full-WRAM literals. Its bootstrap and host
presets are separate setup. This checks independent instruction execution, not
external cycle/bus/device/video/audio, retail or hardware parity. Pointer semantics
were also reviewed against the pinned [Gear indirect-jump implementation](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_opcodes.cpp).

A newly built Rondo consumer separately repeats the previous cold TCP and
same-build checkpoint regression. That existing CD capture does not exercise
static ROM-table discovery and retains its original producer. See
[current status](STATUS.md) for counts and remaining compatibility gates.
