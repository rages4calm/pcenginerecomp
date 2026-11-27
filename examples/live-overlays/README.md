# Live CD overlays to guarded native code

This example authors its own small firmware and two code sectors. No retail ROM,
BIOS or game assets are required. The guest sends real CD READ commands, loads
each sector into the same RAM address, and waits at a disclosed data gate.

```sh
python examples/live-overlays/workflow.py create .local/my-live-overlays
python examples/live-overlays/workflow.py qualify .local/my-live-overlays --generator Ninja
```

To select the loaded code through observed disc origins, add
`--disc-origin-discovery` to `qualify`. Use a fresh scope for that run.

```sh
python examples/live-overlays/workflow.py create .local/my-disc-overlay
python examples/live-overlays/workflow.py qualify .local/my-disc-overlay --generator Ninja --disc-origin-discovery
```

This mode captures the disc-origin reports at the same paused snapshots before
either overlay runs. It selects the 20 authored code bytes at cooked-disc
offsets 2,048 and 4,096, then derives candidates from the explicit logical
entry `$4000`. The two origin-bound epochs travel through library composition,
consumer preparation and guarded emission. Reports retain the original
snapshots, origin observations, selected ranges and resulting graph.

The discovery route still observes only branch variant zero. Both native
variants then exercise all 11 overlay identities, including three branch
identities absent from the original retired-code capture. The same-build
checkpoint forks and changed-byte guard refusal also run with tracking enabled.

Run from a committed checkout with Python 3.11+, CMake, Ninja and a C++20
compiler. A compiler or Ninja outside PATH can be passed with repeated
`--cmake-arg=-DCMAKE_CXX_COMPILER=...` and
`--cmake-arg=-DCMAKE_MAKE_PROGRAM=...`. Use a short output path on Windows.
Keep every source, input and SDK byte unchanged between creation and
qualification; create a new scope if they change.

The workflow builds a bootstrap consumer with one explicit unexecuted firmware
entry, selects the interpreter reference before guest execution, then takes
closed paused RAM snapshots before each loaded sector executes. Conservative
source derivation includes both sides of the RAM branch. It composes both epochs
and the genuine original route history, builds a native consumer, runs both
branch variants, checks full WRAM/CD RAM and final CPU, and compares same-build
interpreter/native paused states. It also forks an actual same-build checkpoint
and confirms that changing a source byte causes native guard refusal.

`qualification.json` reports actual work separately from candidates: **11 unique
RAM keys**, **3 initially unexecuted branch keys**, all 11 subsequently exercised
in the two native routes. Data gates and branch controls are paused-write
assistance, recorded in original process receipts and journals. The changed-code
negative intentionally closes with a guard failure; it is not a successful
positive route. No whole-title, hardware or independent device-clock claim is
made. Independent Geargrafx and managed-build checks are described in the
[interface verification scope](../../docs/LIVE_OVERLAYS.md#verification-scope).

The original creation receipt, snapshots, epoch graphs, captures, package/build
receipts, journals and checkpoint files remain private in the chosen directory.
See [live overlay discovery](../../docs/LIVE_OVERLAYS.md) for CLI commands,
consumer preparation, supported RAM, integrity checks and conservative frontiers.
