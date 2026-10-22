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
| Current bit/stack batch (`--suite bit-stack`) | 24 | 128 native and 128 interpreter | Four base variants each, plus four extra directed variants for each of eight stack opcodes |

Each comparison checks A/X/Y/SP/P, logical PC, all eight MPRs and all 8 KiB
of work RAM after one instruction. No flags are masked out. The new vectors
explicitly cover both states of every selected bit, SP `$00/$01/$FE/$FF`,
zero/positive/negative pulled values, and every saved B/T combination for PLP.
An initial PLP mismatch exposed MAME's different internal B representation;
the runtime now follows Geargrafx/Mesen's B=0 restoration, with T preserved.
See the [instruction contract](CPU_SEMANTICS.md).

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
Source research used a separate main-branch pin recorded in
`references.lock.json`; that is not a claim the release was built from main.

```sh
python scripts/reference_geargrafx.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-oracle-probe.exe
```

That default runs the full current opcode set. To reproduce only the new
bit/stack batch, append `--suite bit-stack --out .local/bit-stack-check`.
The default all-opcode matrix is now 316 cases per tier; the full expanded
matrix was not run in this focused batch. The retained 47-opcode baseline
and the current focused check remain separately identified above.

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
