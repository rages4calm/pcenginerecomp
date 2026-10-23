# Current status — 23 October 2026

## Verified baseline

This is an executable compiler/runtime foundation with continuous software
video, an optional desktop window and locally demonstrated first-mine combat,
level progression and volatile guest SAVE/LOAD. Separate, explicitly assisted
tests reach the Pendant, Storehouse Key and first-storehouse-boss encounter,
with observed damage to the enemy bar. The complete final route reproduces
across headless and SDL hosts within the documented comparison scope.
**No complete game port is certified.**
The public source needs no retail input to build or test. SDL is optional.

## Dispatch and module-build milestone

Observed-code dispatch now uses full-MPR/page/PC routing, exact opcode/operand
keys and shared identical bodies. Source peeks remain pure, checking every
byte on each instruction; direct raw RAM changes cannot hide behind unchanged
generation counters. The dedicated native-source test passes 6,668 independent
expectation groups. Runtime ABI remains **12** and descriptor schema **1**.

The retained 44,832-identity module now emits 207 independently compiled units
with a 256-identity partition target. Its largest same-PC group has 3,695
variants and deliberately stays together. The two hosts share one module
object library. Generated sources total 22,988,937 bytes including the header,
compared with the older 17,067,985-byte source: this change targets compiler
work and dispatch cost, not smaller source text. All listed sources and headers
are hash-pinned through consumer build/run receipts. Authored compiled tests
verify same-page partition boundaries, object reuse and tamper rejection.

The final 17-unit authored probe independently passes Geargrafx's same 78-plan
matrix in both tiers: 156 CPU/MPR/latch states, 156 clock deltas and 78 complete
8 KiB RAM matches per tier, plus 306 local unchanged-state guard checks.
Native execution is 156 instructions with zero fallback. See
[measurement details](PERFORMANCE.md) and [reference scope](REFERENCE.md).

The expanded-module build passes all **21** enabled suites and **231 Python
tests**. An isolated clean source checkout with the same source digest passes
all **20 default suites** (231 tests, four desktop-only skips) and **21 SDL
suites** (all 231 tests), using empty module selection and authored inputs.
The official consumer interface separately builds a five-unit authored module
and verifies its header and every source in the receipt. Execution qualifies
200 native / zero interpreted instructions, A=41, X=140, PC=16387 and 1,794 ticks,
with a complete four-identity capture and unchanged source/input/output hashes.

The final optimized-module hidden SDL/TCP run reproduces all **93,735 frames**,
**25 complete guest PNG hashes** and the original **709 RAM interventions / 723
changed bytes**. It retires **2,920,491,782 native + 981 interpreted instructions**
and all **460,685 block transfers natively**. After checking ephemeral TCP port
and SDL host telemetry separately, its complete final runner JSON equals the
previous full-native run, including tier counts and 981 guard misses. No guest
field or tier counter is projected away in this additional comparison.
The earlier lower-coverage route remains a separate bridge. This adds no new
assistance, progression, boss victory or unassisted qualification. The owned
test host stopped; no new game screenshots were retained.

Local performance measurements separately record full-module compile time
**353.221 → 70.502 seconds** at the same two-job cap (one sample each), and
**1.09472×** authored dispatch throughput across five alternating measured
pairs with identical counters/checksums. A 30-million-instruction Ys III bootstrap
with 1,062 completed frames and zero fallback has identical complete final JSON;
whole-process medians are **3.059198 → 3.015789 seconds**. These scopes differ:
the bootstrap difference is roughly 1.4%, with startup/rendering/media overhead
included. Shared host load/caches are disclosed; no whole-campaign speed claim
is made. See [PERFORMANCE.md](PERFORMANCE.md) for controls and limits.

## Retained observed-code and consumer milestone

The shared compiler now accepts bounded retired-code observations and emits
multiple complete MPR contexts, source-byte variants and overlapping observed
interpretations. Logical PC, full mapping and exact instruction bytes remain
mandatory dispatch guards. The raw capture and generated game/firmware source
stay private. Runtime ABI is still **12**; consumer descriptor schema is **1**.

| Evidence | Result | Limit |
|---|---|---|
| Complete profiling route | 93,735 frames; 44,836 observed identities, 57 full MPR contexts, 2,920,492,763 retirements; zero dropped/unreadable instructions | Complete for this observed run only, not all reachable game code |
| Expanded direct C++ module | 44,832 compiled identities in 57 contexts; four identities / 981 observed hits excluded because they touch the temporary patch span | Original and patched interpretations in that span both remain interpreted; raw capture, original hit totals and completeness are unchanged |
| Executed coverage, full SDL/TCP replay | 2,920,491,782 native + 981 interpreted; **99.9999664% native**, up from 0.1729351%; all 460,685 block transfers native | Retired instruction ratio includes firmware/wait loops; no whole-program coverage, controlled speed benchmark or campaign-completion claim |
| Replay correctness | All 93,735 frames, 25 complete guest PNG hashes, 709 original RAM interventions / 723 changed bytes and every exposed final guest CPU/device/source value match; total retirements and clocks exact | Tier splits/guard counts intentionally change; ephemeral TCP port and additive SDL telemetry checked separately. No whole-RAM, composed-pixel or independent retail-route parity |
| Final Geargrafx observed-code probe | 78 authored plans; per tier 156 CPU/MPR/latch states, 156 instruction-clock deltas and 78 complete 8 KiB RAM comparisons; native tier 156 instructions, zero fallback; 306 local unchanged-state guard checks | Seven contexts / 21 compiled identities; remap, variants, cross-page/wrap, T/decimal, TMA/TAM, PHA/RTI. No IRQ delivery, device timing, retail-route or hardware qualification |
| Consumer interface, authored build/run | Pinned tool/source/ABI/module/input identities verified; embedded shared runtime builds without retail data; 200 native / zero interpreted instructions, A=41, X=140, PC=16387, ticks=1794; valid complete four-identity capture receipt | Source digest equals clean public-source checkout; build/run/capture identities checked separately; parent test configuration preserved |
| Separate Ys III consumer integration | Official project build/run guards reproduce all 93,735 frames, 25 images and 709 interventions with 2,784,362,065 native / 136,130,698 interpreted instructions (95.3387764%) | Consumer deliberately chooses a smaller 2,048-identity / nine-context original-code hot set; same tool source digest. Internal cross-project reproduction, not a second emulator or hardware oracle |
| Current default public-source build | All 19 suites pass; 202 Python tests discovered, four desktop-only skips | Empty module selection; authored fixtures, no private title/firmware/generated module |
| Current SDL public-source and expanded-module builds | All 20 suites and all 202 Python tests pass in each; 119 actual TCP assertions, 18 client checks, 122 SDL renderer/input assertions | Windows x64 / Clang 22.1.8 / SDL 3.4.18; other hosts and physical-controller interaction still require runs |

The successful expanded route uses the same input and assistance journal as
its baseline. It adds no new game progression or RAM intervention. The first
storehouse boss encounter and observed damage remain explicitly assisted;
there is no victory claim. The `gear-good` unknown-response profile and volatile
BRAM conditions remain visible and unresolved as before. See
[CODE_CAPTURE.md](CODE_CAPTURE.md), [CONSUMER.md](CONSUMER.md) and
[REFERENCE.md](REFERENCE.md).

## Retained hardware and gameplay evidence

The following rows preserve earlier qualification scopes and counters. Their
BRAM/debug-batch totals and older native modules describe those retained runs;
the current compiler/consumer result is recorded above.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Retained BRAM/debug default source checkout | Generic sandbox and optional reference probes compiled; all 19 suites pass; 155 Python tests discovered, with four desktop-only tests skipped | Windows x64; SDL disabled, empty module selection, no private dependencies or title inputs |
| Retained BRAM/debug desktop source checkout | All 20 suites and all 155 Python tests pass, including desktop and TCP host integration | Windows x64, SDL 3.4.18 SDK; empty module selection; authored fixtures only, no private game/firmware/generated module |
| Complete local verification, retained BRAM/debug batch | All 20 enabled suites pass, including 155 Python tests | Windows x64, optional SDL enabled; authored synthetic tests; public-source-only qualification is reported separately |
| Frontend/host unit suite, retained BRAM/debug batch | 155 tests pass, including initial-BRAM loader and execution-limit checks, 18 development-client checks and DMA-populated SATB/paused-observation checks | Media/analysis/decoding, loader/source protection, descriptors, controller/scripts, explicit response profiles, reference adapters and live runner/server integration; not retail game fixtures |
| Generic initial BRAM image, retained BRAM/debug batch | Optional read-only exact 2,048-byte seed loads into existing volatile BRAM; absent option preserves blank state; TCP/final JSON identify whether seeded | No formatting, file modification, export, persistent host saves or runtime ABI change; guest changes remain process-local |
| Local formatted-start SAVE/LOAD, retained BRAM/debug batch | Normal SAVE slot 1 at frame 17,886 and LOAD at 18,324 restore Weapon Shop with HP 20, EXP 0, gold 100 and STATUS strength/defense 20/25 | Authentic System Card FORMAT seed is read-only and unchanged; game uses existing volatile BRAM; no cross-process persistence/export or authentic-reset qualification |
| Independent Geargrafx formatted-start SAVE/LOAD and STATUS, retained BRAM/debug batch | Normal SAVE/LOAD slot 1 in Sarina retains STATUS 20/25; stable LEVEL 1 / STR 20 / DEF 25 / NEXT 100 text matches the local loaded scene: 80 × 32 crop, 2,560 pixels, zero differences | Crop aligned by (+24, +3); unrelated scene/menu/cursor/counters excluded; no full-frame, damage/reward, timing, CPU-state or hardware parity |
| Normal level progression, current local and reference routes | Local LEVEL 2, HP 30, EXP 102, gold 168, STATUS 25/30, NEXT 300; Geargrafx LEVEL 2, HP 30, EXP 108, gold 172, same STATUS 25/30/NEXT 300; both reach the four-exit junction | Separate normal-input routes with unequal EXP/gold: outcome classes and displayed stats only; no independent boss, full-route, campaign or audio qualification |
| Ordinary-input local route and current-host bridge | 60,338 frames; four-exit mine junction, normal slot-3 Mine Creek SAVE/LOAD at HP 17 / EXP 132, then stairway combat ending HP 6 / EXP 152; current host matches 14 complete PNG hashes and every original final CPU/device/source diagnostic | Zero RAM edits; only new host-control metadata is projected into older expectations; current-host reproducibility, not whole-route independent emulator or final SDL qualification |
| Assisted local route and retained replay checkpoint | Owner-authorized current-health refills; Roy's Pendant at frame 66,171 and Storehouse Key at 70,079 acquired through normal chest/dialogue triggers; temporary higher jump from 77,859; replay through 79,445 matches 18 complete PNG hashes, final diagnostics and 105 edits (104 health refills, one jump patch) | Separate from ordinary gameplay; no level/max-health/equipment/inventory/quest/position edits at this checkpoint; jump patch active there; no boss or final SDL result in that retained run |
| Later assisted storehouse-interior route, replayed through 87,449 | Clean requested quit after reaching green-brick storehouse interior through an ordinary room transition under position/height assistance; fresh headless replay matches 22 complete PNG hashes, final diagnostics and 346 edits: 128 health (one menu preview), 215 position/camera/cache/height experiments, one earned-item-state transfer after LOAD, two jump-patch transactions | Failed vertical/camera experiments were cleared by normal LOAD; higher-jump patch restored at 85,900; no extra PNG copies; no boss, final SDL or ordinary-gameplay qualification |
| Assisted first-storehouse-boss encounter, final route | Boss entered at frame 93,212; observed green wizard teleport/sword/fireball behavior; ordinary II attacks visibly reduce the ENEMY bar by frame 93,735; 523 boss frames with 14 current-health refills only | No code/position/camera-queue/inventory/quest writes after boss entry; jump patch restored at 85,900; successful approach restores actually earned item checkpoint, then uses queued ascent and height-held traverse, followed by ordinary room transition/Up door entry; no boss defeat, unassisted route or independent whole-route qualification |
| Final assisted local run, retained BRAM/debug batch | 93,735 frames / 33,650,360,835 ticks; 2,920,492,763 instructions: 5,050,558 native + 2,915,442,205 interpreted; 1,181 sectors, zero read errors; 372,199 IRQ/RTI sequences; 1,835,008 ADPCM DMA bytes; final actual/HUD HP 36 / maximum 40, EXP 466, gold 484, RP 75 | 709 RAM transactions / 723 changed bytes: 145 health (one historical menu preview), 463 position/cache/raw-camera experiments, 98 canonical queue, one earlier inventory test, two jump apply/restore; explicit unknown-response profile used 51 times; no victory or full native/AOT qualification |
| Final SDL cross-host replay | All 93,735 frames reproduce; 25 complete guest PNG hashes, all 709 edit transactions / 723 changed bytes and every exposed final CPU/device/source/debug diagnostic match; clean exit 0; zero new PNG files | Same frozen source and unchanged SDL binary; comparison covers exposed diagnostics and guest images, not whole RAM or every composed SDL pixel; internal reproducibility, not independent hardware/full-game parity |
| Independent Geargrafx assisted probes | Health readback/HUD checks, paired ordinary versus higher-jump arcs, and guarded horizontal relocation within the same loaded room | Scoped assist behavior only; no complete assisted route, boss, full-frame, timing, CPU-state or hardware parity; horizontal reference relocation is not local route evidence |
| Continuous video expectations, retained first-mine checks | 3,950 independent checks pass; existing 628,214 snapshot/palette expectations also pass | Historical palette/VRAM/SATB/scroll changes, CR/MWR latches, bounded publication/reset, all VCE timing controls, partitioning and unchanged guest state; physical fetch/contention and sprite IRQs excluded |
| Independent Geargrafx continuous video, retained video batch | Four authored plans × four distinct frames: 16 complete 256 × 192 RGB images / 786,432 pixels match byte for byte; final probe bridges all images and publication timestamps exactly | Active crop of Geargrafx's debug viewport; midline palette, line-latched scroll, VRAM changes, map wrap and sprite modes; no hardware/full-game frame qualification |
| Optional SDL3 desktop host, retained first-mine tests and earlier UI evidence | 122 renderer/input assertions pass; preceding video batch observed visible menu, Run-to-warning, pause/resume and fullscreen transitions | SDL 3.4.18 Windows x64; two-frame quick-tap retention and keypad direction aliases locally tested; physical controller and other operating systems unqualified |
| Loopback development server, retained BRAM/debug batch | 119 actual TCP assertions plus 18 Python client checks pass; both hosts' integration tests pass | Strict bounded protocol, five input slots, pause/step/status/capture/quit, paused RAM/ROM inspection and opt-in compare-before-write RAM edits; source invalidation, disabled/stale/cross-bank refusals, disconnect and stalled-peer behavior; no independent PC Engine oracle claim |
| Independent Geargrafx town controls, retained town batch | Authentic-reset route: 11,230 frames; two neutral-controlled I jump/land cycles; Select menu confirmed; aligned 72 x 40 menu text crop matches all 2,880 pixels | Different startup from local IPL sandbox; blinking cursor/unrelated scene excluded; no full retail-frame, CPU-state, combat, hardware or campaign parity claim |
| Independent Geargrafx first-mine combat, retained first-mine batch | Normal quest/shop progression and visible sword; HP 20 → 10, EXP 0 → 12, gold 100 → 108; death and settled Run retry restore HP 20 | Earlier selected-gear claim withdrawn: red slots alone were ambiguous; restored checkpoint STATUS remains 10/10. Different starting scene/cadence permits outcome-class corroboration only; no exact damage/reward/frame/CPU parity, kill count, boss, campaign, audio or hardware qualification |
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
| Independent Geargrafx MPR batch, retained prior evidence | 524 sequences, 1,614 instruction states and 524 final RAM/latch comparisons per route passed | Not rerun in the retained BRAM/debug batch; native-first: 1,078 native + 536 interpreted after context changes |
| Independent Geargrafx bit-test/branch/BSR batch, retained prior evidence | 480 native + 480 interpreter comparisons across all 30 opcodes passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx RMW/JMP batch, retained prior evidence | 512 native + 512 interpreter comparisons across all 32 opcodes passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx data batch, retained prior evidence | 1,552 native + 1,552 interpreter comparisons across all 97 data encodings passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx bit/stack, retained prior evidence | 128 native + 128 interpreter comparisons across all 24 bit/stack opcodes passed | Not rerun in the retained BRAM/debug batch |
| Independent Geargrafx baseline, retained prior evidence | 188 native + 188 interpreter comparisons across the original 47 opcodes passed | Not rerun in the retained BRAM/debug batch |
| Local owner-supplied Ys III USA CHD | Track metadata, hashing, two-hunk decompression and 4 KiB initial program extraction verified | Filename/internal title identify the local input; no external dump-database certification |
| Supplied USA v3.0 firmware | Raw 256 KiB size and MD5 match the documented USA BIOS; SHA1/SHA256 pinned locally | Supplied patched USA/Japan images have distinct hashes and are excluded from the baseline; see FIRMWARE.md |
| Boot-program-only analysis | 203 discovered instruction sites, all 203 native-emittable, 25 unresolved records | Static discovery is not an execution-coverage measurement |
| Combined local boot/BIOS snapshot | 785 discovered sites, all 785 native-emittable, 47 unresolved records under a 1,024-instruction analysis limit | One initial MPR context; no speculative firmware services |
| Compiled local boot/BIOS module, retained ABI-11 conditional story route | 229,808,207 instructions: 7,234,070 native + 222,574,137 interpreted; 288 sectors, 589,828 DATA IN ACKs including four TOC bytes, 262,144 ADPCM DMA bytes and 18,191 IRQ/RTI sequences; 22 scripted host events; Beginning/Continue → Beginning → blank volatile-BRAM warning → Proceed → opening story portraits and river/mountains/bird scene | Tick-budget stop at 3,000,000,009 ticks, about 139.7 guest seconds, no runtime fault; requires explicit `--cd-unknown-status gear-good`, used twice; no continuous rendering in this retained run, controllable gameplay, campaign, authentic reset or audio-output proof |
| Compiled local boot/BIOS module, ABI-12 continuous menu route | 30 million instructions, 1,062 completed historical frames; all compared CPU/CD/VDC fields exactly match the retained menu route | Recompiled same initial snapshot; reference-response opt-in still required; actual desktop menu observed separately; no full native/AOT or gameplay qualification |
| Compiled local boot/BIOS module, ABI-12 continuous story route | 8,356 completed frames; 229,808,207 instructions: 7,234,070 native + 222,574,137 interpreted; 288 sectors, 262,144 ADPCM DMA bytes, 18,191 IRQ/RTI sequences and all 22 scripted events; historical image shows river/mountains/bird scene | Tick-budget stop at 3,000,000,009 ticks, about 139.7 guest seconds, no runtime fault; same response-profile condition and execution totals as the retained story route; no controllable gameplay, campaign, authentic reset, audible output or full native/AOT qualification |
| Actual SDL window with TCP-controlled Ys III route, retained video batch | Menu → Beginning → warning → Down selects Proceed → I confirms → boat/mast and opening portrait scenes; 8,000 frames, 2,871,925,884 ticks / 133.7 guest seconds; 7,301,883 native + 213,086,766 interpreted instructions; 16,037 IRQ/RTI, 288 sectors, zero read errors, 262,144 ADPCM DMA bytes; clean requested quit | Eight requested guest/SDL captures, no per-frame dump; final hidden GPU-window replay matches three retained guest-image hashes and final state totals; response-profile opt-in used twice; no gameplay/campaign, authentic reset or audible output claim |
| Compiled local boot/BIOS module, retained ABI-12 TCP town-control route | 25,476 frames / 9,145,722,501 ticks; 761,925,353 instructions: 8,504,219 native + 753,421,134 interpreted; 867 sectors, zero read errors, 1,251,328 ADPCM DMA bytes, 79,118 IRQ/RTI sequences; directional movement/camera, I jump, Select menu, world map and town return observed | Clean TCP quit; exact hidden SDL replay matches five complete guest PNG hashes and all final CPU/device diagnostics; explicit unknown-response profile used four times; retained 785-site module, mostly interpreted; no combat/mine/campaign/audio/authentic-reset qualification in that run |
| Compiled local boot/BIOS module, retained ABI-12 TCP first-mine combat route | 31,819 frames / 11,422,827,780 ticks, about 531.9 guest seconds; 948,642,279 instructions: 8,504,219 native + 940,138,060 interpreted; 915 sectors, zero read errors, 1,316,864 ADPCM DMA bytes, 104,414 IRQ/RTI sequences; Tigre unlocked normally, unarmoured death/Run retry, starter gear bought and positively selected, visible sword; final HP 20 → 2, EXP 0 → 12, gold 100 → 108 | Clean TCP quit; exact hidden SDL replay matches seven complete guest PNG hashes and every final CPU/device diagnostic; explicit unknown-response profile used nine times; retained 785-site module, mostly interpreted; no guest CPU/device patch needed; exact kill count, deeper mine/boss/campaign, audio, authentic reset and full native/AOT unqualified |

The first-mine EXP observation above corrects the prior transcription of 124.
Exact glyph checks on the retained frame establish EXP `00012` and the separate
RING field `004`. This corrects the HUD reading; the equipment, attack,
received-damage and gold-reward observations are unchanged. The retained BRAM/debug build's
155-test qualification is separate from retained first-mine gameplay evidence.
New formatted-start SAVE/LOAD, STATUS, ordinary-input mine progression and
the assisted checkpoints are qualified only as listed above. The local
first-boss encounter and visible enemy damage are established under health
assistance. Final route accounting and successful SDL replay are recorded above. No boss
defeat, complete campaign or ordinary-gameplay qualification is claimed.

The public baseline has no ROM, BIOS, extracted game bytes, generated game
source, save files or initialized personal install. Private derived data is
under ignored `.local/`. Original CHD SHA256 was established before work and
is checked again at closeout; nothing writes the original image.

The local toolchain does not provide a `ctest` binary; verification uses
`python scripts/check.py`. The retained pre-desktop batch passed all 17 suites
and 112 Python tests, including a separate generic public-source build.
The retained BRAM/debug build passed all 20 enabled suites, including 155 Python
tests, adding generic initial-BRAM loading and larger explicit execution limits.
The current observed-code/consumer build passes all 202 Python tests as recorded above.
The retained first-mine build passed 138 Python tests. GitHub CI
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
- Both runners accept `--bram RAW_2048_IMAGE`, a read-only exact 2,048-byte
  initial snapshot for existing volatile BRAM. The default remains blank;
  there is no format fabrication, export or host file persistence. Initial
  BRAM use is visible in TCP status and final JSON. A private blank seed
  produced by normal System Card FORMAT inputs in Geargrafx eliminates the
  local startup warning; normal game SAVE/LOAD is observed within volatile
  memory. No changes are written back to the seed. See [REFERENCE.md](REFERENCE.md#initial-bram-image-and-authentic-format-provenance).
- The explicit dispatcher step allowance is at most 20,000,000,000. Tick
  deadlines and optional 1–600-second wall limits still apply.
- PSG retains functional register state. ADPCM implements RAM/port/playback
  consumption and CD DMA, and CDDA models position/control/fader state.
  Oscillators, PCM decoding/mixing and audible output remain unimplemented.
- Deadline accounting is at instruction boundaries, not cycle-accurate.
- CFG-derived modules retain one MPR context and stop discovery at mapping
  changes. Observed-code modules support multiple full contexts and source-byte
  variants, preserving per-instruction guards and explicit fallback.
- Bounded retired-code capture and offline direct emission are implemented.
  No automatic in-process recompiler, persistent overlay cache or optimizing
  block IR is implemented.
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
  not automatic. It does not capture the owner's desktop. Paused RAM edits
  require separate opt-in and whole-range expected bytes; edit counters
  distinguish assisted tests. See [DEV_SERVER.md](DEV_SERVER.md).
- No persistent host save files, save export, rewind, netplay or enhancement release. The full target remains in
  the roadmap.

## Next useful batch

Evaluate guarded multi-instruction blocks and persistent cache identity using
the measured partitioned-module baseline. Preserve exact
source/mapping invalidation, aggregate clock/IRQ behavior and explicit fallback.
Measure compile time, instruction/cycle work and controlled end-to-end performance
separately; hot firmware loops do not measure game completion.

The separate game consumer owns campaign progression, title configuration and
its chosen hot/cold native policy. Use its focused, hash-pinned defect reports
and additional authored diagnostic programs to expand the general toolkit.
Decoded/mixed audio, exact device access phases and the unknown CD command's
operation remain separate correctness tasks. The response-profile opt-in does
not resolve hardware behavior; the IPL-entry sandbox is not authentic reset.

All seven protected input hashes match. No owner installation, original media,
saves or settings were modified. The final Geargrafx process stopped and its
temporary configuration was removed. The toolkit's test hosts have stopped;
the independently owned consumer chat may continue its own tests. Desktop
control was not used during this batch.

Shared positive output growth at closeout is approximately **88 MiB** across
both workspaces and the measured temporary roots, within the owner's **1 GiB**
allowance. A conservative inventory of both complete toolkit build trees,
owned batch directories, the entire concurrent consumer batch and positive
shared-Temp growth is about **198 MiB**, including reused outputs. Existing SDKs
and immutable inputs were reused. The full-route check reuses retained images,
creating zero new retail PNG files.
The private accounting receipt discloses three pre-existing unreadable Temp
folders and any scan races; this is measured logical growth, not a claim to
inspect unrelated private folders.

Contributor issues reviewed on 23 October 2026: #1 (RMB/SMB) and #2 (stack) are
closed; #3 (media fixtures) and #4 (cycle-aware traces/second oracle) remain
open. This batch adds an authored Geargrafx compilation-path probe and does
not close the second-oracle or bus-phase work.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md),
[CONSUMER.md](CONSUMER.md) and [ROADMAP.md](ROADMAP.md) before continuing.
