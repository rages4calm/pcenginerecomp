# Sparse checkpoint scenarios

Run an input scenario on one persistent connection and save only at meaningful
boundaries. Schema-2 plans support long pulses, split internally into bounded
600-frame requests while input stays held. Every checkpoint is explicit.
See [state routes](../../docs/STATE_ROUTES.md) for predicates, deadlines,
input ownership, failure receipts and CLI profiling.

This authored comparison runs the same 1,200 frames twice from one checkpoint:
12 short pulses with 12 saves, then one long pulse with one save. It requires
identical final observations **and complete checkpoint bytes**, zero interpreter
fallback and acknowledgements matching saved-file hashes. Exact bytes include
machine/device state and host cursors, not just the visible picture.

First [build the widescreen example](../widescreen/README.md#build-and-walk).
Then run:

```sh
python examples/state-routes/workflow.py \
  --binary .local/wide-build/pce-widescreen.exe \
  --card .local/wide-fixture/authored-card.pce \
  --out .local/scenario-proof
```

Use the executable name appropriate to your platform. The supplied binary must
be the example's native consumer and the card must be its generated authored
fixture. The output directory must be new. The script forces SDL dummy video,
software rendering and dummy audio: it does not open a GPU window or use owner
media or saves. It retains route plans, original wire journals, timing profiles,
SDK, controller-source, binary and input bindings, and a passing or failed receipt.

The timing result is a local observation, not a promised speedup. The sparse run
saves fewer complete states and sends fewer control/observation requests; it
also records fewer intermediate diagnostic boundaries. When an endpoint
comparison fails, rerun the smaller failing segment with denser boundaries.
The request profile separates journal writes, send/reply envelopes and client
admission. The exchange includes server scheduling and work; it cannot isolate
network latency. Imported checkpoint counters remain lifetime history.

This compares authored same-build native runs. It does not qualify retail
gameplay, replace an independent interpreter comparison or enable cross-build
checkpoint transfer. [Issue #43](https://github.com/rages4calm/pcenginerecomp/issues/43)
tracks the latter separately.
