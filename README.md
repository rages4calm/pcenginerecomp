# PC Engine Recomp

An open, experimental static recompilation toolkit for **PC Engine /
TurboGrafx-16 and CD-ROMÂ²** games. The goal is a shared foundation for native
ports with modern rendering, audio, input, debugging, and game-specific
enhancements.

**Current status: experimental compiler/runtime with direct native code
generation, continuous video, audio, desktop/TCP development hosts and a
reusable consumer-project interface. No complete game port is certified.** The decoder
describes all 256 HuC6280 opcode slots; the native emitter and interpreter
implement 234 opcodes, including
load/store addressing, logical operations, ADC/SBC with T/decimal handling,
comparisons, shifts/rotates, INC/DEC, indirect JMP, RMB/SMB and all eight
push/pop instructions, BIT/TSB/TRB/TST, bit branches, BSR and TAM/TMA with
persistent transfer-latch semantics, plus CSL/CSH speed control and
ST0/ST1/ST2 VDC port writes, all five block transfers, RTI and BRK. The runtime
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

Large observed-code modules build as separately compiled translation
units, shared by headless and desktop hosts. Native dispatch selects exact
opcode/operand keys instead of scanning source variants; every instruction
byte is still checked before guest state changes. Consumer builds pin every
generated source and header. See [performance measurement](docs/PERFORMANCE.md)
for the benchmark and its scope.
The retained ABI-12 Windows x64 comparison compiles the full module in **70.5 seconds
versus 353.2 seconds**, and five alternating authored dispatch samples show
**9.5% higher throughput** with identical results. These measurements cover
module compilation and an authored CPU workload, separately from game testing.
The bounded Ys III bootstrap's whole-process difference is about **1.4%**;
no campaign-wide speedup is claimed.

The runtime produces stereo PCM from PSG, MSM5205 ADPCM and read-only CDDA,
with bounded WAV capture and optional SDL playback. **Raw 44.1 kHz remains
the default reference path.** The opt-in filtered profile adds PSG DC removal,
ADPCM DC/low-pass filtering and gain smoothing, with deterministic **44.1 or
48 kHz** output. Separately compiled Geargrafx 1.8.4 checks match **59,505
filtered PSG stereo frames across 3,266 authored cases** and **34,112 filtered
ADPCM frames across 17 held-input cases**. These source-filter checks exclude
decoder clocks, the final mix, device conversion and analog hardware; earlier
digital-source evidence retains its documented scope.

The authored 64-tap rational FIR has at most **0.001661 dB** passband error in
the tested sweep through 18 kHz and about 0.70 ms causal delay. It cannot remove aliases
already folded into the source observations. Default **`gear-v1` timing** now
uses ceiling-rational sample edges and clock-latched PSG DAC outputs, including
register writes between PSG clocks. `--audio-timing legacy` preserves the
previous sample timing and PCM path. Timing is independent of raw/filtered
selection. **ABI 15** introduced the guest CDDA cursor and sample latch alongside
the held PSG DAC state. Retained ABI-12/13/14/15/16 captures can be re-emitted for current ABI 17, but
modules and runtime must be rebuilt together.
Consumer schema remains **1**. See [audio controls, evidence and limits](docs/AUDIO_OUTPUT.md).

Guest CDDA sample-latch ports **`$1805/$1806`** now work with PCM on or off.
They hold signed post-fader samples, enforce the 700-tick admission interval
and alternate right first. Nine authored cases / **367 distinct Geargrafx
checkpoints** agree with both PCM settings. Filtering, output rate and legacy
presentation timing do not change guest latch behavior. See
[the port contract and reference limits](docs/CD_AUDIO.md#guest-sample-latch).

The retained ABI-16 consumer migration follows a checked verification path: regenerate
the retained capture, preserve translated operations and guards, then check
legacy audio, default Gear timing and audio-off execution separately. Fresh
desktop runs reproduce the **94,800-frame, 39-checkpoint assisted route** in
all three modes; fresh headless comparisons match guest state and PCM/WAV
within each audio timing profile.
Regeneration retains the existing native coverage; it adds no new gameplay
milestone. See the [upgrade guide](docs/CONSUMER.md#upgrade-a-consumer-to-abi-16)
and [consumer integration evidence](docs/STATUS.md#abi-16-consumer-integration).

The base compatibility profile now includes **BRK in both execution tiers**,
**8 KiB work-RAM mirrors across banks `$F8..$FB`**, and **VDC sprite-zero
collision / sprite-overflow status and interrupts**, independently of host
rendering or audio. Current runtime **ABI 17** requires regenerated modules and a
matching runtime; retained ABI-12 through ABI-16 captures remain usable as
original compiler inputs. Bounded unknown-CD diagnostics retain opcode counts
and the original command source context. Strict unknown-command behavior is
unchanged. The fresh build passes **34 suites / 386 Python tests**. Independent
Geargrafx checks cover sprite event timing, BRK/RTI and WRAM aliases; see
[compatibility contracts and limits](docs/COMPATIBILITY.md) and
[verification scope](docs/REFERENCE.md#base-compatibility-references---abi-16).

**System Card reset-vector startup** now runs the supplied firmware from its
actual ROM vector, with explicit Standard/Super memory profiles and no
preloaded IPL or invented BIOS services. Both hosts and the pinned consumer
interface support it. Startup uses a named deterministic Gear initialization
policy; it does not claim unspecified hardware power-on values or warm reset.
An audio-enabled TCP run executes **14,680 frames** from the real reset vector
through the System Card menu and new-game selection into Ys III's town opening:
**432,875,213 native / zero interpreted instructions**, with zero guard misses
and no RAM edits. A separate first-600-frame capture records **17,483,730 native
BIOS instructions**. The established `$FF` response-profile condition still
applies when leaving the introduction. This is bounded observed-code coverage;
unvisited code and complete-game compatibility remain unqualified.
See [reset boot and its reference scope](docs/SYSTEM_CARD_BOOT.md)
and the [authored example](examples/reset-consumer/README.md).

The regenerated ABI-17 module also passes the separate retained
**95,686-frame / 68-checkpoint** gameplay regression, preserving its existing
assists and filtered 48 kHz audio results. See
[native integration evidence](docs/STATUS.md#native-reset-promotion-and-abi-17-integration).

The [capture-to-native reset example](examples/reset-consumer/README.md#capture-mappings-that-a-fixed-cfg-cannot-discover)
demonstrates actual guest MPR changes and mirrored ROM fetches. Four fresh
Standard/Super × headless/desktop consumer builds each retire **200 native /
zero interpreted instructions**; separate TCP runs each execute two frames
entirely natively. The native-only Geargrafx oracle checks **1,320 translated
instructions** across 38 retained reset cases and 12 new mirror-fetch cases.
This authored coverage is separate from retail execution. Consumer receipts
also verify reset metadata against the pinned firmware vector and check fresh
capture ABI, capacity and execution-tier counts. See
[reference scope](docs/REFERENCE.md#system-card-reset-references---abi-17) and
[receipt guarantees](docs/CONSUMER.md).

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
  `--code-capture-start-frame N` can exclude startup from the observation
  window, with explicit start and preceding-retirement metadata.
  Captures and game-derived modules remain private.
- A [consumer-project interface](docs/CONSUMER.md) pins tool source, ABI,
  module and input identities, builds against the shared runtime, and records
  actual native/interpreted execution. The [authored example](examples/consumer/README.md)
  builds and runs without game or firmware data.
  Windows desktop consumers include their selected SDL runtime DLL beside the
  executable and pin its hash in build/run receipts, including when embedded
  from a parent CMake project.
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
  implemented. Geargrafx comparisons pass **16 complete 256 Ã— 192 images /
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
- Six-channel PSG waveform/DDA/noise/LFO synthesis, MSM5205 digital ADPCM
  decoding and CDDA PCM from read-only CHD audio sectors. The existing port,
  IRQ, DMA, CDDA command/timeline and fader models remain separate from
  presentation. A guest-clock mixer produces raw 44.1 kHz signed-16 stereo;
  opt-in source filters and fixed-point rational resampling add filtered
  44.1/48 kHz output without changing guest cadence or the raw diagnostics.
  The optional SDL host plays bounded queues, and explicit WAV output is
  bounded and never overwrites a file. The original eight-plan settled-port
  reference remains distinct from raw CDDA samples, the separately compiled
  PSG oracle and the ADPCM decoder/save-state comparison.
  Complete retail sound, the physical analog circuit and parity with
  Geargrafx's final mixed/device output remain unqualified. See [audio output](docs/AUDIO_OUTPUT.md),
  [control scope](docs/CD_AUDIO.md) and [reference evidence](docs/REFERENCE.md).

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

The retained ABI-13 audio-enabled, partitioned-module SDL/TCP replay matches **25 complete guest PNG hashes,
all 709 existing RAM interventions and every exposed final guest
CPU/device/source diagnostic**. Its complete guest runner report also equals
the previous ABI-12 full-native run after separately validating the new
`audio_output` object and host telemetry, including all original tier and guard counts.
Total retirements, guest clocks, source generations and device results stay
exact; ephemeral TCP port and additive SDL host telemetry are checked separately.
It reads **1,181 sectors with zero errors** and retains no new image files.
The comparison excludes whole RAM and composed-window pixels. Complete accounting belongs in
[status](docs/STATUS.md) and [reference evidence](docs/REFERENCE.md).
That earlier run generates **69,095,406 stereo PCM frames**, with PSG, ADPCM and
CDDA activity and zero runtime queue discard. Unthrottled device output is
intentionally muted. A separate paced SDL check accepts/drains 930,219 frames;
neither result claims listening or analog parity.

Fresh ABI-15 headless TCP regressions complete the original **93,735-frame
assisted Ys III route** with both audio profiles. All 25 images, 25 checkpoint
states, three final states, original guest/native diagnostics, PCM fields and
bounded WAV bytes match the preceding ABI-14 runs exactly. The new port
coverage comes from authored CPU and Geargrafx tests; this replay adds no
campaign progression or listening claim. See
[current latch regression](docs/STATUS.md#ys-iii-latch-regression-through-tcp).

Retained ABI-14 headless TCP replays complete the **93,735-frame assisted Ys III
route** with legacy raw 44.1 kHz and corrected filtered 48 kHz timing. Both
match all 25 images/checkpoint states and original guest/native results.
Legacy PCM/WAV remains exact. Corrected timing produces **75,205,884 output
frames**, with source/processed counts checked against guest time and zero
runtime discard. This is source-timing regression evidence; it adds no campaign
progress or new packaged-playback claim. See
[current timing regression](docs/STATUS.md#ys-iii-timing-regression-through-tcp).

The retained ABI-13 headless and packaged [Ys III consumer](https://github.com/rages4calm/ys3recomp)
TCP replays pass the same **93,735-frame assisted route** with raw and filtered
48 kHz audio. All 25 guest image/state checkpoints and original execution
results match. Raw PCM/WAV remains unchanged; filtered output produces
**75,205,884 frames**, with identical PCM/WAV across both hosts. Separate
paced **44.1/48 kHz** checks confirm packaged SDL loading without an SDK PATH
workaround, pause/resume/input and final queue drain. Those opening checks
exercise CDDA and conversion; active source-filter agreement comes from the
authored Geargrafx cases. All **190 consumer tests** pass. The final independent
batch audit passes **1,997 checks**, rehashing **1,065 actual artifacts** with
no pending evidence. This adds no game progression, listening or hardware-audio claim. See
[retained package evidence](docs/STATUS.md#retained-abi-13-packaged-ys-iii-consumer-qualification).

The previous raw-profile headless TCP replay with the corrected PSG reproduces all
**93,735 frames, 25 complete guest images and checkpoint states**, original
guest diagnostics and native/interpreted counts. All digital audio counters,
the PCM hash and bounded 30-second WAV also remain unchanged. The authored
ultrasonic vectors exercise the fix; this game route is regression evidence
and demonstrates no audible Ys III improvement.

The retained [Ys III consumer](https://github.com/rages4calm/ys3recomp) qualification rebuilds
against the corrected PSG runtime with the SDL packaging correction. Paced playback and the
complete 93,735-frame TCP replay both start from an empty working directory
without SDK or packaged `bin` directories on `PATH`; live process inspection
confirms that Windows loads the adjacent, hash-pinned `SDL3.dll`. All 25
checkpoint images, original guest diagnostics and digital PCM results remain
exact. The separate paced run accepts/drains 710,526 PCM frames with zero
runtime discard, 2,680 explicit pause-flush drops, peak queue 1,583 and final
queue zero; pause freezes guest/PCM state and resume advances normally.
The full replay intentionally mutes fast-forward playback. All **116 consumer
tests** and **137 independent evidence checks** pass.
Official descriptor verification/build and a direct TCP supervisor are
qualified separately. This adds package execution evidence on Windows x64,
with the same assisted route and audio limits. See
[retained qualification](docs/STATUS.md#retained-packaged-ys-iii-consumer-qualification)
and the [package verification procedure](docs/CONSUMER.md#verify-a-windows-desktop-package).

Reusable development features include paused RAM/ROM inspection and explicit
`--dev-memory-write on` RAM edits with whole-range expected-byte checks,
source invalidation and counters. The debugger contains no Ys-specific
address or cheat. Optional `--bram` reads an initial 2 KiB image; guest SAVE
is volatile, with no formatting, export or file writeback. Explicit execution
allowances retain tick and optional wall limits.

Geargrafx independently checks CPU/device behavior, scoped assists and normal
SAVE/LOAD; an aligned STATUS text crop matches **2,560 pixels**. It does not
qualify the complete boss route. The retained ABI-12 observed-code dispatch batch
passes **78 authored Geargrafx plans**, matching CPU/MPR/latch states, instruction
clocks and complete RAM in both tiers. Current runtime ABI is **17**; ABI-12/13/14/15/16
observation captures can be regenerated, but old binary modules are incompatible.
The explicit unknown-command response profile is still required. Standard/Super
reset-vector startup is implemented separately; complete campaign, electrical
reset details, hardware audio parity and full native/AOT remain unfinished. No game/firmware bytes,
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

The current SDL build passes **34 suites and all 360 Python
tests**, including **478,512 authored DSP checks**, **20,852 PCM mixer checks**
and **159 SDL dummy-device checks**. Authored timing checks cover **29,418**
sample-edge, DAC-write and decoder cases; the CDDA cursor tests exercise both
timing modes. The sample-latch suite adds **3,047 authored checks** and
**48 native/interpreter instruction sequences**. The retained ABI-15 clean
public-source default build passes **28 suites**, with eight intentional desktop-only skips among
the same 316 discovered Python
tests. The filter reference's independent
source/artifact review passes **480 checks**, rehashing 244 actual artifacts.
The retained ABI-13 embedded SDL build passes all 28 suites and all 291 Python tests
without skips, including normal nested SDK discovery.
The separately compiled Geargrafx clock-driven oracle passes **102 cases,
1,551 checkpoints and 75,137 stereo frames** after integer mixer headroom.
It clocks real ADPCM decoding at all 16 rates and checks decoder state
separately; reference callback-dependent rate transitions have an explicit
single-master-tick comparison rather than an unconditional parity claim.
[Status](docs/STATUS.md) records each configuration and its evidence separately.

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
and the [complete controls](docs/DESKTOP.md). The desktop attempts audio by
default; `--audio-output off` preserves silent presentation. Headless audio
is off unless requested or a new WAV is specified. Unthrottled desktop runs
mute speakers while retaining guest-clock PCM/WAV generation. See [audio controls](docs/AUDIO_OUTPUT.md).
With audio enabled, `--audio-profile filtered --audio-rate 48000` selects
filtered 48 kHz output; omitting both options retains raw 44.1 kHz with corrected
source timing. Add `--audio-timing legacy` to reproduce the previous PCM path.

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
| [Audio output](docs/AUDIO_OUTPUT.md) | Digital sources, optional filtering/48 kHz resampling, bounded SDL/WAV output and verification limits |
| [Controller semantics](docs/INPUT.md) | Two/six-button pads, TurboTap, sampling and reference differences |
| [Research](docs/RESEARCH.md) | Primary sources, pinned references, existing tools and design decisions |
| [Roadmap](docs/ROADMAP.md) | Full feature target, dependencies and acceptance criteria |
| [Status](docs/STATUS.md) | Verified baseline, known limitations and next useful batch |
| [Development](docs/DEVELOPMENT.md) | Reproduce builds, run the CLI and understand private outputs |
| [Contributing](CONTRIBUTING.md) | Review standards and useful contributor work |

Completing CPU/device semantics, broader independent verification, System
Card integration, audio timing and hardware verification, remaining CD services, saves
and gameplay qualification comes before a playable release. Widescreen, high-refresh presentation,
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

[**R.A.I.D. â€” Retro AI Development**](https://discord.gg/Ad9BwSzctP) Â· a Discord
for AI-assisted retro reverse-engineering, decomp & recomp. I post my work there;
join to discuss this project and the others.
