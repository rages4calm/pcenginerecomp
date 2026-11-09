# Source-qualified static discovery

`discover-roots` expands explicit [declared instruction entries](DECLARED_ROOTS.md)
into bounded control-flow candidates using the user's exact HuCard image. This
reduces manual instruction listing before native compilation. It does not run the
guest, manufacture capture hits or prove that a candidate executes.

The first policy covers read-only `base`, `sf2` and `populous` ROM views. It needs
explicit decoded-ROM code ranges and preserves logical PC, all eight MPRs, mapper
selector and every fetched source byte. It never scans an entire image looking
for plausible instructions. RAM/CD overlays need a different authenticated source
interface and remain unsupported here.

## Discover and verify

```sh
python -m pcerecomp discover-roots .local/seeds.json --image .local/card.pce --rom-range 0x100:0x40 --rom-range 0x2040:0x10 --limit 10000 --context-limit 256 --out .local/discovery
python -m pcerecomp verify-discovery .local/discovery --image .local/card.pce
python -m pcerecomp emit-roots .local/discovery/roots.json --image .local/card.pce --out .local/module --partition-layout stable
```

Use real ranges from the input you are analyzing; these example offsets are not
a generic game recipe. Each `--rom-range OFFSET:LENGTH` uses decoded-ROM file
coordinates, after the explicitly selected copier header removal/byte conversion.
These are distinct from logical and guest physical addresses. Every byte of a
seed or discovered instruction must lie in the allowed ranges and be driven ROM
under its exact current mapping. Use separate ranges to keep known data outside
the search. Input roots must fit; unsupported traversal frontiers remain explicit.

The numeric seeds use the existing exact `pce-declared-roots-1` contract, including
the raw image hash and explicit profile/header/encoding. Seeds are instruction
entries, not observed captures or a claim that every byte nearby is executable.
Caller-supplied continuation seeds must include their own complete mapping/source
context; the tool does not infer that context from a call address alone.

## Conservative traversal

- Straight-line instructions and direct jumps follow their explicit target.
  Conditional branches retain both candidates; branch conditions are not guessed.
- JSR/BSR follow the direct callee and report the unresolved return site. They
  never enqueue the instruction after a call using an assumed return mapping.
  RTS, RTI, BRK and reserved opcodes terminate that path with a reason. Indirect
  JMP also stops under the default policy; the optional ROM-vector policy below
  can resolve a strictly bounded subset.
- Conservative register constants can establish a TAM mapping change. Unknown
  nonzero TAM stops the path; a zero mask leaves the mapping unchanged. Conflicting
  incoming facts lose precision. Candidates that depended on a superseded mapping
  assumption are removed from the final graph.
- SF2 writes that may change the mapper stop traversal instead of assuming its
  selector remains fixed. This includes uncertain indexed/indirect writes and
  transfers that could touch the mapper. This policy does not infer a new selector
  from data written to the latch.
- Source-range boundaries, non-ROM fetches, overlaps, unresolved control flow and
  configured instruction/context limits are reported explicitly. A limit is a
  discovery frontier, not a completed-program result.

Limits default to 10,000 instruction states and 256 mapping contexts; supported
maxima are 1,048,576 states and 4096 contexts. Up to 256 allowed ROM ranges and the
existing declaration/image bounds apply. Both generated numeric roots and the
discovery report must fit their 64 MiB serialized bounds. These are analysis/input
limits; nothing silently drops seeds or presents a bounded frontier as a complete
program analysis.

Report `candidate_roots` and `native_supported` count graph entries, including
distinct selector aliases. `source_identities` counts deduplicated complete
compiler identities. None of these is an emitted, compiled or executed count.

## Optional ROM-vector policy

Repeat `--rom-vector-range OFFSET:LENGTH` to permit indirect JMP pointer reads
from explicitly identified decoded-ROM data ranges:

```sh
python -m pcerecomp discover-roots .local/seeds.json --image .local/card.pce --rom-range 0x100:9 --rom-range 0x120:8 --rom-range 0x140:5 --rom-vector-range 0x1ff:2 --rom-vector-range 0x300:2 --out .local/vector-discovery
```

These offsets describe the [authored vector example](../examples/rom-vectors/README.md),
not a generic game recipe. In Python, pass `rom_vector_ranges=[(start, length), ...]`
to `discover_roots`. Omit it or use `None` for the original policy. An explicitly
empty or invalid range list refuses; the option never means unlimited data reads.

This selects the separate `bounded-source-qualified-rom-vectors-v1` analysis
policy. The existing format/schema and three-file closure remain; options add
`rom_vector_ranges`. The default `bounded-source-qualified-rom-v1` policy and its
canonical artifacts remain unchanged. New readers admit both policies; old readers
refuse the new policy rather than silently interpreting it under old rules.

- `JMP (abs)` reads its two pointer bytes only if both are driven ROM inside the
  vector ranges under the current full MPR mapping and mapper selector.
- `JMP (abs,X)` additionally requires one established X constant. Unknown X stops
  with `indirect_index_unknown`; the analyzer does not enumerate a jump table.
- Pointer addition wraps at 16 bits. The high-byte read crosses $xxFF normally,
  including MPR-page changes and $FFFF to $0000; it has no 6502 page-wrap bug.
- Vector permission does not authorize code decoding. The resolved target must
  independently satisfy the code ranges and instruction/context bounds. Ordinary
  data references are not followed. RAM, I/O, Populous RAM and undriven apertures
  stop with `non_rom_vector`; disallowed ROM pointer bytes report
  `allowed_vector_boundary`. Existing SF2 mapper-write barriers remain in force.
- Conflicting facts retract obsolete resolved-vector descendants. Every resolved
  node records base, index, both logical read addresses, both decoded-ROM offsets
  and target under that node's complete source context. `rom_vector` edges and
  `resolved_vectors` count derivation facts, including targets stopped by a code
  boundary; they do not assert compilation or execution.

Closure admission rederives every pointer read/target from the exact bound image.
Generated indirect jumps retain their real runtime bus reads; the discovered target
is not hardcoded into execution. A changed pointer can therefore select uncovered
code and produce an ordinary dispatch miss. Source guards still protect each
translated target. ABI 29, guest semantics and checkpoint encoding are unchanged.
Return contexts, writable vectors, unknown indices and live RAM/CD source views
remain separate work.

## Closed derivation artifacts

Choose a new output directory. The closed result contains:

| Artifact | Meaning |
| --- | --- |
| `seed-roots.json` | Exact original numeric seed bytes, retained independently |
| `roots.json` | Ordinary source-qualified declarations for the derived candidates |
| `discovery.json` | Separate source/input/output hashes, policy, ranges, graph and diagnostics |

No copy of the ROM is written. The original seed and source image remain
read-only. Existing outputs and linked/aliased artifacts refuse. Inputs are
revalidated at admission and output boundaries; failed partial new output is
diagnostic material, not a qualified graph.

`verify-discovery` rederives the candidates from the retained seeds, exact image,
ranges and policy, then compares the expanded roots and graph. Merely editing
the output hashes cannot establish a different derivation. Verification proves
that bounded derivation under the admitted policy; it establishes no execution,
compilation, producer authorship or independent hardware result.

Python callers use:

```python
from pcerecomp.discovery import discover_roots, load_discovery

result = discover_roots(seeds, image, new_output,
    rom_ranges=[(0x100, 0x40)], instruction_limit=10000, context_limit=256)
checked = load_discovery(result.report_path, image)
checked.revalidate()
```

The admitted result exposes `report`, `roots_path`, `report_path`, `sha256`,
`declarations`, `artifact_bindings` and `revalidate()`. The loader does not execute
an old SDK or script to check the derivation.

## Compile and qualify separately

Use the expanded `roots.json` through `emit-roots` or a
[preparation recipe](PREPARE_PROJECT.md) with `module.kind = "declared"`. An optional
real history can still be composed through the existing declared-root interface.
Observation counts, stages and original captures remain separate from all static
candidates. Generated code contains translated operations and ordinary source guards.

The current consumer contract binds the expanded numeric declarations and source
image. It **does not automatically archive or admit the discovery graph**. Retain
the closed discovery directory separately if you need its seed/derivation provenance,
and use `load_discovery` to validate it. Do not imply that a consumer's ordinary
declaration binding independently authenticates this earlier derivation.

Build and run the consumer through its required startup/routes. A source guard
miss is uncovered execution, not proof that static discovery failed or completed
every possible path. Runtime ABI 29 and guest checkpoint encoding are unchanged;
exact-build source/revision compatibility still applies.

## Reference scope

Mapping facts and mapper-write barriers were source-reviewed against
[Geargrafx's pinned TAM/TMA implementation](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory.cpp#L298),
[Mesen's pinned MPR implementation](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceMemoryManager.cpp#L353)
and [Geargrafx's pinned SF2 mapper](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/sf2_mapper.cpp#L105).
Selected TMA registers are ORed; mask zero uses a transfer latch that this analysis
does not track. SF2's selector comes from the write address, not its data value.
These are source-review references, not newly executed emulator or hardware traces.
The analyzer and authored fixtures are toolkit code; no reference-core code is
copied into the runtime.

The opt-in vector policy's pointer arithmetic was additionally source-reviewed
against [Geargrafx's pinned indirect addressing helpers](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h#L435)
and [Mesen's pinned indirect JMP implementations](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp#L453).
Both distinguish these full-word pointer reads from zero-page indirect addressing;
the HuC6280 does not inherit the 6502's indirect-JMP page-wrap bug. This is source
inspection, not a fresh original-core execution or a hardware timing claim.

## Qualified scope

Frozen code `d23dcbef` passes **2,023 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases** with all 742 tracked inputs
unchanged. The public [authored workflow](../examples/static-discovery/README.md)
derives 15 identities/three mappings from two seeds. Its official cold run
qualifies 100 native instructions, zero fallback/guards and nine exercised keys;
six candidates remain unexecuted. A separate assisted compiled probe reaches
all 15 keys in 110 native instructions and matches independent literal clocks
and every WRAM byte; an interpreter reference also meets those expectations.
The changed-source negative stops at 104 native/one guard without extra work.
See [full producer/proof scope](STATUS.md). These checks establish neither
universal discovery nor newly executed independent emulator/hardware parity.
