# PC Engine Recomp

An open, experimental static recompilation toolkit for **PC Engine /
TurboGrafx-16 and CD-ROM²** games. The goal is a shared foundation for native
ports with modern rendering, audio, input, debugging, and game-specific
enhancements.

**Current status: architecture and executable compiler foundation. No game
is playable or certified.** The decoder describes all 256 HuC6280 opcode
slots; the initial native emitter and interpreter implement 47 opcodes.
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
  debugger: 188 native and 188 interpreter comparisons passed locally.

An owner-supplied Ys III USA CHD exercised the real input pipeline locally:
25 tracks inspected, 4 KiB initial program extracted, 203 instruction sites
discovered, 149 sites emitted, and six native instructions executed before
an explicit unsupported-instruction stop. **This was not a game boot.**
No disc bytes, generated game source, BIOS, or saves are included.

## Build and test

Use Python 3.11+, CMake 3.20+, and a C++20 compiler. Ninja is used below;
MSVC, GCC, and Clang are intended hosts. Only the tested configurations in
[status](docs/STATUS.md) are confirmed locally; CI tests the public matrix.

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
