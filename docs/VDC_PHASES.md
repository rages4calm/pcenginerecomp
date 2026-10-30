# Explaining queued VRAM wait phases

## Periodic horizontal-sync coverage

The new `blank-periodic-hsw-read-v1` profile predicts queued reads through
horizontal-sync blocking. Use
`scripts.vdc_phase.predict_periodic_hsw_dma_read_wait`; the earlier
`predict_blank_dma_read_wait` and its `blank-even-no-hsw-v1` contract remain
unchanged as a separate reference. Neither function changes the guest runtime.

This is a source-backed blank-display profile with latched HSR/HDR
`7F1F/7F7F`. Each 1,365-tick line forces HSW state 3 for 32 VCE dots at divider
3, or 24 dots at dividers 2/4, followed by HDS state 0 for 1,024 dots. HSYNC
starts at horizontal clock zero. Arbitrary geometry, active rendering, queued
writes and SATB interference remain unsupported.

The observing adapter supplies actual launch and target Hstate, remaining-dot
countdown, HSYNC anchor and latched horizontal values. The probes read the four
latched horizontal lengths independently of the live HSR/HDR registers and
retain both. A live register value alone does not prove a latch has updated.
The function checks those inputs against the declared schedule before making
any prediction. Observed waits or grant times are never model inputs.

At each three-tick candidate, the model uses the **pre-callback Hstate**.
While that state is HSW, it blocks if the position three master ticks ahead,
wrapped at 1,365, is less than eight VCE dots since HSYNC start. Equality opens
the guard. Even-dot arbitration remains a separate condition. The elapsed
quantity is three master ticks at either CPU speed, rather than the low-speed
CPU divisor of twelve.

Consequently, the former VCE3 exclusions are now predicted without asserting
that HSW is absent: the read remains queued through clocks 9, 12, 15, 18 and
21, then grants at 24. HSW blocks through 18; odd-dot parity holds at 21.
The scanline tail is another distinct boundary: pre-callback HDS at clock
1,362 can grant even when the callback's end wraps into a new line's HSW.
Using the future Hstate would incorrectly block that access.

The extended authored matrix preserves the 48 earlier recipes and adds 24
source-designed edges: both CPU speeds, all three VCE divisors, scalar high
and TAI2, and sync-start versus scanline-tail families. The extra guest TII
self-copy delay is chosen from declared opcode cycle arithmetic and the
1,365-tick period before observing a wait. Its length and ROM/source hashes
are preserved before execution. Native CSH's genuine 18-tick origin difference
is retained. No state is injected or guest padding changed to fit a result.

Independent literal tests cover all VCE thresholds, parity, equality, line
wrap, queue delay, CPU prefixes, carry and invalid geometry/types/overflow.
Guest runs expose zero queue carry; carry values one and two belong to pure
arithmetic tests and are not presented as executed guest cases. These checks
describe the selected toolkit/Gear software profile, not hardware bus accuracy.

Frozen implementation `d62fbe33190ff22d7c7334c8756d84a1709a1436` passes all
72 recipes across native, interpreted and original Gear processes: **216 exact
periodic-HSW predictions**. The native and separate interpreter tiers each
retire 7,932 instructions, 636 blocks and 1,763,112 copied bytes. Original Gear
retires 7,932 instructions through 1,771,680 actual calls; its 1,763,748 extra
continuations are not guest instructions. Of 372 compiled identities, 362
execute; ten terminal BRA variants stay compiled but unretired.

Actual original candidate callbacks independently join the predicted first
grant and each Hstate, remaining count, HSYNC anchor and latched value. The 72
original ledgers contain 226 joined candidates: 88 HSW-blocked, 66 parity-only
holds and 72 grants. Eight grants use pre-HDS state while the future clock
wraps. Native/interpreted internal candidates are predictions checked against
entry/exit facts and total waits; no native callback observer was added.

The preserved legacy profile still admits 166 observations and explicitly
refuses 50 HSW encounters. Its function body and existing API remain the
reference path. Forty fresh original compilation processes and 1,134 artifact
bindings retain complete raw/compiled source sets, tools, objects, captures,
commands and outputs. Standalone qualification refuses ten altered receipts;
a separate actual missing-raw-source control is also refused. All 24 edge
designs remain byte-identical to their pre-execution ROM/source-plan receipt.

The conservation audit compares all 144 new baseline reports with the preceding
48-recipe run, removing only appended phase values after index 34 and callback
values after index 11. All other clock, source, CPU and memory fields remain
compared. The 48 ROM pairs and 96 capture pairs are byte-identical, and the
legacy function/helpers/constants remain source-identical. The audit rehashes
1,518 bindings without launching another guest or compiling another object.

The selected −6/+3-master-tick differences in the
[VDC/ADPCM overlap matrix](VDC_ADPCM_IRQ.md) come from different entry phases.
They do not demonstrate a new VRAM stall defect. The runtime, emitter, ABI 26
and checkpoint schema 1 remain unchanged.

## The causal chain

The retained fast-CPU source ledgers are identical. Their 18-tick origin
difference comes from the documented [CSH transition rule](CPU_SEMANTICS.md#cslcsh-and-speed-transitions):
the toolkit charges two cycles at the old divisor and one at the new divisor,
27 ticks for low-to-high; pinned Gear charges all three at the selected divisor,
nine ticks. No clock offset is applied to erase that distinction.

The slow-CPU ledgers differ by five CD command-request polling iterations.
Each actual LDA/AND/CMP/taken-BNE quartet costs 13 CPU cycles at divisor 12:
five iterations account for the complete 780-tick entry difference. Logical
PC, all eight MPRs, physical addresses and fetched bytes identify the differing
sites. These are actual executed counts, not an inference from final clocks.

Those different raster origins put the queued read on different dot and
three-tick callback phases. Independent integer arithmetic predicts all 144
retained native/original wait observations, including the 24 recipe/cut pairs
with −6/+3 differences. This is new analysis of retained execution, not 144 new
guest runs. Old entry horizontal positions are source-backed clock projections;
additional private observer runs check those projections separately.

## A deliberately narrow diagnostic

`scripts.vdc_phase.predict_blank_dma_read_wait` is a pure function. It consumes
observed facts and predicts a wait; it does not execute a guest, set a device
phase, authenticate a source capture or implement the runtime's scheduler.
Its explicit profile is `blank-even-no-hsw-v1`.

| Facts | Required scope |
|---|---|
| Clock | Actual launch and target ticks/horizontal positions; CPU divisor 3 or 12, VCE divisor 2, 3 or 4 |
| DMA | One observed LENR-high launch, 1–65,536 words, matching remaining-dot count; constant VCE speed |
| Queue | One pending VRR read, selected register 2, no queued write or SATB interference; bounded transfer delay and carry 0–2 |
| Display | Explicit blank/burst and no-sprite facts; `hsw_excluded=True` proved for the relevant candidate interval |
| Source | The observing adapter separately binds logical PC, every MPR, physical/fetched bytes and execution tier |

Blank display alone does not prove that the horizontal-sync guard is absent.
The caller must establish that predicate from actual source, geometry and
callback state. Active display, writes, SATB interference, invalid types,
inconsistent phase/countdown facts, unsupported profiles and clock overflow
are refused. A queue that clears during the instruction's fixed prefix has
zero dynamic wait; the function does not assume that every access stalls.

Each line is 1,365 master ticks. At VCE divisor `d`, it contains
`floor(1365/d)` complete dots. The leftover tick at divisors 2/4 contributes no
dot; flattening elapsed ticks by `d` loses this line phase. The model inverts
the final DMA-dot ordinal, applies queue delay, then searches the three-tick
callback lattice for an even-dot grant. Eligibility is tested before that
callback advances the raster. Scalar high reads have a one-CPU-cycle prefix;
TAI2 has fourteen startup cycles plus two mapped-read cycles. A complete
horizontal lattice period bounds the search to 455 candidates.

The predicted final-dot time and the logger's device callback timestamp are
different observations: a callback may cover the final dot and report its end.
Original first-grant callback starts are compared separately. Native wait
totals do not provide independently recorded native device-edge timestamps.

## Fresh base-HuCard controls

This section records the retained no-HSW baseline. The newer periodic profile
above predicts its former HSW exclusions while preserving this older contract.

The separate authored suite boots a base HuCard with no CD hardware. Guest
instructions configure the mapping, speed, video registers, VRAM and DMA.
Its 48 recipes vary both CPU speeds, all three VCE divisors, scalar high/TAI2,
127/4,096-word DMA and no padding versus an actual PHA. An odd three-cycle PHA
changes a phase that a two-cycle NOP cannot change in the slow-CPU/VCE4 case.
No phase is injected and no padding is selected after looking for agreement.

All 48 recipes execute in native, interpreted and original-Gear processes.
The narrow model admits 46 recipes, or 138 process observations. Two natural
slow-CPU/VCE3/127-word/PHA cases encounter real horizontal-sync gating and are
explicit off-profile controls, not successful model predictions.

For those two cases, the original read remains queued at horizontal clocks
9, 12, 15, 18 and 21, then grants at 24. The elapsed-three guard blocks through
18; at 21 the guard has opened, but odd-dot parity still blocks access. These
two reasons are checked separately. Changing guest inputs or asserting a false
`hsw_excluded` premise would invalidate the diagnosis.

Frozen implementation `266ffccef675fcba98328fbd91b82447381df1ea` passes all 144
fresh guest processes. The native and separate interpreter tiers each retire
5,280 instructions and 408 block transfers covering 1,171,248 bytes, with zero
native fallback. Gear also retires 5,280 instructions, through 1,176,936 actual
CPU calls; its 1,171,656 extra continuation calls are not opcodes. Of 282
compiled identities, 276 execute; six terminal BRA variants remain unretired.

The strict audit rehashes 918 artifact bindings and all 130 original source
blobs, with 40 fresh reference-build compilation processes. Standalone qualification
refuses ten written altered receipts; a separate missing-raw-VDC-source control
is also refused. Twenty authored model/reference tests cover literal arithmetic,
source/work joins, actual HSW/parity spans and raw-CRLF/compiled-LF preservation.
The latter keeps exact raw SHA256 while checking its normalized Git blob.

Raw wait deltas across the 48 recipes are 34 zero, two +3, four +6 and eight
−3 ticks. The 24 slow-CPU launch origins match; all 24 fast origins differ by
the existing 18 ticks. Changing the guest phase changes the sign and magnitude
of the wait difference; a constant correction would not describe these results.
Full memory and logical CPU values agree while raw clocks remain preserved.

The retained-overlap re-audit is separate: 144 old waits, 72 original grant
starts and 24 full-source origin proofs re-admit with the frozen helper.
Forty-eight additional observer processes expose 1,128 selected phase rows;
removing only their appended read-only phase observations reproduces the old
case records exactly. Their source/tool/object/output bindings remain separate
from the fresh 144 HuCard processes and from the original retained executions.

To run the optional original-core comparison, provide the pinned Gear checkout,
C++20 compiler, CMake, Ninja and compatible existing libchdr, LZMA, miniz and
Zstandard archives. From this toolkit checkout, choose a new private directory:

```text
python scripts/vdc_phase_reference.py --gear-source GEAR_CHECKOUT --out .local/vdc-phase-proof --compiler CLANGXX --cmake CMAKE --ninja NINJA --library LIBCHDR_ARCHIVE --library LZMA_ARCHIVE --library MINIZ_ARCHIVE --library ZSTD_ARCHIVE
python scripts/vdc_phase_qualify.py .local/vdc-phase-proof/result.json --negative-controls
```

Qualification re-emits the authored fixture/module and checks source, tools,
objects, commands, actual outputs and semantic joins without executing a guest.
The negative controls require new output names; omit that flag on later
read-only re-audits. Normal authored tests remain in `scripts/check.py`.

## Reference and hardware limits

Executed Gear remains pinned to
[`1c62a549328241518101f5be5bf3e6840b96ea5d`](https://github.com/drhelius/Geargrafx/tree/1c62a549328241518101f5be5bf3e6840b96ea5d).
Reviewed upstream head `16417e983c5b47ab8358ee91f75c155f208391a7` remains the
separately documented source review, not a new upstream-core execution.

Independent Mesen source also changes speed before the final idle cycle.
Its VDC implementation explicitly treats queue alignment and three-tick stall
granularity as approximate. This corroborates the need to keep software-model
agreement separate from hardware qualification; Mesen was source-inspected,
not executed in this suite. See the pinned
[CPU instructions](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp)
and [VDC source](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceVdc.cpp).
No incompatible implementation is copied into the toolkit runtime.

Active-display arbitration, arbitrary horizontal geometry, sub-three-tick
hardware bus phases and whole-game compatibility remain separate work.
