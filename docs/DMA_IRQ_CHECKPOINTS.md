# Guest-driven CD DMA and IRQ checkpoints

This qualification joins three paths that previously had separate evidence:
CD READ handshakes, ADPCM DMA, and actual CPU interrupt entry/return.
[Coupled DMA checkpoints](CD_ADPCM_CHECKPOINTS.md) check device events using
supervised port operations. [ADPCM IRQ vectors](ADPCM_IRQ.md) execute guest
handlers without a CD command. Neither alone proves that an autonomous guest
can complete READ-fed DMA while an interrupt temporarily diverts execution.

## Guest and checkpoint contract

The authored program initializes its own mapping, stack, speed, interrupt
masks and ADPCM destination. It sends READ through the command/data port and
ACK edges, polls the controller, enables DMA and completes the status/message
handshake. The IRQ2 handler preserves the accumulator used by that polling
code. CPU-controller masking, CD source masking and the CPU I flag are distinct
controls; a status-port read does not acknowledge ADPCM HALF/END.

Checkpoints are taken at observable instruction boundaries. Interrupt entry
completes synchronously as part of retiring an instruction: stack pushes,
vector reads and entry clocks finish before the host receives control.
There is no supported host checkpoint halfway through those pushes. Tests
must distinguish a live source before sampling, the delayed effect of CLI,
completed handler entry, handler masking and RTI with a still-live source.

A restore imports the entire CPU, stack, device, DMA and scheduler state.
Saving/loading must not advance clocks, read a sector, acknowledge CD data,
clear an IRQ or execute an opcode. The reconstructed destination rebinds its
own read-only sector provider. Imported retirements remain separate from new
suffix work. Matching hashes of complete encoded same-tier state establish continuation;
independent literals and original-core observations establish their separate
CPU/device expectations.

## Original-core comparison

The separate Geargrafx executable uses actual Standard CD startup and original
CPU execution with its normal hardware callback partition. Original
continuation calls, completed instructions, internally clocked spans and the
remaining clock drain have separate accounting. IRQ callbacks must witness
the actual vector and interrupted source context. Fetch identity includes
logical PC, all eight MPRs, physical addresses and source bytes.

The long seek/poll primer and the measured interrupt continuation have
different purposes. Aggregate primer work and source hits are retained;
detailed journals focus on the measured boundary. Host register writes or
one-tick device stepping cannot replace the autonomous guest or original CPU
execution in this qualification.

The detailed journal retains the first 64 suffix instructions, handler
instructions, actual IRQ entries and the first original HALF/END causes. It
is not a complete primer/DMA callback stream. Original audio buffer drains
discard presentation samples without advancing hardware; this adapter does
not qualify PCM or listening parity.

The toolkit's DMA counter measures **captured bytes**; the original observer's
write-completion callbacks measure **committed writes**. These are explicitly
different measurements while a write is pending. Both reach the independent
2,048-byte endpoint expectation; unequal intermediate counts stay recorded
with their roles.

Original callbacks and toolkit retirement synchronization can expose different
DMA cadence and transient ACK/REQ states. Raw clocks and boundary observations
remain visible. Functional agreement does not qualify electrical bus phases,
exact cross-core instruction ordinals, physical drive timing or hardware
accuracy. No emulator is treated as a perfect hardware specification.

## Verification record

Frozen implementation `485af70b3c0f10d95dfeb82e75fdefbf625883ab`, ABI **26**,
has **78 relevant source files** and SHA
`d25aea1cbc26903481a500ce3533782e80643e761cf9b9c63aaad3f50618e002`.
Runtime/emitter semantics and checkpoint schema 1 are unchanged.
The fresh Release SDL build passes `python scripts/check.py`: **1,212 Python
tests without skips, 63 C++ suites and 12 fresh-process audio checkpoint
cases**. The full build/check and the separate reference run each use the
frozen implementation above.

The fresh reference run passes **20 guest recipes, 40 boundary cases and 80
fresh restores**, with **200 execution joins and 40 original compilation
joins**. It executes **9,771,064 native instructions** and a separate
**9,771,064 interpreted instructions**, with zero native fallback. Each tier
has 9,322,784 creating-prefix retirements, 224,140 uninterrupted-suffix
retirements and 224,140 new restoring-suffix retirements. The restored prefix
is imported, not replayed. There are 348 actual native source identities;
two additional terminal branch loops are compiled but never retired.

Original Gear executes **9,735,052 actual CPU instructions/calls and hardware
callbacks**: 9,379,576 in creating prefixes and 355,476 in measured suffixes.
Original prefix and suffix clocks are 146,922,084 and 6,840,036 master ticks.
This fixture contains no continued block-transfer opcodes, so original call
count equals completed instruction count here. Creating toolkit runs deliver
16 IRQs and execute 16 RTIs per tier. Restoring suffixes add eight IRQ entries
and 16 RTIs: handler-entry cuts import the already completed entry.

The audit checks **13,107,200 independently expected ADPCM RAM byte values**
across 200 reports, plus CPU/stack/WRAM, source, bounds and work relations. Its
larger admitted-value count does not mean every clock is a literal hardware
expectation. It rehashes **1,226 bindings and 130 original Git blobs**,
reconstructs every authored fixture and emitted module, and joins exact
compile/link/build/guest commands to their artifacts. All **10 written altered
receipts** are refused; the preserved original is requalified independently.

**484 tracked scalar/work differences across all 40 cases remain explicit.**
They include cut/final clocks, polling instruction counts, transient CD/ACK
state, pending writes, pointers/length and the differently defined DMA
counters. Original callback counts also differ by definition from the
toolkit's zero external-callback count. These are not 484 demonstrated runtime
defects. Complete same-tier encoded-state hashes match after each fresh
restore; no final authored raw payload files are emitted for direct byte
comparison.

The separate original core is pinned to
[`1c62a549328241518101f5be5bf3e6840b96ea5d`](https://github.com/drhelius/Geargrafx/tree/1c62a549328241518101f5be5bf3e6840b96ea5d/src).
Its selected CPU, CD, ADPCM and SCSI implementation blobs still match upstream
`16417e983c5b47ab8358ee91f75c155f208391a7`. The core inline header differs in
outer frame-loop cheat handling; the hardware-clock method used here is
unchanged. This is a source comparison, not hardware qualification.

Reproduce using existing pinned dependencies and a new private directory:

```text
python scripts/dma_irq_checkpoint_reference.py --gear-source PINNED_GEAR --tool-source PINNED_TOOL --out .local/dma-irq-reference --compiler CLANG --cmake CMAKE --ninja NINJA --library LIBCHDR --library LZMA --library MINIZ --library ZSTD
python scripts/dma_irq_checkpoint_qualify.py .local/dma-irq-reference/result.json --negative-controls
```

Run the scripts from the declared toolkit checkout. The reference adapter
needs its separate Gear sources/libraries; the baseline authored tests require
no retail data or external emulator. Aggregate source hits cover the complete
guest execution while detailed journals retain the selected excerpts above.

The separate direct suite runs **20 cases and 7,148 checks**, executing **410
interpreted opcodes and zero native opcodes**. Restores import 150 prefix
opcodes; those are not executed again or counted as new work. Real READ/ACK/DMA
transactions are host-supervised setup for these small CPU tests. Two CPU
speeds cover before/after CLI, completed entry, handler masking, post-RTI
continuation, held-line re-entry, held ADPCM reset and CPU/CD/I masks.
Complete encoded state matches through each suffix; independent providers
remain connected without new reads from the buffered sector. Truncation and
schema errors are refused transactionally. These checks do not establish
native execution, fresh-process behavior or independent-emulator parity.

An initial direct-test premise incorrectly required a future capture deadline
at every active-DMA boundary. A transfer waiting for automatic ACK release can
legitimately have none. The corrected test checks the active READ, buffered
data and DMA mode instead; no runtime patch follows from that test failure.

## Separate retail TCP regression

The private retained consumer uses toolkit revision
`d102ecb80664ea45bada4036da46b466339daf09`, ABI 26. It is not rebuilt from the
new toolkit qualification pin. The ordinary-input interval adds **1,054
frames**, reaching a map visibly labeled SARINA and then an outdoor mountain
path. It executes **32,548,213 new native instructions and one interpreted
instruction**, with 96 CD sectors, 131,072 ADPCM DMA bytes and no newly decoded
ADPCM samples. Owner packages, saves, launchers and selectors remain untouched.

One uninterrupted run and two fresh **394-frame** checkpoint suffixes produce
byte-identical complete endpoint checkpoint files and core payloads. Each
restoring suffix executes **12,478,595 new native instructions with zero
fallback**, transferring 48 sectors and 65,536 ADPCM DMA bytes. Both retail
checkpoint boundaries have inactive DMA; they do not qualify in-flight DMA or
exact CPU IRQ delivery. A pending CDDA sector deadline and PCM state continue
identically. Hosts are hidden/muted, so there is no listening claim.

The private auditor checks 453 artifact bindings, 61 pure paused observation
pairs and 52 continued status comparisons. A supplemental check validates all
671 raw status audio-origin markers against the actual save replies: 21
imported PCM frames for the writer and 33 for each fresh restore. All three
owned hosts exit naturally with code zero.

The interval accepts **one additional unknown CD `$FF`** under the explicitly
selected `gear-good` response profile, increasing its counter from two to
three. This is a conditional compatibility result, not implemented `$FF`
semantics or strict-mode qualification. The initial auditor's incorrect
unchanged-counter expectation remains preserved separately from the successful
host runs. No campaign, cross-ABI migration, hardware or broader library
qualification follows from this route.
