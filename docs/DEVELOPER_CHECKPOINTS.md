# Developer checkpoint acceptance plan

**Planned; no machine checkpoint save/restore API is implemented.** Existing
CD BRAM persistence saves the isolated backup-memory payload. TCP memory reads,
images, code captures and build caches are also distinct from a complete machine
checkpoint.

Consumer testing has exposed a concrete need: repeated frontier diagnostics
currently replay a long reset-to-frontier input route. An opt-in paused developer
checkpoint could make those tests practical. The first version should accept
only the exact reviewed runtime ABI/source, executable, generated module, input
identities and runtime/device profiles. Cross-module states, portable saves,
rewind and importing emulator/owner states remain later interfaces.

## Required state and ownership

A CPU/register/WRAM dump is insufficient. The state inventory must include:

- CPU, all eight MPRs, transfer latch, source bytes/generations, pending sampled
  IRQ state, stack and every enabled RAM/device expansion.
- VDC/VCE registers, VRAM/SAT, queued accesses, retained buffers, DMA, raster
  phases, scroll/display latches and the renderer's completed/in-progress state.
- CD command/data/status/message state, ACK edges, FIFOs, read/seek deadlines,
  sector/head positions, provider identity, CDDA cursor/sample latches and fades.
- ADPCM RAM, addresses, nibble/decoder state, DMA and source IRQs; PSG voices,
  noise/LFO/DAC phases; mixer queues and complete resampler/filter/DSP history.
- Joypad SEL/CLR/multitap latches, guest input state, input-recipe position and
  guest event-clock origins.

Opaque host pointers, streams, locks, SDL handles and sector-provider objects
must be reconstructed through checked interfaces, not copied as native bytes.
Unknown or omitted enabled profiles stop explicitly. Host presentation may be
recreated, but its boundary and pending audio policy must be declared and tested.

Save/load must be explicitly requested while paused, use new exclusive private
outputs, and validate size/schema/digests/identity before committing state. Load
must be transactional: rejected or interrupted loading leaves the live machine
unchanged. No owner installation, launcher selection or automatic BRAM publication
is implied. Saving a checkpoint must not advance guest clocks, consume input,
acknowledge IRQs or drain guest data.

## Evidence must retain its origin

A resumed run is a new execution window. Receipts must bind the checkpoint and
its source receipt, record imported absolute clocks/counters separately, and
report only newly executed native/interpreted work as window evidence. Code
capture needs an explicit resumed origin and source completeness/loss window.
Imported prefix counters must never appear as fresh full-reset native execution.
Tick/step deadlines, input offsets, PCM history and frame numbering need explicit
absolute/window semantics. Existing full-reset and BRAM receipt contracts remain
readable with their original labels.

## First implementation gates

Use authored fixtures to compare uninterrupted execution with a fresh process
restored from each paused checkpoint. Check full state, exact source identities
and per-key hits, memory/generations, RGB and digital PCM across active queued
VRAM/DMA, sampled interrupts, CD DATA IN, ADPCM/CDDA and filter-history boundaries.
Include exact end-of-span and input/frame boundaries. Exercise repeated saves,
loads and pause/resume without clock or audio drift.

Actual corrupted/truncated copies, missing fields, unsupported profiles, changed
ABI/source/binary/module/media/profile identities and cross-module attempts must
be rejected without live-state changes. Independent device/reference evidence
remains necessary; internal restore equality alone does not prove hardware
accuracy. A finite isolated retail regression follows the authored gates.

This plan records a shared toolkit requirement from consumer testing. It does
not request consumer migration, an ad-hoc state fork or changes to existing
qualified packages. A complete state inventory and versioned format review are
the next steps before implementing the TCP commands.
