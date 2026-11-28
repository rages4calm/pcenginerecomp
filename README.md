# PC Engine Recomp

**A toolkit for building native PC ports of PC Engine and TurboGrafx-16 games.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![C++20](https://img.shields.io/badge/C%2B%2B-20-00599C)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)

[Get started](#build-and-test) · [Documentation](docs/README.md) · [Games tested](#games-used-in-testing) · [Contribute](CONTRIBUTING.md) · [Discord](https://discord.gg/Ad9BwSzctP)

PC Engine Recomp translates identified HuC6280 code into readable C++20 and
provides the shared runtime and development tools needed to turn it into a PC
port. It supports HuCard and CD-ROM²/Super CD-ROM² workflows, with code
discovery, CD overlay tracking, native builds, video, audio, input and debugging
in one project.

**Ready for port development, in active development.** The capture-to-native
workflow is implemented and tested on authored fixtures and bounded retail-game
routes. Developers can start port projects today, with shared tools for finding
uncovered code, reproducing bugs and qualifying their builds. Compatibility and
finished-port quality still depend on the game and the work done in its port.

## What works today

| Area | Included |
| --- | --- |
| **Native compilation** | Direct C++20 translations, 234 legal opcode encodings, bank-aware source guards, native-only and hybrid execution. |
| **Code discovery** | Static analysis, executed-code capture, writable-code variants, live RAM/CD overlays, declared CD load maps, loader sweeps and native coverage reports. |
| **Shared runtime** | VDC/VCE video, queued VRAM timing, interrupts, PSG/ADPCM/CDDA audio, two/six-button controllers, TurboTap and isolated BRAM saves. |
| **Media and boot** | Supported HuCard mappings, Standard/Super System Card startup, and read-only ISO, BIN/CUE and CHD providers. |
| **Port builds** | Pinned consumer projects, CMake integration, incremental builds, code sharing, package caching, interrupted-build recovery and Windows DLL packaging. |
| **Presentation** | Square pixels, integer/fractional scaling, fullscreen, configurable shaders and reusable widescreen/ultrawide renderer hooks. |
| **Controls** | Five-player keyboard/gamepad profiles, remapping and configurable deadzones. |
| **Gameplay extensions** | Optional consumer-owned C++ adapters, structured initial settings, source-qualified events, transactional edits and checkpoint-bound state. |
| **Development tools** | TCP input, screenshots and frame stepping, sparse scripted routes, request profiling, exact-build checkpoints, audited native-module continuation, interpreter reference runs and bus traces. |

The compiler emits translated operations. The shared runtime supplies console
video, audio, CD and timing services. Native-only execution stops at uncovered
code; hybrid execution can interpret supported unseen paths so they can be
captured and added to the next native build.

## From game to port

1. **Inspect your inputs.** Select the game's media, hardware and firmware recipe.
2. **Discover the code.** Combine gameplay captures, static analysis and observed
   loader/overlay data. Keep unresolved paths visible in coverage reports.
3. **Build a native project.** Prepare a consumer, compile its translated C++ and
   link the shared runtime and optional desktop host.
4. **Test and refine.** Replay routes through TCP, compare state and images,
   restore checkpoints and feed newly discovered code into the next build.

The CLI, structured reports and TCP interface support scripted and AI-assisted
workflows. Ports can reuse the toolkit's input, audio, presentation and debugging
services while keeping their own game-specific behavior and enhancements.

[Prepare your first port project](docs/PREPARE_PROJECT.md) · [Consumer build guide](docs/CONSUMER.md) · [CD loader workflows](docs/LOADER_WORKFLOWS.md)

[Offline CD load maps](docs/CD_LOADS.md) can supply guarded code before every
area has been visited. [Shared RAM/CD analysis](docs/RAM_CD_ANALYSIS.md) adds
opt-in bounded calls and matched returns, with explicit writable data regions
and conservative code/stack mutation barriers. [Resident composition and proven
stack transfers](docs/RESIDENT_FAR_CALLS.md) connect shared RAM routines to CD
overlays and follow supported far transfers from known pushed return bytes.
[Audited checkpoint continuation](docs/CHECKPOINT_CONTINUATIONS.md)
lets compatible native-coverage updates reuse an unchanged checkpoint after
one supported baseline. It requires the same frozen SDK and audited Windows
LLVM-MinGW build producer; it does not convert older or arbitrary cross-build
states. Recovery builds, including resumed builds, can also supply that audit
evidence; a [reproducible example](examples/checkpoint-continuation/README.md)
covers recovery and cache producers.

[Gameplay adapters](docs/TITLE_ADAPTERS.md) let ports add their own optional
settings through the existing host and launcher. The
[authored example](examples/title-adapter/README.md) demonstrates independent
reward multipliers and post-hit protection, with pristine/reference comparisons.
Game-specific rules stay in the port; this is not a built-in cheat database.

Ports without gameplay adapters compile their hooks out of the instruction path.
The [repeatable host benchmark](examples/inactive-adapter/README.md) compares
fixed guest work while checking complete state and keeping timing claims separate
from game compatibility.

[Read-only checkpoint BRAM diagnostics](docs/CHECKPOINT_BRAM.md) extract an exact
source checkpoint's backup-memory image without running or restoring the guest.
Ports can explicitly use it as a fresh developer seed; it does not validate a
game SAVE or make older checkpoints portable.

[Typed checkpoint inspection and comparison](docs/CHECKPOINT_INSPECTION.md)
provide CPU/MPR reports and full state fingerprints through the source build.
Ports can compare native and reference checkpoints without parsing byte offsets;
the optional tier policy ignores only four named execution counters.

[Last-track CD audio handling](docs/CD_AUDIO_LEADOUT.md) supports the following
track as a leadout end boundary. The reusable authored example checks native
playback commands, digital audio and checkpoint restores through TCP.

[Immutable rendering helpers](docs/PORT_RENDER_LAYERS.md) give ports tilemap
sampling, sprite masks, underlays and row palettes for wider views and scenery
effects. The authored example checks an exact original image before enhancement.
See the separately verified [burst border-color correction](docs/BURST_COLOR.md).

[Completed-frame effects](docs/PRESENTATION_EFFECTS.md) add optional software
softness and phosphor-style persistence for original or wider port images.
Their history follows completed guest frames and resets after checkpoint loads;
paused screenshots and resizing do not advance the effect.

<a id="latest-verified-milestone"></a>

## Games used in testing

- Ys III: Wanderers from Ys
- Castlevania: Rondo of Blood
- Bomberman '94
- Street Fighter II: Champion Edition
- Boxyboy
- Soldier Blade

[Current status](docs/STATUS.md) · [Development milestones](docs/MILESTONES.md)

## Build and test

Requirements: **Python 3.11+**, **CMake 3.20+** and a **C++20 compiler**. These
commands use Ninja. SDL3 is optional for desktop builds; CHD decompression uses
an optional libchdr dependency. See [development setup](docs/DEVELOPMENT.md) for
platform and dependency instructions.

Run from a committed checkout so consumer projects can pin an exact toolkit
revision.

```sh
git clone https://github.com/rages4calm/pcenginerecomp.git
cd pcenginerecomp
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
python scripts/check.py --build build --python-timeout 3600
```

### Try the native workflow without a game or BIOS

This example generates an original test card, captures executed code, prepares
and compiles a native consumer, then checks native execution and work RAM.
Use a new destination for each experiment.

```sh
python examples/native-workflow/workflow.py capture .local/my-native-workflow --runner build/pce-headless
python examples/native-workflow/workflow.py prepare .local/my-native-workflow
python examples/native-workflow/workflow.py qualify .local/my-native-workflow --generator Ninja
python examples/native-workflow/workflow.py probe .local/my-native-workflow
```

On Windows, use `build/pce-headless.exe`. Compiler paths and platform-specific
options are covered in the [complete example](examples/native-workflow/README.md).

### Start your own port

Use [prepare-project](docs/PREPARE_PROJECT.md) with a machine/media recipe and
captures, discovery results or declared code entries. It produces translated
source and a pinned consumer descriptor. The [consumer interface](docs/CONSUMER.md)
then builds and runs that project. Keep game-specific code and private inputs
in your port's repository/workspace.

## Desktop and development control

For a desktop host, supply an SDL3 package compatible with your compiler:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_BUILD_DESKTOP=ON -DSDL3_DIR=/path/to/SDL3/lib/cmake/SDL3
cmake --build build
```

The desktop host supports fullscreen, square-pixel fit, configurable shaders,
five-player input profiles and timed confirmation of display changes. A port
renderer can draw extra world content for true widescreen or ultrawide views.
The [authored widescreen example](examples/widescreen/README.md) provides a
working camera/HUD implementation to adapt.

[Display and shader settings](docs/DESKTOP_PRESENTATION.md) · [Input profiles](docs/DESKTOP_INPUT.md) · [Audio](docs/AUDIO_OUTPUT.md)

Append `--dev-port 0 --dev-start-paused on` to a continuous-video runner.
It reports a `PCE_DEV_PORT` for loopback control:

```sh
python scripts/dev_client.py --port 4370 status
python scripts/dev_client.py --port 4370 input 0x8 --frames 2
python scripts/dev_client.py --port 4370 screenshot new-frame.png --source guest
```

Replace `4370` with the reported port and use a new screenshot filename.
[TCP commands](docs/DEV_SERVER.md), [checkpoints](docs/DEVELOPER_CHECKPOINTS.md)
and [logged GPU probes](docs/GPU_TESTING.md) support repeatable testing.
For longer tests, [scenario plans](docs/STATE_ROUTES.md#sparse-checkpoint-scenarios)
hold inputs across bounded steps and save only at explicit boundaries.
[Request profiling](docs/DEV_SERVER.md#measure-client-and-server-response-costs)
helps identify expensive saves, journaling and server work. A
[native-module comparison](docs/NATIVE_EXTENSIONS.md) checks that a coverage
update preserves earlier code identities. A separate
[continuation admission](docs/CHECKPOINT_CONTINUATIONS.md) checks the build,
compiler, media and checkpoint before permitting a compatible module extension.

## Media inspection

Supply your own legally obtained game and firmware files. Inspect them before
preparing a port:

```sh
python -m pcerecomp doctor
python -m pcerecomp inspect "/path/to/your/disc.chd" --hash
```

The toolkit keeps media external to generated code and build receipts. See
[development setup](docs/DEVELOPMENT.md) for optional CHD support and media tools.

<a id="direction-and-contribution"></a>

## Documentation and contributing

<a id="independently-verified-source-sets"></a>
<a id="source-qualified-native-boot-inputs"></a>

| Start here | Purpose |
| --- | --- |
| [Documentation hub](docs/README.md) | Guides grouped by porting task. |
| [Architecture](docs/ARCHITECTURE.md) | Compiler, runtime and bank/source identity. |
| [Readiness](docs/TOOLKIT_READINESS.md) and [roadmap](docs/ROADMAP.md) | Supported workflows, compatibility limits and remaining goals. |
| [Status](docs/STATUS.md) and [milestones](docs/MILESTONES.md) | Detailed validation and development history. |
| [Contributing](CONTRIBUTING.md) | Build, review and contribution expectations. |

Contributions that improve compatibility, discovery, build times, diagnostics,
documentation and reusable port features are welcome. Reproducible bug reports
with clear steps and code-free diagnostics are especially useful. Keep ROMs,
BIOS files, extracted assets, saves and code-bearing traces out of public issues
and pull requests.

<a id="license-and-inputs"></a>

## Credits and license

Original code is [MIT licensed](LICENSE). Opcode metadata and optional
dependencies retain their own terms. See [third-party notes](THIRD_PARTY.md).

Research, comparisons and shared ideas from
[SNESRecomp](https://github.com/RetroPortingToolKit/snesrecomp),
[PSXRecomp](https://github.com/RetroPortingToolKit/psxrecomp),
[Geargrafx](https://github.com/drhelius/Geargrafx),
[RondoRecomp](https://github.com/gminustwo/RondoRecomp),
[PCERecomp](https://github.com/Fabiano-Gelain/PCERecomp),
[YsRecomp](https://github.com/Fabiano-Gelain/YsRecomp) and
[Dungeon Explorer PC](https://github.com/gorigamia/dungeon-explorer-pc)
have helped this project. [Source credits and licensing](THIRD_PARTY.md)
record the applicable attribution and reuse terms.

## Community and contact

Discord: **chrono.trigger**

[**R.A.I.D. — Retro AI Development**](https://discord.gg/Ad9BwSzctP) is a
community for AI-assisted retro reverse-engineering, decompilation and
recompilation. Join to discuss this toolkit, share ports and follow development.
