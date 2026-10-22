# Current status — 22 October 2026

## Verified baseline

This is an executable architecture foundation, **not a playable emulator
or game port**. The public source needs no retail input to build or test.

| Evidence | Result | Limit |
|---|---|---|
| Windows x64, Python 3.14.5, Clang 22.1.8, CMake 3.31.12, Ninja | Runtime, generated synthetic modules, headless runner and optional reference probe compiled | Other hosts require their own build/run evidence |
| Frontend unit suite | 25 tests pass | Synthetic media/analysis/decoding and source protection |
| Internal native/interpreter checks | 3,008 comparisons across 47 opcodes pass | Shared framework assumptions can still be wrong |
| Independent Geargrafx 1.8.4 MCP check | 188 native + 188 interpreter comparisons pass | Single-step registers/flags/PC/MPRs and 8 KiB RAM; no cycle/device parity |
| Local owner-supplied Ys III USA CHD | Track metadata, hashing, two-hunk decompression and 4 KiB initial program extraction verified | Filename/internal title identify the local input; no external dump-database certification |
| Boot-program analysis | 203 discovered instruction sites, 149 native-emittable sites, 25 unresolved records | Static discovery is not an execution-coverage measurement |
| Compiled local boot-program module | Six native instructions retire, then explicit stop at logical `$4811` (`RMB1`) | No System Card execution, title screen, gameplay, graphics or sound |

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

- Decoder metadata covers 256 encoding slots; runtime support is 47 opcodes.
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

Build on the now-working independent MCP comparison before adding CPU
families. Add RMB/SMB and push/pop with independently expected flags/stack
cases, then complete the interpreter's addressing/ALU/T/decimal semantics.
Expand the reference harness for cycle/event traces and the real memory map.
Do not stub System Card calls to make the Ys III route appear to boot.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [REFERENCE.md](REFERENCE.md) and
[ROADMAP.md](ROADMAP.md) before continuing. The optional reference process
is stopped after each run; no owner application or live save root was used.
