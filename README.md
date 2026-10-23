# PC Engine Recomp

An open, experimental static recompilation toolkit for **PC Engine /
TurboGrafx-16 and CD-ROM²** games. The goal is a shared foundation for native
ports with modern rendering, audio, input, debugging, and game-specific
enhancements.

**Current status: architecture and executable compiler foundation. No game
is playable or certified.** The decoder describes all 256 HuC6280 opcode
slots; the native emitter and interpreter implement 233 opcodes, including
load/store addressing, logical operations, ADC/SBC with T/decimal handling,
comparisons, shifts/rotates, INC/DEC, indirect JMP, RMB/SMB and all eight
push/pop instructions, BIT/TSB/TRB/TST, bit branches, BSR and TAM/TMA with
persistent transfer-latch semantics, plus CSL/CSH speed control and
ST0/ST1/ST2 VDC port writes, all five block transfers and RTI. The current
batch adds IRQ delivery and enough functional device state to reach the retail
Beginning/Continue menu and advance into opening story cutscenes. This
conditional boot-to-story milestone requires the explicit
`--cd-unknown-status gear-good` reference-emulator response profile; strict
default mode still faults on the encountered unknown CD command. This is
not an implementation or certification of that unknown command.
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
  ports and VRAM/SATB DMA; undriven VRAM reads still stop explicitly. Dynamic
  VRAM contention and a scanline presentation renderer remain unfinished.
  Geargrafx checks passed 856 settled CPU/VDC states and 48 complete
  work-RAM/VRAM comparisons per tier.
  See [VDC semantics and limits](docs/VDC.md).
- Opt-in master-clock video timing: programmable horizontal/vertical phases,
  VBlank and raster-comparison events, latched status/IRQ acknowledgement, and
  VCE timing control. Native and interpreted instructions both advance the
  device clock. CPU bus phases remain an instruction-level approximation;
  exact access phases and a historical scanline renderer remain unfinished.
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
  and palette comparisons and 1,024 guest palette-read bytes. The optional
  `--frame-out` image shows current storage and registers, not reconstructed
  raster history. See [video scope](docs/VDC.md).
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
  are documented in [controller semantics](docs/INPUT.md). Desktop input,
  turbo generation and other peripherals remain unfinished. Independent local
  expectations pass **50,341 cases/groups**, with eight synthetic headless
  configuration tests. Geargrafx checks pass **56 plans, 2,512 CPU/port-read
  checkpoints and 56 complete work-RAM comparisons per tier**, covering USA
  region with CD hardware present and absent.

An owner-supplied Ys III USA CHD exercised the real input pipeline locally.
With scripted input and the explicit unknown-command response profile, the
BIOS-backed sandbox reaches **Beginning / Continue**, selects Beginning,
passes the blank volatile-BRAM warning through Proceed, and advances through
opening story portraits to the river/mountains/bird scene. The bounded route
executes **229,808,207 instructions: 7,234,070 native and 222,574,137
interpreted**, reads **288 sectors**, transfers **262,144 ADPCM DMA bytes**
and completes **18,191 IRQ/RTI sequences** over about **139.7 guest seconds**.
All 22 scripted host input events apply; the unknown-response profile is used
twice. The run reaches its tick budget without a runtime fault. Controllable
gameplay and campaign progress remain unqualified.
This starts from the extracted disc program with a supplied System Card,
not an authentic hardware reset. It does not establish a playable game,
continuous frame rendering, audible output or full native/AOT execution.
Original image/firmware hashes were checked before and after; no disc bytes,
generated game source, BIOS or saves are included.
Native-module ABI is **11**, adding IRQ/timer and extended functional video
and audio state. Regenerate older modules and rebuild consumers.
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
| [CPU semantics](docs/CPU_SEMANTICS.md) | Instruction contracts, status flags, stack wrapping and verification |
| [VDC semantics](docs/VDC.md) | Video ports, VRAM, raster events, clock phases and explicit limits |
| [CD semantics](docs/CD_CONTROL.md) | Command handshake, reference timing, BRAM and explicit transport limits |
| [CD audio control](docs/CD_AUDIO.md) | Position commands, guest timeline, fader and explicit audio-output limits |
| [Controller semantics](docs/INPUT.md) | Two/six-button pads, TurboTap, sampling and reference differences |
| [Research](docs/RESEARCH.md) | Primary sources, pinned references, existing tools and design decisions |
| [Roadmap](docs/ROADMAP.md) | Full feature target, dependencies and acceptance criteria |
| [Status](docs/STATUS.md) | Verified baseline, known limitations and next useful batch |
| [Development](docs/DEVELOPMENT.md) | Reproduce builds, run the CLI and understand private outputs |
| [Contributing](CONTRIBUTING.md) | Review standards and useful contributor work |

Completing CPU/device semantics, broader independent verification, System
Card integration, continuous video, decoded sound, CD services, saves and a
desktop host comes before a playable release. Widescreen, high-refresh presentation,
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
