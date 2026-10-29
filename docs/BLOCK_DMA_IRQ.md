# DMA IRQ assertion during whole block instructions

The [earlier DMA/IRQ matrix](DMA_IRQ_CHECKPOINTS.md) makes an ADPCM source
pending while the CPU I flag is set, then clears I. This qualification instead
arms READ-fed DMA while I is already clear and witnesses the first HALF/END
source inside an active block-transfer instruction. IRQ2 is delivered after
the complete instruction, with the full copied data and completed return PC.
There is no mid-block checkpoint or partial-block resume interface.

## Authored guest contract

Twenty recipes cover TII, TDD, TIN, TIA and TAI at divisors 3/12 with IRQ2
enabled or CPU-masked. Each program sends its own READ command/ACK edges.
An empty-buffer mode-1 write/readback independently verifies that mode 1
disables itself before data arrives. Continuous mode 2 remains armed across
the seek; this is deliberately a mode-2 matrix, not both-mode coverage.

With I already clear, a finite loop of 1,023-byte ROM-to-WRAM blocks spans the
seek. Each family has its own independent destination pattern. Source and
destination ranges avoid the stack and protocol witnesses. A real original
HALF/END callback must occur in an **incomplete** block continuation before
any IRQ entry. An enabled IRQ must join that same completed block, push
`blockPC + 7`, enter through `$FFF6`, preserve A/X/Y and return through RTI.
The handler masks the CPU controller; the device flags remain latched.

The two cuts are before the DMA-arming store with no source yet, and completed
handler entry for enabled recipes or completed DMA after the masked loop.
Later blocks overwrite the top three stack bytes with their temporary Y/A/X
saves. Entry/RTI frames and final stack residue therefore have separate
independent expectations. Full ADPCM RAM and complete WRAM pattern/hash checks
complement the actual protocol reply and IRQ witnesses.

## Original calls versus completed instructions

For an N-byte block, Geargrafx executes **N+2 actual CPU calls**: a 14-cycle
startup, N six-cycle byte continuations and a three-cycle epilogue. The entire
group produces one fetched-instruction trace and one completed instruction.
An enabled IRQ adds eight cycles after completion. The toolkit retires one
translated or interpreted block instruction with its per-byte clock updates.
Continuation calls are never counted as extra native/guest retirements.

The separate original adapter retains actual returned/internal clocks, each
hardware span, continuation completion flags, first-source and IRQ callbacks,
and full PC/eight-MPR/per-byte physical-fetch identity. It requires exact
call-index/cause/IRQ associations, final-call IRQ delivery and no early
completion. Prefix/new-suffix work and source-edge witnesses join their actual
checkpoint phases. Aggregate hits/calls cover the entire guest run; detailed
journals retain selected first suffix instructions, handlers and cause/IRQ
groups. This is not an unrestricted chronological trace.

Source-generated data is checked independently from cross-core clock equality.
DMA capture counts and original committed-write counts retain distinct roles.
Original callback batching and toolkit synchronization may expose different
clocks and transient device state. Those observations stay raw; no emulator
is treated as a complete hardware specification. Audio PCM/listening,
electrical bus phases, arbitrary late epilogue assertions, IRQ1 contention and
other transfer lengths/alignment combinations remain separate qualification.

## Verification record

Frozen implementation `e08425ca6c607289a18ee6055999e22d4a7461d5`, ABI **26**,
has **78 relevant source files** and SHA
`d9f23444a23ea1d713697ebbef2856dfa2ba80941c6e9aff6b22066d02be3f00`.
Runtime/emitter semantics and checkpoint schema 1 are unchanged.
The fresh Release SDL build passes the complete required check: **1,261
Python tests without skips, 64 C++ suites and 12 fresh-process audio cases**.

The fresh run passes **20 recipes, 40 boundary cases and 80 fresh restores**.
It executes **279,380 native instructions** and a separate **279,380
interpreted instructions**, with zero native fallback. Per tier, 243,300
instructions belong to creating prefixes, 18,040 to uninterrupted suffixes
and 18,040 to newly executed restoring suffixes. Their block counts are
2,520/2,800/2,800 and copied-byte counts 2,577,960/2,864,400/2,864,400.
Imported work is not replayed or counted as new suffix work.

Original Gear completes **261,740 instructions** through **5,709,420 CPU
calls and hardware callbacks**. Its **5,447,680 extra continuation calls are
not opcodes**. These original totals include creating prefixes and measured
suffixes; Gear does not import a toolkit checkpoint. In the fast TII case,
HALF/END occurs in block 190 at incomplete call 810; the slow case witnesses
block 48 at incomplete call 454. Both enter IRQ only at completed call 1,025.
These are actual callback observations, not aligned or inferred byte times.

The auditor checks **13,107,200 ADPCM RAM and 1,638,400 WRAM independently
expected values**, **1,227 artifact bindings**, **130 original Git blobs**,
**200 execution joins and 40 compilation joins**. All **10 written altered
receipts** are refused, then the preserved original is requalified. It
reconstructs exact authored fixtures/emitted modules and joins compile, link,
configure, build and guest commands to their actual artifacts. Source/cause/
IRQ/RTI journals join the correct checkpoint phase and retired source hits.
350 source identities actually retire; two additional terminal branches are
compiled only. Complete same-tier encoded-state hashes match after restores;
no final authored raw payload files are emitted for direct byte comparison.

**330 tracked raw scalar/work differences across all 40 cases remain.** They
include clocks, polling work, pending writes, signals, DMA length/pointers,
capture-versus-commit counters and continuation/callback accounting differences
that exist by definition. They are not 330 demonstrated runtime defects.
The separately compiled original core is pinned to
[`1c62a549328241518101f5be5bf3e6840b96ea5d`](https://github.com/drhelius/Geargrafx/tree/1c62a549328241518101f5be5bf3e6840b96ea5d/src).
Its selected CPU/block, CD, ADPCM and SCSI implementation blobs still match
upstream `16417e983c5b47ab8358ee91f75c155f208391a7`. The core inline header has
separate outer frame-loop cheat changes; its hardware-clock method is unchanged.

The required direct suite separately passes **30 cases and 6,070 checks**,
executing **350 interpreted opcodes, zero native opcodes and 50 block
retirements**. Restores import ten prefix opcodes/blocks. Host-supervised
READ/ACK/DMA setup creates an actual pending 36-tick capture with no IRQ yet;
a 17-byte block spans the first commit at either speed. Independent 119-cycle
block plus eight-cycle entry, registers/flags/stack and full scratch/prefix
patterns are checked. It uses natural before-block/completed-entry cuts,
fresh destination providers and transactional truncation/schema rejection.
It does not supply fresh-process, native or original-core proof.

Reproduce with existing pinned dependencies and a new private output:

```text
python scripts/block_dma_irq_reference.py --gear-source PINNED_GEAR --tool-source PINNED_TOOL --out .local/block-dma-reference --compiler CLANG --cmake CMAKE --ninja NINJA --library LIBCHDR --library LZMA --library MINIZ --library ZSTD
python scripts/block_dma_irq_qualify.py .local/block-dma-reference/result.json --negative-controls
```

Run the scripts from the declared toolkit checkout. The baseline authored
tests need no retail media or external emulator; this additional reference
run compiles the separately supplied original Gear sources and dependencies.

## Separate retained-build Ys III regression

An ordinary-input TCP interval adds **810 frames**, from an outdoor path
through a rope bridge to a cave/water/enemy image. Sampled HP changes from
20 to 11 without a room, damage-cause or quest claim. It executes **26,177,351
new native instructions and one interpreted instruction**. Each of two fresh
450-frame restoring suffixes executes **14,256,668 native instructions and
one interpreted instruction**. Complete endpoint checkpoint files and core
payload bytes match uninterrupted execution.

This uses the retained d102 ABI 26 consumer, not a newly rebuilt toolkit
consumer. The interval adds no CD READ sectors, ADPCM DMA bytes or decoded
ADPCM samples; CDDA/music and PCM continue. Both retail checkpoint boundaries
have inactive DMA, so the authored matrix supplies the source/interrupt proof.
The private audit rehashes 1,485 bindings, checks 33 exact paused host/guest
pairs, 28 continued status comparisons and 547 audio-origin markers. Its 1,006
durable parsed replies are separate from the new raw wire-journal API.

One additional unknown CD `$FF` is accepted under explicit `gear-good` policy,
increasing its counter from three to four. No strict-command, complete port,
ABI 18 migration, hardware or listening qualification follows. Owner packages,
saves, launchers and selectors remain untouched; hosts are hidden/muted and
exit naturally. Mechanical private-auditor failures remain preserved separately
from the successful guest executions.
