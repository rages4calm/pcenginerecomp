# Authored data-driven bank and load workflow

This example creates its own 32 KiB card. It needs no game or BIOS. Run from a
committed checkout with Python 3.11+, CMake and a C++20 compiler:

```sh
python examples/rom-data/workflow.py create .local/my-rom-data
python examples/rom-data/workflow.py prepare .local/my-rom-data
python examples/rom-data/workflow.py qualify .local/my-rom-data --generator Ninja
```

Pass compiler/package paths using repeated `--cmake-arg=-DNAME=VALUE` arguments.
Outputs must be new. Original media, seeds, helper/probe sources and SDK identity
are bound separately and must stay unchanged through qualification.

The main route loads bank selectors and an index from permitted immutable ROM,
changes two MPRs, calls another code bank, reads an indexed constant, follows a
page-crossing indirect vector, writes work RAM and returns on the real guest
stack. It takes 17 native instructions, 87 cycles and 1044 master ticks. The
earlier policy stops after four candidates at a data-driven TAM. Source facts
enable all 17 main-route candidates; they are not substituted into runtime loads.

A separate 64-case load matrix covers every non-immediate LDA/LDX/LDY addressing
form with four directed byte values each. Known X/Y preambles exercise eight-bit
direct-page wrap, indirect pointer wrap, indexing and source mappings. With 65
explicit seeds the combined derivation has 273 candidates and 70 resolved data
loads. Preparation preserves the original graph and makes no observation claim.

Qualification checks the official cold route, then links a probe to its exact
runtime archive. The main native/reference probes each execute 17 instructions;
the separate load matrices each execute 256 and exercise all 256 matrix source
identities. Their CPU, flags, MPRs, clocks, encoded key/hit plan and all 8192 WRAM
bytes have explicit expectations. Host presets/resets separate these windows.
They are not one continuous guest run or retail compatibility proof.

Changing a private ROM-data value copy changes the native result to that actual
value, with no fallback. Changing a bank byte reaches a guarded mapping miss
after four native instructions. Changing target instruction bytes refuses after
ten. These tests retain original files and check no added guest work/clocks or
memory effects at refusals. Partial/failed process outputs remain separate;
`qualification.json` is written only after all checks succeed.

Runtime ABI 29 and checkpoint payloads are unchanged. New source/package/build
contexts still require fresh exact-build checkpoints. See
[ROM data discovery](../../docs/ROM_DATA.md) for permissions, evidence and limits.
