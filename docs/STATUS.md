# Current status — 22 October 2026

## Verified baseline

This is an executable architecture foundation, **not a playable emulator
or game port**. The public source needs no retail input to build or test.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Clean checkout of the public GitHub source | Built the generic sandbox, both generated synthetic modules and reference probe; frontend/runtime suites and source audit passed | Windows x64; no private dependencies or title inputs used |
| Frontend/host unit suite | 38 tests pass | Synthetic media/analysis/decoding, firmware loader/protection, source protection and reference-vector/sequence coverage |
| Internal native/interpreter checks | 14,208 comparisons across 222 opcodes pass | Shared framework assumptions can still be wrong |
| Independently expected bit/stack checks | 92,160 cases pass across both tiers, plus mutation/mapping/fault checks | Instruction-level cycles checked; no bus-phase/IRQ model |
| Independently expected data checks | 7,340,032 arithmetic/logic cases and 340 addressing cases pass | All ADC/SBC byte pairs under C/D/T/V combinations in both tiers; instruction-level timing only |
| Independently expected RMW/JMP checks | 3,932,160 RMW and 16,384 indirect JMP cases pass, plus native wrap/MMU/fault checks | Every RMW byte/status combination in both tiers; instruction-level timing only |
| Independently expected bit-test/branch/BSR checks | 4,849,664 bit-test and 2,228,224 branch/BSR cases pass | Synthetic operands/status/stack cases; fixed native immediate/mask values, not every encoding of literals |
| Independently expected MPR/latch checks | 1,114,112 cases pass, plus remap/mutation/deadline sequences | All masks/byte values in both tiers; arbitrary-map OR sweep interpreted; instruction-level timing only |
| Independent Geargrafx 1.8.4 MCP check, current MPR batch | 524 sequences, 1,614 instruction states and 524 final RAM/latch comparisons per route pass | Four disjoint shards; native-first route: 1,078 native + 536 interpreted after context changes; pure interpreter: 1,614 interpreted; no live cycle/device parity |
| Independent Geargrafx bit-test/branch/BSR batch, retained prior evidence | 480 native + 480 interpreter comparisons across all 30 opcodes passed | Not rerun in the current batch |
| Independent Geargrafx RMW/JMP batch, retained prior evidence | 512 native + 512 interpreter comparisons across all 32 opcodes passed | Not rerun in the current batch |
| Independent Geargrafx data batch, retained prior evidence | 1,552 native + 1,552 interpreter comparisons across all 97 data encodings passed | Not rerun in the current batch |
| Independent Geargrafx bit/stack, retained prior evidence | 128 native + 128 interpreter comparisons across all 24 bit/stack opcodes passed | Not rerun in the current batch |
| Independent Geargrafx baseline, retained prior evidence | 188 native + 188 interpreter comparisons across the original 47 opcodes passed | Not rerun in the current batch |
| Local owner-supplied Ys III USA CHD | Track metadata, hashing, two-hunk decompression and 4 KiB initial program extraction verified | Filename/internal title identify the local input; no external dump-database certification |
| Supplied USA v3.0 firmware | Raw 256 KiB size and MD5 match the documented USA BIOS; SHA1/SHA256 pinned locally | Supplied patched USA/Japan images have distinct hashes and are excluded from the baseline; see FIRMWARE.md |
| Boot-program-only analysis | 203 discovered instruction sites, all 203 native-emittable, 25 unresolved records | Static discovery is not an execution-coverage measurement |
| Combined local boot/BIOS snapshot | 785 discovered sites, all 785 native-emittable, 47 unresolved records under a 1,024-instruction analysis limit | One initial MPR context; no speculative firmware services |
| Compiled local boot/BIOS module, ABI 2 | 48 native instructions retire; TMA passes; TAM changes MPR4/latch to `$F7`; native guard yields at CSL `$FC8F`; hybrid confirms unsupported CSL with matching state | Zero interpreted instructions; zeroed sandbox RAM, explicit MPRs and initial latch zero; no authentic reset/BIOS initialization, title screen, gameplay, graphics or sound |

The public baseline has no ROM, BIOS, extracted game bytes, generated game
source, save files or initialized personal install. Private derived data is
under ignored `.local/`. Original CHD SHA256 was established before work and
is checked again at closeout; nothing writes the original image.

The local toolchain does not provide a `ctest` binary, so the two registered
suites were executed directly through `python scripts/check.py`. GitHub CI
template uses CTest on Windows/Linux/macOS runners and separately builds the
pinned optional CHD backend. The initial CLI credential lacks GitHub's
`workflow` scope, so `.github/ci-template.yml` is initially inactive. No remote
CI pass is claimed. Enable it using the instructions in the developer guide.

## Deliberate limits

- Decoder metadata covers 256 encoding slots; runtime support is 222 opcodes.
- Load/store, logical, ADC/SBC and comparison encodings are supported, including
  indexed/indirect data addressing, T destinations and decimal arithmetic.
- Shifts/rotates, INC/DEC memory/accumulator and both indirect JMP forms are supported;
  indirect destinations remain unresolved in static discovery.
- RMB/SMB, push/pop, BIT/TSB/TRB/TST, BBR/BBS and BSR are supported.
- TAM/TMA cover all masks and the persistent transfer latch. I/O open bus is
  separate and unimplemented. ABI 2 requires regenerating old native modules.
- No complete interpreter, full System Card profile, device bus, RAM mirrors or IRQ model.
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

The bit/stack, data, RMW/JMP, bit-test/branch/BSR and MPR batches are implemented. See
[CPU_SEMANTICS.md](CPU_SEMANTICS.md) for pointer wrapping, T destinations,
decimal flags, MPR latch behavior and instruction totals. Continue with
CSL/CSH speed semantics, exposed next by the supplied BIOS at `$FC8F`, then
port, block-transfer and interrupt semantics. Indirect control flow remains conservative.
Expand the reference harness for cycle/event traces and the real memory map.
Do not stub System Card calls to make the Ys III route appear to boot.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md) and
[ROADMAP.md](ROADMAP.md) before continuing. The optional reference process
is stopped after each run; no owner application or live save root was used.
