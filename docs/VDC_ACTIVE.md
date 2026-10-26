# Active-display VRAM arbitration

This suite extends the [queued-access contract](VDC_ACCESS.md) and the separate
[blank-slot IRQ tests](IRQ_STALLS.md). It uses authored firmware and authored
CUE/BIN media, public Standard CD startup and zero expanded Card RAM. It needs
no user BIOS or game.

The matrix has 138 configurations at both CPU speeds and VCE divisors 4, 3
and 2:

- 72 background cases: four MWR patterns and high/low reads, high/low writes
  or high-port read-modify-write.
- 48 sprite cases: four fetch-cost modes and one or four admitted cells.
- 18 boundary cases: one, four or sixteen cells, with both queues pending.

Guest stores configure VRAM and SATB source data, trigger a real SATB DMA,
set the display registers and execute a warmup. An independent integer
planner derives the observation phase from the complete instruction prefix.
No observed beam position, queue seed or host-written pending state supplies
an expected value.

The selected geometry is HSR `$0202`, HDR `$7F1D`, VPR `$0F02`, VDW 239 and
VCR 2. Measurements stay in a declared steady active interval. CR and MWR
are stable there; this does not qualify live midline changes to those latches.
The original sixteen-cell limit counts a wide sprite as two cells. Transparent
and offscreen cells still consume fetch budget in the selected profile.

The boundary cases require actual ready attempts on three consecutive
three-tick slots: both queues blocked before the BG endpoint, read priority
granting at the exact endpoint, then the remaining write blocked again.
The exact-end discontinuity is pinned Gear behavior, not a hardware claim.

Requests can encounter arbitration and still finish before the CPU needs
their result. The report therefore keeps request classification and actual
CPU waiting separate. A positive wait can also be request latency alone.
Normal guest CPU clocks here are multiples of three; only zero queue carry
is qualified. Earlier direct-device fractional schedules remain separate.

The original observer retains 41 raw kernel fields, full WRAM and
little-endian VRAM hashes, original callbacks, continuation calls and every
clock span. A separate 31-field model checks the selected device state.
The cached original eligibility result is retained only as historical cache
state; inspection never calls the original mutating eligibility method.

`INC $0003` has two distinct waits. Its read queues another prefetch before
the write-side wait; its eventual write must use the byte originally read.
Explicit zero-clock MMIO stages bind this transition to the raw callbacks.
Flattening those waits or substituting the later read buffer must fail.
Only primer WRAM block transfers compact their per-span kernels; exact
continuation clocks and counters remain checked.

The CMake target `pce-vram-active-tests` runs both execution tiers. The Python
fixture and checker tests use authored values. The optional
`scripts/vram_active_reference.py` builds the pinned original Gear core
separately, using explicit existing dependency libraries, and records source,
compiler, object, fixture and raw-output bindings. See its `--help` output.

## Qualification boundary

The working-source proof passes all **138 cases**, with **6,624 measured
retirements per engine**. Actual toolkit work is **36,070 native instructions
with zero fallback**, plus an equal separate interpreter run, **3,048 block
transfers per tier** and **552 pure guards**. All **1,803** translated source
identities are actually observed. There are 76 elapsed retirement matches
and 62 independently predicted differences; both complete engine timelines
are checked rather than forcing equality. All 18 actual endpoint triples pass.
Fresh SDL-enabled `python scripts/check.py` passes **980 Python tests without
skips and 50 C++ suites**. The active C++ suite performs 141,416 checks.
CTest metadata contains 51 registrations including Python; no second CTest
execution is implied.

The proof retains its original parent revision and exact working-source
bindings; it is not relabeled as a later frozen checkout. Earlier failed
preflights exposed checker-contract assumptions about empty wait groups and
coverage labels; their outputs remain separate. No production runtime fix was
needed to pass the authored matrix.

This is an initial authored qualification increment. The fresh Ys III TCP
pair and a separately frozen-source audit for this candidate are deferred.
Earlier retail results remain attached to their own reviewed source pins.
No production CPU/device semantic change or ABI migration is claimed here.

The scope excludes electrical bus phases, whole-renderer equality, all
midline races, mixed interrupt sources, physical hardware and campaign parity.
The source reference is [original Gear arbitration](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h).
Its GPL core stays in a separate reference executable; implementation bodies
are not copied into the toolkit runtime.
