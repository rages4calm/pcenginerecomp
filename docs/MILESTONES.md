# Development milestones

These records were moved from the project README on 27 November 2026.
They describe the revisions, test scopes and limitations of their original
runs. Historical counts and compatibility statements are not fresh checks of
the current build.

For the current overview, see the [project README](../README.md).
For the latest results and known gaps, see [status](STATUS.md) and the
[roadmap](ROADMAP.md).

## Shared presentation and controller tools

Desktop ports can use five-player keyboard/gamepad [input profiles](DESKTOP_INPUT.md),
timed display confirmation and [configurable shader controls](DESKTOP_PRESENTATION.md).
An optional [reconstruction and continuity gate](PRESENTATION_HISTORY.md)
helps ports reject unsafe motion interpolation and recover after checkpoint
loads. [Bounded GPU probes](GPU_TESTING.md) retain Windows diagnostics and
can run on a separate, non-visible Windows desktop. The launcher stays shared.

## Disc origins guide overlay discovery

Ports can now bind paused disc-origin reports to their RAM snapshots and select
overlay code candidates by disc byte ranges. The complete origin evidence follows
the candidates through composition and native compilation. Logical entry points,
MPR mappings and live source-byte guards still constrain execution.
[Discovery guide](DISC_ORIGINS.md#select-overlay-discovery-from-disc-origins)

## Observed CD overlay origins

An opt-in recorder now follows CD READ bytes through supported guest loads,
stores, register transfers and block copies into RAM. Ports can query disc
offsets through paused TCP inspection, identify overwritten overlays, and
retain that report alongside their existing source captures. Checkpoint
restore begins a fresh tracking epoch. [Disc-origin guide](DISC_ORIGINS.md)

## Reference frame comparison

Compare two RGB8 PPM captures with
`python scripts/compare_frames.py reference.ppm ours.ppm --png .local/new-frame-diff`.
The tool reports the first changed pixel and writes reference, result and
highlighted difference images to a new directory. Adapted from
[Fabiano Gelain's PCERecomp](https://github.com/Fabiano-Gelain/PCERecomp)
under its [MIT license](../licenses/PCERecomp-MIT.txt).
[Peer project review](PEER_PROJECTS.md)

Thanks to [gorigamia](https://github.com/gorigamia/dungeon-explorer-pc) and
[Fabiano Gelain](https://github.com/Fabiano-Gelain/YsRecomp) for sharing their
PC Engine port projects.

## Adaptive widescreen and ultrawide cameras

The desktop port example now draws a fixed 21:9 view or bases its camera on
the current window's aspect. The 21:9 camera reveals 50 more world columns
on each side of the centered 16:9 scene. Auto mode clamps to the room width
and keeps the HUD aligned to the viewport. Ports can reuse the camera sizing
helper and develop against paused TCP window resize and checkpoint replay.
[Build and play the example](../examples/widescreen/README.md)

Monochrome and a CRT phosphor-mask preset join the desktop shaders.
Both operate on the final presentation. [Shader and display guide](DESKTOP_PRESENTATION.md)

## Reusable widescreen renderer

Desktop consumers can link a read-only renderer and choose the guest view or
port-rendered 4:3 and 16:9 cameras from the same executable. The authored example
generates its own card and scene. Its wide camera shows terrain on both sides,
keeps the HUD at the edges, and follows the player to either end of the room.
[Build and play the example](../examples/widescreen/README.md)

Smooth and LCD join the Sharp and CRT GPU presets. Smooth eases color transitions
between texels, while LCD adds a grid that fades at smaller scales. The authored
TCP replay ran 12,131,756 native instructions per route with zero fallback.
Changing the view preserved 37,440 overlapping world pixels, the guest CPU,
WRAM and RGB, and byte-identical ending checkpoints. [Presentation guide](DESKTOP_PRESENTATION.md)

## Wider desktop presentation and Rondo loader coverage

Desktop consumers can select integer scaling, fractional square-pixel fit,
4:3 or 16:9, start in fullscreen, and use GPU sharp or CRT shaders. A port that
draws a wider world view can submit its own high-resolution RGB frames to the
same host. The standard guest frame and checkpoint timing stay intact.
[Desktop presentation guide](DESKTOP_PRESENTATION.md)

Rondo's boot through first-stage movement ran 404,669,933
native instructions with zero fallback and matched 17 CPU,
RAM and video samples. The expanded loader sweep tested 19 groups in two pass
orders using each build's own TCP checkpoint. All 38 assisted windows ran
121,493,794 native instructions with zero fallback, matching
interpreter CPU state, RAM, clocks and captured instruction identities.
Independent Geargrafx checks matched CPU and RAM for three seeded loader
groups. [Loader sweep workflow](LOADER_WORKFLOWS.md)

Direct3D 12 and Vulkan both passed UHD presentation, GPU pixel checks and a
TCP checkpoint replay with identical guest video, CPU state and timing.
The full checker passed 2,427 Python tests,
75 C++ suites and 12 fresh-process audio cases.

## Loader discovery, portable setup and rewind

The toolkit can run guest loaders from checkpoints, capture the code they load
into RAM and feed those observations into a fresh native build. It also supports
sharing translated code between known immediate operand variants, exporting
source setup kits with an optional compiler bundle, and adding compressed rewind
to consumer hosts. The design draws on gminustwo's RondoRecomp with permission.
[Workflow guide](LOADER_WORKFLOWS.md) · [Attribution](../licenses/RondoRecomp-notice.txt)

Four authored CD loader calls each ran 346,130 native instructions with zero
fallback. The returned CPU state, MPRs and complete WRAM and CD-RAM matched
Geargrafx. A Windows setup kit built and ran an authored route using the
bundled LLVM toolchain. The route executed 1,140,110 native instructions with
zero fallback. [Authored example](../examples/loader-sweep/README.md)

Rondo's boot, file menu and introduction route reached 404,669,933 native
instructions with zero fallback or guard misses. CPU state, full RAM snapshots
and video samples matched the interpreter reference. Four assisted calls to two
retail loader groups then ran another 18,441,631 native instructions from the
feedback build's own checkpoint, with matching CPU state, RAM, clocks and
instruction identities. Coverage is limited to those routes and calls.

One authored operand-sharing case kept all 2,816 instruction identities while
reducing generated C++ from 1,056,738 to 43,890 bytes. One Clang O2 sample took
4.54 versus 0.65 seconds to build that object. Verification covered 2,426
Python tests, 75 C++ suites and 12 fresh-process audio cases. A stale test-runner
suite-count assertion was corrected and its test module passed on rerun.

## Live RAM and CD overlay discovery

[Live overlay discovery](LIVE_OVERLAYS.md) now turns closed paused TCP RAM
snapshots into bounded code candidates and composes multiple epochs into a
guarded native module. Full logical-PC/MPR/source-byte identity, original package
provenance and every snapshot/derivation artifact survive preparation, catalogues
and managed archives. Genuine observations stay separate. ABI 29 is unchanged.

The [authored CD workflow](../examples/live-overlays/README.md) loads two sectors
into the same RAM address using real guest CD READ commands. Snapshots precede
their first execution. Three branch keys absent from the original route are
derived without invented hits; two native routes exercise all **11 declared RAM
keys**, with zero interpreter fallback. Literal full RAM/final CPU, same-build
reference parity, checkpoint forks and changed-source refusal pass. Data gates
and branch controls are disclosed developer assistance.

Fresh unmodified Geargrafx matches **26 CPU/MPR/source-byte points** and full
WRAM/CD-RAM endpoints across four loaded-code windows. Two managed builds reuse
all **35 objects** after epoch reordering and reject **21** individual archived
artifact tampers before compilation. Thirty-six existing pure/mixed ROM, RAM,
firmware and source-set emission cases remain byte-identical to the prior
loader/emitter.

A fresh Rondo reference route captures two live RAM epochs (26 and 106 keys;
106 unique candidates). The combined native module and genuine history pass
404,669,933 native instructions with zero interpreted work/guards, 25,621 exact
retired identities and 17 paired CPU/full-WRAM/CD-RAM/RGB samples. Of the 106
declared candidates, 93 execute and 13 remain explicitly unexercised. Same-build
checkpoint forks add 59,672 new native steps / 753 keys, separately from imported
counts. This qualifies boot/file/introduction, not action gameplay or a whole
retail title. Ys III remains parked.

The required frozen-source check passes **2,401 Python tests without skips,
74 C++ suites and 12 fresh-process audio cases**. All 846 tracked candidate inputs
remain byte-identical through the seal. Later publication edits are Markdown
only; the 104-file SDK source fingerprint is unchanged.

Snapshots establish reported source content, not remote-process authentication,
disc-sector attribution, routine closure or future RAM contents. Unknown writes,
indirect flow, returns and interrupt boundaries remain explicit frontiers;
normal native guards remain active. See the [remaining gates](ROADMAP.md).

<a id="independently-verified-source-sets"></a>

## Prior source-set milestone

[Source sets](SOURCE_SETS.md) now combine independently verified numeric
RAM-program and firmware entries in one native module, without manufacturing a
recorded capture. Source-role/mapping checks, exact member provenance and live
fetch guards continue through preparation, build inputs and managed archives.
The original single-source paths and runtime ABI 29 are unchanged.

The [authored workflow](../examples/source-sets/README.md) executes all **5,888 declared
keys over 256 mapping windows**, with zero interpreted instructions or guard
misses in positive native runs. Literal CPU/MPR boundaries, clocks, full WRAM/CD
RAM and encoded source/hits pass. Separate changed-payload/firmware tests refuse
before guest effects. Fresh unmodified Geargrafx checks every original source
byte/CPU point and all 256 complete WRAM/CD-RAM endpoints. This is CPU/RAM
evidence, not independent device clocks, hardware or whole-title proof.

Two real managed builds reuse all **31 compiled objects** after an annotation
reorder, retain every numeric member exactly, change checkpoint context and
reject each archive tamper before compilation. Thirty old pure/mixed single-source
emissions remain byte-identical across all three layouts.

Required frozen-source checker: **2,376 Python tests without skips,
74 C++ suites and 12 fresh-process audio cases** pass; all 838
tracked inputs stayed unchanged through the seal. Subsequent edits are Markdown
only; the tested SDK source fingerprint is unchanged.

Fresh Rondo TCP cold/native/reference windows pass: 404,669,933 native
instructions, zero interpreted/guards, 25,621 exact keys and 17 paired
CPU/full-WRAM/CD-RAM/RGB samples. Own-checkpoint forks add 59,672 new native
steps / 753 keys separately from imported counts. These retain the observed
module and cover boot/file/introduction, not retail use of new source sets or
action gameplay. Ys III remains parked.

Geargrafx's self-remapping block-copy fix also passes both unchanged original
test inputs against the original independent CPU/full-RAM expectations; the
old-build timeout remains a separate historical control. See the
[upstream retest and thanks](https://github.com/drhelius/Geargrafx/issues/214#issuecomment-6862517085).

<a id="source-qualified-native-boot-inputs"></a>

## Prior boot-source milestone

[Boot-source declarations](BOOT_SOURCE_DECLARATIONS.md) extend numeric instruction
entries to exact standard-RAM payloads and Standard/Super System Card firmware.
The source role/load/profile must match the actual boot asset; ordinary file,
hash, size, per-byte mapping and use-boundary checks remain strict. Generated
operations keep live source guards. Original ROM format, runtime lowering and
ABI 29 are unchanged; live CD overlay/reachability inference remains open.

The [authored workflow](../examples/boot-sources/README.md) runs all 5,558 declared
source keys over 244 preset mapping windows / 5,612 instructions per tier, with
every literal CPU/MPR boundary, clocks, full WRAM and exact source/hits. Positive
native windows have zero interpreted work/guards. Each changed-source negative
retires five instructions then refuses once without guest effects at refusal.
Fresh unmodified Geargrafx passes all 244 full-WRAM endpoints, eight full-CD-RAM
endpoints and 5,612 CPU/MPR/source-byte points. Authored firmware has unknown CRC;
disjoint helpers are separate from original analyzed bytes. This is CPU/RAM
evidence, not external clocks/devices/hardware or whole-title proof.

Two actual managed payload generations reuse all 30 compiled objects after an
annotation-only reorder, preserve exact archived roots, change checkpoint context
and reject archive tampering before compilation. Six old pure/mixed ROM emission
cases remain byte-identical across all three layouts. Source-growth regressions
check size-race refusal and bounded decoder buffers.

Required frozen-source checker: **2,352 Python tests without skips,
74 C++ suites and 12 fresh-process audio cases** pass; all
830 tracked inputs stayed unchanged. Subsequent public edits are ten
Markdown files only; the tested SDK source fingerprint remains unchanged.

Fresh Rondo TCP cold/native/reference windows pass: 404,669,933 native
instructions, zero interpreted instructions/guard misses, 25,621 exact keys and
17 paired state/full WRAM/CD RAM/RGB samples. Own-checkpoint forks add 59,672
new native steps / 753 keys, separate from imported counts. These retain the
existing observed module and cover boot/file/introduction, not retail use of new
declarations or action gameplay. Ys III remains parked.

## Prior software-interrupt milestone

The new opt-in [BRK/RTI policy](SOFTWARE_INTERRUPTS.md) follows proven ROM/WRAM
vectors, protects nested three-byte frames and restores partial saved status
under current MPR/source views. Runtime lowering and ABI 29 are unchanged.
The [authored workflow](../examples/software-interrupts/README.md) executes all
2,104 derived keys: 49 native main instructions plus 1,024 preset matrix windows
/ 15,360 native instructions, zero interpreted/guards in positive native runs.
Changed vector/status negatives refuse omitted targets after 28/14 native steps.

Fresh unmodified Geargrafx checks all 1,025 original CPU/full-WRAM endpoints and
15,409 instruction points, including known relative stack bits. Two earlier
reference setup failures remain failed harness attempts. This is CPU/RAM evidence;
asynchronous IRQ, external clocks/device/hardware and full-title proof remain open.
Omitting the option preserves 99 previous-option/profile byte comparisons.

Required frozen-source checker: **2,329 Python tests without skips,
74 C++ suites and 12 fresh-process audio cases** pass; all
821 tracked inputs were unchanged. Subsequent public edits are documentation
only; the SDK source fingerprint remains unchanged.

Fresh Rondo TCP cold/native/reference and same-build checkpoint windows pass:
404,669,933 native instructions, zero interpreted/guards and 25,621 exact keys;
17 paired paused CPU/RAM/CD-RAM/RGB samples match. Checkpoint forks add 59,672
new native steps / 753 keys, separately from imported counts. These cover boot,
file selection and introduction, not action gameplay. Ys III remains parked.

## Prior mapper milestone


**Discovery now follows proven cartridge bank changes.**
The opt-in SF2 mapper policy follows address-selected scalar/RMW writes and bank
changes between bytes of a block copy. Subsequent code and data use the current
window, with ordinary source permissions and live runtime operations.

The authored workflow expands 5,032 candidates/609 mapper frontiers to 9,009
identities without frontiers; all execute across separate main/matrix windows.
Gear passes 608 fixed-ROM cases. Full Beetle independently passes the original
self-remapping main; a Gear limitation is [reported upstream](https://github.com/drhelius/Geargrafx/issues/214).
Rondo TCP/checkpoints pass separately. Frozen `f14bd0b` passes **2,312 Python
tests without skips, 74 C++ suites and 12 fresh-process audio cases**. ABI 29 is
unchanged. See [contracts and evidence](MAPPER_FLOW.md) and the
[reusable native workflow](../examples/mapper-flow/README.md).

## Previous ordered-copy discovery milestone

**Discovery now follows ordered block copies and mutable jump tables.**
The opt-in memory-flow policy handles TII/TDD/TIA/TAI/TIN, including overlap and
WRAM aliases, checks temporary stack/mapper hazards, and can enumerate all 256
indices of a proven RAM pointer table. Safe known writes can cross SF2 mapper
barriers. Generated operations continue reading and writing live memory.

The authored base/SF2 workflows each execute all 468 declared identities across
separate main/copy windows, plus every table index. Fresh Gear passes 612
CPU/full-WRAM cases. Rondo TCP/checkpoints pass separately. Frozen `dd08097`
passes **2,298 Python tests without skips, 74 C++ suites and 12 fresh-process
audio cases**. ABI 29 is unchanged. See [contracts and limits](MEMORY_FLOW.md)
and the [reusable native workflow](../examples/memory-flow/README.md).

## Previous writable-data discovery milestone

**Discovery now follows proven writable data and RAM pointers.**
The opt-in WRAM policy tracks explicitly permitted bytes through stores, loads,
RMW/bit/test operations and T-mode arithmetic, then uses known RAM pointers for
indirect ROM jumps. Unknown values/writes remain conservative. Generated code
continues reading and writing live guest memory.

The authored banked main route runs 45 native / zero interpreted / zero guards;
separate 354-preset matrices retire 3,716 per tier. All 3,761 declared identities
execute across the distinct windows. Fresh Gear passes 355 CPU/full-WRAM cases
and known incoming/outgoing/WRAM comparisons. Rondo TCP/checkpoint regression
passes separately. Frozen `62b9af8` passes **2,275 Python tests without skips,
74 C++ suites and 12 fresh-process audio cases**. ABI 29 is unchanged. See
[WRAM contracts](WRAM_VALUES.md) and the
[reusable native workflow](../examples/wram-values/README.md).

## Previous saved-stack discovery milestone

**Static discovery now follows saved register and status values.**
The opt-in stack policy handles PHA/PLA, PHX/PLX, PHY/PLY and partial PHP/PLP
bits through bounded calls, including the HuC6280 B/T rules and WRAM aliases.
Unknown values and unsafe stack accesses stay explicit; generated stack operations
continue reading and writing live guest memory.

The authored banked route now reaches all 39 operations: 39 native / zero
interpreted / zero guards. Separate 281-preset matrices include every PLP/PHP byte;
all 1,979 declared identities execute across the distinct windows. Fresh Gear
passes 282 CPU/full-WRAM cases, 11,049 known components and 5,434 saved bits.
Rondo TCP/checkpoint regression passes separately. Frozen `548ba3f` passes
**2,246 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 is unchanged. See [stack contracts](STACK_VALUES.md) and the
[reusable native workflow](../examples/stack-values/README.md).

## Previous conditional discovery milestone

**Static discovery now handles source-proven conditional paths.**
The opt-in branch policy tracks N/Z/V alongside carry/decimal/T, retains known
conditional arms and refines unknown flag edges without inventing RAM values.
Generated branches continue to test live flags/memory and use normal source guards.

The authored main route expands nine candidates to 28; separate 96-case matrices
exercise all eight flag and 16 bit-branch forms with 1,040 native/zero interpreted/
zero guards. Fresh Gear checks pass 378 CPU/full-WRAM cases and 99 conditional
points. Rondo TCP/checkpoint regression passes separately. Frozen `cb47691f`
passes **2,227 Python tests without skips, 74 C++ suites and 12 fresh-process
audio cases**. ABI 29 remains unchanged. See [conditional discovery](BRANCH_FACTS.md)
and its [reusable native workflow](../examples/branch-facts/README.md).

## Previous register arithmetic milestone

**Static discovery now follows arithmetic through data-driven bank changes.**
The opt-in register evaluator tracks A/X/Y and carry/decimal/T facts through
logic, arithmetic, shifts/rotates and comparisons. Unknown or unsafe inputs stay
unknown; generated operations keep their live CPU/bus reads and source guards.

The authored main route expands seven candidates to 24; separate 280-case matrices
execute 1992 native/zero interpreted/zero guards and the matching interpreter work.
Fresh Gear CPU/full-WRAM checks pass all 281 main/matrix cases. A fresh Rondo
TCP/checkpoint regression passes separately. Frozen `911ef040` passes **2,200
Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 remains unchanged. See [register evaluation](REGISTER_EVAL.md) and its
[reusable native workflow](../examples/register-eval/README.md) for scope and limits.

## Previous ROM data milestone

**Static discovery can now follow values loaded from immutable ROM.**
Explicit data permissions let LDA/LDX/LDY facts feed bank changes, indices and
bounded calls while preserving original source witnesses and dynamic runtime reads.
The reusable authored main route expands four candidates to 17; its native run
has zero fallback or guard misses. A separate 64-case matrix covers all 16 load
forms, and fresh Gear checks match all 65 main/matrix cases on CPU/full WRAM.

Fresh Rondo TCP/checkpoint regression passes separately. Frozen `22b5a7fb` passes
**2,175 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 remains unchanged. See [ROM data analysis](ROM_DATA.md) and the
[authored workflow](../examples/rom-data/README.md) for permissions and exact limits.

## Previous ROM table milestone

**Static discovery can now follow ROM jump tables with an unknown X register.**
The opt-in policy considers all 256 byte indices under explicit vector-data
permissions, retains full source mappings and reports every blocked case.
Call/return analysis and consumer preparation preserve the rederived graph.
Generated jumps still read their live pointers and retain source guards.

The authored example expands three candidates to 19 and executes all 19 in a
1792-instruction native matrix with zero fallback or guard misses. Fresh Gear
checks pass all 256 indices. The new-build Rondo TCP/checkpoint regression also
passes. Frozen `1b8081de` passes **2,156 Python tests without skips, 74 C++ suites
and 12 fresh-process audio cases**. ABI 29 remains unchanged. See
[ROM table analysis](ROM_TABLES.md) and its reusable
[authored native workflow](../examples/rom-tables/README.md).

## Previous shared compilation milestone

**Large native modules can now build much faster with opt-in shared emission.**
The new layout reuses identical guarded code across MPR contexts while retaining
every full source identity. One fresh local SF2 Windows build dropped from
**413 to 52 seconds** (about **7.9× faster**), generated source from **109.7 to
17.2 MB**, and the unpacked executable from **30.4 to 7.4 MB**. All 190,243
identities remain; 1101 generated C++ units become 31.

Native SF2 and Rondo TCP replays plus fresh checkpoint forks match their
same-build interpreter references, with zero interpreted instructions or guard
misses. Separate Gear CPU/RAM matrices pass. Frozen `f2f9fefa` passes
**2,136 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 remains unchanged. This is one Windows build pair and bounded game routes,
not a universal speedup or whole-game compatibility claim. See
[shared emission](SHARED_EMISSION.md) for usage, measurements and limits.

## Previous native CD milestone

**Rondo now runs natively through cold boot and the new-game introduction.**
The private Japanese Super CD route executes **404,669,933 native instructions,
zero interpreted instructions and zero guard misses**, matching all 25,621 source
identities and per-key hit counts. Seventeen paused stages agree with the reference
on reported CPU/device/raster state, all 8 KiB WRAM, all 256 KiB CD RAM and completed
RGB. Fresh same-build checkpoint forks also match.

The deeper route explicitly selects the existing `nec-invalid` CD error profile:
firmware sends ten `$FF` bytes and continues after the documented rejection.
The default strict policy remains unchanged. New bounded TCP block reads make
full memory checks practical; existing small-read/write limits are unchanged.
See the reusable [native CD workflow](NATIVE_CD_WORKFLOW.md).

This qualifies boot, menus, file creation and introduction, not playable action,
a finished port or independent retail/audio parity. Separate fresh Gear CD/VDC
and original Gear/Beetle invalid-command fixtures retain their stated scope.
Frozen `af8bee11` passes **2,124 Python tests without skips, 74 C++ suites and
12 fresh-process audio cases**. ABI 29 and guest/checkpoint payload semantics
remain unchanged. [Status](STATUS.md) records exact producer and limits.

## Previous launch-plan and HuCard milestone

**Caller-owned TCP sessions now have a validated launch-plan interface.**
Use `python -m pcerecomp.project launch-plan` or `prepare_launch` to obtain a built
consumer's argv after source/package validation, with no implicit launch or file
reservation. The shared Gear reference adapter also fixes negotiated HTTP headers.
See [launch plans and the HuCard workflow](LAUNCH_PLANS.md).

A bounded Bomberman '94 route now executes **60,994,880 native instructions with
zero interpretation or guard misses**, matches all 32,255 source keys/hit counts,
and agrees with reference CPU/device state, full WRAM and RGB at 11 paused stages.
Fresh same-build checkpoint forks also agree. This is first-stage internal
qualification, not a complete port or an independent full-game comparison.
Separate Gear matrices match 86 encoding slots/1,120 cases per execution tier.

Frozen `5b00d4ef` passes **2,117 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 and guest semantics remain unchanged. [Status](STATUS.md) records the
producer, comparison scope and remaining compatibility gates.

## Previous call/return discovery milestone

**One startup seed can now recover selected call/return continuations.**
The opt-in `discover-roots --call-depth 8` policy tracks balanced calls and stack
effects under the current complete mapping. Unsafe writes/mappings and limits
stay explicit; generated returns still read the actual guest stack.
See [the contract](STATIC_DISCOVERY.md#optional-synchronous-call-policy)
and [one-seed native workflow](../examples/static-discovery/README.md#one-seed-callreturn-discovery).

Frozen `dc9b9fec` passes **2,099 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
One seed derives 15 identities; the separate assisted native/reference probe
executes all 15, checks literal clocks/full WRAM and verifies changed-source and
changed-return refusals. Both older policies retain their canonical artifacts.
ABI 29 and guest semantics are unchanged. These are bounded compiler/runtime
checks, not universal discovery or fresh independent hardware qualification.
New Bomberman/Rondo TCP/checkpoint windows are interpreter-only startup evidence;
see [status](STATUS.md) and [future compatibility inputs](COMPATIBILITY_CORPUS.md).

## Previous discovery-consumer milestone

**Discovery results now stay attached to prepared consumers and managed builds.**
Select `module.kind = "discovery"` to retain and rederive the exact original
seed/roots/report graph alongside the native module. The expanded roots are stored
once, the ROM stays separate, and build/cache/recovery/run bindings preserve the
extra provenance. Existing declaration-only consumers remain supported.
See [the supported workflow](DISCOVERY_CONSUMERS.md).

The [authored example](../examples/rom-vectors/README.md) supports
`prepare --retain-discovery` and qualifies actual native/reference execution,
full-RAM/literal-clock checks and guard negatives. A real managed test changes
only seed/derivation metadata, preserves every object byte and timestamp, keeps
both original generation graphs, and executes the nine-instruction native route
again with zero fallback or guards. Removing retained provenance refuses.

Frozen `63daf485` passes **2,073 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**. All 750 tracked inputs stayed unchanged
through the full check. Runtime **ABI 29**, guest semantics, discovery policies
and checkpoint encoding are unchanged; changed provenance still gets a fresh
build/checkpoint context.

These are bounded authored compiler/runtime and contributor-interface checks,
not new hardware or gameplay qualification. [ROM-vector discovery](STATIC_DISCOVERY.md),
[declared/observed composition](DECLARED_ROOTS.md) and
[extended captures](EXTENDED_CAPTURE.md) remain supported. See
[status](STATUS.md), [readiness](TOOLKIT_READINESS.md) and
[roadmap](ROADMAP.md) for remaining return/indirect/live-overlay and broader
library/hardware gates.
