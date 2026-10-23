# Current status — 22 October 2026

## Verified baseline

This is an executable architecture foundation, **not a playable emulator
or game port**. The public source needs no retail input to build or test.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Public checkout, preceding CD-transport batch (retained evidence) | Built the generic sandbox and synthetic targets; all six registered suites passed | Windows x64; no private dependencies or title inputs used |
| Frontend/host unit suite | 87 tests pass | Synthetic media/analysis/decoding, firmware loader/protection, source protection, TOC geometry and untrusted descriptor boundaries, joypad CLI/snapshots, trace rejection and reference-vector/sequence coverage |
| Internal native/interpreter checks | 14,528 comparisons across 227 opcodes pass | Shared framework assumptions can still be wrong |
| Independently expected bit/stack checks | 92,160 cases pass across both tiers, plus mutation/mapping/fault checks | Instruction-level cycles checked; no bus-phase/IRQ model |
| Independently expected data checks | 7,340,032 arithmetic/logic cases and 340 addressing cases pass | All ADC/SBC byte pairs under C/D/T/V combinations in both tiers; instruction-level timing only |
| Independently expected RMW/JMP checks | 3,932,160 RMW and 16,384 indirect JMP cases pass, plus native wrap/MMU/fault checks | Every RMW byte/status combination in both tiers; instruction-level timing only |
| Independently expected bit-test/branch/BSR checks | 4,849,664 bit-test and 2,228,224 branch/BSR cases pass | Synthetic operands/status/stack cases; fixed native immediate/mask values, not every encoding of literals |
| Independently expected MPR/latch checks | 1,114,112 cases pass, plus remap/mutation/deadline sequences | All masks/byte values in both tiers; arbitrary-map OR sweep interpreted; instruction-level timing only |
| Independently expected speed checks | 524,288 cases pass, plus sequence/deadline/mutation/fault checks | All status/latch bytes, both entry speeds and tiers; independently specified split-cycle tick table |
| Independently expected CD-control/BRAM checks | 61,440 native/interpreter instruction cases pass, plus whole-extent, lock/alias/RMW/guard/deadline/fault checks | All byte values under four flag contexts; idle control profile; no transport/audio/scheduler |
| Independently expected CD-transport checks | 8,369 groups pass: 4,096 latch/control byte groups, 4,096 RMW groups and directed handshake/timing/reset/IRQ/guard/refusal checks | Both execution tiers and CPU speeds; literal local deadlines, TEST UNIT READY only; no sector responses or live access-phase proof |
| Independently expected TOC/DATA IN checks | 418 groups pass: literal BCD/response bytes, manual/auto-ACK timing, status/message completion, data IRQs, reset/selection aborts, metadata validation and explicit refusal | Both execution tiers/speeds; four-byte Gear/Mesen metadata-response profile, no readable sector provider or hardware qualification |
| Independently expected joypad checks | 50,341 cases/groups pass: 32,768 button, 8,192 control, 136 tap, 9,228 bus and 17 host/configuration checks; eight synthetic headless tests also pass | Both execution tiers/speeds; selected Geargrafx reference profile, no desktop polling or physical controller qualification |
| Independent Geargrafx 1.8.4 joypad check | 56 plans, 2,512 CPU/port-read checkpoints and 56 complete 8 KiB work-RAM comparisons per tier pass; 2,512 native vs 2,512 interpreted instructions | USA region with CD present/absent; Japanese line local/source-only; guest output observations, no direct internal controller-state, host event timing, hardware or gameplay proof |
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
| Compiled local boot/BIOS module, ABI 8 | Completes metadata TOC DATA IN and 10 joypad reads / 12 writes; 25,201 native + 13,984 interpreted instructions, 130,379 cycles / 392,352 master ticks | Released and held Run snapshots reach unsupported CD READ `$08` at `$EA4A`; one VBlank, no sector read, authentic reset, gameplay, graphics or sound proof |

The public baseline has no ROM, BIOS, extracted game bytes, generated game
source, save files or initialized personal install. Private derived data is
under ignored `.local/`. Original CHD SHA256 was established before work and
is checked again at closeout; nothing writes the original image.

The local toolchain does not provide a `ctest` binary, so the seven registered
suites were executed directly through `python scripts/check.py`. GitHub CI
template uses CTest on Windows/Linux/macOS runners and separately builds the
pinned optional CHD backend. The initial CLI credential lacks GitHub's
`workflow` scope, so `.github/ci-template.yml` is initially inactive. No remote
CI pass is claimed. Enable it using the instructions in the developer guide.

## Deliberate limits

- Decoder metadata covers 256 encoding slots; runtime support is 227 opcodes.
- Load/store, logical, ADC/SBC and comparison encodings are supported, including
  indexed/indirect data addressing, T destinations and decimal arithmetic.
- Shifts/rotates, INC/DEC memory/accumulator and both indirect JMP forms are supported;
  indirect destinations remain unresolved in static discovery.
- RMB/SMB, push/pop, BIT/TSB/TRB/TST, BBR/BBS and BSR are supported.
- TAM/TMA cover all masks and the persistent transfer latch. I/O open bus is
  separate and unimplemented. Current native ABI is 8; regenerate older modules.
- CSL/CSH use two cycles at entry speed and one at selected speed.
  Geargrafx's live transition timestamps differ; see CPU_SEMANTICS.md.
- Idle CD-control/BRAM routing and opt-in clocked selection/REQ/ACK transport
  are implemented; TEST UNIT READY and directory/TOC modes 0/1/2 complete
  through DATA IN where needed, then status and message phases. Manual and
  `$1808` auto-ACK are supported for bounded metadata responses.
  See CD_CONTROL.md for exact registers, reference delays and discrepancies.
  Sector, sense, subcode and audio commands still trap. Metadata attachment
  does not provide a readable sector backend or verify the original image at runtime.
- Opt-in joypad I/O routes all `$1000..$13FF` mirrors, with two/six-button
  pads, a five-port TurboTap, region/CD bits and guest-write-sampled output.
  Headless flags provide held button snapshots; desktop input and other
  peripherals remain planned. See [INPUT.md](INPUT.md) for source disagreements.
- Functional single-VDC ports/registers, buffered VRAM and ST0/ST1/ST2 are
  implemented; DMA triggers and undriven reads fault. See [VDC.md](VDC.md).
- Opt-in raster timing generates VBlank and raster-comparison events from
  master-clock horizontal/vertical phases. VCE timing control selects dot
  divisors and 262/263-line frames; palette access remains unsupported.
- No complete interpreter, full System Card profile, general device bus,
  RAM mirrors, CD sector/audio backend or CPU IRQ delivery model. An eligible
  unmasked IRQ1 or IRQ2 stops explicitly.
- Deadline accounting is at instruction boundaries, not cycle-accurate.
- One MPR context per emitted module; mapping changes stop static discovery.
- No persistent overlay cache, capture/recompile loop or optimizing block IR.
- CHD reader supports v5 CD metadata and MODE1/RAW user sectors. Boot
  extraction supports only its documented loader subset. BIN/CUE is planned.
- The headless runner loads a single contiguous payload into an explicit
  sandbox, optionally with a supplied read-only 256 KiB System Card ROM.
  It is not an authentic console reset/BIOS state.
- No renderer/audio/input desktop implementation, saves, rewind, netplay or
  enhancement release. The full target remains in the roadmap.

## Next useful batch

The VDC register/VRAM, raster-event, CD control-handshake, TOC DATA IN and
joypad profiles are implemented. The bounded BIOS route completes its
controller scan and stops explicitly on CD READ (`$08`). A coherent next
batch needs a bounded read-only sector provider with image identity checks,
DATA IN sector streaming, cancellation and actual error semantics. TOC metadata
does not supply sector data. CPU interrupt entry/priority, remaining bus
phases, timer scheduling, block transfers and DMA also remain. The clocked
profile is separate from rendering and host presentation. See [INPUT.md](INPUT.md),
[VDC.md](VDC.md) and [CPU_SEMANTICS.md](CPU_SEMANTICS.md) for exact limits.
Indirect control flow remains conservative. Device-clock and CPU-entry
observations do not complete a general bus/event trace adapter or provide a
second live oracle. Do not fake status events or stub System Card calls to
make a title appear to boot.

Contributor issues reviewed again in this batch: #1 (RMB/SMB) and #2 (stack) are closed;
#3 (media fixtures) and #4 (cycle-aware traces/second oracle) remain open with
no new comments. Their GitHub state was inspected, not changed.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md) and
[ROADMAP.md](ROADMAP.md) before continuing. The optional reference process
is stopped after each run; no owner application or live save root was used.
