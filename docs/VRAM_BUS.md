# Retained VDC VRAM bus

The VDC has 32,768 connected 16-bit VRAM words and a retained read-bus value.
Its 16-bit internal address space is larger than that storage. Within the
toolkit's aggregate VDC profile, a driven read updates the shared held word;
an undriven `$8000..$FFFF` read returns that held value. It does not wrap to
lower VRAM or invent zero. Cold device initialization starts the latch at zero.

This retained word is separate from the CPU VRR read buffer. Writing MARR's
high byte initiates a prefetch and increments MARR. Reading the VRR high byte
returns the old buffer before the next prefetch. The selected increment and
16-bit address wrap apply even when the read is undriven. Ordinary VWR writes
retain their existing pointer increments; upper-half writes are ignored and
do not drive the read latch. Register/status accesses are not VRAM reads.

CPU prefetch, VRAM DMA, SATB DMA and modeled sprite fetches share the latch.
DMA destination writes do not themselves drive it. DMA direction, priority,
completion flags and interrupts retain their separate contracts. Sprite data
is retained at the modeled fetch event rather than re-read later for continuous
presentation. Pure current-state inspection remains a separate view.

Background fetches also update the bus at the existing modeled line-buffer
event. Driven four-bit background fetches retain the final pattern word; the
two-bit profile retains the selected CG word when driven. An undriven two-bit
pattern retains its preceding fetched BAT word. Background scroll/mode tracking and
guest fetch observations must work independently of presentation output.
Disabling a window or choosing snapshot output cannot freeze guest bus state.

Snapshot rendering and debugger/source inspection do not perform guest reads.
They may observe the stored held word, but cannot update it, acknowledge status,
advance clocks or change VRAM/source generations. A snapshot shows current
storage; it does not reconstruct previously fetched sprite data or historical
palette/scroll state. Continuous output consumes the modeled guest history.

The additional latch and fetch state use runtime ABI **23**. Keep original
capture labels and re-emit/rebuild modules for the current runtime. No save-state
format is introduced. A future state format must retain this bus word alongside
the CPU read buffer, pending DMA and fetched sprite/background state.

The reference boundary is an emulator's aggregate fetch model. It is not an
electrical VRAM bus, CPU access queue, dynamic contention/wait implementation,
or proof of every possible mid-scanline race. Unknown bus phases remain
unqualified. Geargrafx provides the CPU/DMA and four-bit rendering comparison;
the toolkit's separate two-bit profile needs its own source-backed checks.
