# IRQ-aware instruction retirement traces

The opt-in `pcerecomp.irq_trace` interface preserves raw engine calls and
explicitly groups them into completed instruction boundaries. It extends the
reference tools; trace v1, its CLI and the default masked Beetle observer
retain their existing contracts. Runtime ABI remains **24**.

```sh
python -m pcerecomp.irq_trace expected.jsonl actual.jsonl --profile architectural-v1 --out .local/comparison.json
python -m pcerecomp.irq_trace native.jsonl interpreter.jsonl --view raw-event-exact
```

Exit codes are 0 for equality, 1 for a valid difference and 2 for invalid input
or file errors. Output files must be new; existing files, links and input
aliases are refused. Reports retain engine/fixture/trace identities and the
comparison policy. A well-formed trace does not authenticate the source or
executable: qualification separately binds actual inputs, builds and outputs.

## Raw calls and retirement groups

Original Beetle's `Run(true)` can return after IRQ entry without fetching an
opcode. It can also resume an unfinished block transfer. Gear and the toolkit
instead finish eligible IRQ delivery inside their ordinary instruction step.
Counting each return as an instruction would invent retirements or mislabel
the first handler instruction.

Format **`pce-cpu-trace-2`**, schema **2**, uses phase
`retirement-boundary-after-irq` and declares `call_model`:

- `aggregate`: one actual opcode call per measured instruction, possibly
  including its delivered IRQ. This first profile refuses aggregate block
  continuations rather than inventing intermediate states.
- `split-irq`: one opcode call, zero or more original block-continuation calls,
  then at most one actual IRQ-entry-only call. Entry/continuation calls add no
  instruction ordinal. A final requested opcode still drains its eligible
  entry-only call without fetching a handler opcode.

The JSONL stream contains a strict header, actual initial state, ordered
`event` records, an `instruction` record after each complete group, then a
complete `final` record. An event stores its contiguous raw-call ordinal,
kind, full entry and post-call states, and actual IRQ vector or null.
Instruction records bind the exact event span, logical entry PC/full MPRs,
final state, and IRQ count/vector. Final counts and state must close both
chains exactly. Every event's entry equals the preceding raw state.

States retain PC, A/X/Y/SP/P, all eight MPRs, physical PC, transfer latch,
speed, raw master ticks and full 8 KiB WRAM hash. Only an unavailable original
transfer latch may be null; flags and mapping are never fabricated. Duplicate
or unknown keys, invalid types/ranges, non-finite numbers, broken chains,
misgrouped events, missing IRQ metadata and incomplete endings are errors.
The protocol bounds are inherited from [trace v1](REFERENCE_TRACES.md).

## Comparison scope

`raw-event-exact` requires exact-profile comparison of compatible raw-call
models and all actual event states, structure and grouping. It is useful for
native/interpreter equality. Different call models are explicitly incompatible
in this view.

`retirement-boundary` compares every completed instruction's full entry
context, architectural state and delivered IRQ count/vector. Internal raw
phases remain in each input but are not equated across call models. The
existing `exact`, `architectural-v1` and `architectural-elapsed-v1` policies
retain their meanings: only the declared transfer-latch exclusion and,
when explicitly selected, the initial clock epoch differ. No P/status, WRAM,
MPR, vector or later timing difference is masked. Raw clock origins and first
differences remain in reports.

## Original-core observers

The separate unmasked Beetle observer predicts the original control branch
from read-only original IRQ pipeline fields before calling `Run(true)`.
It does not infer retirement from PC/SP movement, equal register values or
unchanged last-opcode fields. A separately retained call journal records the
actual pre/post pipeline, selected branch/vector, phase and attached opcode
ordinal for reset, primer, continuations and measured calls. The qualifier
rechecks that journal against the pinned original branch conditions and v2
events. Reset stays separate from opcode retirement; unsupported stepping
configurations and ambiguous boundaries stop explicitly.

The Gear observer uses original `TRACE_CPU` and `TRACE_CPU_IRQ` records,
including the actual vector and return PC. Its build keeps the original
disassembler/trace support enabled. Primers and their continuation counts are
retained separately; measured aggregate calls must each contain one opcode.
Source-hit ledgers use actual fetched bytes and mappings. Native/interpreter
captures retain complete PC/MPR/physical/byte identities and actual tier hits.

Both original cores compile separately from pinned user-supplied source.
No original CPU body is extracted, patched or linked into the MIT runtime.
The default v1 observer retains its I-mask guard; unmasked stepping is a new
opt-in domain. Reproduce with fresh private outputs and existing dependencies:

```text
python scripts/irq_boundary_reference.py --gear-source PINNED_GEAR --beetle-source PINNED_BEETLE --tool-source PINNED_TOOL --out .local/irq-reference --library LIBCHDR --library LZMA --library MINIZ --library ZSTD
```

## Interpretation and remaining work

The authored suite initializes mapping, RAM, timer and registers through guest
instructions. It measures timer delivery, CLI/SEI/PLP/RTI, saved flags and stack
wrap, timer-mask races, pending BRK, speed transitions and a remapped vector.
It preserves source-predicted reference disagreements rather than changing the
toolkit's selected Gear profile just to produce equality. A reference majority
is not physical hardware evidence.

Timer-only vectors do not qualify simultaneous IRQ1/IRQ2 priority, actual VDC
acknowledgement phases, every interrupted block transfer, WAI/overclock
profiles, arbitrary bus mappings or all CPU semantics. The separate measured
TII continuation test checks accounting with interrupts masked. See
[STATUS.md](STATUS.md) for actual frozen run counts and observed differences.
The separate [device IRQ suite](IRQ_DEVICES.md) extends genuine source priority
and acknowledgement evidence to VDC DMA and CD DATA IN/STATUS. Its scope does
not turn this timer-only Beetle adapter into a CD reference adapter.
The [dynamic-stall suite](IRQ_STALLS.md) separately checks DMA IRQ1 and CD
IRQ2 assertion and CPU sampling during real queued VRAM waits against Gear.

Primary sources are the pinned
[original Beetle CPU](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/huc6280.cpp)
and [opcode implementation](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/huc6280_ops.inc),
and [Gear CPU stepping](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h).
