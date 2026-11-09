# Native-port toolkit readiness

The toolkit has a supported, reusable path from authentic observations to a
pinned, compiled and executed native consumer. It is experimental: successful
bounded qualification does not certify every PC Engine game or hardware profile.
The supported baseline is consumer schema **1** and runtime ABI **29**.

## Reproduce the usable baseline

1. Build the toolkit and run the [required checks](../README.md#build-and-test).
2. Run the [authored native workflow](../examples/native-workflow/README.md).
   It captures a real guest program through the headless host, including bank
   switches, block transfer, calls and two writable-code variants.
3. Compose or import a [content-addressed history](OBSERVATION_HISTORY.md).
   Every original remains byte-identical; selection, ABI, origin and actual
   per-tier work remain attached to each original capture.
4. Use [an explicit preparation recipe](PREPARE_PROJECT.md) for your own
   machine/media and observed code. Preparation emits translated C++ and a
   verified descriptor without claiming that it has compiled or run.
5. Use [the official builder and runner](CONSUMER.md), then qualify the
   consumer's actual startup and required routes. A native-only guard refusal
   is an incomplete coverage result; it is never silently converted to success.
6. Add discoveries using stable emission and [managed rebuilds](INCREMENTAL_BUILDS.md).
   Keep checkpoints with their exact owning build and preserve failed receipts.

The framework supplies shared CPU/device and contributor interfaces. Consumers
own title-specific media recipes, routes, patches, generated modules and player
presentation. The pipeline is self-contained for each consumer.

## This milestone's evidence

The final SDL build and required check pass **1,903 Python tests without skips,
74 C++ suites and 12 fresh-process audio cases**. A separate official consumer
build compiles all 65,536 authored LDA sites and executes 65,540 native
instructions with zero fallback or guard misses, matching literal state/clocks.

The complete authored workflow records 200 native retirements, zero interpreted
retirements and zero source guard misses. Literal independent program arithmetic
checks CPU registers and clocks; a compiled checker compares all 8192 canonical
work-RAM bytes. A separate uncaptured operand causes an actual native dispatch
refusal without an extra retirement or clock change. Its 27 identities span five
full MPR contexts and two same-PC/same-map writable source variants. This is
internal compiler/runtime qualification, not an independent emulator comparison.

A separate managed run promotes 101 native/99 interpreted retirements to 200
native/zero interpreted. Only one changed translation unit rebuilds; the no-op,
inline-profile-to-history transition and zero-novel history extension rebuild no
objects. Historical inline bytes and all complete history graphs remain archived.

Five genuine authored LDA captures contain 65,536 identities and 48,441,905 raw
input bytes. Extending their existing inline profile is refused at its unchanged
serialized byte bound. A new history retains the same exact originals in a
91,032,654-byte graph with 16 catalogue shards and a 3459-byte index, then emits
65,536 native bodies. These are authored LDA sites: this is a catalogue-scale
check, not additional opcode coverage. Emission by itself is not compilation
or execution.

A separate final-source official consumer build compiles all 65,536 LDA bodies
in 257 module objects, then executes 65,540 native instructions with zero
interpreter retirements and zero guard misses. Literal state matches PC 12,
A 173, P 132, 327,700 cycles and 983,100 master ticks. All 65,536 catalogue
keys occur in its genuine complete native capture. Appending that zero-novel
capture preserves earlier selection: its native hits remain historical evidence
without being backdated into selected discovery contributions. This scale
fixture makes no independent whole-RAM or additional opcode-coverage claim.

Earlier authored bus/reference, CPU vector, audio/device and isolated consumer
checks retain their original producers and scope in [status](STATUS.md). This
host-tooling milestone does not expand independent hardware/timing qualification.
Historical and final SDK pins are recorded separately; no old result is relabelled
as a fresh final-source run. Runtime/CPU/device/CMake semantics remain unchanged.

## What still prevents a universal finished-tool claim

| Gate | Current boundary | Next acceptance evidence |
| --- | --- | --- |
| General code discovery | Guarded exact observed identities and bounded mapping-aware static analysis are supported; general indirect calls and return continuations are unresolved | Source-qualified roots and interprocedural discovery with full MPR/stack/memory reasoning; unsupported edges remain explicit |
| Console timing correctness | Authored reference matrices cover selected CPU, IRQ, VRAM, CD and audio behaviors; original emulator disagreements remain | Broader independent MMIO/device wait-state traces and eventually hardware evidence, resolving disagreements rather than choosing an emulator as universal truth |
| Library/profile breadth | Selected base HuCard, System Card/CD and mapper/device profiles have bounded tests | Additional diagnostic and independently supplied title routes; dedicated profiles for unimplemented or unqualified boards/devices |
| Capture scale | New history avoids one expanding inline document; v1 retains 65,536 union identities and 262,144 selected contributions | A separately versioned larger-catalogue contract and measured bounded admission/emission, without weakening old limits |
| Native performance | Stable module objects, exact dispatch and managed updates work; optional native spans have no demonstrated general speedup | Reproducible realistic benchmarks and a faster guarded block path preserving instruction/event boundaries |
| Portable distribution | Portable source/CMake and Windows LLVM-MinGW packaging are tested locally | Actual Linux/macOS/ARM64 and additional compiler build/run receipts; enabled hosted CI and reviewed distribution contracts |
| Finished player features | Optional SDL development hosts, input, audio and isolated persistence work | Contributor-facing player configuration, remapping/accessibility, shipping packages and separately qualified presentation extensions |

These are implementation or evidence requirements, not arbitrary project limits.
The toolkit can be used for supported native-port development now; completion of
an individual port still requires its own coverage and runtime qualification.
See [the ordered roadmap](ROADMAP.md) for the larger ecosystem target.
