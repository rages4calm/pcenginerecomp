# Ordered block copies and mutable table discovery

The additional [mapper policy](MAPPER_FLOW.md) can follow proven SF2 latch writes
and changes within a copy. The mapper refusals below describe memory-flow policy
without that extra opt-in; its original qualification remains separate.

`discover-roots --memory-flow --block-transfer-limit 256` extends the opt-in
[WRAM policy](WRAM_VALUES.md) with ordered copy facts and proven write addresses.
It requires `--wram-facts`, explicit `--wram-data-range` permissions,
`--alu-facts --branch-facts --stack-facts --call-depth 8`. Add
`--wram-table-limit 1` to enumerate an unknown-X mutable indirect-JMP table.
Without that additional option, unknown-index WRAM vectors remain frontiers.

The Python API uses `memory_flow=True`, `block_transfer_limit=256` and optional
`wram_table_limit=1` alongside the same prerequisite options. The policy is
`bounded-source-qualified-memory-flow-v1`. Omitting the new options preserves
older policy bytes; older readers refuse the new identifier. The existing
`verify-discovery` and discovery-backed consumer interface rederive the entire
canonical seed/roots/report closure, including every new witness and limit.

## Ordered copy contract

TII, TDD, TIA, TAI and TIN decode the three little-endian operand words. Encoded
length zero means 65,536 bytes. Source and destination addresses wrap at 16 bits;
alternating endpoints start at the encoded address. Each inferred read sees all
earlier writes in the same transfer, including canonical WRAM aliases. This is
sequential copying, so overlap can differ from a snapshot or host `memcpy`.

Reads use only explicitly permitted ROM data or current known permitted WRAM
bytes. Unknown/unpermitted values replace the affected destination fact with
unknown; unrelated facts survive. ROM operands and ROM vector bytes retain their
separate permissions. Initial RAM is unknown and source fetch admission remains
ROM-only. No I/O value or firmware service is invented.

Before applying any copy facts, the analysis proves:

- MPR1 selects canonical base WRAM ($F8–$FB), and current relative stack depth
  plus the three temporary Y/A/X saves fits within 256 bytes.
- Every destination is disjoint from the canonical stack page, including
  aliases, even without an existing call frame. Unsafe writes stop explicitly.
- No SF2 destination can hit physical bank zero offsets $1FF0–$1FFF. A possible
  mapper write stops before any data propagation; latch changes are not inferred.

These conditions let safe copies preserve A/X/Y, existing saved stack cells and
all status except the cleared T bit. They can cross live call/save frames. There
is no assumed initial SP, absolute stack-memory tracking or interrupt closure.

`block_transfer_limit` is an explicit per-instruction byte bound, 1–65,536. The
sum of unique expanded block-state lengths is also limited to 65,536 bytes;
reprocessing an existing source/calling/depth state does not spend it again.
These explored counts can include states later made unreachable by joins.
Over-limit operations remain frontiers. The existing state/context/source/report
bounds also apply. The serialized graph remains limited to 64 MiB.

`block_effect` records operation, decoded operands, temporary stack proof,
ordered logical/physical addresses, known/unknown source reads and tracked old/new
bytes. Refusals retain their reason. Summary counts distinguish explored states
and bytes, currently analyzed states, known/unknown reads and temporary depth.

## Write addresses and mutable tables

For scalar writes/RMW already resolved by WRAM analysis, an actual proven
physical destination can refine the conservative SF2 mapper barrier. An indexed
or indirect write proved outside its latch range can continue. Unknown addresses
and possible latch writes keep the barrier. Accepted block operations use their
fully checked destination span. This does not simulate or guess mapper changes.

With an explicit `wram_table_limit` (1–256 expanded states), an unknown-X indexed
JMP with any possible WRAM pointer byte checks the complete unsigned X domain
0–255. Each low/high byte must be known and separately permitted under the
current MPR/source/calling/depth facts. Mixed ROM/WRAM pointers work. Resolved
entries refine X on their own edges; blocked entries retain per-index reasons.
`source_complete` concerns pointer bytes, not target closure: every target still
needs ordinary ROM code/source admission. The table is reevaluated after joins
and for each calling state; there is no mutable-pointer cache keyed by PC alone.

Nodes retain `wram_vector_table` entries/blocked witnesses and explicit options.
Conflicting joins retract stale targets. A missing permission or unknown byte is
never replaced by a fabricated target, successful entry or aligned-index guess.

## Native operations and verification scope

These facts recover candidate declarations; they do not fold runtime loads,
copies, flags or pointer reads into constants. Emitted code still performs live
operations and ordinary full-MPR/source guards. A changed live pointer can reach
an omitted identity and stop in native-only execution. Runtime C++, emitter,
ABI 29 and checkpoint encoding are unchanged. Fresh exact source/package/build
contexts still require fresh checkpoints.

The [reusable original fixture](../examples/memory-flow/README.md) exercises both
base HuCard and SF2 profiles. Per profile, 51 seeds derive 468 exact identities
across five contexts without frontiers. All identities execute across separate
main and 50 reset/preset copy windows. The main runs 18 native / zero interpreted /
zero guards, 1,615 cycles / 19,380 ticks. Its 256 separately preset X cases retire
4,608 native instructions; the copy matrix retires 450 in each tier. Every byte
of WRAM, CPU/flags/MPR, literal clocks and exact source/hit counts pass. A changed
live pointer stops after 13 native / zero interpreted / one guard without guest
effects at refusal. The Windows probe works without the SDK PATH workaround.

The same inputs under the previous WRAM policy admit 11 main operations for base
and 10 for SF2, stopping at stack/mapper barriers. New analysis admits all 18.
Geometry includes all five operations, lengths 1/2/3/7/8/16, overlap in both
directions, canonical aliases and full-word address wrapping. The 256-byte table
includes a mixed ROM/WRAM pointer. This remains authored bounded evidence.

Fresh independent Geargrafx 1.8.4 passes **612 CPU/full-WRAM endpoints**
and **10,116 before/after instruction points** across the two profiles. All
40,516 known incoming / 43,464 known outgoing register/status components
and 921,496 known WRAM-byte checks agree. The 60,644 incoming /
57,696 outgoing scalar and 1,668,200 permitted-byte components that remain
unknown are not zero guesses. Every table index is exercised, original source and
permitted ROM bytes match the separately bootstrapped reference image, and all
612 original 8 KiB RAM endpoints are retained losslessly and reviewed against
literal expectations. This is CPU/RAM evidence, not external clocks,
device/interrupt, retail or hardware qualification.

Fresh Rondo TCP boot/file creation/introduction again retires 404,669,933 native /
zero interpreted / zero guards, with 25,621 exact keys/hits and 17 paused reported
state/full-WRAM/CD-RAM/RGB samples. Own same-build checkpoint forks match 59,672
new instructions/753 keys, imported 379,716,149-native prefix separate. Post-close
paired/no-write raw journals, all original memory bytes and independently decoded
PNG CRC/pixels pass. This is existing captured-route regression, not retail use of
the new analysis, playable action or whole-game/audio/hardware proof. Host audio
is off; Ys III stays parked. Original source/checkpoint producers stay original.

Frozen **dd08097eeb7247f80aae91359f7ff4e7871b7498** passes **2,298 Python tests
without skips, 74 C++ suites and 12 fresh-process audio cases**, with all
809 tracked inputs unchanged through the required unmodified checker.
SDK source `8f4f6a5660cfd39308e40345d2b799a2d75419622ef4d1cf19bd5ae56739a021`
covers 100 files. Later publication edits are nine Markdown files only. All 96
legacy graph combinations byte-match `02763be1`; its reader rejects the new policy.
Runtime C++, emitter, ABI 29 and checkpoint encoding are unchanged. Exact new
source/package/build contexts still require fresh checkpoints.

Behavioral facts were reviewed against
[Geargrafx 1.8.4 block helpers](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes_inline.h)
and [memory mapping](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/memory.cpp).
Implementation and fixtures are original; no GPL reference code was copied.
General RAM/CD-code recovery, untracked writable memory, interrupt closure,
mapper-latch inference and broad library/hardware/player qualification remain
separate gates. This does not establish a complete-game port.
