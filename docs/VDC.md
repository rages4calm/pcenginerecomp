# Functional VDC register profile

The opt-in `Bus::enable_vdc()` profile implements one HuC6270's CPU-facing
ports, register storage and 64 KiB VRAM. Supplying `--bios` enables it beside
the limited CD-control profile. The ordinary firmware-free sandbox keeps
unsupported I/O faulting. This is a synchronous functional profile: accesses
settle immediately, with no raster events, rendering, contention or DMA.
It starts with zero registers, VRAM, read buffer and status; these deterministic
values are not a claim about hardware power-on or BIOS-initialized state.
The bus layout requires native module **ABI 4**; regenerate older modules.

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
| `$06` | RCR | `$03FF` | Stored raster comparison value; no raster event generation |
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

Status acknowledgement exists, but no engine generates collision, overflow,
raster, DMA-complete or vblank events. The local IRQ1 field is acknowledged
on status read; CPU interrupt delivery is unimplemented. The synchronous
profile never asserts busy. Stored scroll/timing/control values alone do
not implement their scanline, rendering or automatic transfer effects.

## Evidence and sources

The public fixture contains authored code and synthetic RAM/VRAM patterns.
Local expected-value checks and an independent Geargrafx sequence adapter
have separate scopes. The live adapter passed 856 settled CPU/VDC states
and 48 full work-RAM/VRAM comparisons per tier across 48 sequences; it does
not compare status event generation or timing. Full counts are recorded in
[STATUS.md](STATUS.md) and [REFERENCE.md](REFERENCE.md).
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

This project's implementation is original. No GPL VDC implementation is
copied or linked; the independently developed reference remains a separately
supplied process. Source identities are recorded in `references.lock.json`.
