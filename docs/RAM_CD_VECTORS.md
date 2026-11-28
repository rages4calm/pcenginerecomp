# Authenticated RAM/CD indirect vectors

The opt-in `bounded-ram-cd-vectors-v1` policy extends the stack-values analyzer
with `JMP (abs)` and `JMP (abs,X)` when X is proven. The snapshot and CD-load
adapters use the same engine. Origin-aware snapshot reports use
`observed-disc-offset-vectors-v1` and retain their original disc ancestry.

Declare explicit canonical physical `vector_ranges` in the closed source.
Both pointer bytes must be authenticated in those ranges. Each read records its
logical address, full current MPR, physical/canonical address, value and original
snapshot/CD/resident provenance. The high byte uses its own mapping after full
16-bit address wrap; no 6502 page-wrap rule is applied.

Vector bytes are excluded from executable candidates and protected from analyzed
writes from the start. Direct, indexed, aliased, stack and T-mode writes that
could reach them stop traversal. Unknown writes and block transfers keep their
existing frontiers. Ordinary data ranges may overlap vector ranges, but that
does not permit vector mutation. Every vector range must be covered by the
closed snapshot or by each CD group's own loads plus explicit resident sources.

```sh
python -m pcerecomp discover-overlay SNAPSHOT --out NEW_EPOCH \
  --code-range 0x100000:2048 --code-range 0x104000:64 --entry 0x4000 \
  --analysis-policy bounded-ram-cd-vectors-v1 --call-depth 8 \
  --data-range 0x104030:16 --vector-range 0x104032:4
```

Use the same analysis policy and repeated `--vector-range` options with
`discover-origin-overlay` and `declare-cd-loads`. A loader plan's `analysis`
object can select this policy with explicit `vector_ranges` start/length pairs;
all ranges must be in the same captured snapshot. Existing policies retain
their old schemas and behavior and do not accept vector hints.

Unknown X, unbound bytes and uncertain writes remain explicit frontiers.
Discovered destinations are source-qualified candidates, not temporal residency,
routine closure or proof that the jump ran. Generated native JMP operations
still read the live pointer through the runtime bus. The analyzer never replaces
an indirect jump with a guessed fixed branch. Code/source dispatch guards remain
active if runtime contents or mappings differ.

The [authored example](../examples/ram-cd-vectors/README.md) uses a genuine guest
TII copy for resident code, two actual CD READ overlays and both indirect forms.
Snapshot and composed CD/resident consumers compare native/reference TCP routes
and exact-build checkpoint suffixes. No retail BIOS or game image is needed.
ABI 29 and checkpoint encoding are unchanged; ordinary SDK/package binding rules
still apply. Broader unknown-index tables and asynchronous closure remain open.
