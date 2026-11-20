# Authored CD loader sweeps and feedback

This example creates original firmware and two code-bearing CD sectors. Its real
guest loader reads either sector into the same RAM address. No game, System Card
or proprietary data is needed. Run from a committed checkout with Python 3.11+,
CMake, Ninja and a C++20 compiler available.

```sh
python examples/loader-sweep/workflow.py create .local/my-loader-workflow
python examples/loader-sweep/workflow.py qualify .local/my-loader-workflow --generator Ninja
```

Pass compiler settings explicitly when needed:
`--cmake-arg=-DCMAKE_CXX_COMPILER=clang++` and
`--cmake-arg=-DCMAKE_MAKE_PROGRAM=ninja`.
Use a new output directory; do not edit the generated inputs during qualification.

Qualification runs the existing live-overlay example, then four reference guest
loader calls (two groups, independent and cumulative), closes each RAM epoch and
composes the distinct source graphs. Every original call/snapshot remains even
when repeated source content shares a library member. Genuine loader captures
feed a fresh native consumer with operand sharing enabled. Two native/reference
branches and four native loader calls then check literal full WRAM/CD-RAM and
returned CPU; each native call retires 346,130 instructions with zero fallback.

The loader calls explicitly seed CPU/MPRs and a real RTS stack frame. Data gates
and branch controls are disclosed developer assistance. Reaching the target is
not natural game progression, general routine closure or independent hardware
timing proof. The example's numbers stay outside the shared toolkit.

`setup-profile.json` is also an original portable-kit profile:

```sh
python -m pcerecomp export-port-kit .local/my-loader-workflow/setup-profile.json --out .local/my-loader-kit
python -m pcerecomp verify-port-kit .local/my-loader-kit
python .local/my-loader-kit/setup_port.py --out .local/my-loader-port --compiler-root compiler-sdk --asset bios=.local/my-loader-workflow/firmware.bin --asset disc=.local/my-loader-workflow/disc.iso
```

To bundle an explicitly supplied compiler SDK with its notices, add
`--toolchain-root compiler-sdk` to export and omit `--compiler-root` from setup.
The SDK needs `bin/clang++`, `bin/cmake` and `bin/ninja` (`.exe` on Windows).
Kit setup executes discovery and compiles a native package; its final native
gameplay still needs qualification. See the complete
[contracts, evidence and limits](../../docs/LOADER_WORKFLOWS.md).
