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

CTest registers 17 suites: frontend, CPU runtime, CD control, VDC ports,
raster, CD transport, joypad, READ, provider, block transfers, IRQ/RTI,
palette/snapshot, DMA, PSG, ADPCM, CDDA and input scripts.
`scripts/check.py` runs the same suites directly for toolchains without `ctest`.
The complete suite count is 17; the final frontend count is 112 Python tests.
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

The separate `pce-vdc-tests` module checks 77,824 expected CPU cases, 8,192
register-width cases and 392,991 VRAM transfer/address cases. It covers the
opt-in single-VDC profile and serves as its independent-reference probe. See [VDC.md](VDC.md) for port,
register, VRAM and timing contracts and deliberately unsupported behavior.

The separate `pce-raster-tests` module checks 977 groups of literal event
boundaries, VBlank/RCR enable gating, acknowledgement, phase latches and
unsupported operations. These include 161 direct device groups and 816 bus
checks covering all eight VCE timing controls, MPR pages and port mirrors,
fixed waits, generation stability and unsupported/disabled ports. Its 240,015
cadence/alias/speed/refusal checks exercise native and interpreted NOP
retirement at both CPU speeds, multiple frame boundaries and
unchanged clocks on a deadline or source-guard miss. Its `--clock` mode is a
direct device probe for the independent reference, not native instruction
evidence. See [REFERENCE.md](REFERENCE.md) for reproducible Geargrafx checks.

The separate `pce-scsi-tests` module exercises the opt-in clocked CD transport
with authored work-RAM code: 8,369 control groups, including 4,096 latch/control byte
groups and 4,096 RMW groups, plus directed checks. It covers
selection and command-byte deadlines, TEST UNIT READY completion, status/message
acknowledgement, reset cancellation, held ACK, unsupported commands, IRQ2
refusal, native source guards and execution budgets. Its `--probe` mode supplies
settled transaction observations for the Geargrafx `--suite scsi` adapter;
it uses real generated/interpreted NOPs for bounded settling delays. No retail
firmware, sector backend or save file is required. See [CD_CONTROL.md](CD_CONTROL.md).
Its TOC extension separately checks 418 groups of literal directory responses, DATA IN,
manual/auto-ACK deadlines, reset/selection aborts and refusal boundaries.
`--probe-toc` supplies observations for the independent `--suite toc` adapter.
Frontend tests cover disc geometry, descriptor formatting and protected
inputs; headless tests exercise untrusted parser boundaries and exporter/parser
interoperability with entirely authored ISO data.

The separate `pce-joypad-tests` module uses authored port-access code and
independently expected controller nibbles, control edges, tap scans, output
latching, region/CD bits, mapping aliases and guard/deadline refusal. Headless
host tests separately cover CLI configuration and input immutability. See
[INPUT.md](INPUT.md) for the selected reference profile and option format;
[REFERENCE.md](REFERENCE.md) records the live Geargrafx scope.

The generated synthetic test module is always separate from the module
selected for `pce-headless`; a local title experiment cannot silently
substitute game bytes into public tests.
The host tests use the headless executable from the selected build directory
(`PCE_TEST_HEADLESS` under CTest or `scripts/check.py`). See
[FIRMWARE.md](FIRMWARE.md) for private ROM loading and current execution scope.
Runtime ABI **11** adds IRQ/timer, functional palette/DMA, PSG/ADPCM/CDDA state
and bounded scripted-input support. ABI 10 added completed block counters and block-aware access/clock
contracts; modules emit their own block loops. ABI 9 added the sector buffer, provider ownership and load scheduler.
ABI 8 added controller configuration, sampled buttons and joypad protocol
state; ABI 7 added TOC metadata, bounded DATA IN and auto-ACK state; ABI 6
introduced clocked CD transport, ABI 5 introduced the
video-clock execution contract, ABI 4 introduced VDC
state, ABI 3 introduced CD-control bus state and
ABI 2 introduced the MPR latch.
Regenerate older modules and rebuild consumers; the generated assertion rejects
mixing versions. The reference probe's optional MPR sequence mode counts native
execution and interpreter fallback separately after mapping changes.
The speed suite checks both entry divisors and CSL/CSH transitions through
bounded CPU traces. Its explicit result is `architectural_pass_timing_discrepancy`:
state/speed agrees with Geargrafx, while transition ticks follow Mesen/Beetle
and differ from Geargrafx 1.8.4. Do not summarize this as timing parity.
The CD-control suite separately verifies byte-level CPU/device state against
Geargrafx using authored CD media. It does not resolve those timing differences.

## Block-transfer checks

`pce-block-tests` uses wholly authored code and an independent byte-array model.
It checks 1,600 transfers, 5,120 status/stack-pointer matrix cases, source/mapping
and deadline guards, block I/O/VDC waits and deferred IRQ boundaries. Four local
TAI cases deliberately overwrite the active opcode; those are excluded from
live Geargrafx parity because its implementation refetches the opcode. The zero-length
cases execute the full 65,536 bytes. Entire work RAM and changed-byte generations
are compared, including stack aliases; completion counters count instructions
separately from payload bytes. MMIO instruction checks are interpreted; both-tier
RAM and deferred-IRQ cases qualify the generated operations separately.

With `PCE_BUILD_REFERENCE_PROBE=ON`, `pce-block-probe` supports the independent
Geargrafx adapter in `scripts/block_reference.py`. See REFERENCE.md for the actual
live matrix, clock totals and exclusions. No media is required by local tests.
The headless JSON reports `native_block_steps`, `interpreter_block_steps` and
`block_bytes` for completed operations. Partial fatal transfers do not retire or
increment these completion counters.

## IRQ and functional device checks

`pce-irq-tests` checks 65,536 independent entry cases, 262,144 RTI status/stack
cases, 32 sampling sequences, 15 guard/mapping/deadline groups and 779 IRQ/timer
register groups. The optional `pce-irq-probe` plus `scripts/irq_reference.py`
compare real pending sources in Geargrafx with corresponding injected request
lines in the local probe. The live matrix passes 832 plans per tier, 2,496 CPU
states, 832 full RAM images and 832 sequence tick deltas. Those comparisons
qualify aggregate instruction boundaries, not physical device access phases.

`pce-video-tests` checks 628,214 palette/snapshot expectations, and
`pce-dma-tests` checks 14,786 DMA expectations. The optional `pce-video-probe`
and `scripts/video_reference.py` compare settled VCE/VRAM/SATB results with
Geargrafx. Current-state RGB inspection has separate local pixel expectations;
it is not covered by that direct-device live adapter. See [VDC.md](VDC.md).

`pce-audio-tests` checks PSG register/waveform/DDA/noise/LFO storage;
`pce-adpcm-tests` checks RAM, delayed ports, length/playback consumption and
CD DMA. The optional `pce-audio-probe` and `scripts/audio_reference.py` compare
settled manual ADPCM/PSG ports against Geargrafx; playback/DMA/oscillator/PCM
qualification is explicitly excluded. `pce-cdda-tests` checks 7,134 audio
control/position/fader and explicit unknown-response-profile expectations;
its seek/sector profile is documented in
[CD_AUDIO.md](CD_AUDIO.md), without a live CDDA or audible-output claim.

All these public fixtures are authored and use no retail input. Build optional
probes with `-DPCE_BUILD_REFERENCE_PROBE=ON`; the precise run commands and
successful reference scope are in [REFERENCE.md](REFERENCE.md). Keep at most
two isolated reference children active and retain bounded summaries rather
than repeated full memory/trace dumps.

## Metadata-only TOC attachment

```sh
python -m pcerecomp toc "/path/to/disc.chd" --out .local/title/disc.toc
```

This command reads CHD metadata and hashes the source without decompression.
A single-track cooked ISO is also supported. Its bounded `PCE_TOC 1`
descriptor records the source SHA256 and disc INDEX 01/leadout LBAs; it
contains no sectors. Keep it under `.local/`; `*.toc` is ignored and the
publication audit rejects descriptors. The exporter refuses an output alias
of the original input.

Pass `--toc .local/title/disc.toc` to the headless runner, alongside `--bios`
in either order if firmware is needed. The runner validates descriptor syntax
and geometry but does not reopen or rehash the original image. Attachment
alone provides directory responses without readable sectors or the extended
audio profile. `--toc`
alone enables transport/volatile BRAM, without enabling the video profile.
See [CD_CONTROL.md](CD_CONTROL.md) for the exact format, pregap/postgap policy,
BCD bounds and reference discrepancies. Metadata-only attachment does not
supply bytes. To attach an actual read-only image, add `--disc /path/to/disc.iso`
or `--disc /path/to/disc.chd --libchdr /absolute/path/to/libchdr.dll` (use the
shared-library suffix for your host). An existing `--toc` must match the actual
image SHA256 and geometry exactly; without it the provider derives both.
The host hashes the full image once, then reads sectors on demand with one
bounded CHD hunk cached. No extraction is required. Its JSON reports provider,
load/byte/error counters and pure source peeks at the stopped PC, including
overlays. The image is never opened for writing.

`pce-read-tests` checks 621,096 independent READ expectations.
`pce-sector-tests` checks 22,568 provider expectations and requires the built
`pce-sector-decoder-fixture` module path; CTest/check.py supply it. That authored
ABI double tests CHD geometry/cache handling without optional libchdr, and is
not a real CHD decompression test. The generic source build has no libchdr
link dependency; `${CMAKE_DL_LIBS}` supplies portable optional dynamic loading.

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

For a BIOS-backed extended run, `--bios /path/to/syscard.pce` enables IRQ/timer,
functional VCE/DMA and audio state alongside CD transport. Add `--disc` for
real read-only sector access; TOC metadata alone cannot supply bytes. Explicit
step budgets permit up to 500,000,000 instructions. A budget exit, visible
state inspection or functional audio command completion does not certify
playability or full native/AOT execution.

`--frame-out .local/title/state.ppm` exports one bounded P6 RGB image from the
stopped state. Existing output paths are refused. This inspection reads current
VRAM, SATB, palette and registers without advancing clocks; it cannot reproduce
historical scanline effects. Unsupported grayscale/two-bit-background or
undriven-VRAM inspection still faults. Keep retail images private.

Use `--input-script .local/title/input.txt` for reproducible input transitions:

```text
PCE_INPUT 1
# Master tick, then five active-high button masks.
0 0 0 0 0 0
21477273 8 0 0 0 0
21835227 0 0 0 0 0
```

This authored example presses Run on pad one after approximately one guest
second and releases it later. Each event has exactly six unsigned decimal or
`0x` hexadecimal fields. Ticks must increase strictly; button masks are at most
`0xFFF`. Files are ASCII, at most 16 KiB and 256 events, with a `PCE_INPUT 1`
header. Events apply at the first instruction boundary at or after the stated
tick. They update host snapshots; the joypad still relatches only on guest
control writes. A long block transfer can cross an input deadline before the
next boundary. These files are input recipes, not save states or desktop input
configuration. `pce-input-script-tests` verifies parser bounds and malformed
inputs. Do not publish game-derived timing/trace data with the public fixtures.

Unknown CD command IDs fault by default. For explicit compatibility research,
`--cd-unknown-status gear-good` selects the source-documented Geargrafx/Mesen
one-byte unknown-command GOOD-response quirk; the JSON records the selected
policy and `unknown_commands` counter. Known commands with unsupported
operations, including REQUEST SENSE, still fault. Selecting the quirk does
not implement an unknown command's operation or qualify its hardware behavior.
The current retail menu-to-story route is conditional on this opt-in; strict mode
retains the unknown-command stop. Keep that distinction in every result claim.

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
