# Authored conditional-discovery native workflow

From a committed checkout with Python 3.11+, CMake, Ninja and a C++20 compiler:

```sh
python examples/branch-facts/workflow.py create .local/my-branches
python examples/branch-facts/workflow.py prepare .local/my-branches
python examples/branch-facts/workflow.py qualify .local/my-branches --generator Ninja
```

This creates its own 32 KiB card; no game or BIOS is needed. Pass compiler/package
paths with repeated `--cmake-arg=-DNAME=VALUE`. Destinations must be new. Original
inputs, fixture/probe/helper sources and SDK identity stay bound separately.

The main route uses carry, overflow and sign decisions before bank changes and a
banked call. The old both-path join stops at TAM after nine candidates. Branch
facts derive all 28 main instructions, costing 107 cycles/1284 master ticks.
The separate 96-case matrix covers both senses of all eight flag conditions and
all sixteen BBR/BBS forms. Explicit host resets/presets separate these windows.

The combined 97-seed graph has 1068 identities, 99 decided conditions/pruned edges,
36 permitted ROM-load witnesses and 32 separately witnessed ROM bit reads. The
old analysis overdeclares both matrix arms and has 1193 candidates while missing
the main route's later banked code. Preparation is not observed execution.

Qualification executes the main route natively and compares separate native and
interpreter probes. The matrix executes 1040 instructions per tier; every derived
identity/hit and literal full CPU/flags/MPR/clocks/all 8192 WRAM bytes are checked.
Changing private data changes the actual RAM result with no fallback. Carry,
overflow and sign data variants take statically omitted paths and refuse after
5/14/22 native instructions; changed instruction bytes refuse after 18. Each has
zero interpreted work, one guard and no added guest work/clocks or memory effects
at refusal. Generated branches continue to test live flags and memory.

The probe links the official builder's runtime archive and checked Windows DLL
closure, executing without SDK PATH entries. Qualification here uses Windows x64
LLVM-MinGW/Ninja. ABI 29 and checkpoint encoding are unchanged; new source/package/
build contexts require fresh exact-build checkpoints. This is authored bounded
evidence, not whole-game, retail or hardware compatibility.

See [conditional discovery](../../docs/BRANCH_FACTS.md) for analysis permissions,
refinement, graph admission and verification limits.
