# Static discovery across proven bank mappings

Static discovery can now follow constant HuC6280 mapping changes instead of
stopping at every `TAM`. It is opt-in; the existing schema-1, single-mapping
analyzer and emitter remain available unchanged for valid inputs.

```sh
python -m pcerecomp analyze PRIVATE_SNAPSHOT.toml --follow-mappings --context-limit 256 --limit 10000 --listing --out PRIVATE_ANALYSIS.json
python -m pcerecomp emit PRIVATE_SNAPSHOT.toml --follow-mappings --context-limit 256 --limit 10000 --out PRIVATE_MODULE
```

These commands consume the same hash-pinned schema-1 snapshot format. They
produce a schema-2 analysis report and a normal schema-1 module manifest,
respectively. The listing prints the complete MPR context before each
instruction. `--context-limit` requires `--follow-mappings` at the CLI.
The Python equivalent is:

```python
report = analyze(snapshot, follow_mappings=True, context_limit=256)
manifest = emit(report, output_directory)
```

## What can be established

The analysis tracks conservative byte constants for A/X/Y, beginning with
unknown values at every explicit entry. Immediate loads, register clears,
transfers, swaps, increments/decrements and nonzero-mask TMA can establish
constants. TMA combines selected mapping bytes by OR; zero-mask TMA reads an
untracked transfer latch and therefore makes A unknown.

A known A permits TAM to update every selected MPR and continue decoding
through the new mapping. Zero-mask TAM preserves the mapping even when A is
unknown. Every fetched opcode and operand is translated independently through
its actual MPR, including page crossings and logical address wrap. An executing
page can remap itself, and the same logical PC can describe different source
bytes under different complete mappings.

Facts merge at each logical-PC/full-MPR node. Conflicting constants become
unknown; branches are explored conservatively. If a merge invalidates an
earlier proven mapping edge, that edge and unreachable speculative descendants
are removed from the final graph. Calls follow the known target, but do not
assume that the callee preserves mappings or register constants at its return
site. That continuation remains explicitly unresolved.

Loads from memory, ALU results, pulled registers and block-transfer restored
registers are not inferred from snapshot data. The graph still stops at an
unknown nonzero TAM, indirect jump, dynamic return, interrupt transition,
unassigned opcode or missing bytes. There is no speculative RAM-pointer
resolution, automatic overlay cache or general call/return analysis.

## Report identity and bounds

Each instruction has `node_id`, logical `pc`, all eight `mpr` bytes, the
physical address of every fetched byte and the exact instruction bytes.
Edges carry `from` and `to` context objects containing `pc` and `mpr`, plus
node IDs when the corresponding instruction was decoded. Unresolved rows
retain the source context and, for a limit stop, the proposed target context.
Node IDs and report ordering are deterministic; IDs are local graph indices,
not cross-report source identities.

Instruction limits range from 1 to 100,000 and context limits from 1 to 4,096
(default 256). They bound all admitted exploration states, including states
later pruned after a loss of constant precision. Reachable output counts can
therefore be smaller than the work admitted before a reported limit stop.
Limit exhaustion is an unresolved edge, never silent successful discovery.
Ambiguous overlapping instructions in one mapping remain an emission error.

## Execution contract

The new emitter generates direct translated operations selected by complete
MPR mapping and logical PC. Before any instruction side effect it checks the
deadline and every fetched source byte. Discovery constants are not runtime
assumptions: the translated TAM uses the actual A, and the next dispatch must
match the resulting actual mapping. New source bytes or mappings miss into the
existing dispatcher policy rather than running a guessed translation.

Static reports and manifests retain `execution_evidence: false`. Discovery,
emission, host compilation and actual native retirement are separate stages.
This compiler-only addition preserves runtime ABI 24 and capture schema 1;
it changes the canonical compiler source identity, so consumer builds must
pin the new exact source rather than reusing a prior source digest.

The authored `pce-context-tests` firmware demonstrates multi-bit TAM, executing
page remapping, data-bank changes, loops and reused logical PCs. Its source
is original, not extracted game code. The separate original-Gear reference
adapter checks actual instruction states; no GPL reference implementation is
linked into the toolkit runtime. See [DEVELOPMENT.md](DEVELOPMENT.md) for
reproduction and [STATUS.md](STATUS.md) for the completed evidence scope.
