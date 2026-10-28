# Checkpoint qualification of VDC register latches

The existing CR/MWR and burst latch rules are preserved. This adds bounded
qualification around live register writes, queued VRAM transactions and
fresh-process checkpoint continuation; it introduces no new VDC policy or ABI.

## Authored clock matrix

The fixture explicitly configures a base HuCard machine, VDC registers and
authored BAT/pattern data. Positive device clocks generate the raster phases;
the supervisor does not inject a pending queue, latch value or raster phase.
These are **direct device tests with zero CPU retirements**, not guest-program
or electrical-bus timing evidence.

Twenty-seven CR/MWR cases cover three boundaries, each with writes three
master ticks before, exactly at and three ticks after the boundary, crossed
with pending read, write and dual requests:

- CR at HDS on active line 64, local clock 96 with divider 4 and HSR `$0202`.
- MWR at the natural VSW transition on line 258, local clock 1,092.
- MWR at the forced VSync transition on line 259, local clock zero.

Nine supplemental cases apply the same write/queue combinations to the
frame-wrap burst decision. CR is latched at HDS outside burst; display/burst
selection updates at the frame boundary; MWR updates at VSW and VSync.

Each case saves after its register/port effects and before later latch/queue
events. The probe compares an uninterrupted machine with a freshly reconstructed
machine, then a new process reloads the written payload and repeats the suffix.
Full CPU/bus/VRAM/partial-and-completed RGB payloads, the private index buffer,
queue endpoints and independent clock/register literals are checked. Imported
state is never counted as new native or interpreted work.

## Independent original Gear scope

`scripts/vdc_latch_checkpoint_reference.py` builds a separate original
Geargrafx device observer at commit
`1c62a549328241518101f5be5bf3e6840b96ea5d`. Its original device clocks and
register operations produce raw rows; it does not import a toolkit checkpoint.
The GPL implementation remains in that separate executable.

The 27 CR/MWR cases require exact equality of all 38 observed fields. The
supplemental burst cases retain a narrow internal representation difference:
before the first active background refresh, original Gear retains backdrop
index `$100`, while the toolkit's unused line buffer contains zero. Those
indices are not consumed while burst/blank. All 22 control/latch/queue fields
must still match, each engine must satisfy its own exact stale-buffer literals,
and active refreshed indices must match. Arbitrary index differences or a
difference after refresh are rejected. Raw records are never rewritten.

This does not qualify every geometry race, divider, sprite mode, bus phase,
whole-frame rendering behavior or physical hardware. The authored software
clock schedule is separate from native opcode timing and retail regression.
See [STATUS.md](STATUS.md) for executed source pins and finite proof results.

Primary sources are Gear's [register and latch implementation](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270.cpp)
and [clock/queue implementation](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6270_inline.h).
The existing [VRAM access](VDC_ACCESS.md), [active-display](VDC_ACTIVE.md),
[scroll](VDC_SCROLL.md) and [developer checkpoint](DEVELOPER_CHECKPOINTS.md)
contracts remain distinct.
