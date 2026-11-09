# Draft: independent software bus-event traces (issue #4)

Status: **proposal, not an implemented or qualified trace API**. The owner requested
an issue audit after PRs #6/#7. This draft makes the remaining work concrete without
renaming instruction-boundary or cycle-total comparisons as bus-cycle verification.
No runtime instrumentation, ABI change or new emulator execution is shipped here.

## Existing work and the remaining gap

- [Instruction-boundary traces](REFERENCE_TRACES.md) and the separate original
  Beetle/Mednafen adapter already provide a second independent emulator. The
  [IRQ-aware observer](IRQ_TRACES.md) keeps actual core calls separate from retirement.
- [Vector diagnostics](HUC6280_VECTORS.md) preserve Mesen-generated numeric expectations,
  their unknown generator revision, and explicit unsupported/unobserved fields.
- [VDC phase diagnostics](VDC_PHASES.md) provide bounded callback/queue/HSYNC evidence.
  They are a particular software scheduling profile, not arbitrary CPU bus traces.
- Missing: a shared event format and independently observed chronological access
  records from both toolkit tiers and an original reference core, with declared
  phase semantics and negative controls. Instruction-boundary times cannot supply
  missing access phases or dummy-cycle observations.

## Proposed versioned stream

Name: `pce-bus-event-trace-1`, UTF-8 JSONL. Do not change existing trace formats.
A header, initial state, events and one closing record are mandatory. Reject duplicate
or unknown keys, non-finite numbers, booleans as integers, broken mapping/order,
truncation, missing closure and incompatible capabilities before comparison.

Header fields:

| Field | Meaning |
|---|---|
| `schema`, `format` | Exactly 1 and the proposed format name |
| `engine` | Name, exact source revision, source digest and actual executable digest |
| `fixture_sha256` | Exact authored fixture identity |
| `profile` | Initially `software-access-callback-v1` only |
| `clock` | `master-ticks`; preserve raw origin, entry CPU divisor and any transitions |
| `phase` | The precise hook boundary, e.g. `after-read-before-next-clock`; never guessed |
| `capabilities` | Explicit access/dummy/idle/fetch/IRQ visibility and value availability |
| `limits` | Actual instruction, event, byte and wall deadlines of this execution |

Each event contains contiguous `ordinal`, actual `tick`, `instruction_ordinal`,
actual entry logical `pc`, all eight entry `mpr` bytes, a content-bound source identity,
`direction` (`read`, `write`, `idle`), address space and data observation. Repeated
accesses to the same address remain separate. Events at equal ticks retain their
actual ordinal; sorting by address or coalescing duplicates is forbidden.

A code-free source digest must bind the logical entry PC, complete MPR snapshot,
actual mapped instruction-fetch addresses and encoded bytes from the separately
retained private fixture/capture. PC/mapping alone cannot identify a writable overlay.
Do not invent fetch bytes from a later RAM snapshot. The qualification runner checks
that binding independently; syntax validation alone cannot authenticate a producer.

Address spaces:

- `mapped`: the observed logical access address, the actual access-time eight MPRs
  and physical address. Verify `physical = mpr[logical >> 13] * 8192 + (logical & 8191)`.
  Entry and access mappings are distinct, particularly around TAM.
- `fixed-vdc`: an explicitly observed ST0/ST1/ST2 port access. Retain the physical
  device address and mark logical address/mapping as not applicable. Do not apply
  the guest MPR map to a fixed port or retain a reference core's dispatch sentinel
  as a physical address.
- `idle`: address/data are not applicable; emit only an actually observed idle
  interval with explicit start/end ticks. An aggregate cycle total supplies no
  invented idle or dummy events.

Record read/write data only at the declared sampling boundary. `dummy` and access
purpose (`fetch`, `operand`, `stack`, `data`, `vector`) are observed labels or explicit
`unavailable`; do not classify them from an address heuristic. An engine without a
required observation makes that comparison incompatible, not equal by omission.

The closing record binds actual events, CPU calls, retired instructions, stop reason
and `complete`. IRQ entry and original block continuation calls are not opcodes.
Use finite limits similar to the existing CPU trace interface: at most 100,000
records, 16 KiB per line and 128 MiB per stream. These are protocol admission bounds;
execution also has an explicit finite instruction/wall deadline. An exhausted limit
preserves a diagnostic stream but cannot yield a completed equality result.

## Comparison and provenance

Compare raw chronological records and report the first differing ordinal, field,
values and engine identities. An explicitly named elapsed-origin profile may remove
only the recorded initial epoch offset, keeping both original timestamps. It must
not mask later drift, accesses, dummy flags, direction, data, mapping or IRQ ordering.
A pin-level/cycle-by-cycle profile requires new evidence and a distinct profile name.

Bind and revalidate source, reference patches/hooks, compiler/build commands, binary,
fixture and raw output using the existing snapshot/evidence interfaces. A header's
hash strings do not attest execution. Keep both raw streams and unsuccessful receipts.
A common encoder/comparator can be shared; reference CPU, MMU, devices and scheduling
must remain independently implemented. Do not normalize a real core disagreement into
agreement or publish generated fixture/code capture data from a retail image.

## First implementation and qualification slice

1. Publish the strict schema/parser and first-difference comparator with authored
   negative streams: missing/duplicate/reordered records, altered direction/data,
   changed MPR/physical address, same-PC overlay digest changes and shifted ticks.
2. Add a read-only toolkit observer for actual scalar RAM reads/writes and stack
   accesses in both interpreted and translated execution. Preserve a disabled
   reference path, explicit instrumentation identity and unchanged guest clocks.
   Review any CPU/Bus layout or serialized-state changes for an ABI bump before use.
3. Observe the pinned original Beetle callback boundary in a separate executable.
   Demonstrate that observation does not change CPU/RAM/clocks relative to the
   unobserved original core. Do not substitute toolkit memory/device functions.
4. Run an authored short RAM/stack/mapping route with exact declared entry state,
   both CPU speeds and identical input. Include a real native source guard negative
   and a missing-observation refusal. Record actual new retirements per tier.
5. Add one block-transfer diagnostic retaining the known aggregate-versus-finer
   cadence disagreement. A reported timing difference is a valid diagnostic;
   altering guest padding or projecting events into equality is not qualification.
6. Only then extend MMIO waits, interrupt entry and device acknowledgement. Every
   extension needs its own phase contract and independent raw observations.

First-slice completion requires actual separately built toolkit/native/reference
runs, sealed raw streams and negative controls. Parser tests or this document alone
cannot satisfy that gate. Issue #4 therefore remains open.

## Primary source anchors and license boundary

- [Pinned original Beetle CPU](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/huc6280.cpp)
  contains clocked stack, ordinary memory, block-transfer and fixed VDC operations.
  Its `WrMemPhysical` ST-port dispatch includes an internal high-bit marker; the
  observer must distinguish that implementation marker from physical addressing.
- [Pinned original Beetle CPU header](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/huc6280.h)
  supplies the core memory and timing interfaces; the concrete hook placement must
  be reviewed against these bodies before implementation.
- [Pinned Gear opcode source](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_opcodes.cpp)
  and the existing [block-transfer contract](CPU_SEMANTICS.md#block-transfers)
  explain why aggregate timestamps cannot be relabelled as finer bus cycles.
- Original GPL reference code remains separately built, never copied into or linked
  with the MIT runtime. Retain exact license/source/patch identity for each probe.

Hardware bus accuracy, a full Mesen adapter, arbitrary device timing and retail-game
qualification remain separate work. This proposal does not declare them completed.
