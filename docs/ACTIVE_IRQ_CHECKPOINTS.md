# Active-display interrupts and checkpoint continuation

This authored matrix checks raster or sprite-collision IRQ1 competing with
READ-fed ADPCM IRQ2 across a queued VRAM access during active display. It
extends the earlier [blank-display DMA/IRQ matrix](VDC_ADPCM_IRQ.md). It adds
reference probes, strict evidence admission and a required native integration
test. It changes no runtime, emitter, ABI 26 or checkpoint schema.

## Guest program and independent expectations

| Axis | Recipes |
|---|---|
| VDC IRQ1 source | Raster compare or opaque sprite 0/sprite 1 collision |
| Target access | High-byte VRAM read or two-byte TAI |
| Guest IRQ policy | Acknowledge VDC and retain CD IRQ delivery, or also mask CD delivery |
| CPU clock divisor | 3 or 12 |
| VCE divider | 2, 3 or 4 |

The Cartesian product contains 48 recipes. The program starts through an
authored reset vector, maps real device ports, writes VRAM, loads sprite data
through SATB DMA, issues a real CD READ command and polls DATA IN before
enabling ADPCM DMA. There is no firmware image, retail input, synthetic data
phase or injected IRQ flag. The sector provider supplies one authored sector.
The READ provider callback belongs to setup before the target, not the wait.

While I is set, the guest polls the interrupt-status port without acknowledging
VDC status. It then uses ordinary WRAM block transfers where needed to place
the prefetch in the declared active window, arms ADPCM DMA, clears I and
executes the target. The target must begin with a pending VRAM read, live IRQ1,
active vertical display, background enabled in the latched control, non-burst
mode and the selected MWR profile. It must incur a positive queued wait and
retire into IRQ1 first. Timing is not aligned by assigning device phases or
altering observed timestamps.

The fixture uses display widths 256/384/576 for VCE dividers 4/3/2. Their
source-derived background-load end clocks are 1,216/1,320/1,248, allowing the
sprite-fetch event before physical line end. Raster recipes add two declared
WRAM TII delays; collision recipes rely on their source event at display
start. The fixture tests retain this geometry and instruction plan. Earlier
oversized-display, unmasked BUSY-marker and zero-stall design pilots remain
private failed inputs; they do not establish runtime defects.

Three VRAM words contain `DEAD`, `A65C`, `5AA5`. The first prefetch and target
therefore cannot accidentally agree on stale data. The target must return
`A6` or the TAI bytes `5C A6`; the final read buffer must contain `5AA5`, with
MARR at the declared third-prefetch successor. CPU/stack, full work RAM, VRAM
and ADPCM RAM have literal expectations derived from the authored program.
Input hits in the generated module remain source-generation metadata, not
executed native work.

The handler disables its selected VDC source while preserving display, then
reads VDC status. It masks BUSY from its stored source marker while retaining
the raw status-load observation. Acknowledgement must clear IRQ1 and preserve
the ADPCM HALF/END cause. RTI restores the original registers and status.
With CD delivery retained, IRQ2 follows at the next normal sample; with CD
masked, its cause remains set without a second delivery. A controller mask
does not substitute for device acknowledgement.

## What the event records establish

The original Gear adapter retains actual CPU calls, block continuations,
hardware callback spans, source callbacks and named before/after device
states. Dynamic wait callbacks are actual three-master-tick slices. The
qualifier selects the first dynamic pending-read-to-grant edge; a high-byte
read may queue another prefetch whose later grant belongs to an ordinary
epilogue/IRQ callback.

IRQ1 is already pending before target entry in these recipes. The independently
audited original trace distinguishes three actual ADPCM source locations:

| Recipes | Target groups across three cuts | First HALF/END assertion |
|---|---|---|
| 12 fast scalar-read recipes | 36 | Three-tick dynamic-wait callback |
| 12 fast TAI recipes | 36 | Ordinary 42-tick startup callback, incomplete call 1 |
| 24 slow recipes | 72 | 60-tick DMA-arming store before the target |

Both source callbacks and first rising kernel flags join the same actual span
and timestamp. In every group they precede the first dynamic read grant;
requests and sampled causes include both IRQs at that grant. TAI delivers IRQ1
only at completed call 4. The startup callback is not a wait callback and does
not establish an electrical edge within its 42-tick interval. The public
qualifier's `adpcm_asserts_in_target` field deliberately makes the narrower
instruction-group claim; a separate raw-ledger audit establishes this table.

The toolkit records target-entry phase, positive aggregate waits, actual
retirement/source identities and post-instruction state. It does not expose
the same per-device callback stream. Its aggregate observations cannot prove
an exact ADPCM-before-first-grant timestamp. Raw cross-core phase, polling,
counter-role and callback differences remain in the report; they are not
normalized into equality. Functional expectations, exact-build continuation
and original callback evidence are separate checks.

## Three natural checkpoints

1. Before the guest store that starts ADPCM DMA: I is set, IRQ1 is already
   live and the VRAM prefetch is pending. Restoring this cut does not execute
   the imported IRQ1 assertion again.
2. Immediately after completed IRQ1 entry, before its first handler opcode:
   the descending interrupt frame and both device causes remain live.
3. After guest VDC acknowledgement and optional CD masking, before PLA/RTI:
   IRQ1 is cleared while ADPCM HALF/END remains pending.

Each toolkit tier creates a checkpoint and continues, then a fresh process
restores the exact checkpoint and runs the same suffix. Actual captures join
logical PC, every MPR byte, physical fetched locations and instruction bytes.
Imported counters and new suffix retirements remain separate. The actual
checkpoint-file hash is checked; continuation compares full memory records
and the hash of the complete canonical encoded endpoint state. The probe
does not emit endpoint checkpoint files, so this is not a final-file byte
comparison claim. No checkpoint is created inside a guest instruction or
imported into Gear or another module.

The reference probe's `.pcec` files hold raw core-codec bytes. They are not
the desktop host's fingerprint/context wrapper merely because the suffix
matches. The collector separately binds the probe, module, source and media
identities. The private retail TCP check uses its original host wrapper and
context; those two checkpoint contracts are not interchangeable.

## Reproduce and inspect

`scripts/active_irq_reference.py` builds the original pinned source and a
separate toolkit probe, runs the selected recipes/cuts and retains raw
stdout/stderr, command returns, fixtures, captures and checkpoints. It needs
an explicit existing source checkout, compiler and static dependency libraries;
it does not install or download them. See `--help` for arguments. Private
outputs must be new directories under `.local/`.

The reference build has 40 compilation jobs: 39 original/dependency objects
and one authored observer. Counting every job as an original-emulator source
compilation would overstate that work. Raw original sources, normalized compile
copies, Git blobs, object files and the observer source retain distinct bindings.

`--case` and `--cut` select diagnostic subsets. Their receipts remain partial
and cannot claim the complete matrix. The standalone
`scripts/active_irq_qualify.py` rehashes retained bindings and re-admits the
source, phase, work and continuation records without executing a guest.
The normal checker also includes a six-recipe/two-tier checkpoint smoke with
24 actual child processes; it is separate from the full original-engine grid.

## Frozen full-matrix result

Code `a07fba09359103f237a8dbf600842b9bba351617` passes **48 recipes, 144
recipe/cut cases, 720 fresh guest processes and 288 fresh restores**. The run
rebuilds every reference and toolkit object. Its 40 reference compilation jobs
have the split described above; all 130 original Git blobs and 3,399 artifact
bindings rehash. Frozen standalone admission passes and refuses 11 written
altered receipts. Diagnostic subsets are separate earlier pilot epochs.

The native tier executes **37,412,496 instructions with zero fallback**; a
separate interpreted tier executes **37,412,496 instructions**. Creating
prefixes and both new suffix runs are counted as actual work; imported prefix
counters in restoring processes are not counted again. Of 2,800 emitted and
compiled identities, 2,792 actually execute. Compilation is not retirement.

The eight unretired identities are the authored terminal BRA self-loops,
joined by logical PC, all eight MPRs and exact fetched bytes; they are not
missing interpreter fallback sites.

Original Gear retires **36,955,404 instructions through 46,717,884 CPU calls**,
including **9,762,480 additional continuation calls**. It invokes 46,818,564
hardware callbacks. These are different counter domains. Full work-RAM hash,
VRAM and ADPCM RAM expectations accompany source and CPU/stack checks.
The ledger retains **2,437 raw differences across all 144 cases**, including
clock/phase, polling and counter-role differences. Passing this selected
functional and continuation matrix does not diagnose every raw difference or
establish complete timing agreement.

Runtime/compiler inputs remain 79 files, SHA256
`d17bdc9159b53b00144a388ebe45a6f7e5e7c5767b7de1989df0e50db24e213c`;
the new diagnostic sources have separate exact bindings. No production
semantic patch was justified by these tests.

The executed original reference remains
[`1c62a549328241518101f5be5bf3e6840b96ea5d`](https://github.com/drhelius/Geargrafx/tree/1c62a549328241518101f5be5bf3e6840b96ea5d).
Ten selected VDC bodies also match the reviewed upstream
[`16417e983c5b47ab8358ee91f75c155f208391a7`](https://github.com/drhelius/Geargrafx/tree/16417e983c5b47ab8358ee91f75c155f208391a7)
byte for byte, including raster/collision IRQ generation, line events, sprite
fetch/render and queued-access arbitration. Whole files differ elsewhere.
This source review does not execute the newer head or qualify its complete
call graph. No device implementation is copied into the toolkit.

These selected active-display profiles do not qualify arbitrary geometry,
sprite overflow, every IRQ source combination, electrical/sub-three-tick
timing, hardware consensus or complete game compatibility.
