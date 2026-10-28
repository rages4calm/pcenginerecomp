# Guest audio writes and CD end changes — ABI 26

PSG writes now take effect after the current instruction's remaining base
clocks. The CPU-aware bus helper resolves the actual physical I/O mapping,
enabled device and mirrored register range before advancing clocks. Ordinary
RAM writes keep their existing path. Native operations and the interpreter
use the same timing contract for stores, memory shifts/rotates, INC/DEC,
TRB/TSB and all five block transfers. Already incurred VDC waits remain
separate; they are not counted again as base cycles.

During this clock advance devices and interrupt sampling continue. Interrupt
delivery still happens at normal retirement, or after the complete block
transfer. The low-level `Bus::write` and `write_block` APIs remain immediate
supervisor operations; guest lowering uses `write_timed` and
`write_block_timed` with the remaining base cost.

The original pinned Geargrafx CPU flushes pending cycles before calling
`WritePSG`. A retained pre-fix execution places an authored STA write at tick
444 instead of tick 504. This crosses a PCM boundary and changes the sample.
Raw Gear PSG amplitude and the toolkit's divided mixer amplitude are separate
domains; the authored expectation accounts for that documented gain.
The independent matrix matches the first stereo boundary, completed clocks
and actual original port-write traces. Later synthesis samples still differ
and remain recorded; this fix does not establish full waveform parity. VDC
read-source controls use an explicitly matched functional read-buffer seed,
not a claim about original hardware reset values.

The subsequent [matched-domain audio qualification](AUDIO_TRACES.md) explains
all 144 retained later differences: Gear's `EndFrame` included its HPF while
the earlier toolkit probe selected raw output. Separate raw and filtered
comparisons preserve those observations and verify the appropriate domains.

An admitted CD D9 end position may precede the currently playing sector.
Changing the end now preserves the current sector's remaining samples, then
applies LOOP, completion IRQ or STOP at its boundary. It neither rejects the
command nor immediately gates the DAC to silence. Rounded natural completion
retains the final source-frame token even when the new end is behind the
cursor. Explicit stop, reset and reseek continue to cancel that token.

The canonical guest CDDA source/latch works with presentation disabled. Legacy
presentation has its own cursor and receives the same end-boundary fix.
Authored ramps independently check exact sample order and remainder length.
Fresh checkpoint restores also compare complete source, queue and filter
state for output off, raw 44.1 kHz and filtered 44.1/48 kHz in both timing
profiles. These continuity checks are internal evidence; original Gear
execution provides the separate CPU/device reference.

ABI 26 is required because older generated operations omit the timed write
helper. Merely editing an ABI assertion does not upgrade them. Re-emit
original-labeled ABI 12–25 captures, rebuild modules and runtime together,
pin the new source identity and obtain fresh execution evidence. Consumer,
capture and checkpoint payload schemas remain 1. Exact-build checkpoint
bindings reject earlier binaries and ABIs; there is no checkpoint migration.

The probes qualify selected guest write phases and end-change behavior.
Absolute drive seek timing, complete electrical bus phases, analog filtering,
listening parity and full-game compatibility are not established by them.
See [current measured results](STATUS.md), [consumer migration](CONSUMER.md#upgrade-a-consumer-to-abi-26)
and [developer checkpoints](DEVELOPER_CHECKPOINTS.md).

The original reference is Geargrafx commit
`1c62a549328241518101f5be5bf3e6840b96ea5d`:

- [PSG pending-cycle flush](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/memory_inline.h)
- [CPU clocks and interrupt sampling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h)
- [CD end admission and sector completion](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_audio_inline.h)

The public `pce-psg-phase-tests` and `pce-cdda-end-tests` targets run without
retail input and are included in `scripts/check.py`. Independent runners
`scripts/psg_phase_reference.py` and `scripts/cdda_end_reference.py` require
an explicit original source checkout, compiler and dependency archives; their
`--help` lists the inputs. They compile the original GPL implementation in a
separate executable. The toolkit does not copy those implementation bodies.
