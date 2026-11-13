# PC Engine Recomp

An open, experimental static recompilation toolkit for **PC Engine /
TurboGrafx-16 and CD-ROM²**. It translates identified HuC6280 instructions into
readable C++20 and supplies shared video, audio, input, CD and debugging services
for native consumer projects.

This is a general toolkit. Each consumer owns its game-specific discovery,
patches, assets and presentation. Ys III has supplied useful regression cases;
it is not a runtime dependency or the definition of platform compatibility.

## Build and test

Use Python 3.11+, CMake 3.20+ and a C++20 compiler. Ninja is used below. Run from
a committed checkout so prepared consumers can pin an exact SDK revision.

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
python scripts/check.py --python-timeout 3600
```

Then try the [complete authored native workflow](examples/native-workflow/README.md).
It creates its own test card, captures executed code, preserves the original
observations, prepares a pinned consumer, compiles translated operations and
checks actual native execution plus every work-RAM byte. No game or BIOS is needed.

```sh
python examples/native-workflow/workflow.py capture .local/my-native-workflow --runner build/pce-headless
python examples/native-workflow/workflow.py prepare .local/my-native-workflow
python examples/native-workflow/workflow.py qualify .local/my-native-workflow --generator Ninja
python examples/native-workflow/workflow.py probe .local/my-native-workflow
```

On Windows, use `build/pce-headless.exe`. Compiler/package paths can be passed
explicitly; see the example. Keep source, media and generated inputs unchanged
between preparation and qualification. Destinations must be new.

For your own project, [prepare-project](docs/PREPARE_PROJECT.md) accepts an
explicit capture/profile/history or source-qualified declarations and a machine
recipe. It produces a verified descriptor, translated module and preparation
receipt. The official
[consumer interface](docs/CONSUMER.md) then builds and runs that descriptor.
Preparation, compilation and actual execution remain separate evidence.

## What works today

| Area | Supported foundation |
| --- | --- |
| CPU and translation | 234 legal opcode encodings, explicit reserved-opcode traps, direct C++ operations, full logical-PC/MPR/source-byte guards and native/interpreter counters |
| Discovery | Bank-aware bounded static analysis, exact retired-code captures, overlay/writable-code variants, source-qualified ROM/RAM-payload/firmware declarations and multi-source composition and bounded ROM discovery with opt-in data, arithmetic, conditional, saved-stack, WRAM data/pointer, ordered block-copy/mutable-table, proven mapper-transition and protected synchronous BRK/RTI facts, native coverage reports and unresolved-edge reporting |
| Capture histories | Content-addressed original files, recomputed sharded catalogues, mixed-ABI provenance, staged additive selection and full-graph validation |
| Consumer builds | Pinned descriptors, general explicit preparation, embedded CMake modules, Windows DLL packaging, stable changed-unit rebuilds, opt-in shared guarded-code emission, exact package caching and verified interrupted-build recovery |
| Media and startup | Supported HuCard mappings, Standard/Super System Card reset, read-only ISO/BIN-CUE/CHD providers, TOC and supported CD transport/audio services |
| Shared runtime | VDC/VCE rendering and queued VRAM access, raster/timer/IRQ, PSG/ADPCM/CDDA audio, two/six-button and multitap input, isolated BRAM persistence |
| Development | Headless and optional SDL3 hosts, bounded loopback TCP control/screenshots, exact-build checkpoints, interpreter reference windows and software bus-event tracing |

These capabilities have explicit profile and verification limits. Native-only
dispatch refuses identities absent from its guarded module; hybrid mode can
execute supported unseen code through the interpreter. Generated code contains translated operations.
CPU translation still needs device models and guest timing for original hardware
behavior. There is no universal automatic ROM-to-finished-port guarantee.

## Latest verified milestone

### Independently verified source sets

[Source sets](docs/SOURCE_SETS.md) now combine independently verified numeric
RAM-program and firmware entries in one native module, without manufacturing a
recorded capture. Source-role/mapping checks, exact member provenance and live
fetch guards continue through preparation, build inputs and managed archives.
The original single-source paths and runtime ABI 29 are unchanged.

The [authored workflow](examples/source-sets/README.md) executes all **5,888 declared
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

### Prior boot-source milestone

[Boot-source declarations](docs/BOOT_SOURCE_DECLARATIONS.md) extend numeric instruction
entries to exact standard-RAM payloads and Standard/Super System Card firmware.
The source role/load/profile must match the actual boot asset; ordinary file,
hash, size, per-byte mapping and use-boundary checks remain strict. Generated
operations keep live source guards. Original ROM format, runtime lowering and
ABI 29 are unchanged; live CD overlay/reachability inference remains open.

The [authored workflow](examples/boot-sources/README.md) runs all 5,558 declared
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

### Prior software-interrupt milestone

The new opt-in [BRK/RTI policy](docs/SOFTWARE_INTERRUPTS.md) follows proven ROM/WRAM
vectors, protects nested three-byte frames and restores partial saved status
under current MPR/source views. Runtime lowering and ABI 29 are unchanged.
The [authored workflow](examples/software-interrupts/README.md) executes all
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

### Prior mapper milestone


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
unchanged. See [contracts and evidence](docs/MAPPER_FLOW.md) and the
[reusable native workflow](examples/mapper-flow/README.md).

### Previous ordered-copy discovery milestone

**Discovery now follows ordered block copies and mutable jump tables.**
The opt-in memory-flow policy handles TII/TDD/TIA/TAI/TIN, including overlap and
WRAM aliases, checks temporary stack/mapper hazards, and can enumerate all 256
indices of a proven RAM pointer table. Safe known writes can cross SF2 mapper
barriers. Generated operations continue reading and writing live memory.

The authored base/SF2 workflows each execute all 468 declared identities across
separate main/copy windows, plus every table index. Fresh Gear passes 612
CPU/full-WRAM cases. Rondo TCP/checkpoints pass separately. Frozen `dd08097`
passes **2,298 Python tests without skips, 74 C++ suites and 12 fresh-process
audio cases**. ABI 29 is unchanged. See [contracts and limits](docs/MEMORY_FLOW.md)
and the [reusable native workflow](examples/memory-flow/README.md).

### Previous writable-data discovery milestone

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
[WRAM contracts](docs/WRAM_VALUES.md) and the
[reusable native workflow](examples/wram-values/README.md).

### Previous saved-stack discovery milestone

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
ABI 29 is unchanged. See [stack contracts](docs/STACK_VALUES.md) and the
[reusable native workflow](examples/stack-values/README.md).

### Previous conditional discovery milestone

**Static discovery now handles source-proven conditional paths.**
The opt-in branch policy tracks N/Z/V alongside carry/decimal/T, retains known
conditional arms and refines unknown flag edges without inventing RAM values.
Generated branches continue to test live flags/memory and use normal source guards.

The authored main route expands nine candidates to 28; separate 96-case matrices
exercise all eight flag and 16 bit-branch forms with 1,040 native/zero interpreted/
zero guards. Fresh Gear checks pass 378 CPU/full-WRAM cases and 99 conditional
points. Rondo TCP/checkpoint regression passes separately. Frozen `cb47691f`
passes **2,227 Python tests without skips, 74 C++ suites and 12 fresh-process
audio cases**. ABI 29 remains unchanged. See [conditional discovery](docs/BRANCH_FACTS.md)
and its [reusable native workflow](examples/branch-facts/README.md).

### Previous register arithmetic milestone

**Static discovery now follows arithmetic through data-driven bank changes.**
The opt-in register evaluator tracks A/X/Y and carry/decimal/T facts through
logic, arithmetic, shifts/rotates and comparisons. Unknown or unsafe inputs stay
unknown; generated operations keep their live CPU/bus reads and source guards.

The authored main route expands seven candidates to 24; separate 280-case matrices
execute 1992 native/zero interpreted/zero guards and the matching interpreter work.
Fresh Gear CPU/full-WRAM checks pass all 281 main/matrix cases. A fresh Rondo
TCP/checkpoint regression passes separately. Frozen `911ef040` passes **2,200
Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 remains unchanged. See [register evaluation](docs/REGISTER_EVAL.md) and its
[reusable native workflow](examples/register-eval/README.md) for scope and limits.

### Previous ROM data milestone

**Static discovery can now follow values loaded from immutable ROM.**
Explicit data permissions let LDA/LDX/LDY facts feed bank changes, indices and
bounded calls while preserving original source witnesses and dynamic runtime reads.
The reusable authored main route expands four candidates to 17; its native run
has zero fallback or guard misses. A separate 64-case matrix covers all 16 load
forms, and fresh Gear checks match all 65 main/matrix cases on CPU/full WRAM.

Fresh Rondo TCP/checkpoint regression passes separately. Frozen `22b5a7fb` passes
**2,175 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 remains unchanged. See [ROM data analysis](docs/ROM_DATA.md) and the
[authored workflow](examples/rom-data/README.md) for permissions and exact limits.

### Previous ROM table milestone

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
[ROM table analysis](docs/ROM_TABLES.md) and its reusable
[authored native workflow](examples/rom-tables/README.md).

### Previous shared compilation milestone

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
[shared emission](docs/SHARED_EMISSION.md) for usage, measurements and limits.

### Previous native CD milestone

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
See the reusable [native CD workflow](docs/NATIVE_CD_WORKFLOW.md).

This qualifies boot, menus, file creation and introduction, not playable action,
a finished port or independent retail/audio parity. Separate fresh Gear CD/VDC
and original Gear/Beetle invalid-command fixtures retain their stated scope.
Frozen `af8bee11` passes **2,124 Python tests without skips, 74 C++ suites and
12 fresh-process audio cases**. ABI 29 and guest/checkpoint payload semantics
remain unchanged. [Status](docs/STATUS.md) records exact producer and limits.

### Previous launch-plan and HuCard milestone

**Caller-owned TCP sessions now have a validated launch-plan interface.**
Use `python -m pcerecomp.project launch-plan` or `prepare_launch` to obtain a built
consumer's argv after source/package validation, with no implicit launch or file
reservation. The shared Gear reference adapter also fixes negotiated HTTP headers.
See [launch plans and the HuCard workflow](docs/LAUNCH_PLANS.md).

A bounded Bomberman '94 route now executes **60,994,880 native instructions with
zero interpretation or guard misses**, matches all 32,255 source keys/hit counts,
and agrees with reference CPU/device state, full WRAM and RGB at 11 paused stages.
Fresh same-build checkpoint forks also agree. This is first-stage internal
qualification, not a complete port or an independent full-game comparison.
Separate Gear matrices match 86 encoding slots/1,120 cases per execution tier.

Frozen `5b00d4ef` passes **2,117 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
ABI 29 and guest semantics remain unchanged. [Status](docs/STATUS.md) records the
producer, comparison scope and remaining compatibility gates.

### Previous call/return discovery milestone

**One startup seed can now recover selected call/return continuations.**
The opt-in `discover-roots --call-depth 8` policy tracks balanced calls and stack
effects under the current complete mapping. Unsafe writes/mappings and limits
stay explicit; generated returns still read the actual guest stack.
See [the contract](docs/STATIC_DISCOVERY.md#optional-synchronous-call-policy)
and [one-seed native workflow](examples/static-discovery/README.md#one-seed-callreturn-discovery).

Frozen `dc9b9fec` passes **2,099 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases**.
One seed derives 15 identities; the separate assisted native/reference probe
executes all 15, checks literal clocks/full WRAM and verifies changed-source and
changed-return refusals. Both older policies retain their canonical artifacts.
ABI 29 and guest semantics are unchanged. These are bounded compiler/runtime
checks, not universal discovery or fresh independent hardware qualification.
New Bomberman/Rondo TCP/checkpoint windows are interpreter-only startup evidence;
see [status](docs/STATUS.md) and [future compatibility inputs](docs/COMPATIBILITY_CORPUS.md).

### Previous discovery-consumer milestone

**Discovery results now stay attached to prepared consumers and managed builds.**
Select `module.kind = "discovery"` to retain and rederive the exact original
seed/roots/report graph alongside the native module. The expanded roots are stored
once, the ROM stays separate, and build/cache/recovery/run bindings preserve the
extra provenance. Existing declaration-only consumers remain supported.
See [the supported workflow](docs/DISCOVERY_CONSUMERS.md).

The [authored example](examples/rom-vectors/README.md) supports
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
not new hardware or gameplay qualification. [ROM-vector discovery](docs/STATIC_DISCOVERY.md),
[declared/observed composition](docs/DECLARED_ROOTS.md) and
[extended captures](docs/EXTENDED_CAPTURE.md) remain supported. See
[status](docs/STATUS.md), [readiness](docs/TOOLKIT_READINESS.md) and
[roadmap](docs/ROADMAP.md) for remaining return/indirect/live-overlay and broader
library/hardware gates.

## Desktop and development control

Supply an SDL3 package compatible with your compiler for the optional window:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_BUILD_DESKTOP=ON -DSDL3_DIR=/path/to/SDL3/lib/cmake/SDL3
cmake --build build
python scripts/check.py --python-timeout 3600
```

`pce-desktop` shares the runtime and translated module with the headless host.
Guest cadence and host presentation remain separate. See [desktop controls](docs/DESKTOP.md)
and [audio output](docs/AUDIO_OUTPUT.md) for pacing, raw/filtered output and SDL/WAV controls.
Windows consumer packages bind their selected non-system runtime DLLs beside the executable.

Append `--dev-port 0 --dev-start-paused on` to a continuous-video runner for
loopback development control. Use its reported `PCE_DEV_PORT` with the
[TCP client](docs/DEV_SERVER.md); screenshot/output paths must be new.

```sh
python scripts/dev_client.py --port 4370 status
python scripts/dev_client.py --port 4370 input 0x8 --frames 2
python scripts/dev_client.py --port 4370 screenshot new-frame.png --source guest
```

## Media inspection

Supply your own inputs. CHD decompression optionally uses a project-local
libchdr build; nothing is installed or downloaded implicitly.

```sh
python -m pcerecomp doctor
python -m pcerecomp inspect "/path/to/your/disc.chd" --hash
python -m pcerecomp toc "/path/to/your/disc.chd" --out .local/title/disc.toc
```

See [development setup](docs/DEVELOPMENT.md) for optional decoder bootstrapping,
bounded IPL snapshots and static analysis. Firmware, captures, generated game
source, extracted data and saves remain private.

## Direction and contribution

| New interface | Purpose |
| --- | --- |
| [Toolkit readiness](docs/TOOLKIT_READINESS.md) | Supported native-port workflow, evidence and remaining acceptance gates |
| [Prepare a consumer](docs/PREPARE_PROJECT.md) | Explicit portable recipes and separate prepare/build/run boundaries |
| [Observation histories](docs/OBSERVATION_HISTORY.md) | Content-addressed graph, admission, staged selection and migration |
| [Authored workflow](examples/native-workflow/README.md) | Reproduce genuine captures, native compilation, RAM checks and guard refusal |

| Read | Purpose |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Execution model, bank identity, runtime boundaries and state ownership |
| [Consumer projects](docs/CONSUMER.md) | Pinned project descriptors, shared-runtime builds and execution receipts |
| [Native capture](docs/CODE_CAPTURE.md) | Bounded executed identities, source variants and offline native promotion |
| [Stable emission](docs/STABLE_EMISSION.md) | Opt-in full-MPR/logical-range parts and independent Gear execution |
| [Managed rebuilds](docs/INCREMENTAL_BUILDS.md) | Checked same-workspace object reuse, immutable history and failure handling |
| [Native spans](docs/NATIVE_SPANS.md) | Experimental bounded native batches with per-instruction boundaries |
| [Developer checkpoints](docs/DEVELOPER_CHECKPOINTS.md) | Exact-build paused machine save/restore, private files and resumed evidence |
| [CPU semantics](docs/CPU_SEMANTICS.md) | Instruction contracts, status flags, stack wrapping and verification |
| [VDC semantics](docs/VDC.md) | Video ports, VRAM, raster events, clock phases and explicit limits |
| [VDC latch checkpoints](docs/VDC_LATCH_CHECKPOINTS.md) | Live CR/MWR/queue boundaries, fresh-process restoration and raw reference differences |
| [Continuous video](docs/VIDEO_OUTPUT.md) | Historical pixel/line output, frame publication and remaining fetch-phase limits |
| [Desktop host](docs/DESKTOP.md) | Optional SDL3 presentation, controls, pacing and isolation |
| [Development control](docs/DEV_SERVER.md) | Loopback TCP commands, frame stepping and requested RGB captures |
| [CD semantics](docs/CD_CONTROL.md) | Command handshake, reference timing, BRAM and explicit transport limits |
| [CD audio control](docs/CD_AUDIO.md) | Position commands, guest timeline, fader and explicit audio-output limits |
| [CD audio gap admission](docs/CD_AUDIO_GAPS.md) | Preserved playback/source state, controller quirks and independent admission checks |
| [Audio output](docs/AUDIO_OUTPUT.md) | Digital sources, optional filtering/48 kHz resampling, bounded SDL/WAV output and verification limits |
| [Controller semantics](docs/INPUT.md) | Two/six-button pads, TurboTap, sampling and reference differences |
| [Research](docs/RESEARCH.md) | Primary sources, pinned references, existing tools and design decisions |
| [Roadmap](docs/ROADMAP.md) | Full feature target, dependencies and acceptance criteria |
| [Status](docs/STATUS.md) | Verified baseline, known limitations and next useful batch |
| [Development](docs/DEVELOPMENT.md) | Reproduce builds, run the CLI and understand private outputs |
| [Contributing](CONTRIBUTING.md) | Review standards and useful contributor work |


Widescreen, enhanced rendering, localization, accessibility, rewind and netplay
have separate shared-framework and game-specific milestones. Review
[the roadmap](docs/ROADMAP.md) before treating a planned feature as available.
Hosted CI is not enabled; the CI template is an intended matrix, not a passing
public check. Locally tested configurations are recorded in status.

## License and inputs

Original code is [MIT licensed](LICENSE); opcode metadata retains its BSD
notice. Optional dependencies retain their own terms. See
[third-party notes](THIRD_PARTY.md). Supply your own game and firmware
inputs. Please do not attach ROMs, discs, BIOS images, extracted data, or
code-bearing traces to issues or pull requests.

## Community and contact

Discord: **chrono.trigger**

[**R.A.I.D. — Retro AI Development**](https://discord.gg/Ad9BwSzctP) · a Discord
for AI-assisted retro reverse-engineering, decomp & recomp. I post my work there;
join to discuss this project and the others.
