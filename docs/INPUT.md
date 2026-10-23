# Controller I/O reference profile

The opt-in controller profile implements the hardware-bank joypad port at
physical `$1FF000..$1FF3FF`. Every address in that range aliases the same
port after MPR translation. It is a deterministic guest protocol, with
explicit host-supplied button state; a desktop input backend is still planned.
This profile selects pinned Geargrafx 1.8.4 behavior where independent emulator
implementations differ. It is not electrical hardware qualification.

## Port and controller contract

Guest writes use bit 0 as SEL and bit 1 as CLR; upper bits have no controller
meaning. Reads return a latched byte, sampled by the preceding guest port
write. Changing a host button alone does not resample that byte. Reading the
port does not advance a controller, toggle a bank or change the latch.

| Read bits | Meaning |
|---|---|
| 0-3 | Active-low selected controller nibble |
| 4-5 | Both set |
| 6 | Set for Japanese PC Engine profile, clear for TurboGrafx profile |
| 7 | Set when CD hardware is absent, clear when present |

With CLR low, a standard pad returns I, II, Select and Run on bits 0-3 when
SEL is low, or Up, Right, Down and Left when SEL is high. Pressed buttons
clear their bits. Opposing directions remain explicit input; the guest
protocol does not invent filtering, turbo pulses or Select/Run suppression.
With CLR high, a selected supported pad returns zero in the low nibble.

A six-button pad alternates its extra-button bank on CLR falling edges.
In that bank, SEL low returns III, IV, V and VI; SEL high returns the zero
identifier nibble. The normal bank uses the standard-pad mapping. The bank
is shared by the selected Geargrafx profile, rather than independent hidden
state per multitap child. Repeated writes at the same CLR level do not toggle it.

An optional five-port TurboTap advances its slot on a write with new CLR low
and a SEL rising edge. A CLR rising edge with new SEL high resets the slot to
zero. Advancing past port 4 saturates at slot 5; reads then return `$F` in the
low nibble. Overflow is checked before CLR gating and six-button bank toggling.
Without a tap, every write selects port zero. There is no modulo-five wrap.
All five slots contain supported two/six-button pads; disconnected ports
are not exposed as a selectable device type in this batch.

The reference reset starts SEL and CLR high, slot zero, normal bank, all
buttons released, then samples a `$FF` control write. It is a defined sandbox
reset profile, not evidence of a console's physical power-on state. Runtime
reset retains controller types and region/CD/tap configuration.
Controller I/O adds no fixed VDC-style access wait. It does not modify code-bank
generations or the separate MPR transfer latch. Native mapping/source guards
and execution deadlines still precede device side effects.

## Headless configuration

`--bios` or `--toc` enables five released standard pads, with no tap and the
USA region profile. Region is explicit sandbox configuration, not inferred
from firmware contents. Without those options, controller I/O remains disabled
unless one of the following options enables it:

```sh
pce-headless IMAGE LOAD PC MPRS STEPS TICKS hybrid --joypad 6 --joypad-region usa --multitap on --buttons 0x001,0x008,0,0,0
```

`--joypad` accepts `2` or `6` for all five slots. `--joypad-region` accepts
`japan` or `usa`; `--multitap` accepts `on` or `off`. `--buttons` accepts one
to five comma-separated active-high 12-bit masks; unspecified slots are
released. Bits 0-11 are I, II, Select, Run, Up, Right, Down, Left, III, IV,
V, VI. This is a held snapshot for a bounded run, not a timed movie or host
device poller. Protocol reads remain active-low. Unsupported values, duplicate
flags and malformed masks are rejected.

## Source differences and limits

The selected behavior follows pinned
[Geargrafx input](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/input_inline.h),
[reset](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/input.cpp)
and [memory routing](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory_inline.h).
Source pins and hashes are in [references.lock.json](references.lock.json).
The implementation is original project code based on observed facts, not
copied GPL reference code.

Pinned Mesen agrees on standard-pad nibbles, region/CD bits and the TurboTap
advance/reset and overflow rules, but reads live button state instead of a
write-sampled register. Its [six-button pad](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/Input/PceAvenuePad6.h)
toggles on CLR rising edges and returns `$F` while CLR is high; its standard
pad returns zero there. Mesen forwards inactive tap children a `$03` write,
so per-device bank behavior differs from Geargrafx's global bank.

Pinned [Beetle input](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/input.cpp)
requires old and new CLR low for tap advancement and returns zero on overflow.
Its [gamepad](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/pce/input/gamepad.cpp)
toggles the extra bank only when SEL remains high across CLR falling, does
not gate reads on CLR, and resets SEL/CLR low. These are source cross-checks,
not additional live emulator qualification. Ordinary scan sequences overlap;
arbitrary edge sequences do not have universal emulator agreement.

Mouse, keyboard, MB128, TurboLink, analog devices, turbo generation, hot-plug
scheduling, desktop polling/remapping, movie formats and persistent input/state
serialization are outside this profile. Unsupported device configurations
fail explicitly. A later host must supply inputs at explicit guest boundaries
without tying simulation to presentation FPS. Future states must include
controller types, button snapshots, SEL/CLR, slot, extra bank, output latch,
region and CD-presence profile.

## Verification scope

The authored `pce-joypad-tests` fixture checks **50,341** independent expected
cases/groups: 32,768 button-nibble cases, 8,192 control/reset cases, 136 tap
cases, 9,228 native/interpreted bus cases and 17 host/configuration groups.
These cover both CPU speeds, mapping aliases, RMW, source guards, deadlines
and unsupported access/configuration refusal. Eight synthetic headless tests
separately check CLI validation, profile activation, region/CD bits, held
snapshots, window aliases, six-button identifier and tap overflow, preserving
their authored input files. Local expectations do not establish physical
controller behavior. Live reference scope is in [REFERENCE.md](REFERENCE.md).

Geargrafx live checks pass 56 authored plans across HuCard and CD profiles:
2,512 CPU/guest-port-output checkpoints and 56 full 8 KiB work-RAM comparisons
per tier, with 2,512 native versus 2,512 interpreted instructions. The reference
headless Auto setting yields the USA line; both CD-presence states are covered.
The Japanese line remains local/source-checked. Internal device structs and
host events during a sequence are not live-compared. See the adapter details
and remaining limitations in [REFERENCE.md](REFERENCE.md).
