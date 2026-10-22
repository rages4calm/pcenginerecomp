# Independent reference check

The optional `scripts/reference_geargrafx.py` harness controls a separately
developed **Geargrafx** emulator through its actual HTTP MCP tools. It starts
and terminates its own headless portable process on a dedicated loopback
port. It does not attach to an owner's emulator session or change an AI
client's plugin configuration.

## What was checked

On Windows x64, Geargrafx **1.8.4** passed the following separate checks:

| Run | Opcodes | Comparisons per tier | Scope |
|---|---|---|---|
| Original baseline, retained prior evidence | 47 | 188 native and 188 interpreter | Four register/flag variants each, including both conditional-branch outcomes |
| Bit/stack batch, retained prior evidence (`--suite bit-stack`) | 24 | 128 native and 128 interpreter | Four base variants each, plus four extra directed variants for each of eight stack opcodes |
| Data batch, retained prior evidence (`--suite data`, four completed shards) | 97 | 1,552 native and 1,552 interpreter | 16 vectors per encoding; all C/D/T/V combinations, indexed/indirect data addressing and full-RAM comparison |
| RMW/JMP batch, retained prior evidence (`--suite rmw-jump`, two completed shards) | 32 | 512 native and 512 interpreter | 16 vectors per opcode; edge values with both carries, T/D/V contexts, indexed memory and consecutive jump pointer bytes |
| Current bit-test/branch/BSR batch (`--suite bit-test-bsr`, two completed shards) | 30 | 480 native and 480 interpreter | 16 vectors per opcode; zero/full/mixed bits, flag contexts, zero-page/indexed targets and stack wrap |

Each comparison checks A/X/Y/SP/P, logical PC, all eight MPRs and all 8 KiB
of work RAM after one instruction. No flags are masked out. The new vectors
explicitly cover both states of every selected bit, SP `$00/$01/$FE/$FF`,
zero/positive/negative pulled values, and every saved B/T combination for PLP.
An initial PLP mismatch exposed MAME's different internal B representation;
the runtime now follows Geargrafx/Mesen's B=0 restoration, with T preserved.
See the [instruction contract](CPU_SEMANTICS.md).

The data input matrix has 16 vectors per opcode, covering every C/D/T/V
combination with zero, sign, valid BCD and invalid-nibble inputs. It sets
zero-page operands to `$FF`, absolute bases to `$22FF`, and indirect pointers
to `$22FF`, exercising zero-page pointer wrapping and indexed page crossings.
T destination/source and pointer-high-byte aliases remain visible in the
full-RAM comparison. Immediate bytes remain the compiled `$20`; variable
operand values are exercised through memory forms. The exhaustive byte-pair
tests described in CPU_SEMANTICS are local expected-value tests, not an
exhaustive run against Geargrafx.

The RMW/JMP input matrix pairs each of `$00/$01/$02/$7F/$80/$81/$FE/$FF`
with both incoming carry states. It varies T/D/V and uses X values
`$00/$01/$E0/$FF`. All 30 RMW encodings and both indirect JMP forms are
selected. Jump pointer bytes are consecutive across `$22FF/$2300`, with
multiple targets including `$FFFF`; the test ends after JMP and does not
execute its destination. Full-address-space wrap and cross-MPR cases use
additional local native fixtures; they are not live Geargrafx evidence.

This uses self-authored synthetic HuCard/bootstrap code and synthetic RAM
patterns. Initial emulator registers/MPRs are randomized, so the harness
first establishes and verifies its mapping/speed, then sets registers
explicitly for every case. It restores mapping after TAM. It compares both
the native tier and the interpreter directly with the reference.

**Not checked:** cycle/bus phases, IRQ entry/delivery, speed-change timing,
block transfer, unsupported opcode semantics, devices, CD, sound, rendering
or any game. This is independent single-step evidence, not whole-system
conformance or proof the reference emulator is infallible.

## Reproduce

Build the optional probe from the entirely synthetic fixture generator:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DPCE_BUILD_REFERENCE_PROBE=ON
cmake --build build --config Release --parallel 4
```

Obtain a portable Geargrafx release from its [official releases](https://github.com/drhelius/Geargrafx/releases).
Use a dedicated copy under `.deps/geargrafx-oracle/`, including its required
runtime files. The harness refuses an executable outside this project's
`.deps/` directory. It creates `portable.ini` and writes no retail saves.
No emulator or binary is included or downloaded by the harness.

The baseline Windows artifact was:

| Identity | Value |
|---|---|
| Archive | `Geargrafx-1.8.4-desktop-windows-x64.zip` |
| Release | `1.8.4`, published 15 October 2026 |
| Archive SHA256 | `c1aceb116acf1949ab2319c217f3c0c9e9fcf836f8857176b670a749d8a2347c` |
| Executable SHA256 | `742b2d8d21060368134324e1ce6c32a9751e7a9776549ed78448eca93e6e8563` |

The archive digest matched GitHub's release-asset `digest` field before use.
The research register retains both the original main-branch pin and the
separate 1.8.4 source pin `1c62a549328241518101f5be5bf3e6840b96ea5d`,
used for the bit/stack and data semantics. This does not assert a reproducible
source-to-binary build of the supplied release executable.

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-oracle-probe.exe
```

That default selects the full current opcode set (2,824 cases per tier).
Large runs can exceed the 180-second cap; partition them with
`--shard-count 8 --shard-index N` for each N from 0 through 7, using a distinct
output folder for each. Every shard records the exact checked opcode list;
all shards must pass to claim the complete selected suite.

To reproduce the data batch, run four commands sequentially, substituting
N with each value from 0 through 3:

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-oracle-probe.exe --suite data --shard-count 4 --shard-index N --out .local/data-check/four-N
```

Their disjoint opcode lists must cover all 97 data encodings and their totals
must sum to 1,552 comparisons per tier. Each run remains incomplete until
its entire shard passes. All four lists and comparison totals were checked
at closeout; they cover every selected encoding exactly once.
To select only bit/stack, use `--suite bit-stack --out .local/bit-stack-check`.
The full expanded all-opcode matrix has not been run in this batch; retained
checks remain separately identified above.

For the RMW/JMP batch append `--suite rmw-jump --shard-count 2 --shard-index N`
and `--out .local/rmw-jump-check/shard-N`, with N=0 and N=1 in separate
sequential runs. Their opcode lists must be disjoint, cover all
32 selected encodings and total 512 comparisons per tier. Each vector is
checked independently against both execution tiers. The exhaustive RMW
byte/status sweep is a local expected-value test, not an exhaustive oracle run.
Both completed reports and their combined opcode coverage/totals were verified.

For the latest batch use `--suite bit-test-bsr --shard-count 2 --shard-index N`
and `--out .local/bit-test-check/shard-N`, with N=0 and N=1 sequentially.
The disjoint reports cover all 30 selected opcodes, totaling 480 comparisons
per tier. Memory cases use `$FF` / `$22FF`, TST's compiled mask is `$55`,
BIT's compiled immediate is `$20`, and relative fixtures branch to themselves
when taken. BBR/BBS exercise both selected-bit states, and BSR varies SP
through `$00/$01/$FE/$FF`. Other displacement/fetch-wrap checks are local
expected-value tests; this is not exhaustive oracle testing of literals.

On other hosts supply the corresponding executable filename. On a
multi-configuration build the probe may be under `build/Release/`. Those
reference sessions have not yet been run by this project.

The default output is ignored `.local/geargrafx-check/`. A compact
`result.json` records emulator identity and exact check scope. A failing
run retains one synthetic mismatch and exits nonzero; it cannot reuse a
previous pass as the current result. Work is bounded to 180 seconds, MCP
responses to 2 MiB each, and probe invocations to five seconds. No frame or
audio dump is enabled. The harness always terminates only its own child.

The reference check is optional and outside the default CI suite, so a
green synthetic CI job must not be reported as a fresh independent-reference
run. A second independently developed reference and hardware test vectors
remain useful next work.
