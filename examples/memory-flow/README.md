# Ordered copies, mutable tables and banked native execution

This original fixture needs no game or firmware. It derives source-qualified
code, compiles direct C++ operations and checks live runtime behavior for both
base HuCard and SF2 mapper profiles. Run each command from a committed checkout:

```sh
python examples/memory-flow/workflow.py create .local/my-memory-flow --profile base
python examples/memory-flow/workflow.py prepare .local/my-memory-flow
python examples/memory-flow/workflow.py qualify .local/my-memory-flow --generator Ninja
```

Use a new output directory with `create --profile sf2` for the second profile.
Compiler and make-program locations can be supplied with
`--cmake-arg=-DCMAKE_CXX_COMPILER=...` and
`--cmake-arg=-DCMAKE_MAKE_PROGRAM=...`. Windows packaging and the standalone probe
use the common [native example support](../native_support.py); the probe is
executed with a system-only PATH. Original inputs/SDK/fixture hashes must remain
unchanged from creation through qualification. A changed source requires a new
proof rather than repinning an existing receipt.

The main route maps WRAM and its alias, saves unknown X, fills a RAM jump table
with TAI, restores X, follows JMP ($1FFF,X) and changes the code bank. Every
possible X byte reaches $E2E2, including a mixed ROM/WRAM pointer at index zero.
A separate 256-preset matrix executes every index; it does not claim 256 fresh
hardware resets. Fifty separate copy windows check all five block operations,
six lengths, overlap, aliases and 16-bit wrapping using literal expected bytes.
Safe indexed writes and fully checked copy spans work under the SF2 profile.

Per profile: 51 seeds → 468 declared exact identities, all executed across the
separate windows. The official cold main is 18 native / zero interpreted / zero
guards, 1,615 cycles / 19,380 ticks. Main/reference and the 450-instruction copy
matrix check CPU/flags/MPR, clocks, every WRAM byte and exact encoded keys/hits.
The 256-index native matrix retires 4,608 instructions. The changed-pointer
negative proves live RAM is read, then refuses an omitted target after 13 native
instructions with one guard miss and no additional guest effects.

The receipt distinguishes original inputs, graph derivation, preparation, build,
official execution and standalone preset/negative probes. Static facts remain
candidates; generated operations are not specialized to the inferred RAM values.
See [policy, bounds and external reference scope](../../docs/MEMORY_FLOW.md).
Runtime ABI 29 is unchanged. No retail, external-clock, device/interrupt,
full-game or hardware claim is made by this example.
