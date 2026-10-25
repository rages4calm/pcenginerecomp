# Queued VDC VRAM accesses

Clocked VDC profiles default to queued CPU VRAM reads and writes. The untimed
functional device remains synchronous. Select `--vdc-access immediate` in
either host, or `vdc_access = "immediate"` in a consumer's `[runtime]` table,
to retain the previous aggregate reference path. `queued` selects the current
path explicitly. The host option requires an enabled clocked VDC.

## Requests and completion

Writing MARR high queues a read. Reading VRR high returns the previous buffer
and queues another read when register 2 is selected. Writing VWR high queues
a word write. Neither a queued request nor inspection publishes its result
early. The shared countdown uses these master-clock delays:

| VCE dot clock | Read | Write |
|---|---:|---:|
| 5.37 MHz | 24 | 21 |
| 7.16 MHz | 24 | 18 |
| 10.74 MHz (controls 2 and 3) | 15 | 12 |

The queue is serviced in three-master-tick groups, retaining fractional
progress while a request is pending. At most one operation completes per
group; reads have priority over writes. Completion uses live MARR/MAWR, VWR
and CR increment, preserving address wrap and the retained read-bus behavior
in [VRAM_BUS.md](VRAM_BUS.md).

Status bit 6 reports pending CPU VRAM work. Reading status clears event flags
and the local IRQ assertion while retaining BUSY for outstanding requests.
Data-port reads enter a wait only if a read is pending. Data writes to MAWR,
MARR or VWR enter a wait if either operation is pending. Once entered, the
wait drains both pending operations. Selection and other register writes do
not introduce that wait. A direct low-level port access that requires clock
progress faults; CPU accesses use the bus helper to advance it safely.

## Arbitration and CPU clocks

SATB and VRAM DMA take precedence. Otherwise admission follows the selected
display state, background fetch window and MWR access pattern, sprite count
and fetch cost, alternating idle slots and HSync exclusion window. Queue
service precedes raster advancement within a pending three-tick chunk, so
completion cannot claim a DMA slot released later in that same chunk.

Mapped reads inject their one fixed CPU cycle before observing the port;
mapped writes inject it after the port operation. Block transfers use two
fixed cycles on their respective side. ST0/ST1/ST2 advance two CPU cycles
before the port and one after it, leaving two cycles for retirement: five
base cycles in total. Generated ST bodies call the shared timed port helper,
without invoking the interpreter.

Dynamic stalls add three master ticks at either CPU speed. They advance
devices and IRQ sampling without inventing base CPU cycles or instruction
retirements. Interrupt entry remains at the existing CPU boundary. A
malformed request that cannot obtain a slot within eight longest frames
faults explicitly rather than publishing fabricated completion. This bound
exceeds a full 65,536-word DMA plus SATB and display interference.

Status and final output include a pure `vdc_access` object: `profile`,
`pending_read`, `pending_write`, `delay`, `phase` (0–2 carried master ticks),
and cumulative `wait_ticks`. Explicit consumer selections validate that
report. Debug snapshots, peeks and native guards do not advance the queue.

## ABI and qualification boundary

Runtime ABI **24** includes the queue flags, countdown, carried ticks,
arbitration windows/HSync origin and CPU wait counter. Re-emit original
ABI-12 through ABI-23 captures without relabeling them and rebuild modules
and runtime together. Consumer/capture schemas remain **1**. No save-state
format is introduced; a future format must retain these fields and bind the
selected timing profile. BRAM-only saves remain a separate contract.

Queued timing can change instruction counts, video or PCM at a fixed frame.
Preserve the old qualified package and qualify a fresh same-profile route;
do not demand historical immediate timing from the queued profile.

The independent adapter in `scripts/vdc_queue_reference.py` uses authored
fixtures and the separately compiled, unchanged Geargrafx core pinned at
`1c62a549328241518101f5be5bf3e6840b96ea5d`. It distinguishes synthetic slot
matrices, free-running device schedules and real CPU execution. Source
references are the [VDC queue and arbitration](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h),
[hardware scheduler](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/geargrafx_core_inline.h),
[CPU stall accounting](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h)
and [mapped access ordering](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory_inline.h).
The MIT implementation is original; the GPL reference is not linked into
the toolkit or copied into its runtime.

This is an emulator-reference model, not electrical or full instruction-bus
parity. Background rendering retains the separately qualified Mesen two-bit
profile, which differs from Geargrafx's four-bit-only background renderer.
Reference reports retain those raw bus differences explicitly; they cannot
be described as whole-VDC equality. Cold read-buffer initialization remains
the toolkit's deterministic zero; reference queue traces establish a common
buffer using actual prefetch and clock progress. Other dummy/fetch bus phases,
all mid-scanline races and physical hardware remain unqualified. Timer/IRQ
progress during waits has authored local checks; independent timer-underflow
and IRQ-entry traces during those waits remain deferred.

The final frozen-source reference run passes **615 cases / 2,556 records**,
with **3,678 independent literal checks per tier**. It executes **582 native
retirements**, zero interpreter fallback, 97 source identities, four MPR
contexts and 24 pure guard negatives. All 12 actual CPU cases match Gear's
states and timestamps. Exactly 99 retained MWR3 background bus differences
are reported separately; all queue/timing fields remain exact. The authored
C++ queue suite adds **49,279 expectations**. These checks establish the
bounded model above, not hardware or whole-game parity.
