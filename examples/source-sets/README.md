# Native calls across declared RAM and firmware sources

This authored example creates its own RAM program and 256 KiB firmware image.
It declares the two sources independently, composes them, prepares an official
consumer and checks real native calls/returns. No game or retail BIOS is needed.

```sh
python examples/source-sets/workflow.py create .local/my-source-set
python examples/source-sets/workflow.py prepare .local/my-source-set
python examples/source-sets/workflow.py qualify .local/my-source-set --generator Ninja
```

Run from a committed toolkit checkout with Python 3.11+, CMake and a C++20
compiler. Use a new output directory and create its parent first. Compiler paths
can be passed with repeatable `--cmake-arg=-DNAME=VALUE`; keep all source/SDK
inputs unchanged between commands. Qualification compiles and executes a host;
creation/preparation do not claim execution. Failure outputs stay available.

The program sets up the stack, saves registers, calls a firmware routine, returns
and checks restored state. Eight CD-RAM banks combine with 32 sandbox BIOS banks:
256 explicitly preset windows, 23 instructions/80 cycles/942 master ticks each.
All 5,888 full PC/MPR/physical/code keys execute. A third annotation deliberately
overlaps the payload member: 10,752 memberships and 4,864 overlapping keys remain
in provenance while the compiler emits the 5,888-key union.

The official cold RAM start executes 23 native instructions with no interpreter
fallback or guards. Separate native/reference probes check every literal CPU/MPR
boundary, clocks, full 8 KiB WRAM, unchanged 64 KiB CD RAM and exact encoded keys/
hits across all windows. Changed-payload and changed-BIOS probes execute five/
thirteen instructions respectively, then require one guard refusal before guest
CPU/clock/memory/generation effects. Windows probes use only packaged DLLs and
system directories in PATH. The exact runtime archive, headers and probe inputs
are bound in the qualification receipt.

The workflow also reconstructs the versioned source-set catalogue and joins the
actual closed native capture into a gap report. All 5,888 declared keys must be
exercised, with zero declared/emitted entries left unexercised. That execution
evidence stays separate from the original unexecuted member annotations.

The fixtures qualify explicit cross-source compiler/consumer composition. They
do not infer overlays or routines, reset real firmware, qualify hardware/device
timing, or establish whole-title compatibility. The independent Geargrafx and
managed-build checks in [current status](../../docs/STATUS.md) are separate
receipts; this example does not download an oracle or use private test media.

See the [source-set contract](../../docs/SOURCE_SETS.md) and
[consumer interface](../../docs/CONSUMER.md).
