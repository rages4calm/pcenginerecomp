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
| Discovery | Bank-aware bounded static analysis, exact retired-code captures, overlay/writable-code variants, source-qualified static declarations and bounded ROM discovery with opt-in immutable data facts, native coverage reports and unresolved-edge reporting |
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
