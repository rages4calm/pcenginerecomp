# Authored register-evaluation native workflow

This example creates its own 32 KiB card. No game or BIOS is needed. From a
committed checkout, with Python 3.11+, CMake and a C++20 compiler:

```sh
python examples/register-eval/workflow.py create .local/my-register-eval
python examples/register-eval/workflow.py prepare .local/my-register-eval
python examples/register-eval/workflow.py qualify .local/my-register-eval --generator Ninja
```

Compiler/package paths use repeated `--cmake-arg=-DNAME=VALUE` options. Outputs
must be new; original media, seeds, probe/helper sources and SDK stay bound.

The main route masks a ROM-loaded bank selector, shifts it, changes MPRs, adds
another bank, then calls a banked routine using decimal subtraction from ROM.
It takes 24 native instructions, 88 cycles and 1056 master ticks. Without register
evaluation, discovery stops after seven candidates at a data-driven TAM. The
opt-in analysis derives all 24 main candidates. Runtime operations stay dynamic.

A separate 280-case matrix covers ADC/SBC in binary and valid decimal modes,
AND/ORA/EOR, T-routed operations, accumulator shifts/rotates and CMP/CPX/CPY.
Immediate and permitted absolute-ROM operands are included. It executes 1992
instructions per tier under explicit resets/presets. The combined 281-seed graph
has 2016 identities, with 109 ROM ALU operand witnesses and two ROM load witnesses.

Qualification checks literal CPU/MPR/flags/clocks/full-WRAM and exact encoded
source-key/hit expectations, with separate native and interpreter runs. Changing
a private operand-data copy changes the native result with no fallback. Changed
bank/source copies refuse after seven/fourteen native instructions with one guard,
no interpreted work and no added guest work/clocks or memory effects at refusal.
These are separate authored windows, not a continuous campaign or retail proof.

The probe links the official runtime archive and checks its packaged Windows DLLs;
it executes without SDK PATH entries. ABI 29 and checkpoint encoding are unchanged.
New source/package/build contexts still need fresh exact-build checkpoints.
