# Typed checkpoint inspection and comparison

Use typed reports instead of parsing checkpoint offsets in private port scripts.
The exact producer executable admits the original file through the canonical
loader and reports CPU, complete HOST/CORE fingerprints, frame and pending-audio
metadata. It exits before SDL initialization, audio devices, TCP or guest
execution. No state is committed to a live machine.

## Inspect a source checkpoint

Run from the unchanged producer SDK, with its original package and inputs.
The output directory must be new, beneath an existing ordinary directory:

```sh
python -m pcerecomp.checkpoint_inspection inspect port.toml --build build \
  --checkpoint checkpoints/own.pcec --checkpoint-sha256 EXACT_FILE_SHA256 \
  --reference-enabled --out diagnostics/own-inspection
```

`--reference-enabled` must match the source recipe's capability, even if its
guest work was native. Enhanced consumers require the exact original
`--title-mode enhanced` and repeated `--title-setting NAME=VALUE` choices.
Pristine adapter packages retain schema 1; enhanced packages use schema 2.
The source's configured HuCard, payload or System Card machine is supported;
this interface adds no hardware profiles.

The Python API is `project.inspect_checkpoint(descriptor, build_dir, checkpoint,
output, expected_checkpoint_sha256=sha, reference_enabled=True,
title_mode='pristine', title_settings=None)`.

The source binary validates its executable/dependencies, media, machine and
checkpoint context. Typed admission checks ABI, schema, file/body hashes, state
bounds and immutable configuration. The host shares ordinary restore's script
cursor, joypad and adapter-state checks. Semantic adapter validation runs without
restoring state or calling guest event hooks. Package/source bindings are
rechecked before publication.

The new directory contains `runtime.json`, `stderr.log` and an atomically
published `receipt.json`. Accept only a complete receipt with `passed: true`.
CPU counters describe **imported source work**; top-level new native/interpreted
counts remain zero. PC, eight MPRs, latches, clocks, guards, IRQs, block accounting
and HOST cursors remain visible. Adapter state is fingerprinted without dumping
its bytes. No ROM, RAM or audio bytes are exported.

## Compare two inspected states

Supply the independently recorded SHA256 of each inspection's `receipt.json`:

```sh
python -m pcerecomp.checkpoint_inspection compare \
  --left diagnostics/native --left-receipt-sha256 EXACT_LEFT_RECEIPT_SHA256 \
  --right diagnostics/reference --right-receipt-sha256 EXACT_RIGHT_RECEIPT_SHA256 \
  --policy tier-counters --out diagnostics/new-comparison
```

The API is `project.compare_checkpoint_inspections(left, right, output,
expected_left_receipt_sha256=left_sha, expected_right_receipt_sha256=right_sha,
policy='exact')`.

Both retained receipts, checkpoint files and producer packages are revalidated.
Two **fresh offline inspections** must reproduce the entire retained typed
reports. Rewritten JSON and recomputed receipt hashes cannot substitute for
actual typed state. V1 requires the same exact producer, checkpoint identity and
title recipe; cross-package or cross-SDK comparisons are refused.

| Policy | CORE | HOST |
| --- | --- | --- |
| `exact` (default) | Complete original CORE hash. | Complete canonical HOST hash. |
| `tier-counters` | Re-encode a private CPU copy with exactly four named tier counters zeroed. | Complete canonical HOST hash, including any adapter extension. |

The four fields are `native_steps`, `interpreter_steps`, `native_block_steps`
and `interpreter_block_steps`. No offsets are used. Original values remain in the
report; guards, clocks, waits, block bytes, IRQ/RTI, memory, video, audio and all
other serialized state remain exact. There is no WAV-cursor, input, adapter or
device normalization.

A comparison's `passed` means the operation completed; **`equal` is the agreement
result**. Component results and original tier counters are retained. The CLI
returns 0 for equal, 1 for a valid unequal comparison, and 2 for refused/invalid
input. Inspection returns 0 on success and 2 on refusal.

## Scope and preservation

State agreement does not prove native coverage, hardware accuracy, a valid game
SAVE or permission to restore into another package. Matching hashes never issue
a continuation permit. The source binary must already include the feature;
rebuilding cannot retrofit an older checkpoint. ABI 29 and checkpoint encodings
are unchanged.

Exclusive new directories and complete atomic receipts protect outputs. Lost or
replaced directory ownership fails closed. Preserve failed artifacts and retry
elsewhere. Source checks do not lock files or grant ongoing freshness. Fresh
comparison processes have validation cost; no retail migration speedup is claimed.

The [authored example](../examples/checkpoint-inspection/README.md) covers real
native/reference TCP checkpoints, pristine/enhanced consumers, exact restore,
nonempty pending PCM and strict refusal cases. The [BRAM example](../examples/checkpoint-bram/README.md)
also uses these supported comparisons.
