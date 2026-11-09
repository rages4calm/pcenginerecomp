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
python scripts/check.py --python-timeout 1800
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
| Discovery | Bank-aware bounded static analysis, exact retired-code captures, overlay/writable-code variants, source-qualified static declarations and bounded ROM discovery, native coverage reports and unresolved-edge reporting |
| Capture histories | Content-addressed original files, recomputed sharded catalogues, mixed-ABI provenance, staged additive selection and full-graph validation |
| Consumer builds | Pinned descriptors, general explicit preparation, embedded CMake modules, Windows DLL packaging, stable changed-unit rebuilds, exact package caching and verified interrupted-build recovery |
| Media and startup | Supported HuCard mappings, Standard/Super System Card reset, read-only ISO/BIN-CUE/CHD providers, TOC and supported CD transport/audio services |
| Shared runtime | VDC/VCE rendering and queued VRAM access, raster/timer/IRQ, PSG/ADPCM/CDDA audio, two/six-button and multitap input, isolated BRAM persistence |
| Development | Headless and optional SDL3 hosts, bounded loopback TCP control/screenshots, exact-build checkpoints, interpreter reference windows and software bus-event tracing |

These capabilities have explicit profile and verification limits. Native-only
dispatch refuses identities absent from its guarded module; hybrid mode can
execute supported unseen code through the interpreter. Generated code contains translated operations.
CPU translation still needs device models and guest timing for original hardware
behavior. There is no universal automatic ROM-to-finished-port guarantee.

## Latest verified milestone

**Bounded static discovery now expands entry annotations into native compiler inputs.**
The [new walker](docs/STATIC_DISCOVERY.md) follows direct control flow and proven
MPR changes inside explicit ROM code ranges. It preserves original seeds and a
recomputable derivation graph, while keeping unknown calls/returns, indirect flow,
mapper-write hazards and analysis limits explicit. It creates no execution hits.

The [authored example](examples/static-discovery/README.md) expands two seeds into
15 instruction identities across three mappings. Its official cold run retires
100 native instructions with zero fallback/guards, leaving six candidates
unexecuted. A separate compiled probe reaches all 15 in 110 native instructions,
checks every work-RAM byte and literal clocks, and tests a real source-guard refusal.
The interpreter reference also matches the literal expectations and whole RAM.

The final SDL build and required check pass **2,023 Python tests without skips, 74 C++ suites and 12 fresh-process audio cases** at frozen code
`d23dcbef`. Runtime **ABI 29**, CPU/device behavior and guest checkpoint encoding
are unchanged. [Declared-root/history composition](docs/DECLARED_ROOTS.md) and
[extended captures](docs/EXTENDED_CAPTURE.md) remain supported independently.

This is bounded compiler/runtime evidence. Pinned Geargrafx/Mesen source review
informs mapping rules; it is not a newly executed hardware/emulator qualification.
See [status](docs/STATUS.md), [readiness](docs/TOOLKIT_READINESS.md) and
[roadmap](docs/ROADMAP.md). General return/indirect recovery, live source overlays
and broader independent hardware/library coverage remain work.

## Desktop and development control

Supply an SDL3 package compatible with your compiler for the optional window:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_BUILD_DESKTOP=ON -DSDL3_DIR=/path/to/SDL3/lib/cmake/SDL3
cmake --build build
python scripts/check.py --python-timeout 1800
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
