# Software bus-event tracing

The opt-in `software-access-callback-v1` observer records actual data reads and
writes from translated native code and the bounded interpreter. It observes
software callback returns, including waits inside the method, before the caller
charges another clock. It does not describe electrical bus pins.

## Scope and compatibility

- Each actual execution call has separate entry/return records and an observed
  retirement delta. A candidate source at entry is not proof that an opcode
  retired: guards, budgets, interrupts and original-core block continuations can
  retire zero instructions.
- A source SHA256 binds entry logical PC, all eight MPRs, encoded instruction
  length, mapped byte addresses and bytes at that entry. Bytes are retained
  privately for independent binding checks. Later RAM cannot reconstruct them.
  Block operands can change after entry; this is explicitly an entry snapshot.
- Access records retain raw master ticks, direction, returned/written byte,
  logical address, access-time MPRs and physical address. Fixed ST0/ST1/ST2 ports
  use their real device addresses with null logical/MPR values. Repeated accesses
  remain separate and equal-time observations keep their original order.
- Opcode/operand fetches, native source checks, host peeks, unobserved dummy
  accesses and idle intervals are excluded. Purpose and dummy classification
  remain null. No unavailable bus activity is synthesized from cycle totals.
- Observation lives outside CPU/Bus/checkpoint state. Runtime ABI remains 29;
  guest state layout is unchanged. Traced native modules must be regenerated
  with manifest `bus_trace = {schema: 1, profile: "software-access-callback-v1",
  code_fetch: "separate-v1"}`. Existing unmarked modules still run normally but
  refuse host tracing. The known no-module interpreter sandbox is supported.
- Host tracing requires configured native span 1. It does not silently change a
  consumer's dispatch recipe. A trace finishes its bounded window and detaches;
  subsequent frame/game execution is separate evidence.

## Consumer and TCP use

Keep outputs private and use a new filename in an existing directory:

```powershell
python -m pcerecomp.project run project.toml --build-dir .local/build `
  --receipt .local/run.json --dev-port 0 --start-paused `
  --checkpoint-dir .local/checkpoints --bus-trace .local/bus.jsonl `
  --bus-trace-calls 256 --bus-trace-events 60000
```

The launcher binds source revision/digest, actual executable, reviewed recipe,
requested limits and actual imported checkpoint origin. It validates the closed
stream against host counters and the host's file hash. The trace boundary can
precede the final frame boundary; trace retirements are a subset of newly executed
work, never imported checkpoint work. Restoring a different-build checkpoint is
still forbidden. Trace paths are not guest state or checkpoint compatibility.

The raw host accepts `--bus-trace`, `--bus-trace-calls`, `--bus-trace-events`, plus
required `--bus-trace-context` and `--bus-trace-source` SHA256 values and a full
`--bus-trace-revision`. Raw callers own those metadata bindings; hash syntax alone
does not attest their source. The reviewed project launcher supplies them.

At a settled TCP pause, `bus_trace_summary` (or `DevClient.bus_trace_summary()` /
`python scripts/dev_client.py --port PORT bus-trace-summary`) reads stored counters.
It does not read guest memory, flush the trace, advance clocks or restart capture.
Inspection while running or with pending frame steps refuses. Use ordinary frame
steps, screenshots and own-build checkpoints to compare instrumented/unobserved
runs. The JSONL is exclusively created when the process closes the trace.

## Format and comparison

`pce-bus-event-trace-1` is strict UTF-8 JSONL: header, initial state, interleaved
`call-begin` / `access` / `call-end`, then final closure. One-based call/event
ordinals are contiguous. The parser checks exact key sets, finite numbers, types,
state chains, full access mapping, per-call tier sums, declared limits and EOF.
It refuses partial/truncated files, repeated keys and non-finite floats. A closed
incomplete diagnostic is retained but cannot qualify as equality.

The code-free state contains PC, A/X/Y/SP/P, all eight MPRs, mapped PC, clock
divisor, raw ticks and WRAM SHA256. MPR latch is explicitly outside this profile.
Tier counts are provenance, not architectural equality; unavailable reference
counts remain unknown. IRQ counts are compared only when both cores observe them.

```powershell
python -m pcerecomp.bus_trace expected.jsonl actual.jsonl --out compare.json
python -m pcerecomp.bus_trace expected.jsonl actual.jsonl `
  --profile elapsed-origin-v1 --scope mapped-callback-v1 --structural --out diagnostic.json
```

Exact comparison is the default. `elapsed-origin-v1` subtracts only the two initial
clock epochs and retains raw values. A structural diagnostic can describe matching
accesses with differing timestamps; it never changes a timing mismatch to equality.
Default exact scope requires identical declared call models/capabilities. The
named `mapped-callback-v1` scope accepts only mapped events, retaining every call,
source, state, access and timestamp while reporting differing call-model, fixed
VDC capability and stop policy as provenance. It does not project or merge block
continuations. No arbitrary ignored
fields, sorting, coalescing, inserted events or clock padding are supported.

Limits admit at most 100,000 records, 16 KiB per line and 128 MiB per file. Host
capture bounds are 1..10,000 calls and 1..60,000 data events, default 256/60,000.
The recorder also has a retirement cap and its own steady-clock deadline checked
at execution boundaries. These are explicit diagnostic bounds, not build budgets.
Event overflow, missing source, faults and cancelled windows remain incomplete.

## Independent references

`scripts/bus_event_reference.py` builds separate original pinned Geargrafx and
Beetle executables, retaining their memory/CPU implementations and direct paths.
Read-only observation is added to fresh private source snapshots. The unmodified
original, instrumented-but-disabled and enabled runs are separately compared.
The authored fixture includes RAM, stack, TAM mapping, both CPU speeds, direct
FastMap and handler reads; a TII route retains original block continuation calls.

Geargrafx and Beetle place software callbacks at different clock points, including
scalar operations. Raw timing disagreement is expected diagnostic evidence, not a
reason to insert idle cycles. Native/interpreter parity is internal evidence;
original emulator comparison is independent software evidence. Neither proves
hardware timing or whole-console compatibility. MMIO/IRQ/wait-state qualification
needs further fixtures and explicit device contracts.

Primary source pins:

- [Geargrafx CPU](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_opcodes.cpp)
- [Beetle CPU](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/huc6280.cpp)
- [Beetle direct/handler memory paths](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/huc6280.h)

GPL reference code is built separately and is not linked into the MIT runtime.
Public tests and fixtures are authored; game bytes, traces and checkpoints stay
private. The [original proposal](BUS_TRACE_PROPOSAL.md) is retained as design history.

## Qualified implementation slice

The original-core runner executes original, instrumented-disabled and observed
variants separately, plus actual source refusal controls. Twenty fresh process
runs retain the source/build provenance; subsequent qualification explicitly
reuses and revalidates those pinned original binaries. Low/high routes each
retire 29 instructions and observe 15 data accesses; the TII route retires seven
with 15 accesses. All 90 original event timestamps match finite source-derived
literals. Gear's TII route has 11 actual calls; Beetle/toolkit have seven.

Six fresh toolkit observed/disabled cases preserve complete checkpoints. The
256 source-length/digest controls and actual changed-byte native guard negative
pass. Under `mapped-callback-v1`, Gear low matches exactly and high matches only
after explicit subtraction of its 18-tick origin difference. Beetle's real callback
timestamps remain different even after epoch subtraction. Reports retain those
differences, all original call brackets and the original strict-scope metadata.

The official project build/run API additionally validates a four-native-opcode,
four-event authored consumer receipt. Six Ys III TCP runs qualify cold boot and
its own frame-one checkpoint: tracing on/off preserves complete machine/host
checkpoints, RAM, images and guest PCM, and resumed WAVs match. The complete
256-call native/reference prefix matches 596 chronological records and 84
accesses; the cold prefix has 15,932 data accesses. Full-frame comparisons are
separate from these bounded traces and exclude only the four tier counters for
native/reference state equality. The observer build is unselected.

The actual consumer producer is commit
`0222955b815d7cf2ca3d1952a9199c5b4dae3111`, canonical source digest
`a2e0ef2279e6a4675e6bf7ff6fbfc75457b380bd47872831674078a21140f977`.
Final toolkit runtime/emitter/CMake bytes are unchanged from that producer.
Later catalog changes preserve legacy identity membership while declaring the
ABI29 fetch-observation contract separately. Historical CRLF and canonical LF
source bindings are kept distinct; checkpoints are not repinned.

C++ developer hosts must rebuild against matched headers for the additive
`DevSnapshot` callback; guest state layout and generated CPU/Bus contract stay
at ABI29. TCP clients retain their existing commands. A recorder is one-shot;
use a new recorder for another execution window. Missing source may be explicit
null only in an incomplete diagnostic, never a completed source-bound trace.
