# SF2 bank writes and code-window transitions

This original fixture needs no game or firmware. It exercises the existing
SF2 board profile using authored data and instructions, then compiles and
executes translated C++ operations from a discovery-backed consumer.

From a committed checkout with Python, CMake, Ninja and a C++20 compiler:

```sh
python examples/mapper-flow/workflow.py create .local/my-mapper-flow
python examples/mapper-flow/workflow.py prepare .local/my-mapper-flow
python examples/mapper-flow/workflow.py qualify .local/my-mapper-flow --generator Ninja
```

Use a new output directory. Optional compiler/make-program paths use
`--cmake-arg=-DCMAKE_CXX_COMPILER=...` and
`--cmake-arg=-DCMAKE_MAKE_PROGRAM=...`. Inputs, SDK and fixture hashes must stay
unchanged from creation through qualification; changing them requires a new
proof. The common [native support](../native_support.py) checks archive/header/DLL
bindings and executes the standalone Windows probe with a system-only PATH.

609 seeds derive 9,009 exact identities in 150 selector/MPR contexts. All execute
across separate windows: the cold main runs 17 native / zero interpreted / zero
guards, 104 cycles / 1,248 ticks; the 608-case matrix retires 8,992 per tier.
Cases cover every latch address, direct/RMW/indexed/indirect writes and all five
ordered block forms, including a latch write changing a later source read.
Each matrix case stores its status byte and a distinct selected-window byte so
CPU, clocks, every WRAM byte and exact source/hit counts can be checked.

The main changes its executing code window, then changes source/code windows
during a TII. A changed live index selects an omitted window: ten native
instructions, zero interpreted, one guard, no guest effects at refusal. Runtime
operations remain dynamic; inferred facts do not replace live writes or reads.

The qualification receipt separates derivation, preparation, compilation,
official cold execution and standalone presets/negative/reference windows.
Its C++ interpreter comparison is internal evidence. See
[policy and independent reference scope](../../docs/MAPPER_FLOW.md), including
the Geargrafx self-remapping-block limitation and separate full Beetle result.
ABI 29 is unchanged. No whole-game, external-device/bus timing or hardware claim
is made by this example.
