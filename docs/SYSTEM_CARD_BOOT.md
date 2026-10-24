# System Card reset-vector boot

Runtime ABI **17** adds a separate startup path which executes a supplied
System Card ROM from its real reset vector. It does not extract an IPL program,
preload game RAM, patch firmware services or select a game entry point.
The existing snapshot/IPL startup remains available with its original behavior.

## Run the firmware

```sh
build/pce-headless --system-card-reset super /path/to/syscard.pce 20000000000 100000000000 hybrid --toc /path/to/disc.toc --disc /path/to/disc.chd --libchdr /path/to/libchdr --dev-port 0 --dev-start-paused on
```

Use the platform's executable/library suffixes. The same grammar works with
`pce-desktop`. Existing audio, video, input, capture and bounded execution
options remain available. The BIOS must be an explicitly supplied raw
256 KiB image; length checking does not authenticate it. Firmware, disc images,
derived modules, captures and saves stay private.

Choose `standard` or `super` hardware explicitly. The loader does not infer
expansion RAM from a filename, checksum or apparent firmware version. Snapshot
payload/load/PC/MPR arguments and another `--bios` are rejected in reset mode.
Supplying `--bios` to the original snapshot command still only maps firmware
services; it does not implicitly enable reset-vector startup.

## Memory and initial state

| Region | Reset profile |
|---|---|
| Banks `$00..$7F` | 256 KiB System Card ROM mirrored through the cartridge range, except expansion RAM below |
| Banks `$68..$7F` | Independent 192 KiB RAM on Super hardware; ROM on Standard |
| Banks `$80..$87` | 64 KiB CD RAM on both profiles |
| Banks `$F8..$FB` | Four aliases of the same 8 KiB work RAM |
| Bank `$F7` | Existing gated, volatile 2 KiB BRAM and upper holes |
| Bank `$FF` | Implemented device ports; known unsupported I/O still faults |

Absent memory reads return the selected reference profile's `$FF`; writes to
absent memory and cartridge ROM are ignored. These behaviors are specific to
the selected machine profile. The standalone sandbox keeps its strict unmapped
and ROM-write faults. Super identification ports `$18C0..$18C3` return
`00 AA 55 03`; Standard returns `$FF`. Writes to those pins have no effect.
Source identities retain the original mapped physical address even when ROM
or work-RAM storage resolves through a mirror. Loader generations remain
coherent across aliases, and native dispatch retains byte/MPR guards.

The host selects **`gear-deterministic-zero-v1`**, an explicit reproducible
initialization policy. A/X/Y/SP and unspecified flag bits start from zero;
I is set and D/T/B clear. MPR7 is zero, and the vector is read from physical
`$001FFE/$001FFF`; the other MPRs are explicitly seeded zero. CPU speed starts
low, at 12 master ticks per cycle. Reset itself retires no instructions and
starts the recorded clocks/counters at zero. The MPR transfer latch is zero,
I/O latch `$FF`, timer/IRQ state cleared, and VDC read buffer `$FFFF`.

This is a reproducible software reference profile. Unspecified CPU,
MPR and RAM values are deterministic test choices, not claims about electrical
power-on state. Device geometry follows the named Gear reference profile
without its optional safe display defaults. The lower-level API permits
explicit CPU/MPR/RAM seed bytes for directed qualification.

Memory setup requires a pristine bus. CPU power-on is one-shot and rejects
advanced device clocks or another power-on before changing state. There is no
warm-reset, reset-pin waveform, snapshot restore or host-save migration API.

BRAM starts blank and unformatted unless `--bram` supplies an exact read-only
2,048-byte image. The toolkit never formats BRAM on reset, writes the seed back
or discovers an owner's save. Gear's default new-session BRAM formatting is an
emulator convenience, not a physical reset operation. Reference tests seed
BRAM explicitly on both sides. Real formatting, if requested through firmware
controls, affects only the running guest's volatile copy.

## Consumer projects and diagnostics

Consumer schema remains **1**. A reset project replaces `[payload]` with:

```toml
[boot]
mode = "system-card-reset"
profile = "super"

[bios]
path = "private/syscard.pce"
sha256 = "REPLACE_WITH_THE_ACTUAL_IMAGE_SHA256"
```

All normal tool/module/input hash pins, runtime settings and limits remain
required. `[payload]` and `[boot]` are mutually exclusive. The positive native
module contract remains; an unmatched module may fall back in hybrid mode,
and that work must be reported honestly. ABI-12 through ABI-16 captures remain
accepted as their original observations; re-emit and rebuild for ABI 17.

The [authored reset consumer](../examples/reset-consumer/README.md) demonstrates
native reset entry without any game or firmware data. Standard headless and
Super desktop official verify/build/run sequences each retire **200 native /
zero interpreted instructions**, with actual capture identities and literal
CPU/clock expectations.

Reset-only `boot` metadata appears in final JSON and TCP `host.boot`: selected
profile, initialization policy, physical vector location, initial CPU/MPR
state and BRAM source policy. It remains the initial state as execution moves
on. Paused startup lets TCP inspect the reset state before the first guest
instruction. Existing snapshot output fields are unchanged.

## Verification and limits

The fresh SDL/reference build passes **34 suites / 360 Python tests without
skips**, including **6,105,054 authored reset expectations**. Independent
unchanged Geargrafx 1.8.4 execution passes **38 cases / 29,824 observations**:
1,260 CPU snapshots, 36 complete 109-field device snapshots, 14,944 memory
observations, 13,568 source peeks and 16 signature reads. Explicit seed,
region, vector and memory expectations are checked independently too.

All selected CPU/device/memory values agree. **36 known CSH transitions have
an 18-master-tick difference**: this runtime preserves two entry-speed cycles
and changes the final cycle, while that Gear version changes the whole
instruction. The comparison records both raw clocks and the disclosed
transition adjustment. This is not unconditional cycle or physical bus-phase
parity. See [CPU semantics](CPU_SEMANTICS.md).

Separate private execution of the clean USA System Card and actual disc reaches
the firmware menu in both implementations. At frames 120 and 600, all **256 ×
237 overlapping pixels** match. Full frames differ: the toolkit's documented
active-VDC crop excludes three black rows retained by Gear's fixed VCE
viewport. No device timing or images are changed to force equality. See
[video framing](VIDEO_OUTPUT.md) and [current boot tests](STATUS.md).

This establishes the reset-vector/firmware path for the tested profile, not
every System Card revision, game, electrical reset detail or console variant.
Unknown CD commands, physical VRAM contention, finer CPU bus phases, HuCard
mappers, SuperGrafx/Arcade Card and persistent host saves retain their explicit
limits. The established retail `$FF` CD response condition is not removed by
reset-vector startup.

Primary implementation references are the pinned Geargrafx
[reset sequence](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/geargrafx_core.cpp#L1237-L1275),
[CPU initialization](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280.cpp#L209-L273), and
[memory initialization](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory.cpp#L100-L198).
