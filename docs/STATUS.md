# Current status — 22 October 2026

## Verified baseline

This is an executable architecture foundation, **not a playable emulator
or game port**. The public source needs no retail input to build or test.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Fresh clone from the public GitHub repository | Built the generic sandbox, both generated synthetic modules and reference probe; frontend/runtime suites and source audit passed | Windows x64; no private dependencies or title inputs used |
| Frontend unit suite | 30 tests pass | Synthetic media/analysis/decoding, source protection and reference-vector coverage |
| Internal native/interpreter checks | 10,176 comparisons across 159 opcodes pass | Shared framework assumptions can still be wrong |
| Independently expected bit/stack checks | 92,160 cases pass across both tiers, plus mutation/mapping/fault checks | Instruction-level cycles checked; no bus-phase/IRQ model |
| Independently expected data checks | 7,340,032 arithmetic/logic cases and 340 addressing cases pass | All ADC/SBC byte pairs under C/D/T/V combinations in both tiers; instruction-level timing only |
| Independent Geargrafx 1.8.4 MCP check, current data batch | 1,552 native + 1,552 interpreter comparisons across all 97 data encodings pass | Four disjoint completed shards; full C/D/T/V contexts, registers/PC/MPRs and 8 KiB RAM; no live cycle/device parity |
| Independent Geargrafx bit/stack, retained prior evidence | 128 native + 128 interpreter comparisons across all 24 bit/stack opcodes passed | Not rerun in the data batch |
| Independent Geargrafx baseline, retained prior evidence | 188 native + 188 interpreter comparisons across the original 47 opcodes passed | Not rerun in the data batch |
| Local owner-supplied Ys III USA CHD | Track metadata, hashing, two-hunk decompression and 4 KiB initial program extraction verified | Filename/internal title identify the local input; no external dump-database certification |
| Boot-program analysis | 203 discovered instruction sites, 186 native-emittable sites, 25 unresolved records | Static discovery is not an execution-coverage measurement |
| Compiled local boot-program module | Eight native instructions retire, then yield at `$E05A`; hybrid mode confirms an unmapped firmware read | The old RMB1 stop is resolved; no System Card execution, title screen, gameplay, graphics or sound |

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

- Decoder metadata covers 256 encoding slots; runtime support is 159 opcodes.
- Load/store, logical, ADC/SBC and comparison encodings are supported, including
  indexed/indirect data addressing, T destinations and decimal arithmetic.
- Shifts/rotates, INC/DEC memory/accumulator and indirect JMP remain unsupported.
- RMB/SMB and push/pop are supported; BIT/TSB/TRB/TST and bit branches remain unsupported.
- No complete interpreter, System Card, device bus, RAM mirrors or IRQ model.
- Deadline accounting is at instruction boundaries, not cycle-accurate.
- One MPR context per emitted module; mapping changes stop static discovery.
- No persistent overlay cache, capture/recompile loop or optimizing block IR.
- CHD reader supports v5 CD metadata and MODE1/RAW user sectors. Boot
  extraction supports only its documented loader subset. BIN/CUE is planned.
- The headless runner loads a single contiguous payload into an explicit
  sandbox. It is not an authentic console reset/BIOS state.
- No renderer/audio/input desktop implementation, saves, rewind, netplay or
  enhancement release. The full target remains in the roadmap.

## Next useful batch

The bit/stack and load/store/logical/arithmetic/comparison batches are
implemented. See [CPU_SEMANTICS.md](CPU_SEMANTICS.md) for pointer wrapping,
T destinations, decimal flags and instruction totals. Continue with
shifts/rotates, INC/DEC, indirect JMP and the remaining bit instruction families.
Expand the reference harness for cycle/event traces and the real memory map.
Do not stub System Card calls to make the Ys III route appear to boot.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md) and
[ROADMAP.md](ROADMAP.md) before continuing. The optional reference process
is stopped after each run; no owner application or live save root was used.
