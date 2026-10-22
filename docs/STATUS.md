# Current status — 22 October 2026

## Verified baseline

This is an executable architecture foundation, **not a playable emulator
or game port**. The public source needs no retail input to build or test.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Clean checkout of the public GitHub source | Built the generic sandbox, three generated synthetic modules and reference probes; frontend/runtime/CD-control suites and source audit passed | Windows x64; no private dependencies or title inputs used |
| Frontend/host unit suite | 42 tests pass | Synthetic media/analysis/decoding, firmware loader/protection, source protection, trace rejection and reference-vector/sequence coverage |
| Internal native/interpreter checks | 14,336 comparisons across 224 opcodes pass | Shared framework assumptions can still be wrong |
| Independently expected bit/stack checks | 92,160 cases pass across both tiers, plus mutation/mapping/fault checks | Instruction-level cycles checked; no bus-phase/IRQ model |
| Independently expected data checks | 7,340,032 arithmetic/logic cases and 340 addressing cases pass | All ADC/SBC byte pairs under C/D/T/V combinations in both tiers; instruction-level timing only |
| Independently expected RMW/JMP checks | 3,932,160 RMW and 16,384 indirect JMP cases pass, plus native wrap/MMU/fault checks | Every RMW byte/status combination in both tiers; instruction-level timing only |
| Independently expected bit-test/branch/BSR checks | 4,849,664 bit-test and 2,228,224 branch/BSR cases pass | Synthetic operands/status/stack cases; fixed native immediate/mask values, not every encoding of literals |
| Independently expected MPR/latch checks | 1,114,112 cases pass, plus remap/mutation/deadline sequences | All masks/byte values in both tiers; arbitrary-map OR sweep interpreted; instruction-level timing only |
| Independently expected speed checks | 524,288 cases pass, plus sequence/deadline/mutation/fault checks | All status/latch bytes, both entry speeds and tiers; independently specified split-cycle tick table |
| Independently expected CD-control/BRAM checks | 61,440 native/interpreter instruction cases pass, plus whole-extent, lock/alias/RMW/guard/deadline/fault checks | All byte values under four flag contexts; idle control profile; no transport/audio/scheduler |
| Independent Geargrafx 1.8.4 MCP check, current CD-control batch | 48 sequences; 720 CPU/device states and 48 full RAM/BRAM comparisons per tier pass | Two disjoint shards; authored synthetic bootstrap/CD; 720 native vs 720 interpreted instructions; no live nonzero IRQ-source, cycle/device-phase or gameplay proof |
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
| Compiled local boot/BIOS module, ABI 3 | Hybrid retires 48 native + 31 interpreted instructions; `$1807` unlock and `$1803` lock execute; stops at `$FCC7` on STA to unimplemented VDC select port `$0000` | Native-only still yields at `$FC8F`; final divisor 3, 366 cycles/2,313 ticks; zeroed RAM and unformatted volatile BRAM; no authentic reset/gameplay/graphics/sound |

The public baseline has no ROM, BIOS, extracted game bytes, generated game
source, save files or initialized personal install. Private derived data is
under ignored `.local/`. Original CHD SHA256 was established before work and
is checked again at closeout; nothing writes the original image.

The local toolchain does not provide a `ctest` binary, so the three registered
suites were executed directly through `python scripts/check.py`. GitHub CI
template uses CTest on Windows/Linux/macOS runners and separately builds the
pinned optional CHD backend. The initial CLI credential lacks GitHub's
`workflow` scope, so `.github/ci-template.yml` is initially inactive. No remote
CI pass is claimed. Enable it using the instructions in the developer guide.

## Deliberate limits

- Decoder metadata covers 256 encoding slots; runtime support is 224 opcodes.
- Load/store, logical, ADC/SBC and comparison encodings are supported, including
  indexed/indirect data addressing, T destinations and decimal arithmetic.
- Shifts/rotates, INC/DEC memory/accumulator and both indirect JMP forms are supported;
  indirect destinations remain unresolved in static discovery.
- RMB/SMB, push/pop, BIT/TSB/TRB/TST, BBR/BBS and BSR are supported.
- TAM/TMA cover all masks and the persistent transfer latch. I/O open bus is
  separate and unimplemented. Current native ABI is 3; regenerate older modules.
- CSL/CSH use two cycles at entry speed and one at selected speed.
  Geargrafx's live transition timestamps differ; see CPU_SEMANTICS.md.
- Limited idle CD-control/BRAM routing is implemented; see CD_CONTROL.md for
  exact registers and reference discrepancies. `$1807` subcode reads still trap.
- No complete interpreter, full System Card profile, general device bus,
  RAM mirrors, CD transport/audio or IRQ delivery model.
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

The CPU batches and limited idle CD-control/BRAM batch are implemented. See
[CPU_SEMANTICS.md](CPU_SEMANTICS.md) for pointer wrapping, T destinations,
decimal flags, MPR latch behavior and instruction totals. Continue with
VDC register/port and actual bus/scheduler contracts exposed at `$FCC7`,
then CD transport, block-transfer and interrupt semantics. Indirect
control flow remains conservative. The focused CPU-entry trace does not
complete the general cycle/event adapter or supply a second live oracle.
Expand the reference harness for cycle/event traces and the real memory map.
Do not stub System Card calls to make the Ys III route appear to boot.

Contributor issues reviewed this batch: #1 (RMB/SMB) and #2 (stack) are closed;
#3 (media fixtures) and #4 (cycle-aware traces/second oracle) remain open with
no new comments. Their GitHub state was inspected, not changed.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md) and
[ROADMAP.md](ROADMAP.md) before continuing. The optional reference process
is stopped after each run; no owner application or live save root was used.
