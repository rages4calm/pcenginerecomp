# Saved stack facts → banked native calls

This original 32 KiB fixture needs no game or firmware. It exercises relative
PHA/PLA, PHX/PLX, PHY/PLY and PHP/PLP facts, nested JSR/BSR/RTS, a canonical WRAM
alias change, a code-bank change and a branch after restored status. Runtime
pushes, pops, flags, memory reads and source guards remain real operations.

Run from the repository root, using a **new** output directory:

```powershell
python examples/stack-values/workflow.py create .local/stack-example
python examples/stack-values/workflow.py prepare .local/stack-example
python examples/stack-values/workflow.py qualify .local/stack-example
```

`qualify` accepts `--generator` and repeatable `--cmake-arg` for the same supported
CMake/compiler setup as other native examples. It builds the official prepared
consumer, then links a probe against that exact runtime archive. Windows probes
use the verified packaged DLLs with only Windows directories on PATH.

The main cold route retires 39 native instructions, zero interpreted and zero
guard misses: 137 guest cycles / 1,644 master ticks. Separate 281-preset matrices
exercise eight boundary bytes per register pair, every PLP/PHP byte, and a PHP
whose incoming status bits remain unknown to analysis. Each tier retires 1,940
matrix instructions. The 282-seed graph declares 1,979 exact identities; all are
executed across these distinct windows. These are not one continuous guest run.

Literal CPU/flags/MPR/clocks, every WRAM byte and exact encoded source keys/hits
are checked. A separate negative changes the saved status byte before PLP; the
generated restore and BNE read it and reach an omitted source after 31 native
instructions, with zero interpreted, one guard and no guest effects at refusal.
The host RAM write is explicit fixture setup, not an inference or retail cheat.

Creation, preparation, build and execution are separate receipts. Qualification
binds original inputs, fixture/helper sources, SDK identity, discovery closure,
probe/header, binaries and captures. Source changes refuse admission; create new
proof instead of rewriting the original producer identity. This example alone
does not establish external emulator, device, interrupt, retail or hardware
compatibility. Static facts remain candidates rather than whole-game closure.
