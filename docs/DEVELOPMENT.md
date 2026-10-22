# Developer guide

## Layout

```text
pcerecomp/       Python media, decoder, CFG and C++ emitter
runtime/        C++20 state, bus, partial interpreter and headless host
tests/          Authored synthetic fixtures and native comparison harness
scripts/        Dependency bootstrap, test runner and publication audit
docs/           Architecture, sources, roadmap and current status
.local/         Ignored private images-derived snapshots/reports/modules
.deps/          Ignored optional dependency source/build
.research/      Ignored downloaded reference material
build/          Ignored CMake outputs, including synthetic generated module
```

## Reproducible baseline

Python 3.11+, CMake 3.20+, C++20, and Ninja for the commands below. There are
no third-party Python runtime requirements. A source checkout can be used
without `pip install`. An optional install provides the `pcerecomp` command.

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 4
python scripts/check.py
```

For a Clang build append `-DCMAKE_CXX_COMPILER=clang++` on configure. For an
MSVC build use an initialized developer shell or the appropriate Visual
Studio generator. With a multi-configuration generator build with
`--config Release` and use `ctest --test-dir build -C Release`.
The convenience test runner expects binaries directly under `--build`;
use CTest for multi-configuration generators.

CTest registers frontend, runtime and CD-control suites. `scripts/check.py`
runs all three directly for minimal toolchains that lack a `ctest` binary.
The C++ suite checks generated instructions against the interpreter and also
checks 92,160 independently expected bit/stack cases, 7,340,032 arithmetic/
logic cases, 340 addressing cases, 3,932,160 RMW cases, 16,384 indirect
JMP cases, 4,849,664 bit-test cases, 2,228,224 bit-branch/BSR cases and
1,114,112 MPR/latch cases and 524,288 speed cases,
plus source guards, mapping aliases and explicit faults. Synthetic host tests
exercise optional firmware mapping, call/return and rejection/protection rules.
See [CPU_SEMANTICS.md](CPU_SEMANTICS.md)
for the status and cycle contracts and [REFERENCE.md](REFERENCE.md) for the
optional independently developed emulator comparison.
The separate `pce-io-tests` module adds 61,440 expected CD-control/BRAM
instruction cases and doubles as the CD reference probe. Its entirely
authored fixture uses MPR aliases for hardware and BRAM and tests locked/
upper-hole writes, RMW side effects, deadlines, guards and unsupported reads.

The generated synthetic test module is always separate from the module
selected for `pce-headless`; a local title experiment cannot silently
substitute game bytes into public tests.
The host tests use the headless executable from the selected build directory
(`PCE_TEST_HEADLESS` under CTest or `scripts/check.py`). See
[FIRMWARE.md](FIRMWARE.md) for private ROM loading and current execution scope.
Runtime ABI 3 includes CD-control bus state; ABI 2 introduced the MPR latch.
Regenerate older modules and rebuild consumers; the generated assertion rejects
mixing versions. The reference probe's optional MPR sequence mode counts native
execution and interpreter fallback separately after mapping changes.
The speed suite checks both entry divisors and CSL/CSH transitions through
bounded CPU traces. Its explicit result is `architectural_pass_timing_discrepancy`:
state/speed agrees with Geargrafx, while transition ticks follow Mesen/Beetle
and differ from Geargrafx 1.8.4. Do not summarize this as timing parity.
The CD-control suite separately verifies byte-level CPU/device state against
Geargrafx using authored CD media. It does not resolve those timing differences.

## Optional CHD backend

```sh
python scripts/bootstrap_chd.py --cc clang
```

This explicitly fetches a pinned source revision, refuses an existing dirty
or differently pinned checkout, and builds a shared libchdr locally. It does
not install anything system-wide. The default backend has no network fetch
during its CMake build. Source acquisition uses GitHub and can be performed
ahead of time. An existing compatible library can instead be supplied with
`--libchdr`. Metadata-only `inspect` does not need the library.

## A private image experiment

```sh
python -m pcerecomp inspect "/path/to/disc.chd" --hash --out .local/title/disc.json
python -m pcerecomp boot "/path/to/disc.chd" --out .local/title/boot
python -m pcerecomp analyze .local/title/boot/snapshot.toml --out .local/title/analysis.json --listing
python -m pcerecomp emit .local/title/boot/snapshot.toml --out .local/title/native
```

Boot/native output directories must be empty to avoid replacing a different
experiment. Analysis JSON can be regenerated in place. Default CFG budget
is 10,000 instructions, with a hard accepted maximum of 100,000. The CHD
reader keeps four hunks in memory. Only IPL-declared boot sectors are read;
this command does not extract a BIN/WAV copy of the disc.

For a single physically contiguous boot segment, link the generated module
by passing its **absolute** path to CMake:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_MODULE_SOURCE=/absolute/private/title/native/module.cpp
cmake --build build
```

The headless runner's positional arguments are:

```text
pce-headless IMAGE PHYSICAL_LOAD PC MPR_CSV MAX_STEPS MAX_TICKS native|hybrid
```

Take the load address, entry and mapping from your snapshot. For the
standard CD RAM analysis mapping, an example is:

```sh
build/pce-headless .local/title/boot/boot-0.bin 0x100000 0x4000 255,248,128,129,130,131,132,0 100 100000 hybrid
```

On Windows use `build/pce-headless.exe`. A JSON result reports stop reason,
registers, cycles/ticks and native/interpreter counters. Exit **0** means a
step or tick boundary was reached, **2** is invalid input, **3** is an
unsupported instruction, guard miss in native-only mode, or bus fault.
An explicit unsupported stop is useful development evidence; it is not a
successful boot. The runner handles one contiguous payload only; it does
not reconstruct an authentic firmware-initialized machine.

Clear a private module selection before returning to the generic sandbox:

```sh
cmake -S . -B build -DPCE_MODULE_SOURCE=
cmake --build build
```

## Snapshot schema 1

A hand-authored snapshot pins physical byte segments. Each file is resolved
relative to the TOML file; source SHA256 is verified before analysis.

```toml
schema = 1
mpr = [255, 248, 128, 129, 130, 131, 132, 0]
entry_points = [16384]

[[segments]]
physical = 1048576
file = "your-private-code.bin"
sha256 = "replace-with-the-actual-segment-sha256"
```

TOML/JSON snapshots and generated modules contain original program bytes or
translated logic. Keep them private even if the filename itself is not an
image extension. `module.json` reports emission counts; it is not execution
evidence. `.gitignore` is a convenience, not authorization to publish data.

## Publishing source

The initial GitHub credential permits source publication but lacks the
`workflow` scope needed to publish Actions workflows. The reviewed pipeline
is retained as `.github/ci-template.yml`; it does not execute in that location.
After the repository owner authorizes `gh auth refresh -h github.com -s workflow`,
copy that file to `.github/workflows/ci.yml`, commit and push. The template
runs synthetic tests on Windows/Linux/macOS and builds the optional pinned
CHD backend. It uses no game input. A template is not a passing CI run.

Stage only authored source, synthetic tests and documentation, inspect
`git diff --cached`, then run `python scripts/audit_public.py`. The audit
checks tracked paths, simple credential/personal-path patterns, text/binary
content and size caps. It is a focused publication check, not a complete
secret, copyright or license scanner. CI uses no retail inputs and uploads
no title-derived artifacts.
