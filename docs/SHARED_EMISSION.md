# Shared guarded-code layout

Use the opt-in `shared` layout for a fresh large module with repeated code across
full MPR contexts. It keeps every selected identity while reusing exact guarded
instruction helpers. The default CLI layout remains `balanced`; preparation
recipes still default to `stable`.

```sh
python -m pcerecomp emit-capture observed-code.json --out new-module --partition-layout shared --partition-size 1024
```

`emit-profile` and `emit-history` accept the same options. In a
[preparation recipe](PREPARE_PROJECT.md), set these fields in the existing
`[module]` table, alongside its kind/path:

```toml
partition_layout = "shared"
partition_size = 1024
```

Capture, profile, history, declaration and discovery-backed preparation all use
the same layout. Original observations, declared membership and their producers
retain their provenance; a generated or compiled candidate is not an executed one.

## Identity and dispatch

Each complete MPR context is split into fixed 64-byte logical-PC ranges. Two
range helpers may share a body only if their entire ordered row sets are equal:
logical PC, every physical instruction-fetch address and every encoded byte.
Equality uses full tuples, not digest equality or a masked MPR assumption.
Partially overlapping ranges are not unioned. Same-PC source variants stay together.

The global dispatcher still checks all eight live MPRs and selects only the
helpers admitted for that context, in logical-PC order. The shared helper peeks
every source byte and executes direct translated C++ operations against the live
CPU/bus. Data-address mappings, TMA/TAM, stack accesses and dynamic jumps retain
their normal semantics. Instruction bytes crossing an MPR boundary are individually
guarded. Unseen context/PC and changed or unreadable source return a miss before
guest mutation. A reached instruction-boundary deadline returns budget without
executing the instruction. No per-opcode interpretation is substituted.

Unique helpers are packed into numbered C++ files. `partition_size` is a target
of 1..4096 unique guarded source rows per file. A complete helper, including all
its same-PC variants, stays whole even if it exceeds that target. The dispatcher
and header are separate; empty output still retains that partitioned structure.
More distinct contexts can still enlarge the dispatcher, and unrelated code may
offer little sharing. The unique-helper bound is 65,536; excess refuses explicitly.

The manifest adds:

```json
{
  "partition_layout": "shared",
  "partition_identity": "exact_guarded_pc_ranges_v1",
  "pc_bucket_size": 64,
  "unshared_partition_count": 14572,
  "shared_part_count": 2038
}
```

The counts above are one measured catalogue, not required constants.
`native_instructions_emitted` and catalogue membership count full source
identities; sharing does not drop them. `translated_body_count` counts the emitted
operation bodies. Catalogue admission independently rederives selected range
membership, exact sharing, packing and artifact counts from original inputs.
Python consumer/CMake readers validate typed layout metadata and artifact hashes;
these checks alone do not attest arbitrary C++ semantics or actual execution.

## Choosing a layout

| Layout | Intended use | Contract |
| --- | --- | --- |
| `balanced` | Existing one-off output | Existing per-context target-sized parts; unchanged default bytes |
| `stable` | Managed changed-unit rebuilds and optional native spans | Full-MPR/256-PC names; existing artifacts remain stable as unrelated inputs grow |
| `shared` | Smaller fresh builds when contexts repeat guarded code | Exact 64-PC helper sharing and packed files; names/packing may change as inputs grow |

Shared layout rejects `single_unit` and `native_span`. The existing managed
producer remains stable-only; this adds no stable changed-object or cross-workspace
reuse contract. All six checked legacy layout/span cases remain byte-identical
to the prior committed emitter. Runtime ABI 29 and checkpoint payloads are unchanged,
but a new source/package/build identity still requires fresh exact-build checkpoints.
Pin a toolkit revision with shared-layout support before preparing/building it;
an older ABI-29 reader need not accept this new manifest layout.

## Measured fresh-build result

One local SF2 capture contains 190,243 full identities across 1100 MPR contexts.
Both layouts retain all identities and exact per-key retirement counts.

| Measurement | Balanced, target 4096 | Shared, target 1024 |
| --- | ---: | ---: |
| Generated C++ translation units, including dispatcher | 1101 | 31 |
| Translated operation bodies | 187,009 | 26,647 |
| Generated `.cpp` + `.hpp` bytes | 109,743,387 | 17,153,558 |
| Preparation seconds | 27.61 | 32.84 |
| Fresh official build seconds | 412.82 | 52.06 |
| Unpacked executable bytes | 30,394,880 | 7,419,904 |

Build time is about 7.9 times faster for this pair (87.4% less); preparation
itself is slightly slower. These are sequential fresh Windows Release builds,
same SDK/capture/board/LLVM-MinGW compiler/Ninja two-job limit. Baseline ran first,
shared second. Other owned build/reference/test processes were excluded during
the pair; OS caches and uncontrolled host load remain possible influences.
This is not a universal speedup, runtime-speed benchmark, Linux result or measurement
of a contributor's different larger catalogue/routes. Executable bytes are unpacked.

## Verification scope

Frozen `f2f9fefa` has 2136 Python tests without skips, 74 C++ suites and
12 fresh-process audio cases. The authored compiled shared probe checks actual
reuse under differing live data mappings, TMA/TAM, sparse remapped helper order,
context-specific source variants and boundary-crossing operands. Source/mapping/
deadline/unreadable-bank refusals preserve state, clocks, generations and full
physical memory. Separate metadata/artifact negatives refuse malformed packages.

Fresh original Geargrafx 1.8.4 single-step comparisons using a compiled shared
probe pass 384 selected data/ALU and 512 RMW/indirect-jump cases per tier: CPU,
flags, PC, MPRs and all 8 KiB WRAM. This does not cover cycles, bus phases,
devices, video/audio, retail or hardware parity.

Actual cold TCP replays compare the new shared candidate with its same-build
interpreter reference. SF2's 3600-frame no-input attract route retires 100,397,977
native/zero interpreted/zero guards, with all 190,243 exact keys/hits, six paused
state/full-WRAM/RGB checks and two-frame checkpoint forks. The balanced build
also passes that cold replay. Rondo repeats the existing boot-to-introduction
route: 404,669,933 native/zero interpreted/zero guards, 25,621 keys, 17 paused
state/full-WRAM/CD-RAM/RGB checks and fresh same-build forks. Original captures
and recorded retail expectations keep their older producer; new candidate runs
are separate. Imported checkpoint work is excluded from suffix counts.
These are bounded internal retail checks, not full games, external retail timing,
audio quality or playable Rondo combat. Ys III remains parked. See [status](STATUS.md).
