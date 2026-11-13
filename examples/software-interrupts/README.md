# Authored software-interrupt discovery → native execution

This standalone workflow authors its own 32 KiB card and literal expectations.
It needs no game or BIOS. Use a committed checkout, Python 3.11+, CMake 3.20+
and a C++20 compiler; Ninja is shown below. Each output destination must be new.

```sh
python examples/software-interrupts/workflow.py create .local/my-software-interrupts
python examples/software-interrupts/workflow.py prepare .local/my-software-interrupts
python examples/software-interrupts/workflow.py qualify .local/my-software-interrupts --generator Ninja
```

The creation receipt pins SDK/source hashes and original card/seeds. Preparation
derives a [software-interrupt graph](../../docs/SOFTWARE_INTERRUPTS.md), preserves
its closure in the official consumer descriptor and emits translated operations.
Qualification compiles that exact package, checks the official cold endpoint and
builds a probe against the same runtime archive/header/DLLs. Changed inputs or SDK
identity require a new experiment; do not repin existing proof.

The nested 49-instruction main checks BRK/RTI, JSR/RTS, real save/restore sequences,
ROM and proven WRAM vectors, stack aliases, current MPR return views and decimal
arithmetic. It checks literal CPU/MPR/clocks and all 8 KiB WRAM, plus exact encoded
source identities/hits in both tiers. All 256 status bytes run under SP presets
0, 1, 254 and 255, giving 1,024 independent windows / 15,360 instructions per tier.
Across main and matrix, all 2,104 declared keys execute; the 3,889 analysis states
include distinct calling contexts and must not be counted as unique code keys.

Two separately preset negatives mutate a live WRAM vector or saved status byte.
The runtime takes the actual changed path and native dispatch refuses an omitted
identity after 28 or 14 retired instructions. CPU/clocks/WRAM generations remain
unchanged by the guard refusal itself. These are explicitly assisted authored
windows, not unmodified retail routes. Windows probes run with a system-only PATH.

The workflow provides internal native/interpreter and independent literal checks.
The separately recorded Geargrafx matrix described in the policy documentation
is external evidence from this development batch, not silently rerun by `qualify`.
No asynchronous IRQ closure, device timing or complete game claim is made.
