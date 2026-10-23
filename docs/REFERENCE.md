# Independent reference check

The optional `scripts/reference_geargrafx.py` harness controls a separately
developed **Geargrafx** emulator through its actual HTTP MCP tools. It starts
and terminates its own headless portable process on a dedicated loopback
port. It does not attach to an owner's emulator session or change an AI
client's plugin configuration.

## What was checked

On Windows x64, Geargrafx **1.8.4** produced the following separate results.
The speed batch agrees on CPU state/speed but has documented timing differences.
The retained CD batch checks the limited idle profile described in CD_CONTROL.md.
The retained VDC port suite checks settled register/VRAM state; it does not
compare raster events or dynamic access timing. The separate raster suite
checks the clocked video profile. The CD transport suite separately checks
settled selection, command reception and status/message completion. The TOC
suite adds actual metadata response bytes and bounded DATA IN handshakes.
The joypad suites compare CPU accesses and guest-observed controller bytes
under held input snapshots, separately with and without CD hardware.

| Run | Opcodes | Comparisons per tier | Scope |
|---|---|---|---|
| Original baseline, retained prior evidence | 47 | 188 native and 188 interpreter | Four register/flag variants each, including both conditional-branch outcomes |
| Bit/stack batch, retained prior evidence (`--suite bit-stack`) | 24 | 128 native and 128 interpreter | Four base variants each, plus four extra directed variants for each of eight stack opcodes |
| Data batch, retained prior evidence (`--suite data`, four completed shards) | 97 | 1,552 native and 1,552 interpreter | 16 vectors per encoding; all C/D/T/V combinations, indexed/indirect data addressing and full-RAM comparison |
| RMW/JMP batch, retained prior evidence (`--suite rmw-jump`, two completed shards) | 32 | 512 native and 512 interpreter | 16 vectors per opcode; edge values with both carries, T/D/V contexts, indexed memory and consecutive jump pointer bytes |
| Bit-test/branch/BSR batch, retained prior evidence (`--suite bit-test-bsr`, two completed shards) | 30 | 480 native and 480 interpreter | 16 vectors per opcode; zero/full/mixed bits, flag contexts, zero-page/indexed targets and stack wrap |
| MPR sequence batch, retained prior evidence (`--suite mpr`, four completed shards) | TAM/TMA | 1,614 instruction states and 524 final RAM/latch comparisons per route | 524 sequences; native-first: 1,078 native + 536 interpreted after MPR changes; pure interpreter: 1,614 interpreted |
| Speed batch, retained prior evidence (`--suite speed`) | CSL/CSH, NOP and TMA #0 | 120 CPU/speed states and 24 final RAM/latch comparisons per tier agreed | Not rerun this batch; 92 matching tick deltas and 28 documented transition differences per tier |
| Idle CD-control/BRAM batch, retained prior evidence (`--suite cd-control`, two completed shards) | Existing CPU loads/stores/indexed/RMW and TMA #0 | 720 CPU/device states and 48 complete work-RAM/BRAM comparisons per tier pass | 48 sequences; 720 native instructions vs 720 interpreted; real CD hardware enabled with authored bootstrap/disc; no retail inputs |
| Clocked CD command-handshake batch, retained evidence (`--suite scsi`) | CPU port accesses and settling NOPs | 743 settled CPU/device checkpoints and 21 full work-RAM/BRAM comparisons per tier pass | 21 authored plans; 1,007,851 native instructions vs 1,007,851 interpreted; original frozen probe observations bridged exactly to that batch's final build, three added edge plans checked live; no media responses or exact access-phase proof |
| TOC/DATA IN batch, qualified scope (`--suite toc`) | CPU port accesses and settling NOPs | 1,964 settled CPU/device checkpoints and 25 full work-RAM/BRAM comparisons per tier | 25 of 26 plans qualified; 653,294 native vs 653,294 interpreted instructions; eight earlier TOC plans bridge exactly to the final probe; one pending-response reset plan crashes Geargrafx and remains unqualified |
| Joypad batch (`--suite joypad` and `--suite joypad-cd`, eight completed shards each) | Port loads/stores and RMW | 2,512 CPU/port-output checkpoints and 56 complete 8 KiB work-RAM comparisons per tier pass | 56 authored plans: 28 HuCard and 28 authored-CD; 2,512 native vs 2,512 interpreted instructions; USA region line, both CD-presence states; no internal controller-state, host event scheduling, hardware or gameplay qualification |
| Settled VDC batch, retained prior evidence (`--suite vdc`, eight completed shards) | ST0/ST1/ST2, ordinary port loads/stores and settling NOPs | 856 settled CPU/VDC states and 48 complete work-RAM/VRAM comparisons per tier pass | 48 authored sequences; 14,552 native instructions vs 14,552 interpreted, including 16 settling NOPs per tested operation; standard non-CD, non-SuperGrafx HuCard profile |
| Clocked raster batch, retained evidence (`scripts/raster_reference.py`, fifteen completed shards) | Direct device-clock probe | 4,165 exact-clock checkpoints and 15 guest acknowledgements total | 15 authored timing plans; default VCE divider 4 and 262 lines; no per-tier live CPU or bus-phase claim |

Each single-step comparison checks A/X/Y/SP/P, logical PC, all eight MPRs and all 8 KiB
of work RAM after one instruction. No flags are masked out. The new vectors
explicitly cover both states of every selected bit, SP `$00/$01/$FE/$FF`,
zero/positive/negative pulled values, and every saved B/T combination for PLP.
An initial PLP mismatch exposed MAME's different internal B representation;
the runtime now follows Geargrafx/Mesen's B=0 restoration, with T preserved.
See the [instruction contract](CPU_SEMANTICS.md).

The data input matrix has 16 vectors per opcode, covering every C/D/T/V
combination with zero, sign, valid BCD and invalid-nibble inputs. It sets
zero-page operands to `$FF`, absolute bases to `$22FF`, and indirect pointers
to `$22FF`, exercising zero-page pointer wrapping and indexed page crossings.
T destination/source and pointer-high-byte aliases remain visible in the
full-RAM comparison. Immediate bytes remain the compiled `$20`; variable
operand values are exercised through memory forms. The exhaustive byte-pair
tests described in CPU_SEMANTICS are local expected-value tests, not an
exhaustive run against Geargrafx.

The RMW/JMP input matrix pairs each of `$00/$01/$02/$7F/$80/$81/$FE/$FF`
with both incoming carry states. It varies T/D/V and uses X values
`$00/$01/$E0/$FF`. All 30 RMW encodings and both indirect JMP forms are
selected. Jump pointer bytes are consecutive across `$22FF/$2300`, with
multiple targets including `$FFFF`; the test ends after JMP and does not
execute its destination. Full-address-space wrap and cross-MPR cases use
additional local native fixtures; they are not live Geargrafx evidence.

This uses self-authored synthetic HuCard/bootstrap code and synthetic RAM
patterns. Initial emulator registers/MPRs are randomized, so the harness
first establishes and verifies its mapping/speed, then sets registers
explicitly for every case. It restores mapping after TAM. It compares both
the native tier and the interpreter directly with the reference.

**Not checked by the earlier suites:** cycle/bus phases, IRQ entry/delivery, speed-change timing,
block transfer, unsupported opcode semantics, devices, CD, sound, rendering
or any game. This is independent single-step evidence, not whole-system
conformance or proof the reference emulator is infallible.

## Reproduce

Build the optional probe from the entirely synthetic fixture generator:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DPCE_BUILD_REFERENCE_PROBE=ON
cmake --build build --config Release --parallel 4
```

Obtain a portable Geargrafx release from its [official releases](https://github.com/drhelius/Geargrafx/releases).
Use a dedicated copy under `.deps/geargrafx-oracle/`, including its required
runtime files. The harness refuses an executable outside this project's
`.deps/` directory. It creates `portable.ini` and writes no retail saves.
No emulator or binary is included or downloaded by the harness.

The baseline Windows artifact was:

| Identity | Value |
|---|---|
| Archive | `Geargrafx-1.8.4-desktop-windows-x64.zip` |
| Release | `1.8.4`, published 15 October 2026 |
| Archive SHA256 | `c1aceb116acf1949ab2319c217f3c0c9e9fcf836f8857176b670a749d8a2347c` |
| Executable SHA256 | `742b2d8d21060368134324e1ce6c32a9751e7a9776549ed78448eca93e6e8563` |

The archive digest matched GitHub's release-asset `digest` field before use.
The research register retains both the original main-branch pin and the
separate 1.8.4 source pin `1c62a549328241518101f5be5bf3e6840b96ea5d`,
used for the bit/stack and data semantics. This does not assert a reproducible
source-to-binary build of the supplied release executable.

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-oracle-probe.exe
```

That default selects the full current opcode set (2,848 single-step cases per tier).
The expanded default matrix has not been rerun live in this batch. It does not
include the directed MPR, speed, CD-control, CD-transport, TOC or VDC sequence suites below.
Large runs can exceed the 180-second cap; partition them with
`--shard-count 8 --shard-index N` for each N from 0 through 7, using a distinct
output folder for each. Every shard records the exact checked opcode list;
all shards must pass to claim the complete selected suite.

To reproduce the data batch, run four commands sequentially, substituting
N with each value from 0 through 3:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-oracle-probe.exe --suite data --shard-count 4 --shard-index N --out .local/data-check/four-N
```

Their disjoint opcode lists must cover all 97 data encodings and their totals
must sum to 1,552 comparisons per tier. Each run remains incomplete until
its entire shard passes. All four lists and comparison totals were checked
at closeout; they cover every selected encoding exactly once.
To select only bit/stack, use `--suite bit-stack --out .local/bit-stack-check`.
The full expanded all-opcode matrix has not been run in this batch; retained
checks remain separately identified above.

For the RMW/JMP batch append `--suite rmw-jump --shard-count 2 --shard-index N`
and `--out .local/rmw-jump-check/shard-N`, with N=0 and N=1 in separate
sequential runs. Their opcode lists must be disjoint, cover all
32 selected encodings and total 512 comparisons per tier. Each vector is
checked independently against both execution tiers. The exhaustive RMW
byte/status sweep is a local expected-value test, not an exhaustive oracle run.
Both completed reports and their combined opcode coverage/totals were verified.

For the bit-test batch use `--suite bit-test-bsr --shard-count 2 --shard-index N`
and `--out .local/bit-test-check/shard-N`, with N=0 and N=1 sequentially.
The disjoint reports cover all 30 selected opcodes, totaling 480 comparisons
per tier. Memory cases use `$FF` / `$22FF`, TST's compiled mask is `$55`,
BIT's compiled immediate is `$20`, and relative fixtures branch to themselves
when taken. BBR/BBS exercise both selected-bit states, and BSR varies SP
through `$00/$01/$FE/$FF`. Other displacement/fetch-wrap checks are local
expected-value tests; this is not exhaustive oracle testing of literals.

### MPR and transfer-latch sequences

The dedicated suite checks every TMA/TAM mask, zero-mask preservation,
ordinary memory traffic between transfers, same-value TAM writes, and
multi-register OR under a second mapping. Every sequence ends with TMA #0,
observing the reference latch through A; Geargrafx's MCP API does not expose
that latch directly. Mapping and latch resets execute actual LDA/TAM
instructions from RAM, rather than assuming debugger register writes reset
hidden CPU state. MPR1 stays mapped to work RAM so fetches remain valid.

Run four commands sequentially, substituting N with 0 through 3:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-oracle-probe.exe --suite mpr --shard-count 4 --shard-index N --out .local/mpr-check/shard-N
```

The disjoint reports must cover 524 sequence IDs and total 1,614 instruction
states per tier, plus 524 complete RAM/latch comparisons per tier. The
`native` route here is **native-first**: a changed MPR context makes its next
generated guard yield, with counted interpreter fallback. This differs from
the single-step suites' entirely native comparisons. Each sequence starts
with a native operation; same-mapping sequences remain native. Reports
include actual native/interpreter/guard counts, the probe hash and the exact
checked sequence IDs. The local expected-value suite separately executes
every mask directly in generated code under its compiled mapping.

These sequence checks do not add live cycle, speed-change or device evidence.
All four completed reports were checked for disjoint sequence IDs and complete
coverage. Native-first totals were 1,078 native instructions, 536 interpreted
instructions and 536 guard misses. The pure interpreter retired 1,614
instructions. Both routes matched every recorded instruction state and all
524 final RAM images/latch observations. Earlier single-step results were
retained and were not rerun in this batch.

### Speed transitions and the timing discrepancy

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-oracle-probe.exe --suite speed --out .local/speed-check/reference
```

This bounded suite has 24 authored sequences: both entry speeds, both speed
opcodes, four status contexts and repeated/mixed selections with following
NOPs and TMA #0. Actual LDA/TAM instructions reset mapping and latch; an
actual speed instruction establishes entry speed before registers are set.
Every measured instruction remains in work RAM under the compiled mapping.
There is no interpreter fallback in the native route.

CPU-entry timestamps come from Geargrafx's in-memory `cpu.instructions`
trace. A sentinel NOP supplies the end timestamp for the last measured
instruction. The adapter requests the current tail explicitly: the API's
`next_sequence` is a page cursor, not automatically the logger's latest
position. It rejects missing entries, stale/wrong bank/PC, non-monotonic
timestamps and overruns. Only the current bounded sequence is fetched;
full traces and retail captures are not written to the repository.

Both tiers matched **120 CPU/speed states and 24 final RAM/latch observations**.
The live trace matched 92 instruction tick deltas per tier. In the remaining
28 cases per tier, the CPU changed speed and Geargrafx charged all three
cycles at the selected speed. The runtime instead uses two entry-speed cycles
plus one selected-speed cycle, agreeing with the pinned Mesen and Beetle
source implementations. High→low CSL is 18 ticks here versus Geargrafx's 36;
low→high CSH is 27 here versus Geargrafx's 9. Same-speed selections agree.
See [CPU_SEMANTICS.md](CPU_SEMANTICS.md#cslcsh-and-speed-transitions) for sources.

The report result is **`architectural_pass_timing_discrepancy`**, with every
observed difference retained as compact metadata. Unexpected state or tick
results fail the run; the adapter does not broadly ignore timing. A known
transition difference is not presented as reference timing parity. Mesen and
Beetle were source cross-checks, not live executions in this batch. This
focused CPU timestamp schema does not complete issue #4's general bus/event
trace schema, second oracle or hardware verification.

### Idle CD control and BRAM

Build the normal test targets, then run N=0 and N=1 sequentially:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-io-tests.exe --suite cd-control --shard-count 2 --shard-index N --out .local/io-check/shard-N
```

This suite uses **`pce-io-tests`**, whose generated module has fixed hardware/
BRAM MPR aliases. It differs from the ordinary opcode probe. The harness
creates a shared authored 256 KiB reset bootstrap and a 300-sector blank
CUE/BIN under its private output parent. Geargrafx accepts that bootstrap as
an unknown-CRC System Card; the warning is expected. No known firmware CRC
is forged and no retail firmware is supplied. Media status must prove CD
hardware is enabled: HuCard-only tests could otherwise compare disabled
hardware that ignores writes. The child remains an isolated portable process,
and any synthetic BRAM files belong to that authored test media.

Each case establishes mapping/latch through actual CPU transfers, resets the
idle CD control state through CPU writes, and seeds exactly 2 KiB synthetic
BRAM plus 8 KiB work RAM. Every measured instruction compares unmasked CPU
registers/PC/MPRs and independently exposed device state: BRAM gate, ACK,
IRQ-enable/active fields, reset and IRQ2 line. The full work RAM and BRAM
contents are compared at the end. Plans cover zero/full/mixed control values,
both lock states, ignored/read-only writes, logical aliases, all BRAM boundary
classes, indexed hole crossings and TSB/TRB read-to-lock side effects.
Each sequence ends with TMA #0 so ordinary I/O cannot silently alter its latch.

The completed disjoint lists cover 48 sequences exactly once and total **720
instruction-state comparisons plus 48 full memory comparisons per tier**.
The native route retired 720 native instructions with no interpreter fallback;
the interpreter route retired 720 interpreted instructions. The local C++
suite separately checks 61,440 expected instruction cases and fatal refusal
of unsupported subcode/register accesses. Those exhaustive local byte sweeps
are not exhaustive Geargrafx runs.

This is byte/state evidence for an idle profile. Nonzero IRQ source
combinations are local/source-level checks, not live device events. It does
not verify transport, subcode, audio, IRQ delivery, device/bus timing, hardware
or gameplay. Reference disagreements and deliberately unsupported `$1807`
reads are documented in [CD_CONTROL.md](CD_CONTROL.md). Earlier emulator
checks retain their original scope and were not rerun in this batch.

### Settled VDC register and VRAM sequences

Build the normal test targets, then run N=0 through N=7 sequentially with a
separate output directory for each shard:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-vdc-tests.exe --suite vdc --shard-count 8 --shard-index N --out .local/vdc-check/shard-N
```

This suite uses **`pce-vdc-tests`** and an authored 8 KiB bootstrap. Every
run verifies that Geargrafx loaded a standard HuCard mapper with CD hardware
and SuperGrafx disabled. It establishes mapping through actual CPU transfers,
initializes the exposed VDC register state and primes the hidden read buffer
through an actual MARR high-byte write before seeding synthetic VRAM. Display,
interrupt sources and automatic DMA remain disabled in the reference profile.
No retail firmware, disc or owner save is used.

The adapter executes each target operation followed by **16 settling NOPs**.
It then compares unmasked CPU registers, PC and all eight MPRs, the VDC
selector and all twenty register values. A full 8 KiB work-RAM image and
64 KiB VRAM image are compared at each sequence's end. The directed plans
cover all 32 selectors, byte writes and masks with DMA triggers excluded,
mirrored ports and MPR aliases, all four address increments, MAWR boundaries
and ignored upper-half writes, buffered VRAM read/write streams and dedicated
ST0/ST1/ST2 routing. CR interrupt/display bits and DCR automatic-transfer
bits stay constrained; upper-half reads requiring the rendering-bus latch
are explicit local faults rather than live reference cases.

All eight completed shard lists cover **48 unique sequences** exactly once.
They pass **856 settled instruction/device observations and 48 full RAM/VRAM
comparisons per tier**, using the same emulator and probe hashes. The native
route retires **14,552 native and zero interpreted instructions**; the pure
interpreter route retires **14,552 interpreted instructions**. Each route
contains 856 tested operations and 13,696 settling NOPs. The probe's SHA256
is `80ffe5c39ac6414d4ab753afc2cc89dc8d6246d35ab9fb9ba53374669b344b30`.

These are settled functional comparisons. They do not compare busy intervals,
status event generation/acknowledgement, raster behavior, dynamic stalls,
IRQ delivery, DMA, rendering or timing. The settling NOPs also clear T, so
these observations cannot isolate when the target operation clears T; the
local independently expected instruction cases check that immediate result,
fixed access waits and both clock speeds. The local suite separately checks
77,824 CPU cases, 8,192 register-width cases and 392,991 VRAM transfer/address
cases plus status, guards, deadlines and unsupported-operation faults.
Those broader local cases are not exhaustive live Geargrafx evidence.
Earlier live suites retain their original scope and were not rerun this batch.

### Clocked CD command handshake

The `--suite scsi` adapter uses **`pce-scsi-tests`**, whose authored RAM
fixture explicitly enables the transport profile. It uses the same isolated
synthetic bootstrap and blank CUE/BIN as the idle CD suite, verifies that CD
hardware is enabled, and establishes MPRs through actual CPU transfers.
Retail firmware, disc bytes and owner saves are not used.

Run three shards sequentially, substituting `N` with 0, 1 and 2:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-scsi-tests.exe --suite scsi --shard-count 3 --shard-index N --out .local/scsi-check/shard-N
```

Plans cover the host data latch, idle/held ACK, reset, six-byte TEST UNIT READY
under different IRQ masks and MPR aliases, and reset aborts during selection,
partial command reception, held ACK and status. Added edge plans check extra
ACKs after status consumption, reselection while already in COMMAND, and
signal changes under held reset. Observations compare unmasked
CPU registers/PC/MPRs, exposed SCSI phase/signals and drive data byte, ACK,
IRQ-enable/active fields, reset, IRQ2 and BRAM gate. The final 8 KiB work RAM
and 2 KiB BRAM are also compared for every plan. CPU `$1801` reads separately
observe the host latch when the drive is not sending a byte.

Finite authored delay loops advance Geargrafx by the same master ticks as
real generated/interpreted NOPs in the runtime probe. Scratch RAM and loop
registers are restored before each settled comparison. Deliberately generous
settling intervals avoid qualifying access phases as exact cycle boundaries;
the local independent suite checks literal deadline edges separately.

The completed evidence covers **21 unique plans**, passing **743 settled
checkpoints and 21 full work-RAM/BRAM comparisons per tier**. The native route
retires **1,007,851 native and zero interpreted instructions**; the interpreter
route retires **1,007,851 interpreted instructions**. Each route includes 743
observed operations and 1,007,108 settling NOPs.

The first 18 plans ran in three six-plan live shards against frozen probe
SHA256 `aed2d3604e751f229297d48566fad43e44ee2315466398ffcdb7d4ba70b26375`.
After additional edge fixes, all 18 plans produced exactly equal complete
JSON in both tiers against the final probe, including CPU/device observations,
full RAM/BRAM and instruction counters: 615 checkpoints, 18 memory comparisons
and 891,071 retirements per tier. This is an equivalence bridge, not another
live emulator run. The three added plans then ran live individually against
the final probe, adding 128 checkpoints and three memory comparisons per tier.
That batch's final ABI-6 probe SHA256 was
`bda34df2ffe2fc3be16c41683676eec732bb296155628cd3475a2e5bbea2a3eb`.
The reproduction command above partitions the current 21-plan matrix into
three seven-plan shards; it is equivalent coverage, not the exact historical
partition used for the retained proof.

This checks settled control transactions, not a sector backend, media
readiness, REQUEST SENSE, TOC/subcode, CDDA/ADPCM, CPU interrupt delivery,
hardware drive latency or gameplay. Geargrafx's response delays are an explicit
reference profile, with Mesen differences documented in [CD_CONTROL.md](CD_CONTROL.md).
Earlier suites retain their original evidence and were not rerun live in
this batch.

### Directory/TOC and DATA IN

The `--suite toc` adapter uses **`pce-scsi-tests --probe-toc`** through the
normal reference client. It creates a separate authored twelve-track CUE/BIN:
86 sectors per track, 1,032 total, with first/last tracks marked data and the
others audio. The reference's exposed metadata must match those actual tracks,
INDEX 01 LBAs and leadout before CPU comparisons begin. A synthetic System
Card bootstrap enables CD hardware; no retail BIOS/disc/save is supplied.

To reproduce the qualified selection, run the following command sequentially
with `N` equal to **0, 1, 2, 3, 5 and 6**:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-scsi-tests.exe --suite toc --shard-count 7 --shard-index N --out .local/toc-check/shard-N
```

Then run these individual plans with `I` equal to **4, 11 and 18**:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-scsi-tests.exe --suite toc --shard-count 26 --shard-index I --out .local/toc-check/case-I
```

The public matrix retains all 26 plans. Its remaining plan, index 25
(`toc-reset-auto-response-pending`), reproducibly crashed the isolated
Geargrafx 1.8.4 child twice with access violation `C0000005` in `ucrtbase.dll`.
It has no completed independent comparison and is **unqualified**, rather
than a passing or ignored mismatch. The local literal reset expectations
and source checks pass separately. This limitation also prevents calling a
full seven-shard matrix an all-pass result. The named plan remains available
as a reproducer through `--shard-count 26 --shard-index 25`; it is excluded
from the qualified commands above, without being removed from the matrix.

Plans cover all three supported `$DE` modes, BCD count and MSF replies,
track zero/valid audio/valid data/above-last-track and `$AA` leadout selectors,
manual and `$1808` auto-ACK, IRQ masks, MPR aliases, transfer reselection and
reset. Every observed instruction compares unmasked CPU registers/PC/MPRs,
SCSI phase/signals and actual drive byte, ACK, IRQ-enable/active fields,
reset, IRQ2 and BRAM gate. Final 8 KiB work RAM and 2 KiB BRAM are compared
per plan. Guest loads observe each response byte; expected bytes are not
injected into the reference bus.

Finite reference delay loops and actual translated/interpreted NOPs provide
the same elapsed master ticks, with reference scratch/register restoration
as in the control suite. These remain settled comparisons, not exact CPU
access phases. Local tests separately check literal 9,000/900/21/3,000-tick
boundaries, BCD limits, malformed metadata and refusal. The live selection-abort
checks retain Geargrafx's observed active IRQ `$60` until ACK clears REQ;
the source/reference difference is described in [CD_CONTROL.md](CD_CONTROL.md).

The retained 21-plan control suite was also bridged to the final ABI-7 probe:
complete JSON is exactly equal in both tiers, including 743 checkpoints,
21 full RAM/BRAM comparisons and 1,007,851 retirements per tier. This preserves
the earlier live evidence without claiming another independent emulator run.

The completed report is **`qualified_pass` for 25 of 26 registered plans**,
with **1,964 settled CPU/device checkpoints and 25 full work-RAM/BRAM
comparisons per tier**. The native route retires **653,294 native and zero
interpreted instructions**; the interpreter route retires **653,294 interpreted
instructions**. Each route includes 1,964 observed operations and 651,330
settling NOPs. The crashing plan's 50 potential checkpoints are excluded from
these totals because no independent result exists for them.

Eight plans from original shards 0/3 ran live against frozen probe SHA256
`2a870243460e18b0aa7e758068951090b387fdadcc3d424d09ffbdfc84788f5a`.
Their complete JSON then matched exactly in both tiers against the final
probe: 616 checkpoints, eight RAM/BRAM comparisons and 160,566 retirements per
tier. The remaining 17 qualified plans ran live against the final probe,
using seven-way shards 1/2/5/6 and individual indices 4/11/18. These bridges
compare full CPU/device states, memory and counters; they are not additional
live emulator runs. Final ABI-7 probe SHA256 is
`d11be952c49c3788f3ecb9968d5bbc0b9896fda58e12e0f0c2399b67514fcef9`.

This suite does not qualify physical drive response length/timing, sector
reads, media-content authentication, REQUEST SENSE, subcode, CDDA/ADPCM, CPU
interrupt delivery or gameplay. In particular, the four-byte response profile
follows Geargrafx/Mesen; Beetle's differing lengths remain documented.

## Clocked raster reference

The separate `scripts/raster_reference.py` harness compares the direct
clocked device probe **`pce-raster-tests --clock`** with Geargrafx. Its authored
HuCard executes finite CPU delay loops; debugger observations provide VCE
master-clock positions, VDC dot/line positions, horizontal/vertical phases,
latched status and local IRQ1 assertion. Explicit elapsed-clock checks reject
a delay which does not arrive at its expected VCE position. This is direct
device-clock evidence, not a native/interpreter instruction comparison.

Fifteen plans combine standard, short, narrow, delayed and oversized vertical
geometries with disabled, enabled and display-enabled CR contexts. They sample
startup and two-frame timing, including line/frame boundaries and status
accumulation. A stable guest status-port read checks acknowledgement at the
end of each plan. This suite uses the default VCE dot divider 4 and 262 lines;
the other VCE controls have local expected-value coverage, not live parity.
Register setup uses debugger writes; their CPU write phases are not qualified.

The completed run passes **4,165 exact-clock checkpoints and 15 guest status
acknowledgements across all 15 plans**, using one frozen direct probe with
SHA256 `a3baeb7a17e7c5d9d3334af0ed3a484c80bb6e7e2a65643ddb49e36c8b0ceaaa`.
The five earlier passing plans each contain 277 checkpoints; the remaining
ten contain 278 after adding one interior checkpoint. The current public
client includes that checkpoint for every plan, so a fresh complete run has
4,170 checkpoints. The retained combined result is 4,165; it is not inflated
to the newer matrix size.

The final rebuilt probe has SHA256
`1b8d401e0c3cf2c443b10859cb153e621a4b19b69f43155bb13648b51826f45c`.
All fifteen retained clock inputs produce byte-identical JSON against the
live-tested frozen probe: 4,165 checkpoints and 15 acknowledgements. This
bridge checks that added local tests and acknowledgement-window guards did
not change the retained device observations; it is not another emulator run.
The final probe also rejects an enabled event inside a status-read observation
window, avoiding an ambiguous acknowledgement comparison.

To reproduce, run fifteen commands sequentially with `N` from 0 through 14:

```sh
python scripts/raster_reference.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-raster-tests.exe --shard-count 15 --shard-index N --out .local/raster-check/shard-N
```

Each run starts its own dedicated portable child and rejects CD/SuperGrafx
hardware profiles. Shards have a 180-second runtime limit, MCP responses are
bounded by the shared 2 MiB reader, and direct probe calls time out after ten
seconds. The compact report begins as incomplete and becomes a pass only after
all selected observations agree. The child is terminated on success or error.
No rendered video, retail image, firmware, owner settings or saves are used.

The local independent suite separately exercises literal event edges, CR
changes at event boundaries, raster-register changes, vertical latches,
partition independence, all eight low VCE timing controls and CPU retirement
cadence at both speeds. Neither this direct device reference nor those local
checks establishes CPU bus-phase accuracy, interrupt delivery, dynamic VRAM
waits, DMA, rendering or hardware qualification. Gear/Mesen event differences
are retained in [VDC.md](VDC.md).

On other hosts supply the corresponding executable filename. On a
multi-configuration build the probe may be under `build/Release/`. Those
reference sessions have not yet been run by this project.

The default output is ignored `.local/geargrafx-check/`. A compact
`result.json` records emulator identity and exact check scope. A failing
run retains one synthetic mismatch and exits nonzero; it cannot reuse a
previous pass as the current result. Work is bounded to 180 seconds, MCP
responses to 2 MiB each, and probe invocations to five seconds. No frame or
audio dump is enabled. The harness always terminates only its own child.

The reference check is optional and outside the default CI suite, so a
green synthetic CI job must not be reported as a fresh independent-reference
run. A second independently developed reference and hardware test vectors
remain useful next work.

## Joypad I/O sequence adapter

The `pce-joypad-tests --probe` fixture uses authored instructions in work RAM.
Run each command for shard indices 0 through 7, with at most two isolated
reference children at once:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-joypad-tests.exe --suite joypad --shard-count 8 --shard-index N --out .local/joypad-check/cart-N
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-joypad-tests.exe --suite joypad-cd --shard-count 8 --shard-index N --out .local/joypad-check/cd-N
```

All sixteen final shards passed: **56 plans, 2,512 CPU/port-output checkpoints
and 56 complete 8 KiB work-RAM comparisons per execution tier**. The native
route retired 2,512 generated instructions and no interpreter steps; the
interpreter route retired 2,512 interpreted instructions and no native steps.
Held button state is set through Geargrafx MCP; expected CPU registers,
flags, MPRs and guest-read port bytes come from the independent emulator.
No flags or port bits are masked out. Internal controller structs are not
compared directly; their behavior is observed through actual guest port reads.

The plans cover all twelve individual buttons, released/full/mixed masks,
two/six-button pads, five distinct pad snapshots and mixed types, TurboTap
advance/reset/overflow, repeated SEL/CLR levels, every output byte, ten
logical address aliases and RMW side effects. Separate MPR-latch preservation
is a local expected-value check, not an added live TMA observation here. Both
HuCard and authored-CD profiles use isolated synthetic inputs and compare
RAM without publishing retail bytes. The CD plans reuse the authored blank
media/bootstrap, not the owner's disc or firmware.

Geargrafx's headless `Auto` setting leaves its console enum as Auto. The
pinned core only asserts the Japanese line for explicit PCE/SGX types, so
these live checks qualify the USA line polarity, with CD present and absent.
The adapter uses that source-defined profile rather than deriving a region
from expected runtime output. An initial Japan-profile assumption failed on
bit 6 and was corrected in the adapter; the runtime was unchanged. The
Japanese bit remains independently expected/source-checked locally, with
no live qualification here. Host input changes during a guest sequence,
electrical timing, peripherals, CPU IRQ entry and gameplay remain unverified.
See [INPUT.md](INPUT.md) for source disagreements rather than assuming all
emulators implement unusual controller edges identically.

The frozen ABI-8 probe used for all final shards has SHA256
`5a4a8f16c590559645d2c31255ec9f73cbce69e879485ca3d1ced1db4e090dab`.
All final reports bind that same probe and the pinned Geargrafx executable.

## CD READ sector adapter

`scripts/read_reference.py` starts a dedicated portable Geargrafx child and
loads an authored 24-sector MODE1/2048 CUE/BIN plus an authored bootstrap.
Every sector has a deterministic, position-dependent payload. No retail
firmware, disc bytes, save files or initialized personal install are used.
Run seven shards, with `N` from 0 through 6, sequentially or at most two at once:

```sh
python scripts/read_reference.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-read-tests.exe --shard-count 7 --shard-index N --out .local/read-check/live-N
```

All seven final shards pass: **201 CPU/settled-CD checkpoints and seven
complete 2,048-byte sectors (14,336 payload bytes) per execution tier**.
The native probe retires 15,552,742 generated instructions and no interpreter
steps; the interpreter route retires 15,552,742 interpreted instructions and
no native steps. Those totals include settling NOPs and port-access stream
instructions; they are not unique translated sites or a performance result.
All reports bind the same frozen ABI-9 READ probe, SHA256
`2887817019e0d837526cb497d3802ed59430310720658ab7d5d42c72e80c1399`.
The final probe, SHA256
`9886dbd21bf93bc7fd282770d67d76531050ba1795eb90ebf4eeb0a224f0d8b0`,
returns identical complete JSON for all seven retained plans in both tiers:
201 checkpoints per route, including payloads and execution counts. This
bridge verifies that the final added local tests and cancelled-command
cleanup preserve the live-qualified observations; it is not another
Geargrafx run.

The reference guest executes finite ordinary HuC6280 read/store loops to
capture all 2,048 payload bytes in work RAM. The toolkit probe executes its
generated or interpreted port-access instructions and returns the full
payload. Both routes compare settled CPU registers, MPRs, guest-observable
CD signals and IRQ levels with Geargrafx. Host register restoration removes
the reference capture loop's scratch registers from these observations.
The loops have different CPU instruction cadence, so this is settled
sector/handshake evidence, not exact access-phase or stream-loop CPU parity.
The complete RAM contents are not compared in this adapter.

The matrix covers manual and `$1808` automatic ACK, distinct first and next
sector payloads, backpressure, ignored upper bits in READ's LBA byte, crossing
the authored leadout, and reset with pending or buffered reads. The zero
count plan aborts before data; its effective 256-sector length is checked
by independent local expectations, not by this live fixture. Settling waits
cover the reference's seek delay, initial random drive phase and 290 ms
backpressure retry. They do not qualify those timings, physical drive
behavior, ECC/EDC decoding, IRQ delivery or gameplay.

Source facts come from the pinned Geargrafx
[READ command and sector loader](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp)
and [clock/IRQ integration](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller_inline.h).
Geargrafx returns GOOD for an invalid starting LBA, while a failed sector
load or a transfer crossing leadout produces CHECK CONDITION. The runtime
deliberately reports invalid media requests as errors; invalid-start parity
is excluded from the live matrix. The runtime's fixed initial seek profile
also excludes Geargrafx's distance-dependent seek and random initial phase.
These differences must not be presented as hardware qualification.

Each shard has a 180-second work limit, 256 KiB process-log limit, shared
2 MiB MCP response limit and 30-second toolkit-probe timeout. Authored media
is reused per output parent. The compact report starts incomplete and becomes
a pass only after every selected checkpoint and payload agrees; failures
retain a bounded synthetic mismatch. Only the child started by the adapter
is terminated, including on exceptions.

## Block-transfer instruction adapter

`scripts/block_reference.py` checks TII (`$73`), TDD (`$C3`), TIN (`$D3`),
TIA (`$E3`) and TAI (`$F3`) against a separate Geargrafx 1.8.4 process.
Build the optional `pce-block-probe` with `PCE_BUILD_REFERENCE_PROBE=ON`.
Run sixteen shards, with `N` from 0 through 15 and at most two children:

```sh
python scripts/block_reference.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-block-probe.exe --shard-count 16 --shard-index N --out .local/block-check/live-N
```

All inputs are authored. A tiny HuCard bootstrap establishes the reference
mapping, then actual guest TAM instructions map every logical page to the
same 8 KiB RAM bank. This deliberately exercises MPR aliases and complete
16-bit address wrap without introducing unsupported MMIO or writable ROM.
Each probe executes one completed instruction in its selected tier. The
adapter compares every CPU register, all flags, PC, all eight MPRs and the
entire 8 KiB RAM image, including the stack's saved and restored bytes.
Native fallback is forbidden: each native case must retire exactly one
generated instruction and zero interpreted instructions; the interpreted
case requires the converse.

The matrix contains **810 plans** across both CPU speeds and four status/SP
contexts, plus ten directed operand/stack aliases. It covers lengths 1, 2,
3, 4, 7, 9, 17, 255, 256, 257 and 1,023; all five zero-length encodings
transfer 65,536 bytes. Forward/backward overlaps, alternating-byte parity,
fixed destinations, source/destination page crossings and wrapping through
`$FFFF` are included. Stack-source and stack-destination aliases expose the
real Y/A/X pushes and X/A/Y pops. In the directed operand aliases, those
pushes modify the encoded destination and length before operand fetching.

All sixteen shards passed: **810 CPU states, 810 complete 8 KiB RAM images
and 810 complete-instruction tick deltas per execution tier**. The native
route retired 810 generated instructions and zero interpreted instructions;
the interpreter route retired 810 interpreted instructions and zero native
instructions. Forty plans exercise zero-length encodings. The frozen probe
used for every final shard has SHA256
`e5fd9765467c29048b78385b7938650d1dc4cc52aa246ce53a6575cf62bdf665`.

Geargrafx's instruction trace suppresses internal transfer microsteps.
One block-entry timestamp and a subsequent host-injected NOP sentinel give
the entire instruction's master-tick delta without storing a per-byte trace.
The CPU/RAM observation is captured before the sentinel is injected. This
qualifies complete-instruction `17 + 6*n` timing for the RAM-only profile,
including zero counts and both speed divisors. It does not qualify the bus
phase of each byte, device waits, interrupts or gameplay.

The pinned Geargrafx implementation re-fetches the opcode between transfer
bytes. This differs from the toolkit's latched, whole-instruction contract
when a transfer overwrites its own opcode. Live fixtures preserve that
opcode: zero-length TII/TDD copy each byte to itself, TIN/TIA use fixed safe
destinations, and zero-length TAI's two source bytes are authored `$F3`.
Self-overwritten opcodes therefore remain outside the independent-reference
claim rather than being treated as an emulator agreement. See the pinned
[transfer implementation](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_opcodes_inline.h)
and [instruction trace filtering](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280.cpp).

The adapter shares the established 2 MiB MCP response limit. Each shard has
a 180-second work limit, 256 KiB process-log limit and five-second toolkit
probe timeout. Only the adapter's own reference child is terminated. The
pass report binds both executable hashes and exact selected plan IDs; a
failing run keeps one bounded synthetic mismatch and remains incomplete.
