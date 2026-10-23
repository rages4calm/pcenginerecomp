# VDC ports, raster timing and functional video

`Bus::enable_vdc()` implements one HuC6270's CPU-facing ports, register
storage and 64 KiB VRAM. Its synchronous functional mode remains available
for focused port tests. `Bus::enable_video_timing()` additionally enables
raster events while retaining the original unsupported-DMA exits.
`Bus::enable_video()` adds VCE palette ports and clocked VRAM/SATB DMA;
supplying `--bios` selects this extended profile beside CD, interrupts and PSG
register storage. The ordinary firmware-free sandbox keeps unsupported I/O
faulting. CPU VRAM accesses still settle synchronously; the profile does not
implement the reference emulator's queued CPU access/contention machinery.

The untimed functional profile begins with zero registers, VRAM, read buffer
and status. `Bus::enable_video_timing()` instead seeds HDR `$001F` and VDR
`$00EF`, matching Geargrafx's reference reset geometry, with the other registers
zero. This describes 256-dot/240-line display counters; it does not initialize
a renderer. `Vdc::enable_raster()` itself preserves the caller's register
values. These deterministic profiles are not hardware power-on or
BIOS-initialized state. ABI 5 introduced the video-clock contract; the current
native module **ABI 11** also includes IRQ, palette, DMA and PSG state alongside
CD, joypad and block-transfer state. Regenerate older
modules and rebuild consumers together.

## Port routing and instructions

Physical `$1FE000..$1FE3FF` mirrors four ports using address bits 0–1.
Memory accesses first translate their logical address through the current
MPRs, so all mapped aliases reach the same VDC. Instruction-source peeks
remain side-effect-free and refuse I/O.

| Port | Read | Write |
|---|---|---|
| 0 | Return latched status bits 0–5; clear those latches and the local IRQ1 assertion | Select `value AND $1F` |
| 1 | Return zero | Ignore |
| 2 | Return low byte of the VRAM read buffer, regardless of selection | Write selected register's low byte |
| 3 | Return high byte of the read buffer; prefetch the next word only when register 2 is selected | Write selected register's high byte and apply its side effect |

`ST0 #imm`, `ST1 #imm` and `ST2 #imm` write ports 0, 2 and 3 respectively.
They bypass the MPR mapping, advance PC by two, preserve A/X/Y/SP/MPRs and
all flags except ordinary T clearing, and retire in five CPU cycles.
A disabled profile or unsupported trigger faults before retirement.
Generated bodies perform the port operation directly; they do not call the
interpreter. Their immediate operand remains source guarded.

Every successful ordinary memory-mapped VDC read or write adds one CPU cycle
at the current speed, in addition to the instruction's base total. An RMW
therefore has a wait on both its read and write. The dedicated ST instructions'
five-cycle total already includes their fixed port cost. This accounts for a
fixed access wait only; queued VRAM latency, display contention, clock phases
and complete instruction timing parity remain unimplemented.

## Register and VRAM behavior

Selectors 3/4 are unused and retain zero. Selectors `$14..$1F` ignore writes;
reads still return the shared read buffer. Other register writes merge one
byte with the retained byte, then mask unimplemented bits:

| Selector | Register | Retained bits | Functional effect |
|---|---|---|---|
| `$00` | MAWR | `$FFFF` | VRAM write word address |
| `$01` | MARR | `$FFFF` | High-byte write prefetches a word and advances MARR |
| `$02` | VWR / VRR | `$FFFF` | Low byte latches; high byte commits the complete word at MAWR and advances MAWR |
| `$05` | CR | `$1FFF` | Bits 11–12 select address increment 1, 32, 64 or 128 words |
| `$06` | RCR | `$03FF` | Raster comparison value, used by the opt-in clocked profile |
| `$07` | BXR | `$03FF` | Stored horizontal scroll value |
| `$08` | BYR | `$01FF` | Stored vertical scroll value |
| `$09` | MWR | `$00FF` | Stored memory configuration |
| `$0A` | HSR | `$7F1F` | Stored horizontal timing value |
| `$0B` | HDR | `$7F7F` | Stored horizontal display value |
| `$0C` | VSR | `$FF1F` | Stored vertical timing value |
| `$0D` | VDR | `$01FF` | Stored vertical display value |
| `$0E` | VCR | `$00FF` | Stored vertical timing value |
| `$0F` | DCR | `$001F` | DMA directions, completion IRQ gates and SATB auto-repeat in the extended video profile |
| `$10` | SOUR | `$FFFF` | Stored DMA source |
| `$11` | DESR | `$FFFF` | Stored DMA destination |
| `$12` | LENR | `$FFFF` | High byte starts VRAM DMA when enabled; otherwise faults before mutation |
| `$13` | DVSSR | `$FFFF` | High byte arms SATB transfer for VBlank when enabled; otherwise faults before mutation |

MARR prefetch copies a VRAM word to the read buffer, then advances MARR by
CR's current increment. Reading port 3 returns the previous buffered high
byte before prefetching, and only selection 2 initiates that new fetch.
Port 2 reads never increment. Selection and unrelated register writes do
not discard the read buffer. MAWR/MARR increments wrap modulo 65,536.

The physical VRAM holds 32,768 words. Writes with MAWR at `$8000..$FFFF`
are ignored while the write latch and 16-bit increment still update. They
do not mirror into the lower half. Reads in that upper half need the VDC's
rendering-bus latch; this profile faults explicitly rather than inventing its
value. MARR high-byte writes reject such a prefetch before mutating MARR.
A high VRR read which needs an unsupported next fetch also faults.

## Raster clock and event contract

The clocked profile advances in **master ticks**, separately from host
presentation. Every retired native or interpreted instruction advances it,
including fixed I/O waits and both portions of a CSL/CSH speed transition.
A dispatch miss or unsupported instruction does not invent retired time.
The first CPU-facing device access samples instruction-entry time; preceding
fixed waits can advance later accesses within the same instruction. Base
instruction cycles advance devices on retirement. This explicitly approximates
bus phases; an access straddling an event does not establish cycle accuracy.

The legacy HuC6260 timing control is write-only at physical
`$1FE400..$1FE7FF`, mirrored where `address AND 7` equals zero. It adds one
CPU wait cycle. Control bits 0–1 select dot divisors 4, 3, 2, 2; bit 2 selects
262 or 263 scanlines. Each scanline lasts **1,365 master ticks**, independent
of pixel width and CPU speed. The extended profile implements the palette
ports below; the legacy timing-only profile retains their unsupported exits.
The default is divider 4 and 262 lines. Dot phase restarts at each scanline;
1,365 is not divisible by every supported dot divisor.

The VDC keeps separate programmable horizontal and vertical phases:

| Phase | Programmed duration |
|---|---|
| HSW | `(HSW + 1) × 8` dots |
| HDS | `(HDS + 1) × 8` dots |
| HDW | `(HDW + 1) × 8` dots |
| HDE | `(HDE + 1) × 8` dots |
| VSW | `VSW + 1` vertical counter clocks |
| VDS | `VDS + 2` vertical counter clocks |
| VDW | `VDW + 1` vertical counter clocks |
| VCR | `VCR` vertical counter clocks; zero is skipped |

Every VCE scanline boundary interrupts the horizontal machine with a forced
HSW of 24 dots, or 32 dots at divider 3. Horizontal values latch on HSW;
vertical values latch on VSW. VCE sync forces VSW three scanlines before
the end of the frame. The initial horizontal phase is HDS with a one-dot
countdown; the initial vertical phase is VDS. This deterministic startup
contract is distinct from an authentic reset.

At HDW the raster-counter event is scheduled near the display end. Gear's
ordering decrements a newly scheduled event on the same dot as its horizontal
transition. Vertical counters advance at that event, or at the forced line
boundary if HDW was interrupted. Entering VDW resets the raster counter and
allows the next VBlank event. A raster comparison matches `RCR − 64`;
**CR bit 2** gates status `$04` and local IRQ1 assertion.

At the HDS event outside VDW, the first unconsumed blank event is consumed.
**CR bit 3** gates status `$20` and local IRQ1 assertion at that instant;
enabling it afterward does not retroactively raise an event. Status is
latched until a port-0 read, which acknowledges the flags and local IRQ1.
Collision and sprite overflow flags are not generated. The extended profile
generates the DMA completion flags described below. Busy remains clear because
the CPU-facing VRAM path is synchronous. With interrupts enabled, eligible
IRQ1 is delivered using [CPU_SEMANTICS.md](CPU_SEMANTICS.md)'s aggregate boundary
profile. The legacy timing-only profile retains the unsupported automatic-SATB
exit when its blank event arrives; storing DCR bit 4 does not fabricate DMA.
Clock synchronization rejects CPU time moving behind the device clock.
Changing VCE frame length behind the live line counter also faults until
that wrap behavior has separate qualification.

This foundational timing profile follows Geargrafx's event ordering. Mesen
corroborates the programmable phase durations, fixed line length, CR gating
and acknowledgement, but differs in some scheduling: its non-display HDS
event is 25 dots before display start versus Gear's 26; startup blank and
zero-VCR handling also differ. Mesen was inspected, not run live. These
corners are reference differences, not hardware timing certification.

## VCE palette ports

The extended profile decodes physical `$1FE400..$1FE7FF` as eight mirrored
ports, selected with `address AND 7`. Every successful mapped read or write
adds one CPU cycle, including unused ports and block-copy accesses. There are
512 palette entries, each holding nine bits; deterministic initial palette
storage and address are zero. This is an explicit sandbox initialization.

| Port | Read | Write |
|---|---|---|
| 0 | `$FF` | Store control; propagate dot divider and line count to raster timing |
| 1 | `$FF` | Ignore |
| 2 | `$FF` | Replace palette-address low byte |
| 3 | `$FF` | Replace palette-address bit 8 from value bit 0 |
| 4 | Current color low byte, without increment | Replace color low byte, preserve bit 8 |
| 5 | `$FE OR color_bit_8`; increment address | Replace color bit 8 from value bit 0; increment address |
| 6/7 | `$FF` | Ignore |

Address increments wrap modulo 512. A low-byte color access does not latch a
separate color or advance the address; the high-byte access uses the current
entry. Port control bit 7 is retained, but the optional image exporter
explicitly refuses unqualified grayscale conversion.

## VRAM and SATB DMA

DMA is enabled by `Bus::enable_video()`. Writing LENR's high byte captures the
current SOUR and DESR and starts `LENR + 1` word transfers, so LENR `$FFFF`
requests 65,536 words. The engine advances at VDC dots, before horizontal
events on each dot: every fourth eligible dot copies one word. SATB DMA takes
priority; pending VRAM DMA waits until SATB has completed. Dividers 2/4 must
account for the partial dot at a 1,365-master-tick line boundary, rather than
assuming that `master_ticks / divider` always counts actual VDC clocks.

Each VRAM DMA word reads its source before writing the destination. Overlap
therefore propagates newly written data. DCR bits 2/3 select decrement rather
than increment for the source/destination, respectively; these bits are live
at each copied word. Active addresses are latched at the trigger: subsequent
SOUR/DESR writes do not redirect the active copy. After each word the 16-bit
addresses advance and are written back to SOUR/DESR; LENR becomes remaining
words minus one, ending at `$FFFF`. Writes to the unconnected VRAM half are
ignored while counters still progress. A readable source in the unconnected
half explicitly faults until the rendering-bus latch exists. No invented
zero-filled source is supplied.

Writing DVSSR's high byte arms a 256-word SATB copy for the next VBlank event.
DCR bit 4 requests a copy on every VBlank, independently of CR's VBlank IRQ
gate. A copy takes 1,024 VDC dots. Its source is the current DVSSR plus the
current word index, with 16-bit wrapping; DVSSR changes during the copy affect
later words. Starting another SATB transfer replaces its pending count, as in
the selected reference profile.

On completion, DCR bit 0 gates SATB status `$08` and IRQ1; DCR bit 1 gates
VRAM status `$10` and IRQ1. A disabled completion gate produces neither flag
nor IRQ. Status-port acknowledgement clears these flags with the other VDC
latches. The copied SATB is separate from VRAM and supplies the optional
snapshot inspector. CPU VRAM stalls, bus contention, exact access phases and
sprite collision/overflow IRQs remain outside this functional DMA contract.

## Current-state image inspection

`render_snapshot` creates a bounded RGB image from current VDC registers,
VRAM, VCE palette and an optional 256-word SATB. Headless `--frame-out` writes
that image as a P6 PPM file to a new path. It preserves simulation clocks,
device status, memory, counters and IRQ lines. It is an inspection image,
not a reconstruction of a frame's historical scanline state or a desktop
presentation loop.

The image uses `(HDR.HDW + 1) * 8` pixels by `VDR.VDW + 1` lines, up to
1,024 by 512. Background maps support 32/64/128 columns and 32/64 rows,
current BXR/BYR scroll, 8-by-8 four-plane tiles, palette selection and the
shared transparent color-zero entry. Standard RGB maps each three-bit
component to 0..255; this does not emulate composite output. When both CR
display enables are clear, the current-state burst profile produces black.

Optional sprites support 16/32-pixel widths, 16/32/64-line heights, both flips,
palette and foreground/background priority, and a 16-cell line limit. Lower
SATB indices have priority, including an opaque sprite behind the background
masking later sprite candidates. Two-bit sprite data uses the selected Gear
profile. Unsupported two-bit background mode, grayscale conversion and
undriven VRAM reads fault explicitly. Raster effects, historical scroll and
palette latches, sprite collision/overflow generation, analog filtering and
hardware-qualified frame output are not implemented by this inspector.

## Evidence and sources

The public fixture contains authored code and synthetic RAM/VRAM patterns.
Local expected-value checks and independent Geargrafx adapters have separate
scopes. The retained port adapter passed 856 settled CPU/VDC states
and 48 full work-RAM/VRAM comparisons per tier across 48 sequences; it does
not compare status event generation or timing. Full counts are recorded in
[STATUS.md](STATUS.md) and [REFERENCE.md](REFERENCE.md).

The separate clocked adapter passed **4,165 exact-clock device checkpoints
and 15 actual guest status acknowledgements** across 15 timing plans. It
compares VCE/VDC positions, horizontal/vertical phases, sticky VBlank/RCR
flags and local IRQ1 using default divider 4 and 262 lines. This direct device
probe is separate from the local native/interpreter retirement checks; the
other VCE controls have local expected-value coverage. It does not establish
CPU bus-phase timing, interrupt delivery or rendering.

The BIOS-backed experiment is described in [FIRMWARE.md](FIRMWARE.md).
The added local suites check **628,214** palette/snapshot expectations and
**14,786** DMA expectations, including mirror/address wrap, color planes,
all sprite sizes and flip combinations, offscreen sprite line-budget use,
sprite priority, no simulation mutation, source/destination ordering,
dot cadence, SATB priority, repeat and explicit unsupported paths. These are
independently authored expectations; the live video/DMA adapter's completed
scope is recorded separately in REFERENCE.md. None of these isolated checks
establishes a playable game or hardware-qualified frame rendering.

Behavior was checked against pinned primary implementations:

- [Geargrafx 1.8.4 register reads/writes](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270.cpp),
  [register masks and state](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270.h),
  [VRAM transfers and undriven reads](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h),
  [register/status definitions](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_defines.h)
  and [single-VDC port routing](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6202_inline.h).
- [Mesen VDC](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceVdc.cpp):
  independent source check of read buffering, increments, status acknowledgement,
  ignored upper-half writes and the additional queued-access behavior this
  profile does not implement. Mesen was not executed live.
- [Geargrafx CPU port instructions](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_opcodes.cpp)
  and [memory routing](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory_inline.h):
  dedicated-port operations and fixed mapped-access waits.
- [Geargrafx VCE clock](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6260_inline.h)
  and [timing definitions](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6260.h):
  master-clock line boundaries, dot phases and forced sync signals.
- [Mesen VCE](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceVce.cpp):
  independent timing-control divisors, line-count selection and palette ports.
- [Geargrafx VCE registers and RGB conversion](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6260.cpp),
  [VDC rendering and DMA](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270.cpp)
  and [Mesen sprite/tile inspection](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/Debugger/PceVdcTools.cpp):
  palette byte lanes, DMA triggers/order, tile planes, sprite attributes,
  transparency and priority. The inspector follows current storage, not the
  reference emulator's full scanline pipeline.

This project's implementation is original. No GPL VDC implementation is
copied or linked; the independently developed reference remains a separately
supplied process. Source identities are recorded in `references.lock.json`.
