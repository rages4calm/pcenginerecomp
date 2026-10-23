# PC Engine Recomp

An open, experimental static recompilation toolkit for **PC Engine /
TurboGrafx-16 and CD-ROM²** games. The goal is a shared foundation for native
ports with modern rendering, audio, input, debugging, and game-specific
enhancements.

**Current status: architecture and executable compiler foundation. No game
is playable or certified.** The decoder describes all 256 HuC6280 opcode
slots; the native emitter and interpreter implement 227 opcodes, including
load/store addressing, logical operations, ADC/SBC with T/decimal handling,
comparisons, shifts/rotates, INC/DEC, indirect JMP, RMB/SMB and all eight
push/pop instructions, BIT/TSB/TRB/TST, bit branches, BSR and TAM/TMA with
persistent transfer-latch semantics, plus CSL/CSH speed control and
ST0/ST1/ST2 VDC port writes.
Decoded, emitted, compiled, and executed are different milestones here.

The project is AI-assisted and welcomes human and AI-assisted contributions.
Every contribution needs understandable code, appropriate source
attribution, and evidence for the behavior it claims. The maintainer is
building this with contributors; expert hardware and compiler review is
especially welcome.

## What works today

- Read-only CHDv5 track inspection, hashing, stored/virtual pregap handling,
  and separation of disc LBAs from padded CHD frame offsets.
- Optional libchdr decompression with a four-hunk cache; no full-disc extraction.
- Bounded IPL discovery from CHD or cooked ISO and creation of a pinned
  boot-program snapshot. The supported loader subset is documented.
- HuC6280 instruction decoding, bank-aware fetches, bounded control-flow
  discovery, and explicit unresolved edges.
- Direct C++20 emission with mapping and source-byte guards. Changed code
  falls back to the interpreter when supported, or exits explicitly.
- Headless CPU sandbox, native/interpreter counters, deterministic synthetic
  tests, CMake/CTest integration, and a cross-platform CI template (activation
  requires GitHub workflow authorization).
- Optional independent single-step comparison through Geargrafx's MCP
  debugger: the original 47-opcode baseline passed 188 comparisons per tier;
  the 24 added bit/stack opcodes passed 128 directed comparisons per tier.
  The 97-encoding data suite passed 1,552 comparisons per tier,
  including T and decimal contexts. See [verification scope](docs/REFERENCE.md).
  The 32-opcode shift/rotate/INC/DEC/indirect-JMP batch passed 512
  comparisons per tier, including full work-RAM checks.
  The bit-test/bit-branch/BSR batch passed 480 comparisons per tier.
  The MPR batch passed 524 sequences and 1,614 instruction-state comparisons
  per route; its native-first route includes counted fallback after mapping
  changes. See the same verification scope for exact totals and limits.
  CSL/CSH checks match 120 CPU/speed states per tier. Live traces expose
  28 transition-timing differences per tier against Geargrafx 1.8.4; the
  runtime follows Mesen/Beetle's final-cycle speed-change rule.
- Optional user-supplied 256 KiB System Card ROM mapping, with read-only
  protection and synthetic firmware loader tests. See [firmware scope](docs/FIRMWARE.md).
- Limited idle CD control and **volatile 2 KiB BRAM**: `$1807` access control,
  `$1803` read-to-lock, ACK/IRQ-enable/reset state, physical MPR aliases and
  protected/hole writes. Geargrafx checks passed 720 CPU/device states per
  tier and 48 complete work-RAM/BRAM comparisons per tier.
  See [implemented registers and reference differences](docs/CD_CONTROL.md).
- Opt-in clocked CD selection and command handshake: separate host/drive data
  latches at `$1801`, REQ/ACK reception, six-byte TEST UNIT READY, and delayed
  status/message completion with an IRQ2 source. Sector reads, sense, TOC,
  subcode and audio remain unsupported. Drive delays follow an explicit
  reference-emulator profile; GOOD status does not certify readable media.
  Geargrafx checks passed **743 settled CPU/device checkpoints and 21 full
  work-RAM/BRAM comparisons per tier**, including reset and ACK edge sequences.
  See [CD transport scope](docs/CD_CONTROL.md).
- Functional single-VDC register ports, 64 KiB VRAM, buffered reads, address
  increments, register masks and direct ST0/ST1/ST2 instructions. Mapped
  accesses include a fixed CPU wait. DMA triggers and undriven VRAM reads
  stop explicitly; rendering and dynamic VRAM contention remain unfinished.
  Geargrafx checks passed 856 settled CPU/VDC states and 48 complete
  work-RAM/VRAM comparisons per tier.
  See [VDC semantics and limits](docs/VDC.md).
- Opt-in master-clock video timing: programmable horizontal/vertical phases,
  VBlank and raster-comparison events, latched status/IRQ acknowledgement, and
  VCE timing control. Native and interpreted instructions both advance the
  device clock. CPU bus phases remain an instruction-level approximation;
  interrupt delivery, palettes, rendering and DMA remain unfinished.
  Geargrafx checks passed **4,165 exact-clock device checkpoints and 15 guest
  status acknowledgements** across 15 authored timing plans.

An owner-supplied Ys III USA CHD exercised the real input pipeline locally:
25 tracks inspected, 4 KiB initial program extracted, 203 instruction sites
discovered, with all 203 now emit-able. A private snapshot including a verified
USA v3.0 BIOS now passes the former VDC fault and VBlank wait using the
clocked reference profile. It now passes the `$1801` port fault and receives
a complete ten-byte CD directory/TOC command. The bounded run retires
**12,207 native plus 13,614 interpreted instructions**, observes one VBlank
event and stops explicitly at logical `$EA4A` when dispatching unsupported
command `$DE`. A real TOC response and DATA IN/media backend are next.
**This was not a disc read or game boot.**
No disc bytes, generated game source, BIOS, or saves are included.
Native-module ABI is **6**, including clocked CD transport state alongside
the video clock. Regenerate older modules and rebuild their consumers together.
BRAM has no file persistence.

Contributor issues were reviewed on 22 October 2026: [RMB/SMB #1](https://github.com/rages4calm/pcenginerecomp/issues/1)
and [stack semantics #2](https://github.com/rages4calm/pcenginerecomp/issues/2)
are complete. [Media fixtures #3](https://github.com/rages4calm/pcenginerecomp/issues/3)
and [cycle-aware traces / second oracle #4](https://github.com/rages4calm/pcenginerecomp/issues/4)
remain open. Focused CPU timestamp and idle CD-control checks exist; a second live
reference adapter and general bus/event traces are still needed.

## Build and test

Use Python 3.11+, CMake 3.20+, and a C++20 compiler. Ninja is used below;
MSVC, GCC, and Clang are intended hosts. Only the tested configurations in
[status](docs/STATUS.md) are confirmed locally. The CI template defines the
intended public matrix and currently requires activation.

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
python scripts/check.py
```

Clang can be selected with `-DCMAKE_CXX_COMPILER=clang++`. CTest is also
supported: `ctest --test-dir build --output-on-failure`.

The frontend works directly from a checkout without installing packages:

```sh
python -m pcerecomp doctor
python -m pcerecomp --help
python -m pcerecomp inspect "/path/to/your/disc.chd" --hash
```

For optional project-local CHD decompression, install no system components;
the following command explicitly fetches the pinned libchdr source and
builds it under `.deps/` (requires Git, CMake, Ninja and a C compiler):

```sh
python scripts/bootstrap_chd.py --cc clang
python -m pcerecomp boot "/path/to/your/disc.chd" --out .local/my-game/boot
python -m pcerecomp analyze .local/my-game/boot/snapshot.toml --out .local/my-game/analysis.json --listing
python -m pcerecomp emit .local/my-game/boot/snapshot.toml --out .local/my-game/native
```

Use an empty boot/native output directory. Pass `--libchdr /path/to/library`
if it is outside the default `.deps/libchdr-build` location. See
[the developer guide](docs/DEVELOPMENT.md) for running a generated module.

## Direction and contribution

| Read | Purpose |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Execution model, bank identity, runtime boundaries and state ownership |
| [CPU semantics](docs/CPU_SEMANTICS.md) | Instruction contracts, status flags, stack wrapping and verification |
| [VDC semantics](docs/VDC.md) | Video ports, VRAM, raster events, clock phases and explicit limits |
| [CD semantics](docs/CD_CONTROL.md) | Command handshake, reference timing, BRAM and explicit transport limits |
| [Research](docs/RESEARCH.md) | Primary sources, pinned references, existing tools and design decisions |
| [Roadmap](docs/ROADMAP.md) | Full feature target, dependencies and acceptance criteria |
| [Status](docs/STATUS.md) | Verified baseline, known limitations and next useful batch |
| [Development](docs/DEVELOPMENT.md) | Reproduce builds, run the CLI and understand private outputs |
| [Contributing](CONTRIBUTING.md) | Review standards and useful contributor work |

Full CPU semantics, an independent reference harness, cycle scheduling,
System Card integration, video, sound, CD services, saves, and a desktop
host come before a playable release. Widescreen, high-refresh presentation,
mods, localization, achievements, rewind, and netplay are part of the target
architecture, with separate implementation and qualification milestones.

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
