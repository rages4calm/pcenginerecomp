# PC Engine Recomp

An open, experimental static recompilation toolkit for **PC Engine /
TurboGrafx-16 and CD-ROM²** games. The goal is a shared foundation for native
ports with modern rendering, audio, input, debugging, and game-specific
enhancements.

**Current status: experimental compiler/runtime with locally demonstrated
Ys III mine progression, volatile guest SAVE/LOAD and an explicitly assisted
first-storehouse-boss encounter with observed enemy damage.
No complete game port is certified.** The decoder
describes all 256 HuC6280 opcode slots; the native emitter and interpreter
implement 233 opcodes, including
load/store addressing, logical operations, ADC/SBC with T/decimal handling,
comparisons, shifts/rotates, INC/DEC, indirect JMP, RMB/SMB and all eight
push/pop instructions, BIT/TSB/TRB/TST, bit branches, BSR and TAM/TMA with
persistent transfer-latch semantics, plus CSL/CSH speed control and
ST0/ST1/ST2 VDC port writes, all five block transfers and RTI. The runtime
includes continuous video from guest scanline/palette history and an optional
SDL3 desktop window with keyboard/gamepad input, pause and fullscreen. The
opt-in loopback development server adds status, controller input, bounded
frame advancement, requested guest/SDL captures and paused physical-memory
inspection for either runner. Explicitly enabled, expected-byte-guarded RAM
edits support reproducible assisted tests; edits are counted and remain
separate from ordinary gameplay qualification. See [TCP debugging](docs/DEV_SERVER.md).
The BIOS-backed Ys III experiment advances through its opening into controllable
town navigation, equipment selection and first-mine attacks, enemy rewards,
received damage, death/retry and normal guest SAVE/LOAD. This conditional gameplay milestone requires the explicit
`--cd-unknown-status gear-good` reference-emulator response profile; strict
default mode still faults on the encountered unknown CD command. This is
not an implementation or certification of that unknown command.
Decoded, emitted, compiled, and executed are different milestones here.

The shared toolkit supports multi-context native promotion and hash-pinned
consumer builds. On the retained 93,735-frame Ys III test route,
executed native instruction coverage rises from **0.173% to 99.99997%**.
This measures that route, including firmware/wait loops; unvisited code and
complete-game compatibility still require qualification.

Large observed-code modules now build as separately compiled translation
units, shared by headless and desktop hosts. Native dispatch selects exact
opcode/operand keys instead of scanning source variants; every instruction
byte is still checked before guest state changes. Consumer builds pin every
generated source and header. See [performance measurement](docs/PERFORMANCE.md)
for the benchmark and its scope.
The local Windows x64 comparison compiles the full module in **70.5 seconds
versus 353.2 seconds**, and five alternating authored dispatch samples show
**9.5% higher throughput** with identical results. These measurements cover
module compilation and an authored CPU workload, separately from game testing.
The bounded Ys III bootstrap's whole-process difference is about **1.4%**;
no campaign-wide speedup is claimed.

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
- Direct C++20 emission with mapping and source-byte guards. Unmatched code
  falls back to the interpreter when supported, or exits explicitly.
- Opt-in [retired-code capture](docs/CODE_CAPTURE.md) records exact executed
  instruction identities and per-tier hit counts. Offline `emit-capture`
  supports multiple full MPR contexts, overlays and source-byte variants,
  with direct translated operations and guards before guest mutation.
  Adaptive partitions and exact operand-key dispatch support larger captures;
  CMake compiles each selected module once for both hosts.
  Captures and game-derived modules remain private.
- A [consumer-project interface](docs/CONSUMER.md) pins tool source, ABI,
  module and input identities, builds against the shared runtime, and records
  actual native/interpreted execution. The [authored example](examples/consumer/README.md)
  builds and runs without game or firmware data.
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
- Limited idle CD control and **volatile 2 KiB BRAM**: `$1807` access control
  and Gear-reference gate readback,
  `$1803` read-to-lock, ACK/IRQ-enable/reset state, physical MPR aliases and
  protected/hole writes. Geargrafx checks passed 720 CPU/device states per
  tier and 48 complete work-RAM/BRAM comparisons per tier.
  Both runners accept `--bram RAW_2048_IMAGE` to read an exact 2,048-byte
  initial image into existing volatile BRAM. The file is never modified;
  there is no automatic formatting, export or host save persistence. Omitting
  the option preserves blank BRAM. TCP status and final JSON report
  `cd_control.bram_seeded`. See [BRAM initialization scope](docs/REFERENCE.md#initial-bram-image-and-authentic-format-provenance).
  See [implemented registers and reference differences](docs/CD_CONTROL.md).
- Opt-in clocked CD selection and command handshake: separate host/drive data
  latches at `$1801`, REQ/ACK reception, six-byte TEST UNIT READY, and delayed
  status/message completion with an IRQ2 source. REQUEST SENSE and raw
  subchannel capture remain unsupported. Drive delays follow an explicit
  reference-emulator profile; GOOD status does not certify readable media.
  Geargrafx checks passed **743 settled CPU/device checkpoints and 21 full
  work-RAM/BRAM comparisons per tier**, including reset and ACK edge sequences.
  See [CD transport scope](docs/CD_CONTROL.md).
- Directory/TOC command `$DE` modes 0/1/2, BCD track/MSF conversion and leadout
  selection, four-byte DATA IN responses, manual and `$1808` auto-ACK, data IRQ
  sources and reset/transfer aborts. A bounded `pcerecomp toc` exporter accepts
  CHD metadata or a single-track ISO; `pce-headless --toc` attaches the resulting
  descriptor. This supplies metadata responses; sector attachment is separate.
  Geargrafx/Mesen and Beetle differ on response lengths; the selected four-byte
  profile and exact limits are in [CD semantics](docs/CD_CONTROL.md).
  Geargrafx checks qualified **25 of 26 plans: 1,964 settled checkpoints and
  25 full work-RAM/BRAM comparisons per tier**. One pending-response reset case
  remains unqualified after reproducible crashes of the isolated reference.
- TII, TDD, TIN, TIA and TAI block transfers: forward/backward/fixed/alternating
  addresses, 16-bit wrapping, zero length as 65,536 bytes, sequential overlap,
  genuine stack saves/restores and operands fetched after those saves. Generated
  C++ contains the copy operations directly. Guest clocks progress per byte;
  VDC waits and block-specific I/O reads are explicit. See
  [CPU semantics](docs/CPU_SEMANTICS.md) for timing, atomic deadline and IRQ limits.
  Geargrafx checks pass **810 completed-instruction CPU states, full 8 KiB RAM
  comparisons and total clock deltas per tier**, including all five zero-length
  operations. Exact per-byte bus phases and hardware behavior remain unqualified.
- CD READ `$08`: 21-bit LBA, zero-count-as-256, bounded 2 KiB DATA IN
  streaming, manual/automatic ACK, backpressure, reset and explicit failures.
  `pce-headless --disc` attaches a read-only ISO/CHD provider with actual-image
  SHA256 binding, bounded CHD caching and no extraction. CHD requires an explicitly
  selected optional libchdr library. The deterministic 1x access profile does
  not model distance-dependent seeks or initial jitter. Geargrafx checks pass
  **seven plans, 201 settled CPU/device checkpoints and seven complete sectors
  (14,336 payload bytes) per tier**. Local READ/provider expectations pass
  **621,096 / 22,568 checks**; see [CD semantics](docs/CD_CONTROL.md).
- Functional single-VDC register ports, 64 KiB VRAM, buffered reads, address
  increments, register masks and direct ST0/ST1/ST2 instructions. Mapped
  accesses include a fixed CPU wait. The extended video profile adds palette
  ports and VRAM/SATB DMA; undriven VRAM reads still stop explicitly.
  Physical VRAM contention and fetch phases remain unfinished.
  Geargrafx checks passed 856 settled CPU/VDC states and 48 complete
  work-RAM/VRAM comparisons per tier.
  See [VDC semantics and limits](docs/VDC.md).
- Opt-in master-clock video timing: programmable horizontal/vertical phases,
  VBlank and raster-comparison events, latched status/IRQ acknowledgement, and
  VCE timing control. Native and interpreted instructions both advance the
  device clock. CPU bus phases remain an instruction-level approximation;
  exact access phases remain unfinished.
  Geargrafx checks passed **4,165 exact-clock device checkpoints and 15 guest
  status acknowledgements** across 15 authored timing plans.
- IRQ priority, mask/status registers, clocked timer, eight-cycle interrupt
  entry and seven-cycle RTI in both execution tiers, including delayed CLI/PLP
  recognition and already-sampled requests after SEI. Geargrafx passed **832
  plans per tier: 2,496 CPU states, 832 complete RAM images and 832 sequence
  clock deltas**. This qualifies the documented instruction-boundary profile,
  with finer MMIO/timer access phases still excluded.
- VCE's 512-entry palette, VRAM/SATB DMA and bounded RGB state inspection.
  Geargrafx passed **12 direct-device plans**, including complete VRAM, SATB
  and palette comparisons and 1,024 guest palette-read bytes. With
  `--video-output snapshot`, `--frame-out` inspects current storage and registers.
  Continuous mode instead saves the last completed historical frame.
  See [video scope](docs/VDC.md).
- Continuous software video preserves line history and converts the live VCE
  palette at every emitted guest dot. BXR/BYR, CR/burst and MWR latches,
  background/sprite priority and bounded completed-frame publication are
  implemented. Geargrafx comparisons pass **16 complete 256 × 192 images /
  786,432 RGB pixels**, including midline palette, scroll and VRAM changes.
  Local expectations pass **3,950 checks**. See [continuous video](docs/VIDEO_OUTPUT.md)
  for the selected line-buffer profile, state contract and remaining limits.
- Optional SDL3 desktop host: nearest-neighbor streaming texture, integer
  letterboxing, resizing, fullscreen, pause/resume, keyboard and gamepad input,
  focus release and guest-master-clock pacing. The default build has no SDL
  dependency. See [desktop controls and scope](docs/DESKTOP.md).
- Opt-in local TCP development control: status, five controller masks,
  pause/resume, bounded frame stepping, guest or composed SDL RGB captures,
  and orderly quit. Both hosts preserve normal guest input sampling. The
  standard-library Python client can save requested images as new PNG/PPM
  files. The server is disabled by default and binds only loopback; it receives
  no file paths. See [development protocol and bounds](docs/DEV_SERVER.md).
- Functional six-channel PSG register/waveform/DDA/noise/LFO storage and ADPCM
  RAM, delayed ports, length/playback consumption, IRQs and CD DATA IN DMA.
  Geargrafx passed **eight settled device plans and 292 guest read bytes**;
  ADPCM playback/DMA and PSG oscillators are outside that live check.
  CDDA D8/D9/DA/DD implements a clocked position/control timeline and fader.
  **PCM decoding, mixing and audible output remain unimplemented.** See
  [audio control scope](docs/CD_AUDIO.md) and [reference evidence](docs/REFERENCE.md).

- Opt-in joypad I/O throughout the hardware-bank `$1000..$13FF` window:
  active-low two/six-button pads, a five-port TurboTap, region/CD-presence
  bits, latched guest-write sampling.
  The selected Geargrafx reference profile and differences from Mesen/Beetle
  are documented in [controller semantics](docs/INPUT.md). The optional desktop
  host maps its live input to pad one; turbo generation and other peripherals
  remain unfinished. Independent local
  expectations pass **50,341 cases/groups**, with eight synthetic headless
  configuration tests. Geargrafx checks pass **56 plans, 2,512 CPU/port-read
  checkpoints and 56 complete work-RAM comparisons per tier**, covering USA
  region with CD hardware present and absent.

The general toolkit is exercised with an owner-supplied Ys III USA CHD. A
**60,338-frame ordinary-input route** reaches LEVEL 2, the four-exit mine
junction, combat and normal guest SAVE/LOAD. Its retained baseline-host replay
matches **14 complete checkpoint images and all original final
CPU/device/source diagnostics**, with zero RAM edits.

A separate, explicitly authorized assisted route reaches the **first
storehouse boss at frame 93,212**. Its approach uses health assistance,
queued ascent and height-held traversal, followed by an ordinary room
transition and Up door entry. During **523 boss frames**, ordinary II attacks
visibly reduce the ENEMY bar while the wizard teleports and attacks. Only
**14 current-health refills** occur during the fight; no code, position,
queue, inventory or quest edits occur after entry. Original jump code is
restored beforehand. This establishes an assisted encounter and enemy
damage, not victory or unassisted completion.

The original 785-identity module executes **5,050,558 native and
2,915,442,205 interpreted instructions** on that 93,735-frame route. Bounded
profiling observes **44,836 identities in 57 full MPR contexts** without loss.
The expanded module compiles **44,832 identities** and executes
**2,920,491,782 native instructions and 981 interpreted**, including all
460,685 block transfers natively. The entire temporary code-patch span is
excluded from promotion; original and patched identities there stay interpreted.
The unchanged raw capture and exclusion counts remain separately recorded.

A fresh optimized, partitioned-module SDL/TCP replay matches **25 complete guest PNG hashes,
all 709 existing RAM interventions and every exposed final guest
CPU/device/source diagnostic**. Its complete guest runner report also equals
the previous full-native run, including all tier and guard counts.
Total retirements, guest clocks, source generations and device results stay
exact; ephemeral TCP port and additive SDL host telemetry are checked separately.
It reads **1,181 sectors with zero errors** and retains no new image files.
The comparison excludes whole RAM and composed-window pixels. Complete accounting belongs in
[status](docs/STATUS.md) and [reference evidence](docs/REFERENCE.md).

Reusable development features include paused RAM/ROM inspection and explicit
`--dev-memory-write on` RAM edits with whole-range expected-byte checks,
source invalidation and counters. The debugger contains no Ys-specific
address or cheat. Optional `--bram` reads an initial 2 KiB image; guest SAVE
is volatile, with no formatting, export or file writeback. Explicit execution
allowances retain tick and optional wall limits.

Geargrafx independently checks CPU/device behavior, scoped assists and normal
SAVE/LOAD; an aligned STATUS text crop matches **2,560 pixels**. It does not
qualify the complete boss route. The new observed-code dispatch additionally
passes **78 authored Geargrafx plans**, matching CPU/MPR/latch states, instruction
clocks and complete RAM in both tiers. Runtime ABI remains **12**, and the explicit
unknown-command response profile is still required. Authentic reset, audible output, complete
campaign and full native/AOT remain unfinished. No game/firmware bytes,
generated game source, captures or saves are included.

Contributor issues were reviewed on 23 October 2026: [RMB/SMB #1](https://github.com/rages4calm/pcenginerecomp/issues/1)
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

For the optional window, supply an SDL3 SDK compatible with your compiler:

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_BUILD_DESKTOP=ON -DSDL3_DIR=/path/to/SDL3/lib/cmake/SDL3
cmake --build build
python scripts/check.py
```

This adds `pce-desktop`, using the same payload/mapping/budget and optional
firmware/disc arguments as `pce-headless`. It defaults to continuous video;
headless rendering opts in with `--video-output continuous`. Arrow keys move,
Z/X are I/II, Enter is Run, Shift is Select, Space pauses, F11 toggles
fullscreen and Escape closes. See [desktop setup](docs/DEVELOPMENT.md#optional-desktop-host)
and the [complete controls](docs/DESKTOP.md). There is no audio output yet.

Append `--dev-port 0 --dev-start-paused on` to either continuous-video runner
for local development control; port zero chooses an available loopback port.
The runner reports it as `PCE_DEV_PORT=N` on standard error. For example:

```sh
python scripts/dev_client.py --port 4370 status
python scripts/dev_client.py --port 4370 input 0x8 --frames 2
python scripts/dev_client.py --port 4370 screenshot new-frame.png --source guest
```

Replace the example port with the reported value. Screenshots are requested
explicitly and new output paths are required. See [the TCP guide](docs/DEV_SERVER.md)
for pause semantics, limits and the composed-window capture option.

The frontend works directly from a checkout without installing packages:

```sh
python -m pcerecomp doctor
python -m pcerecomp --help
python -m pcerecomp inspect "/path/to/your/disc.chd" --hash
python -m pcerecomp toc "/path/to/your/disc.chd" --out .local/title/disc.toc
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
| [Consumer projects](docs/CONSUMER.md) | Pinned project descriptors, shared-runtime builds and execution receipts |
| [Native capture](docs/CODE_CAPTURE.md) | Bounded executed identities, source variants and offline native promotion |
| [CPU semantics](docs/CPU_SEMANTICS.md) | Instruction contracts, status flags, stack wrapping and verification |
| [VDC semantics](docs/VDC.md) | Video ports, VRAM, raster events, clock phases and explicit limits |
| [Continuous video](docs/VIDEO_OUTPUT.md) | Historical pixel/line output, frame publication and remaining fetch-phase limits |
| [Desktop host](docs/DESKTOP.md) | Optional SDL3 presentation, controls, pacing and isolation |
| [Development control](docs/DEV_SERVER.md) | Loopback TCP commands, frame stepping and requested RGB captures |
| [CD semantics](docs/CD_CONTROL.md) | Command handshake, reference timing, BRAM and explicit transport limits |
| [CD audio control](docs/CD_AUDIO.md) | Position commands, guest timeline, fader and explicit audio-output limits |
| [Controller semantics](docs/INPUT.md) | Two/six-button pads, TurboTap, sampling and reference differences |
| [Research](docs/RESEARCH.md) | Primary sources, pinned references, existing tools and design decisions |
| [Roadmap](docs/ROADMAP.md) | Full feature target, dependencies and acceptance criteria |
| [Status](docs/STATUS.md) | Verified baseline, known limitations and next useful batch |
| [Development](docs/DEVELOPMENT.md) | Reproduce builds, run the CLI and understand private outputs |
| [Contributing](CONTRIBUTING.md) | Review standards and useful contributor work |

Completing CPU/device semantics, broader independent verification, System
Card integration, decoded sound, remaining CD services, saves and gameplay
qualification comes before a playable release. Widescreen, high-refresh presentation,
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
