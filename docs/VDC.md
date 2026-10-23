# VDC ports and raster timing

`Bus::enable_vdc()` implements one HuC6270's CPU-facing ports, register
storage and 64 KiB VRAM. Its synchronous functional mode remains available
for focused port tests. `Bus::enable_video_timing()` additionally enables
raster events; supplying `--bios` selects this clocked profile beside the
clocked CD command-control profile. The ordinary firmware-free sandbox keeps
unsupported I/O faulting. VRAM accesses still settle synchronously; raster
events do not implement rendering, contention or DMA.

The untimed functional profile begins with zero registers, VRAM, read buffer
and status. `Bus::enable_video_timing()` instead seeds HDR `$001F` and VDR
`$00EF`, matching Geargrafx's reference reset geometry, with the other registers
zero. This describes 256-dot/240-line display counters; it does not initialize
a renderer. `Vdc::enable_raster()` itself preserves the caller's register
values. These deterministic profiles are not hardware power-on or
BIOS-initialized state. ABI 5 introduced the video-clock contract; the current
native module **ABI 7** also includes CD TOC/response/auto-ACK state. Regenerate older
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
| `$0F` | DCR | `$001F` | Stored DMA configuration; no DMA engine |
| `$10` | SOUR | `$FFFF` | Stored DMA source |
| `$11` | DESR | `$FFFF` | Stored DMA destination |
| `$12` | LENR | `$FFFF` | Low byte stores; high-byte DMA trigger faults before mutation |
| `$13` | DVSSR | `$FFFF` | Low byte stores; high-byte SATB trigger faults before mutation |

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

The HuC6260 timing control is write-only at physical
`$1FE400..$1FE7FF`, mirrored where `address AND 7` equals zero. It adds one
CPU wait cycle. Control bits 0–1 select dot divisors 4, 3, 2, 2; bit 2 selects
262 or 263 scanlines. Each scanline lasts **1,365 master ticks**, independent
of pixel width and CPU speed. Palette and other VCE ports remain unsupported.
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
Collision, sprite overflow and DMA-complete flags are not generated. Busy
remains clear because VRAM transfers are synchronous. An unmasked pending
IRQ1 stops execution explicitly: CPU interrupt entry is not implemented.
Automatic SATB transfer requested through DCR bit 4 faults when its blank
event arrives; storing the control bit does not silently complete DMA.
Clock synchronization rejects CPU time moving behind the device clock.
Changing VCE frame length behind the live line counter also faults until
that wrap behavior has separate qualification.

This foundational timing profile follows Geargrafx's event ordering. Mesen
corroborates the programmable phase durations, fixed line length, CR gating
and acknowledgement, but differs in some scheduling: its non-display HDS
event is 25 dots before display start versus Gear's 26; startup blank and
zero-VCR handling also differ. Mesen was inspected, not run live. These
corners are reference differences, not hardware timing certification.

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
None of these checks establishes rendered output or a playable game.

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
  independent timing-control divisors and line-count selection.

This project's implementation is original. No GPL VDC implementation is
copied or linked; the independently developed reference remains a separately
supplied process. Source identities are recorded in `references.lock.json`.
