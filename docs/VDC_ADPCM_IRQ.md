# VDC wait, ADPCM DMA and interrupt priority

This authored fixture combines two independently scheduled interrupt sources:
READ-fed ADPCM IRQ2 and VDC VRAM-DMA completion IRQ1. It checks the CPU boundary
after a queued VRAM access stalls. It changes neither runtime ABI 26 nor
checkpoint schema 1. No retail code, firmware or save is needed.

## Required behavior

The CPU begins the target access with I clear and both sources absent. ADPCM
DMA receives real CD READ data while a 4,096-word VDC DMA and queued prefetch
occupy the VRAM bus. Both interrupt requests become eligible before the target
instruction completes. IRQ1 must win the shared sample and enter `$FFF8`.
The guest handler reads VDC status to acknowledge IRQ1, leaving the ADPCM cause
pending. After RTI and the next normal sampling opportunity, IRQ2 enters
`$FFF6`. The alternate guest handler masks CD delivery while preserving the
device cause. An interrupt controller acknowledgement cannot replace the VDC
status read or erase the ADPCM cause.

The two target accesses are a high-byte scalar VRAM read and a two-byte TAI.
The matrix varies both CPU speeds and all three VCE clock divisors. Read data,
stack contents, registers, mapping and source bytes remain explicit checks.
A high-byte read may queue the next prefetch, so IRQ entry does not imply an
empty VRAM queue.

## Direct checkpoint cases

The required C++ suite `pce-vdc-adpcm-irq-checkpoint-tests` checks 48 cases:
two CPU speeds, three VCE divisors, two accesses, two handler policies and two
whole-instruction cuts. It uses explicit unit-test CPU registers and actual
READ command/ACK and device-register setup. The retained seek deadline is
1,024 ticks beyond the target start, inside the much longer queued wait.
This is supervised setup, separate from the autonomous reference program.

The suite passes 29,760 checks, executes 1,224 interpreted opcodes and 36 TAI
instructions, and executes zero native instructions. Imported prefixes contain
24 opcodes and 12 TAI instructions; they are not newly executed suffix work.
Literal PC/P/SP/stack and cycle expectations accompany complete WRAM/VRAM
checks. ADPCM data checks establish committed prefix order and pointer
relationships at the observed length, rather than prescribing a hardware byte
timestamp. The wait window bounds source assertion through source reasoning;
it does not record independent device-edge callbacks.

Each checkpoint reconstructs the machine with a distinct sector provider and
compares complete serialized suffix states. Save purity, provider rebinding,
and transactional refusal of truncated or incompatible payloads are checked.
Cuts are natural instruction boundaries. No checkpoint resumes inside a VRAM
wait or block instruction.

## Autonomous original-core comparison

The frozen reference pipeline runs **24 recipes, 72 boundary cases and 144
fresh restores**: each recipe has an original Gear run and native/interpreted
creating/restoring processes at three cuts, for 360 actual guest processes.
Its program performs real reset/mapping, READ command/ACK, ADPCM setup and
VRAM-DMA writes. It does not seed IRQ flags or a synthetic CD data phase.

The three natural cuts are before the high LENR write starts DMA, after
completed IRQ1 entry with both sources live, and after real guest VDC/CD status
reads and optional CD masking immediately before PLA/RTI. The last cut has
acknowledged IRQ1 while preserving the ADPCM cause. No provider read occurs
during checkpoint creation or restoration; later cuts retain the loaded buffer.

The native tier executes **1,264,464 instructions with zero fallback**, with
another **1,264,464 separately interpreted instructions**. Per tier, 456,360
belong to creating prefixes and 404,052 to each creating/restoring suffix.
Imported work is not replayed. Of 642 compiled source identities, 638 execute;
four terminal BRA variants are compiled but unretired.

Original Gear retires **1,105,272 instructions through 11,566,224 CPU calls**.
The additional 10,460,952 continuation calls are not guest instructions.
Actual source callbacks join their dynamic three-tick wait spans and selected
device state transitions. For TAI, both causes arrive in incomplete first-byte
call 2; delivery waits for completed call 4. The callback, DMA completion,
pending sample and queued-read grant order is explicitly checked.

The toolkit exposes atomic instruction boundaries, so its evidence is different:
an actual sector-provider callback observes the target's full source identity,
I clear, a positive wait and live pending VRAM DMA with no prior ADPCM cause.
Observed pending DMA spans 9,236–13,910 dots. Even the minimum divisor gives a
remaining-time bound larger than the conservative 81-tick first-write bound.
This establishes source-before-grant ordering without inventing exact native
source-edge timestamps or exposing a mid-instruction checkpoint.

Complete RAM/VRAM, stack/vector/acknowledgement, source ledgers, variable-length
block counts, actual execution tiers and imported origins are checked. The
persisted checkpoint hash joins actual `.pcec` bytes. Endpoint comparison uses
SHA256 of the **complete canonical encoded state in memory**; final endpoint
files are not emitted, so it is not a raw-file byte-comparison claim.
All 1,807 artifact bindings and 130 original Git blobs are rehashed; ten written
altered receipts are refused. Thirteen authored tests exercise admission
failures, including omitted source transitions and cross-phase accounting.

Raw differences remain in all 72 cases, including continuation accounting,
CD polling/phase, captured-byte versus committed-write counters and pending
CPU samples. Dynamic wait totals differ in eight recipes across their three
cuts: CPU divisor 3/VCE divisor 2 gives toolkit −6 master ticks, while CPU
divisor 12/VCE divisor 4 gives +3. The other 16 recipes match wait totals.
Cross-core reset, seek, polling and raster origins differ; these executions do
not isolate a stall-algorithm defect. The precise phase/slot cause remains an
open timing gap. No phase injection, timestamp normalization or runtime patch
was used to obtain agreement.

## Evidence boundaries

The independently built Gear reference is pinned to
[`1c62a549328241518101f5be5bf3e6840b96ea5d`](https://github.com/drhelius/Geargrafx/tree/1c62a549328241518101f5be5bf3e6840b96ea5d).
The reviewed upstream head is
[`16417e983c5b47ab8358ee91f75c155f208391a7`](https://github.com/drhelius/Geargrafx/tree/16417e983c5b47ab8358ee91f75c155f208391a7).
Selected CPU, block, CD, ADPCM and SCSI source blobs match. VDC source blobs
differ: current source adds debugger scroll metadata and inlines countdown
decrements above one. Inspection of both `Clock` and `LineEvents` shows the
same selected countdown behavior: values above one decrement without an event;
one becomes zero and runs the same event body; nonpositive values are untouched.
The two direct callers are unchanged. This is source review of the selected
DMA/IRQ/queue path, not an execution claim for the current upstream renderer.
See the pinned [VDC access and event code](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h),
[CPU sampling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h)
and [hardware order](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/geargrafx_core_inline.h).

Priority, acknowledgement and same-build continuation are separate from exact
bus-phase accuracy. Geargrafx provides an independently developed software
reference, not a hardware oracle. Its continuation calls and device callbacks
must remain separate from toolkit retired instructions. Original timing and
state differences are retained rather than normalized away.

These selected blank-display DMA cases do not establish active-display raster
or sprite contention, arbitrary transfer lengths/edge alignments, hardware
parity, cross-build checkpoint migration or complete-game compatibility.
See [dynamic IRQ stalls](IRQ_STALLS.md), [block/DMA IRQs](BLOCK_DMA_IRQ.md) and
[developer checkpoints](DEVELOPER_CHECKPOINTS.md) for the adjacent matrices.

Run the normal authored suites with `python scripts/check.py --build BUILD`.
The separately compiled original-core fixture needs the pinned Gear checkout,
C++20 compiler, CMake, Ninja and compatible existing libchdr, LZMA, miniz and
Zstandard archives. It builds fresh original objects and a translated module;
it does not download dependencies. From the toolkit checkout, choose a new
private output path:

```text
python scripts/vdc_adpcm_irq_reference.py --gear-source GEAR_CHECKOUT --out .local/vdc-adpcm-proof --compiler CLANGXX --cmake CMAKE --ninja NINJA --library LIBCHDR_ARCHIVE --library LZMA_ARCHIVE --library MINIZ_ARCHIVE --library ZSTD_ARCHIVE
python scripts/vdc_adpcm_irq_qualify.py .local/vdc-adpcm-proof/result.json --negative-controls
```

The second command rehashes source, tools, libraries, compiled objects, commands,
captures and checkpoints and checks their semantic joins. It executes no guest.
Its optional controls create new altered receipts and refuse existing names;
use the original receipt for later read-only re-audits without that flag.
