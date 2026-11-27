# Read-only checkpoint BRAM diagnostics

An offline command can copy the 2,048-byte CD backup-memory image from a
source-bound developer checkpoint. It uses the canonical typed checkpoint
loader, validates the complete state, and extracts from a private decoded copy.
It never restores the live machine or executes guest instructions. The command
exits before creating a window, audio device or TCP server.

## Export

Run the controller from the **exact producer SDK**, against the unchanged
consumer build that created the checkpoint. Supply its independently recorded
whole-file SHA256 and a new output directory beneath an existing directory:

```sh
python -m pcerecomp.checkpoint_bram port.toml --build build \
  --checkpoint checkpoints/own.pcec --checkpoint-sha256 EXACT_SHA256 \
  --out diagnostics/new-export --reference-enabled
```

Use `--reference-enabled` only if that capability was enabled in the source
checkpoint recipe; it affects identity even when the guest ran natively.
The Python API is `project.export_checkpoint_bram(descriptor, build_dir,
checkpoint, output, expected_checkpoint_sha256=sha, reference_enabled=True)`.

The controller verifies the consumer package, executable, adjacent DLLs, source
graph, SDK and inputs before and after extraction. The source executable
recomputes its checkpoint identity and admits the file with
`load_checkpoint_file`. Wrong identities, hashes, layouts, profiles and malformed
state fail closed. Output must be new; links/reparse points and replacement of
the reserved output directory are refused. The raw image is published without
replacement. A complete, atomically published `receipt.json` with `passed: true`
is the success marker. Partial or failed output is not an accepted export.

The output directory contains `bram.bin`, `runtime.json`, `stderr.log` and the
receipt. Imported source ticks, frame, raster frame count, execution counters,
pending PCM and WAV history are reported separately from the diagnostic's zero
retirements. Source checkpoints and inputs remain unchanged. Failed receipts
should be preserved; retry into a new directory.

## Boundaries

- The feature must already exist in the source consumer executable. Rebuilding
  an older package does **not** authorize export of its old checkpoints. Keep its
  original SDK and package; establish a new baseline before using this feature.
- V1 supports pristine schema-1 ABI29 CD/F7 BRAM layouts. HuCard and all
  adapter-bearing packages are excluded, including compiled-pristine adapters.
- Normal `--bram-out` reference/checkpoint exclusions and TCP/`Bus.peek` BRAM
  refusal remain unchanged. This is an offline diagnostic operation.
- The bytes are not automatically a valid game SAVE, an authentic player save,
  or portable checkpoint state. Game-specific save eligibility and validation
  belong to the consumer. This command accesses no installed or owner save.
- A developer may explicitly select the image as a new immutable BRAM asset
  for a **fresh cold consumer**. This changes its asset and machine identity;
  create appropriate new seeded declarations/observation epochs. Never relabel
  blank-seed captures or rebind earlier checkpoints to that consumer.

The [authored example](../examples/checkpoint-bram/README.md) exercises genuine
guest reads and writes, TCP checkpoints, native/repeat/reference comparisons,
offline extraction, refusal cases and a separately built cold seeded consumer.
It does not qualify retail save formats, hardware or a campaign.
