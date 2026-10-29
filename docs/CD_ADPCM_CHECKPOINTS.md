# Coupled CD READ and ADPCM DMA checkpoints

The CD transport and ADPCM engine share data and acknowledgement state.
Restoring either device correctly in isolation does not establish that an
in-flight transfer between them will continue correctly. This qualification
extends [CD READ checkpoints](CD_READ_CHECKPOINTS.md) to the coupled path.

## State and continuation contract

Authored commands create actual READ data before enabling ADPCM DMA. Tests
distinguish the scheduled DMA capture, captured write latch, later RAM commit,
automatic ACK pulse and subsequent DATA IN request. A checkpoint preserves
every pending step, destination pointer, length, buffer position and deadline.
Save/load must not fetch another sector, consume a byte, complete a RAM write,
acknowledge a request or advance a clock.

Restoration constructs the destination's read-only sector provider normally,
then reconnects checkpoint state to that provider. Already buffered CD data
and ADPCM RAM belong to the saved machine. Source-object pointers and host
file/decompression caches are not imported. Fresh work counts exclude the
creating process's imported prefix.

Reset behavior is device-specific. In the selected reference profile,
ADPCM soft reset clears port transactions, pointers, decoder and IRQ state
while retaining the DMA mode/countdown. A scheduled DMA capture can still
sample the bus while reset prevents its subsequent RAM commit. CD reset and
command reselection also do not imply cancellation of an independently
scheduled ADPCM beat. These behaviors require explicit observations and
expected values; a generic cancellation rule would be wrong.

DMA mode 1 stops at the drained sector buffer. Mode 2 can remain armed across
the gap before a subsequent sector. The direct fixture additionally checks
CPU-write collision retries, disabled-countdown suspension, destination wrap,
17-bit length wrap, playback and HALF/END source masks. Observing an IRQ2 line
is distinct from qualifying CPU interrupt entry/RTI. The earlier
[ADPCM CPU IRQ qualification](ADPCM_IRQ.md) retains its separate scope.

## Independent reference profile

The separately compiled original Gear core is pinned to
`1c62a549328241518101f5be5bf3e6840b96ea5d`. Its original CD/ADPCM code remains
outside the toolkit implementation. The pinned ADPCM and SCSI implementation
blobs match upstream `16417e983c5b47ab8358ee91f75c155f208391a7`; the core inline
header differs only in outer frame-loop cheat handling, not the hardware-clock
method used by this adapter.
See the [original source](https://github.com/drhelius/Geargrafx/tree/1c62a549328241518101f5be5bf3e6840b96ea5d/src).

Original Gear can consume a pending DMA event only once per ADPCM callback.
Large external clock jumps therefore cannot stand in for an active DMA
timeline. The adapter declares its clock-stepping profile and retains raw
edge observations. Gear's CD/ADPCM callback ordering can expose different
transient ACK/REQ states from the toolkit's immediate transport handshake.
Those raw differences must remain visible; settled functional agreement does
not establish identical CPU bus phases, event timestamps or hardware behavior.

The authored direct-device suite and the supervised guest-instruction pipeline
have separate work accounting. Direct clocks retire zero guest instructions.
The guest pipeline executes actual translated or interpreted port operations,
while its supervisor explicitly selects PC/accumulator values and clock waits.
Complete PC/MPR/physical-byte source identity and actual retirement hits are
required. No original-emulator checkpoint is imported.

## Verification record

Frozen implementation `43ebd1cdf875e004f17c090c12d26f2a9517cc59` passes the
separate reference matrix: **32 cases, 64 fresh restoring processes and 160
execution joins**. It binds **1,182 artifacts and 130 original Git blobs**.
The auditor refuses **10 written altered receipts**, then requalifies the
preserved original. Successful build diagnostics stay hashed; actual execution
stderr must remain empty and all process results must be successful.

Toolkit work is **2,092 actual native retirements** and a separate **2,092
interpreted retirements**, with zero native fallback. Per tier this includes
876 creating-prefix instructions, 608 uninterrupted-suffix instructions and
608 new restoring-suffix instructions. Nine port sites actually retire; nine
terminating branch loops are also compiled but never executed. The hardware
DMA transfers are device work, not extra retired guest instructions.

There are **10,488,480 independently expected RAM/reply/end-IRQ values**. The
larger validated-field count of 10,497,708 includes bounded state, journals and
clock ledgers; it is not a count of independent exact clock expectations.
The original adapter makes **4,277,838 one-master-tick hardware-clock calls**
and 6,026 separately recorded coarse calls. Coarse pre-load waits require no
active transfer, preserve a disabled DMA residual, and assert unchanged RAM,
length, pointer and provider/head state before the load deadline.

All **54 raw cut-field differences** remain in the audit result:

| Field | Unequal observations |
| --- | ---: |
| Absolute clock | 28 |
| DMA residual | 14 |
| Bus signals | 4 |
| Write residual | 2 |
| Active IRQ bits | 4 |
| Automatic ACK residual | 2 |

They occur in 28 of 32 cases. Functional agreement and fresh same-runtime
continuation do not erase these event-ordering differences. No runtime patch
was justified by this evidence.

The required direct-device suite passes **7,343,716 expectations across 60
cases**, including complete RAM bytes and untouched regions, pure save/load,
provider rebinding, invalid-copy rejection, two-sector DMA mode differences
and the reset/slot/wrap/IRQ boundaries above. It retires **zero guest
instructions** and qualifies device IRQ-line state, not CPU delivery.

The original adapter uses actual authored Standard CD BIOS/media loading to
enable the CD audio hardware. Merely exposing CD registers in a HuCard setup
does not enable the original ADPCM clock path. A failed initial adapter epoch
and the disabled-counter wait-guard diagnostic remain preserved. That guard
was corrected without increasing its finite wait limit or changing runtime
semantics.

Runtime ABI **26** and checkpoint schema **1** remain unchanged. The frozen
relevant-code identity is **78 files**, SHA-256
`bf024e586702e159c7ba353c2faf7df266414ebeb6c659ecce3d51922092898b`.
The changed digest reflects the added CMake test target; runtime/emitter source
is unchanged. The fresh frozen Release build passes the full required
`python scripts/check.py`: **1,200 Python tests without skips, 62 C++ suites and
12 fresh-process audio checkpoint cases**, including both SDL dummy-host suites.

## Private retail continuation

The retained earlier ABI 26 diagnostic consumer supplies a separate Ys III
regression. A new exact-build street checkpoint is restored in two fresh
processes. Each 304-frame suffix retires **9,732,834 native instructions and
5 interpreted instructions**, importing a separate **711,441,587 native and
65 interpreted** prefix. It continues **65,536 ADPCM DMA bytes**, **32 CD
sectors**, **65,350 ADPCM samples** and **65,536 DATA IN acknowledgements**.

The uninterrupted and two restored runs reach the same observed street
endpoint at frame **24,759**. Their complete endpoint checkpoint files and
serialized machine payloads are byte-identical, including ADPCM RAM, device
scheduler state and PCM queues. Read-only status/source, RAM and pixel
observations agree as well. The checkpoint and endpoint are between transfers;
this does not claim a retail checkpoint taken mid-DMA or exact IRQ delivery
timing. The authored fixtures qualify the in-flight boundaries.

An initial short Right input reached its finite cap without moving the actor;
that failed attempt remains failed. The longer retained ordinary-input route
observes X 48 to 128. It establishes that finite sequence, not unrestricted
bidirectional control, campaign completion, listening parity or complete ABI
migration. No owner save, selected package, assists, memory writes or retail
capture/WAV is used or modified.

See [developer checkpoints](DEVELOPER_CHECKPOINTS.md),
[state-aware TCP routes](STATE_ROUTES.md) and [current status](STATUS.md).
