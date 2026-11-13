# Authored unknown-X ROM table workflow

This example builds its own 8 KiB card. No game or BIOS is required. Run from a
committed checkout with Python 3.11+, CMake and a C++20 toolchain:

```sh
python examples/rom-tables/workflow.py create .local/my-rom-tables
python examples/rom-tables/workflow.py prepare .local/my-rom-tables
python examples/rom-tables/workflow.py qualify .local/my-rom-tables --generator Ninja
```

Pass explicit compiler/package paths with repeated `--cmake-arg=-DNAME=VALUE`.
Outputs must be new. Keep the toolkit, card, seeds and copied graph unchanged
through qualification. No software is fetched or installed.

One seed establishes work-RAM mapping and reaches `JMP (abs,X)` with unknown X.
The vector permission covers exactly 257 data bytes. Opt-in `rom_table_limit=1`
examines all 256 byte-index values, deriving four target lanes, including logical
aliases under the full mapping. Code and pointer-data permissions are separate.
The old known-X vector policy stops after three candidates; the new table policy
derives 19. These are static declarations, with no observation hits or execution
claim. The original three-file graph is retained in the prepared consumer.

Qualification builds the official native consumer and checks a seven-instruction
cold prefix against literal CPU/clocks. A separately linked probe then resets the
authored machine and explicitly presets X for each of its 256 values. It executes
seven native instructions per case and checks literal PC/registers/MPRs, 30 cycles,
360 master ticks and every byte of work RAM. An interpreter-only matrix repeats
those preconditions. Each matrix retires 1792 instructions and exercises all 19
full source identities; cold startup alone exercises seven. Encoded captures are
checked against the separate literal code/hit plan.

Two negative probes alter only their private in-memory source copy. A changed
pointer is read dynamically and reaches uncovered code; a changed target byte
fails its source guard. Both stop after three native instructions with one guard
miss and no extra guest clocks or memory changes. Original files remain intact.

Host X presets and resets are matrix preconditions, not guest work or a continuous
route. The fixture is internal compiler/runtime qualification, not retail,
independent emulator or hardware proof. `qualification.json` is written only
after all checks succeed; process outputs and timeout/failure receipts remain
separate. Runtime ABI 29 and checkpoint payloads are unchanged; new build contexts
still need their own checkpoints. See [table analysis](../../docs/ROM_TABLES.md).
