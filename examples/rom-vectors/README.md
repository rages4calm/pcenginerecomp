# Authored ROM-vector discovery and native execution

This small authored HuCard demonstrates the optional ROM-vector discovery policy.
One numeric seed expands to nine exact instruction identities in two full MPR
contexts. The program sets up work RAM, executes `JMP ($E1FD,X)` with X = 2 across
the $E1FF/$E200 boundary, then executes `JMP ($E300)`. Both pointer pairs have
explicit decoded-ROM vector permissions, separate from the allowed code ranges.
No commercial image, firmware, save, captured code or generated game source is
included in this example.

From a clean, committed toolkit checkout, choose a new private output directory:

```sh
python examples/rom-vectors/workflow.py create .local/rom-vector-example
python examples/rom-vectors/workflow.py prepare .local/rom-vector-example
python examples/rom-vectors/workflow.py qualify .local/rom-vector-example --generator Ninja
```

If needed, repeat `--cmake-arg=-DCMAKE_CXX_COMPILER=...` and
`--cmake-arg=-DCMAKE_MAKE_PROGRAM=...` with your installed toolchain paths.
Preparation does discovery and ordinary declared-root consumer preparation. It
does not compile or run the guest. Qualification builds through the supported
consumer interface and runs nine instructions using the official native host.

To retain the complete discovery provenance inside the consumer, use
`prepare --retain-discovery` instead of the plain preparation command above.
That selects `module.kind = "discovery"`; the consumer owns the exact seed/roots/
report closure and later verification rederives it. Roots are stored once, media
stays separate, and all build/cache/recovery/run bindings include the graph.
The default preparation remains declaration-only. See
[discovery consumer contracts](../../docs/DISCOVERY_CONSUMERS.md).

The literal official endpoint is PC $E143, A 42, X 2, Y/SP 0, P 4, MPRs
`[0,248,0,0,0,0,0,0]`, divisor 12, 39 cycles and 468 master ticks. Its complete
capture must contain exactly the nine expected PC/MPR/physical/byte identities,
each with one native hit, zero interpreted hits and no guards. Source ranges and
constants do not create execution evidence by themselves.

A separately compiled probe links the actual official runtime archive and the
same generated module. Fresh native and interpreter-reference processes execute
the same nine instructions, check the literal registers/clocks, and compare all
8192 work-RAM bytes to an independently authored expectation: byte 0 = 42,
byte 1 = 2, every other byte = 0. Complete captures verify full identities and
actual per-tier hit counts. No host flag write or assisted guest progression is
used in this positive route. Whole-RAM checks belong to this probe; the official
host run records CPU state and capture identities.

Two separate negatives modify in-memory image copies without changing the input
file:

- Changing the first vector's low byte selects uncovered $E160. The translated
  jump must read the changed pointer dynamically; it must not embed the analyzer's
  old $E120 target. Four native instructions retire before the next dispatch misses.
- Changing the original $E120 immediate operand leaves the pointer intact but
  makes the target's source guard refuse. Again, four native instructions retire.

Both negatives stop at 16 cycles/192 ticks with one guard miss, zero interpreted
work and no extra retirement or clocks on the refused dispatch. Their complete
captures contain only the four real prefix keys; all work RAM remains zero.

Original inputs, exact SDK, generated consumer/build, discovery graph, process
logs, binaries and receipts remain bound separately. Verification refuses a
changed SDK or original input rather than repinning earlier evidence. Keep this
small closed qualification directory until its proof is retired; remove disposable
compiler output when it is no longer needed. Do not relocate it onto the Desktop.

This is authored compiler/runtime evidence. It neither executes an independent
emulator nor qualifies hardware, gameplay, unknown-X jump tables, RAM/CD vectors,
asynchronous interrupt paths or complete routine recovery. See the
[discovery contract](../../docs/STATIC_DISCOVERY.md#optional-rom-vector-policy).
