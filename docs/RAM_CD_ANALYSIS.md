# Shared RAM/CD candidate analysis

The opt-in `bounded-ram-cd-candidates-v1` policy uses one analyzer for closed
RAM snapshots and authenticated offline CD load groups. It follows direct
branches and bounded synchronous calls, then resumes a caller only after a
matched, balanced return. Existing discovery commands retain their original
defaults and reproduce older reports unchanged. Runtime ABI 29 is unchanged.

## Analyze a captured RAM epoch

```sh
python -m pcerecomp discover-overlay .local/snapshot --code-range 0x100000:8192 --entry 0x4000 --analysis-policy bounded-ram-cd-candidates-v1 --call-depth 8 --data-range 0x100030:16 --out .local/candidates
python -m pcerecomp compose-overlays .local/candidates --out .local/library
python -m pcerecomp verify-overlays .local/library
```

Use your port's verified entry points, physical ranges and full snapshot MPR
context. The example numbers describe an authored layout. `--data-range` is a
canonical physical start and length. Repeat it for separate sorted, disjoint
regions. Data may lie inside a broad code range: it is then excluded from every
instruction fetch, including operands crossing its boundary. A seed intersecting
data is refused. Snapshot code and data permissions must have captured bytes.

Known stores into writable RAM outside executable permission can continue.
Stores that may touch executable bytes still stop, even when the written value
would happen to equal the snapshot. Data declarations supply neither immutable
constants nor evidence that a game naturally reached a path. Unknown indexed
stores consider every possible byte index; unknown indirect destinations,
block transfers and opaque device writes remain explicit frontiers.

`discover-origin-overlay` accepts the same options. Its disc-origin selections
still determine code permission, and its original snapshot and ancestry reports
remain independently bound. Multiple snapshots can be composed without treating
alternative RAM epochs as one simultaneous memory image.

## Analyze an offline CD load group

```sh
python -m pcerecomp declare-cd-loads load-map.json --disc game.iso --toc game.toc --analysis-policy bounded-ram-cd-candidates-v1 --call-depth 8 --limit 10000 --context-limit 256 --data-range 0x100030:16 --out .local/cd-candidates
python -m pcerecomp verify-cd-loads .local/cd-candidates/roots.json --disc game.iso --toc game.toc
```

The [numeric load map](CD_LOADS.md) is unchanged. Each group's explicit roots
become traversal seeds instead of single-instruction declarations. Every derived
instruction retains its logical PC, all eight MPR bytes, physical fetch identity,
exact instruction bytes and per-byte load/disc offsets. Each alternative group
is analyzed separately. Direct-copy hashes and complete media bindings remain
mandatory; traversal does not infer loaders, decompression or source transforms.

CD data exclusions can describe canonical standard CD RAM or WRAM absent from a
particular alternative group. They only remove executable permission; they never
supply missing bytes. An unloaded target stops. A resident source must itself be
authenticated in that group, or analyzed as a separate bound snapshot epoch.
Combining unrelated live snapshots with disc bytes into an assumed simultaneous
image is unsupported.

Both commands serialize the exact policy, call depth, data exclusions and state
limits. Admission rederives the complete graph and rejects modified options or
results. Older readers refuse the new policy/fields. Omit all new options to
retain legacy behavior. Depth defaults to 16 and is bounded to 1–64; instruction
states to 100,000 and mapping contexts to 4,096. Reports retain pending/frontier
diagnostics when a bound is reached.

There are at most 256 explicit seeds per traversed source group. Return-stack
contexts consume states too, so the same state budget can visit a different
subset than legacy discovery. A bounded new graph is not guaranteed to contain
every older candidate. Keep retained epochs and compose old and new reports
when both should contribute; do not discard existing verified coverage merely
because a newer analysis found additional identities.

## What a return proves

The analyzer tracks symbolic saved return words and relative stack depth,
starting with an unknown stack pointer. Balanced PHA/PHP/PHX/PHY and matching
pulls are supported, without inventing the popped register values. RTS requires
an intact matched frame and uses the callee's resulting MPR mapping and register
facts. Mapping changes are followed only when their value is proven.

If broad code permission includes the WRAM stack page, explicitly exclude that
page as data before analyzing calls. With unknown initial SP, a push must consider
the whole physical stack page; executable bytes there remain a write barrier.

A possible write to the physical stack page while a call is active stops,
including writes through WRAM aliases and explicitly data-declared memory.
Stack-pointer replacement, return-word pulls, unbalanced stack use, incompatible
stack mappings and excessive depth stop too. This matters for far-call thunks
that rewrite saved returns or consume inline caller data: they require a future
explicit, source-guarded effect contract, not ordinary JSR fallthrough.

Unmatched RTS, RTI, BRK, indirect jumps, unknown mappings and source boundaries
remain frontiers. There is no asynchronous interrupt closure, jump-table
enumeration, mutable-memory constant folding or whole-routine proof. Static
candidates are declared-only until actual execution exercises them; runtime
source guards remain required.

## Loader sweep plans and Python APIs

A [loader sweep](LOADER_WORKFLOWS.md) can include this optional top-level field:

```json
"analysis": {
  "policy": "bounded-ram-cd-candidates-v1",
  "call_depth_limit": 8,
  "data_ranges": [[1048624, 16]]
}
```

Every data span must be captured in that sweep's snapshot ranges. The existing
`limits.states` and `limits.contexts` bound each graph; actual guest loader work
and explicitly assisted CPU/stack setup remain separately reported.

`overlays.discover_overlay`, `overlays.discover_origin_overlay` and
`cd_loads.declare` accept `analysis_policy`, `call_depth_limit` and `data_ranges`
keywords. Their instruction/context limit keywords keep their existing spelling.
The callback-based `ram_cd_analysis.derive` engine is internal: adapters own
input authentication and memory permission. Ports should use the admitted
snapshot or CD APIs.

The [authored example](../examples/ram-cd-analysis/README.md) compares RAM/CD
candidate sets, builds both source types, executes native/reference TCP routes
and checks same-build checkpoint suffixes without proprietary media.
