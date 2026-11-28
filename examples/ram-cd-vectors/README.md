# Authenticated indirect jumps through RAM and CD sources

This authored example copies a resident thunk with real guest TII, loads two
alternative sectors with CD READ, and reaches two explicit pointer words:

- `LDX #2; JMP ($6030,X)` reads `$6032/$6033` and reaches `$6028`.
- `JMP ($6034)` reads `$6034/$6035` and reaches `$602C`.

Both retain their live indirect runtime behavior. The declared vectors are
separate data, authenticated from the closed resident snapshot; no target is
invented from an unknown index or unbound source.

```sh
python examples/ram-cd-vectors/workflow.py create .local/vector-example
python examples/ram-cd-vectors/workflow.py qualify .local/vector-example --generator Ninja
```

Add compiler/Ninja paths with repeated `--cmake-arg=...` when needed. The fixture
uses authored System Card reset firmware and synthetic media, not a retail BIOS
or game. No physical GPU or speaker is used.

The workflow compares snapshot-derived and composed CD/resident candidates,
checks both per-byte vector witnesses against authored literals, builds both
native consumers, then tests both branch variants against the interpreter through
TCP. It compares complete guest WRAM/CD RAM and paused CPU/device state, then
checks exact-build checkpoint suffixes. All native routes must have zero fallback.
The original branch/data release gates are disclosed assistance.

This qualifies bounded candidate discovery and execution. It does not establish
whole-game coverage, arbitrary mutable jump tables, temporal residency, hardware
correctness or cross-package checkpoint portability. See
[the vector contract](../../docs/RAM_CD_VECTORS.md).
