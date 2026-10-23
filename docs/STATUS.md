# Current status — 22 October 2026

## Verified baseline

This is an executable compiler/runtime foundation with continuous software
video and an optional desktop window, **not a certified playable game port**.
The public source needs no retail input to build or test. SDL is optional.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Public source checkout, retained previous batch | Generic sandbox, optional reference probes and all 17 then-current suites built and passed, including 112 Python tests | Windows x64; empty module selection; no private dependencies or title inputs used |
| Complete local verification, current batch | All 20 enabled suites pass, including 136 Python tests | Windows x64, optional SDL enabled; authored synthetic tests; public-source-only qualification is reported separately |
| Frontend/host unit suite, current batch | 136 tests pass, including 15 development-client checks | Media/analysis/decoding, loader/source protection, descriptors, controller/scripts, explicit response profiles, reference adapters and live runner/server integration; not retail game fixtures |
| Continuous video expectations, current batch | 3,950 independent checks pass; existing 628,214 snapshot/palette expectations also pass | Historical palette/VRAM/SATB/scroll changes, CR/MWR latches, bounded publication/reset, all VCE timing controls, partitioning and unchanged guest state; physical fetch/contention and sprite IRQs excluded |
| Independent Geargrafx continuous video, current batch | Four authored plans × four distinct frames: 16 complete 256 × 192 RGB images / 786,432 pixels match byte for byte; final probe bridges all images and publication timestamps exactly | Active crop of Geargrafx's debug viewport; midline palette, line-latched scroll, VRAM changes, map wrap and sprite modes; no hardware/full-game frame qualification |
| Optional SDL3 desktop host, current batch | 122 renderer/input assertions pass; visible Windows menu, Run-to-warning, pause/resume and fullscreen transitions observed | SDL 3.4.18 Windows x64; two-frame quick-tap retention and keypad direction aliases locally tested; physical controller and other operating systems unqualified |
| Loopback development server, current batch | 69 actual TCP assertions plus 15 Python client checks pass; both hosts' integration tests pass | Strict bounded protocol, five input slots, pause/step/status/capture/quit, exact RGB/base64, disconnect and stalled-peer behavior; loopback-only opt-in, no independent PC Engine oracle claim |
| Internal native/interpreter checks | 14,912 comparisons across 233 opcodes pass | Shared framework assumptions can still be wrong |
| Independent IRQ/RTI expectations | 65,536 entry cases, 262,144 RTI cases, 32 sampling sequences, 15 guard/mapping/deadline groups and 779 register/timer groups pass | Both tiers/speeds; aggregate sampling contract, no physical bus-phase qualification |
| Independent Geargrafx IRQ/RTI check | 832 plans per tier: 2,496 CPU states, 832 complete work-RAM images and 832 complete-sequence clock deltas pass | Real pending sources in reference, corresponding injected lines in local probe; no native fallback; source edge/MMIO phases and hardware excluded |
| Independent palette/snapshot expectations | 628,214 checks pass | Palette byte/index/mirror sweep, tile planes, sprite sizes/flips/priority/line budget and no simulation mutation; current-state image only |
| Independent VRAM/SATB DMA expectations | 14,786 checks pass | Direction/overlap/address wrap, dot cadence, terminal registers, completion gates and SATB priority/repeat; CPU contention excluded |
| Independent Geargrafx palette/DMA check | 12 direct-device plans pass, including full VRAM/SATB/palette and 1,024 guest palette-read bytes | Settled device effects, no per-tier CPU execution, exact DMA phases, frame rendering or hardware claim |
| Independent PSG expectations | 2,144 register groups, 174,592 waveform/DDA/LFO cases and 769 bus/latch groups pass | Write-side state only, no oscillator clocks or PCM synthesis |
| Independent ADPCM expectations | 20,736 port/slot/control groups, 67 playback/length groups, 10 DMA groups and 257 bus groups pass | RAM/ports, consumed nibbles, length IRQs and CD DMA; no decoded PCM or audio output |
| Independent Geargrafx ADPCM/PSG check | Eight direct-device plans pass: 292 guest read bytes, complete ADPCM RAM and six PSG channel states | Settled manual ports only; ADPCM playback/DMA, waveform bytes, oscillators and mixed audio excluded |
| Independent CDDA control/fader/response-profile expectations | 7,134 checks pass | D8/D9/DA/DD state/position/response boundaries, fader and explicit unknown-command profile; deterministic seek and sector timeline, no live CDDA or PCM qualification |
| Independent input-script expectations | 4,136 checks pass | ASCII/size/event bounds, full 12-bit masks, integers and host snapshot format; no desktop polling or gameplay certification |
| Independently expected bit/stack checks | 92,160 cases pass across both tiers, plus mutation/mapping/fault checks | Instruction-level cycles checked; no bus-phase/IRQ model |
| Independently expected data checks | 7,340,032 arithmetic/logic cases and 340 addressing cases pass | All ADC/SBC byte pairs under C/D/T/V combinations in both tiers; instruction-level timing only |
| Independently expected RMW/JMP checks | 3,932,160 RMW and 16,384 indirect JMP cases pass, plus native wrap/MMU/fault checks | Every RMW byte/status combination in both tiers; instruction-level timing only |
| Independently expected bit-test/branch/BSR checks | 4,849,664 bit-test and 2,228,224 branch/BSR cases pass | Synthetic operands/status/stack cases; fixed native immediate/mask values, not every encoding of literals |
| Independently expected MPR/latch checks | 1,114,112 cases pass, plus remap/mutation/deadline sequences | All masks/byte values in both tiers; arbitrary-map OR sweep interpreted; instruction-level timing only |
| Independently expected speed checks | 524,288 cases pass, plus sequence/deadline/mutation/fault checks | All status/latch bytes, both entry speeds and tiers; independently specified split-cycle tick table |
| Independently expected CD-control/BRAM checks | 67,584 native/interpreter instruction cases, 2,048 BRAM readback sequences and 16,144 decoded register groups pass, plus extent/lock/alias/RMW/guard/deadline/fault checks | Both tiers/speeds and reference BRAM readback/undefined-read decoding; idle control scope, no transport/audio scheduler claim |
| Independent Geargrafx unknown-command response check | Three plans, 87 CPU/device checkpoints and three complete RAM/BRAM comparisons per tier pass | Explicit unknown-response profile; proves protocol response, not unknown-command operations or hardware |
| Independent Geargrafx BRAM/read decoding check | Four plans, 27 CPU/device checkpoints and four complete RAM/BRAM comparisons per tier pass | BRAM gate readback, lock/alias behavior and unused decoded CD read `$FF`; no subcode interpretation or persistence |
| Independently expected CD-transport checks | 8,369 groups pass: 4,096 latch/control byte groups, 4,096 RMW groups and directed handshake/timing/reset/IRQ/guard/refusal checks | Both execution tiers and CPU speeds; literal local deadlines, TEST UNIT READY only; no sector responses or live access-phase proof |
| Independently expected TOC/DATA IN checks | 418 groups pass: literal BCD/response bytes, manual/auto-ACK timing, status/message completion, data IRQs, reset/selection aborts, metadata validation and explicit refusal | Both execution tiers/speeds; four-byte Gear/Mesen metadata-response profile, no readable sector provider or hardware qualification |
| Independently expected joypad checks | 50,341 cases/groups pass: 32,768 button, 8,192 control, 136 tap, 9,228 bus and 17 host/configuration checks; eight synthetic headless tests also pass | Both execution tiers/speeds; selected Geargrafx reference profile, no desktop polling or physical controller qualification |
| Independent block-transfer expectations | 1,600 instructions plus 5,120 status/stack cases, four local destructive-opcode cases, 23 guards/deadlines, 8,204 device checks and four deferred IRQ groups pass | Both tiers/speeds for RAM and deferred IRQ; interpreted actual MMIO plus block-aware wrapper checks; aggregate cycle profile, no exact bus-phase claim |
| Independent Geargrafx block transfers | 810 completed-instruction CPU/MPR states, 810 full 8 KiB RAM comparisons and 810 matching complete-instruction clock deltas per tier; all 16 shards pass | Both speeds, all five zero-count transfers, overlap/wrap/stack/operand aliases; no native fallback; excludes opcode-overwrite/MMIO/access phases/IRQ delivery/hardware |
| Independent READ expectations | 621,096 checks pass: full 256-sector request, both CPU tiers/speeds and ACK modes, byte/backpressure/reset/failure/guard boundaries | Deterministic 1x timing constants; no physical seek or IRQ delivery proof |
| Independent provider expectations | 22,568 checks pass: SHA256 known answers, ISO, CHD geometry/cache through an authored decoder ABI double | ABI double does not test actual decompression |
| Independent Geargrafx READ check, retained evidence | Seven plans; 201 settled CPU/device checkpoints and seven complete sectors / 14,336 payload bytes per tier pass | 15,552,742 retired native vs interpreted instructions including delay NOPs; exact seek/access/stream-loop cadence not qualified; final probe bridged exactly |
| Private on-demand CHD provider check | Six real sectors / 12,288 bytes agree with Python slicing/mapping; six protected input hashes unchanged | Shared libchdr decoder, not independent decompression qualification |
| Independent Geargrafx 1.8.4 joypad check, retained evidence | 56 plans, 2,512 CPU/port-read checkpoints and 56 complete 8 KiB work-RAM comparisons per tier pass; 2,512 native vs 2,512 interpreted instructions | USA region with CD present/absent; Japanese line local/source-only; guest output observations, no direct internal controller-state, host event timing, hardware or gameplay proof |
| Independent Geargrafx 1.8.4 TOC/DATA IN check, retained qualified scope | 25 of 26 plans qualified; 1,964 settled CPU/device checkpoints and 25 full work-RAM/BRAM comparisons per tier; 653,294 native vs 653,294 interpreted instructions | `toc-reset-auto-response-pending` remains unqualified after two reference access violations; eight earlier TOC plans bridge exactly to final ABI-7 probe; no sector, exact access-phase, hardware or gameplay proof |
| Independent Geargrafx 1.8.4 CD-transport check, retained evidence | 21 plans; 743 settled CPU/device checkpoints and 21 full work-RAM/BRAM comparisons per tier pass | 1,007,851 native vs 1,007,851 interpreted instructions including settling NOPs; frozen original 18 plans bridged exactly to that batch's final build, three added edge plans checked live; no sector backend, access-phase, hardware or gameplay proof |
| Independently expected VDC checks | 77,824 instruction expectations, 8,192 register-width cases and 392,991 VRAM transfer/address cases pass, plus status/guard/deadline/fault checks | Both execution tiers for CPU cases; synchronous functional profile; fixed access waits, no raster/rendering/DMA |
| Independent raster expectations | 977 directed groups plus 240,015 native/interpreter cadence, alias, speed and refusal checks pass | Literal edges, CR gating, status acknowledgement, timing latches, partition independence, all eight VCE timing controls; no sub-instruction bus-phase or rendered proof |
| Independent Geargrafx 1.8.4 raster check, retained evidence | 15 plans; 4,165 exact-clock device checkpoints and 15 guest status acknowledgements pass | VCE/VDC positions, horizontal/vertical phases, sticky VBlank/RCR flags and local IRQ1; divider 4 / 262 lines; direct device probe, no per-tier live CPU or bus-phase claim |
| Independent Geargrafx 1.8.4 MCP check, retained VDC port batch | 48 sequences; 856 settled CPU/VDC states and 48 full work-RAM/VRAM comparisons per tier pass | Eight disjoint shards; 14,552 native vs 14,552 interpreted instructions including 13,696 settling NOPs per route; no live busy/status-event, dynamic timing, DMA, rendering or gameplay proof |
| Independent Geargrafx 1.8.4 MCP check, retained CD-control batch | 48 sequences; 720 CPU/device states and 48 full RAM/BRAM comparisons per tier pass | Two disjoint shards; authored synthetic bootstrap/CD; 720 native vs 720 interpreted instructions; no live nonzero IRQ-source, cycle/device-phase or gameplay proof |
| Independent Geargrafx speed batch, retained prior evidence | 24 sequences; 120 CPU/speed states and 24 final RAM/latch comparisons per tier agreed; 92 tick deltas per tier agreed | Not rerun this batch; 28 documented transition-timing differences per tier remain |
| Independent Geargrafx MPR batch, retained prior evidence | 524 sequences, 1,614 instruction states and 524 final RAM/latch comparisons per route passed | Not rerun in the current batch; native-first: 1,078 native + 536 interpreted after context changes |
| Independent Geargrafx bit-test/branch/BSR batch, retained prior evidence | 480 native + 480 interpreter comparisons across all 30 opcodes passed | Not rerun in the current batch |
| Independent Geargrafx RMW/JMP batch, retained prior evidence | 512 native + 512 interpreter comparisons across all 32 opcodes passed | Not rerun in the current batch |
| Independent Geargrafx data batch, retained prior evidence | 1,552 native + 1,552 interpreter comparisons across all 97 data encodings passed | Not rerun in the current batch |
| Independent Geargrafx bit/stack, retained prior evidence | 128 native + 128 interpreter comparisons across all 24 bit/stack opcodes passed | Not rerun in the current batch |
| Independent Geargrafx baseline, retained prior evidence | 188 native + 188 interpreter comparisons across the original 47 opcodes passed | Not rerun in the current batch |
| Local owner-supplied Ys III USA CHD | Track metadata, hashing, two-hunk decompression and 4 KiB initial program extraction verified | Filename/internal title identify the local input; no external dump-database certification |
| Supplied USA v3.0 firmware | Raw 256 KiB size and MD5 match the documented USA BIOS; SHA1/SHA256 pinned locally | Supplied patched USA/Japan images have distinct hashes and are excluded from the baseline; see FIRMWARE.md |
| Boot-program-only analysis | 203 discovered instruction sites, all 203 native-emittable, 25 unresolved records | Static discovery is not an execution-coverage measurement |
| Combined local boot/BIOS snapshot | 785 discovered sites, all 785 native-emittable, 47 unresolved records under a 1,024-instruction analysis limit | One initial MPR context; no speculative firmware services |
| Compiled local boot/BIOS module, retained ABI-11 conditional story route | 229,808,207 instructions: 7,234,070 native + 222,574,137 interpreted; 288 sectors, 589,828 DATA IN ACKs including four TOC bytes, 262,144 ADPCM DMA bytes and 18,191 IRQ/RTI sequences; 22 scripted host events; Beginning/Continue → Beginning → blank volatile-BRAM warning → Proceed → opening story portraits and river/mountains/bird scene | Tick-budget stop at 3,000,000,009 ticks, about 139.7 guest seconds, no runtime fault; requires explicit `--cd-unknown-status gear-good`, used twice; no continuous rendering in this retained run, controllable gameplay, campaign, authentic reset or audio-output proof |
| Compiled local boot/BIOS module, ABI-12 continuous menu route | 30 million instructions, 1,062 completed historical frames; all compared CPU/CD/VDC fields exactly match the retained menu route | Recompiled same initial snapshot; reference-response opt-in still required; actual desktop menu observed separately; no full native/AOT or gameplay qualification |
| Compiled local boot/BIOS module, ABI-12 continuous story route | 8,356 completed frames; 229,808,207 instructions: 7,234,070 native + 222,574,137 interpreted; 288 sectors, 262,144 ADPCM DMA bytes, 18,191 IRQ/RTI sequences and all 22 scripted events; historical image shows river/mountains/bird scene | Tick-budget stop at 3,000,000,009 ticks, about 139.7 guest seconds, no runtime fault; same response-profile condition and execution totals as the retained story route; no controllable gameplay, campaign, authentic reset, audible output or full native/AOT qualification |
| Actual SDL window with TCP-controlled Ys III route, current batch | Menu → Beginning → warning → Down selects Proceed → I confirms → boat/mast and opening portrait scenes; 8,000 frames, 2,871,925,884 ticks / 133.7 guest seconds; 7,301,883 native + 213,086,766 interpreted instructions; 16,037 IRQ/RTI, 288 sectors, zero read errors, 262,144 ADPCM DMA bytes; clean requested quit | Eight requested guest/SDL captures, no per-frame dump; final hidden GPU-window replay matches three retained guest-image hashes and final state totals; response-profile opt-in used twice; no gameplay/campaign, authentic reset or audible output claim |

The public baseline has no ROM, BIOS, extracted game bytes, generated game
source, save files or initialized personal install. Private derived data is
under ignored `.local/`. Original CHD SHA256 was established before work and
is checked again at closeout; nothing writes the original image.

The local toolchain does not provide a `ctest` binary; verification uses
`python scripts/check.py`. The retained previous batch passed all 17 suites
and 112 Python tests, including a separate generic public-source build.
This batch passes all 20 enabled suites, including 136 Python tests, adding
continuous-video, actual TCP and optional desktop verification. GitHub CI
template uses CTest on Windows/Linux/macOS runners and separately builds the
pinned optional CHD backend. The initial CLI credential lacks GitHub's
`workflow` scope, so `.github/ci-template.yml` is initially inactive. No remote
CI pass is claimed. Enable it using the instructions in the developer guide.

## Deliberate limits

- Decoder metadata covers 256 encoding slots; runtime support is 233 opcodes.
- Load/store, logical, ADC/SBC and comparison encodings are supported, including
  indexed/indirect data addressing, T destinations and decimal arithmetic.
- Shifts/rotates, INC/DEC memory/accumulator and both indirect JMP forms are supported;
  indirect destinations remain unresolved in static discovery.
- RMB/SMB, push/pop, BIT/TSB/TRB/TST, BBR/BBS and BSR are supported.
- TAM/TMA cover all masks and the persistent transfer latch. I/O open bus is
  separate and retained by the IRQ/PSG profile. Current native ABI is 12; regenerate older modules.
- CSL/CSH use two cycles at entry speed and one at selected speed.
  Geargrafx's live transition timestamps differ; see CPU_SEMANTICS.md.
- Idle CD-control/BRAM routing and opt-in clocked selection/REQ/ACK transport
  are implemented; TEST UNIT READY and directory/TOC modes 0/1/2 complete
  through DATA IN where needed, then status and message phases. Manual and
  `$1808` auto-ACK are supported for bounded metadata responses.
  See CD_CONTROL.md for exact registers, reference delays and discrepancies.
  REQUEST SENSE and raw captured subchannels still trap. CDDA D8/D9/DA/DD has
  functional control/position responses; no PCM output. READ `$08` requires a separately
  attached read-only provider. Metadata-only attachment does not verify an image;
  `--disc` hashes/derives geometry and enforces exact descriptor agreement.
  The deterministic 1x profile omits seek distance, reset jitter and accelerated speeds.
- Opt-in joypad I/O routes all `$1000..$13FF` mirrors, with two/six-button
  pads, a five-port TurboTap, region/CD bits and guest-write-sampled output.
  Headless flags provide held button snapshots and bounded tick-scripted input;
  the optional SDL3 host maps keyboard/gamepad input to slot zero. Other
  peripherals remain planned. See [INPUT.md](INPUT.md) and [DESKTOP.md](DESKTOP.md).
- Functional single-VDC ports/registers, buffered VRAM and ST0/ST1/ST2 are
  implemented; the extended profile adds VCE palette and VRAM/SATB DMA, while
  undriven reads still fault. See [VDC.md](VDC.md).
- Opt-in raster timing generates VBlank and raster-comparison events from
  master-clock horizontal/vertical phases. VCE timing control selects dot
  divisors and 262/263-line frames. Optional images inspect current VRAM,
  SATB, palette and registers. Separately enabled continuous output records
  historical lines and live-dot palette values; it preserves the legacy
  non-rendering path. Physical VRAM contention/fetch phases, narrow latch
  rewrites and sprite collision/overflow IRQs remain. See [VIDEO_OUTPUT.md](VIDEO_OUTPUT.md).
- TII/TDD/TIN/TIA/TAI have genuine stack effects, wrapped per-byte addressing,
  17+6*n base cycles and block-aware I/O. A started bounded block completes
  past the entry deadline; IRQ entry is deferred until the transfer completes.
  Fatal faults are nontransactional; there is no partial-transfer resume state.
- IRQ delivery, RTI and timer/interrupt registers are implemented using an
  explicit aggregate sampling profile. Finer device access phases, a complete
  interpreter, full System Card profile, general bus and RAM mirrors remain.
- Unknown CD commands fault by default. Explicit `--cd-unknown-status gear-good`
  selects the source-documented reference-emulator GOOD-response quirk and
  counts each use. It does not implement unknown command operations or convert
  known unsupported commands to success. Retail menu evidence is conditional
  on that profile; strict mode remains an unresolved correctness boundary.
- PSG retains functional register state. ADPCM implements RAM/port/playback
  consumption and CD DMA, and CDDA models position/control/fader state.
  Oscillators, PCM decoding/mixing and audible output remain unimplemented.
- Deadline accounting is at instruction boundaries, not cycle-accurate.
- One MPR context per emitted module; mapping changes stop static discovery.
- No persistent overlay cache, capture/recompile loop or optimizing block IR.
- CHD reader supports v5 CD metadata and MODE1/RAW user sectors. Boot
  extraction supports only its documented loader subset. BIN/CUE is planned.
- The headless runner loads a single contiguous payload into an explicit
  sandbox, optionally with a supplied read-only 256 KiB System Card ROM.
  It is not an authentic console reset/BIOS state.
- The optional desktop displays completed frames with nearest pixels and
  guest-clock pacing, and supports resize/fullscreen/pause/focus/input. It has
  no audio output, settings persistence or owner-save access. Physical gamepad
  and non-Windows host qualification remain.
- The optional `pce-dev-1` TCP interface controls only the running guest and its
  SDL composition. It binds loopback, is disabled by default, and bounds
  request/response storage, polling and idle peers. Captures are requested,
  not automatic. It does not capture the owner's desktop or provide arbitrary
  memory writes. See [DEV_SERVER.md](DEV_SERVER.md).
- No saves, rewind, netplay or enhancement release. The full target remains in
  the roadmap.

## Next useful batch

Continue from the visible continuous-video milestone toward controllable
gameplay, using actual traces for the next hardware gap. Add decoded/mixed
audio and bounded overlay capture/offline AOT promotion with separate proof.
The conditional route reaches the Beginning/Continue menu and advances into
opening cutscenes with 8,356 continuous frames. The separate visible desktop
route uses exact TCP input through 8,000 frames and opening portraits; neither
route qualifies a full game.
Investigate the unknown CD command separately:
the reference-response opt-in does not settle its operation or hardware behavior.
Keep historical rendering, decoded/mixed audio, exact access phases
and unseen-overlay compilation distinct from current-state snapshots and
functional control timelines. Do not mask IRQs or invent firmware/audio
services to force progress. Overlay identity remains tied to current MPRs and
source bytes. The IPL-entry sandbox does not establish authentic reset.

CPU_SEMANTICS.md and REFERENCE.md describe block behavior and live proof limits.
Private receipts remain under the existing ignored batch/title scratch roots.
The owner disc/firmware hashes were checked before/after; no install, saves,
settings or original images were modified. All owned reference children stop
at completion. The current batch budget includes optional SDK/build output,
temporary files and diagnostics under the owner-authorized 1 GiB allowance;
the previous batch's 15.9 MiB closeout is retained historical evidence only.

Contributor issues reviewed on 22 October 2026: #1 (RMB/SMB) and #2 (stack) are closed;
#3 (media fixtures) and #4 (cycle-aware traces/second oracle) are open with
zero comments. The GitHub inspection did not change the issues.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md) and
[ROADMAP.md](ROADMAP.md) before continuing. The optional reference process
is stopped after each run; no owner application or live save root was used.
