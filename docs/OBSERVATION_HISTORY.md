# Content-addressed observation histories

An observation history is a private, portable directory containing exact original
capture files and a derived instruction catalogue. It provides a scalable
transport for the same staged contribution policy as [observation
profiles](OBSERVATION_PROFILES.md), without base64-embedding every original in
one JSON document. The format is `pce-observation-history-1`, schema **1**.

This is an offline catalogue. Composition and emission do not execute a guest,
convert checkpoints, certify a runtime migration or establish native execution.
Original captures retain their own ABI, checkpoint origin, execution policy and
tier counters; supported historical capture ABIs are 12 through 29. Emitted
modules target current ABI **29**. There is no invented aggregate execution ABI
or checkpoint origin for a mixed history.

Histories contain game or firmware instruction bytes. Keep the entire history,
captures and generated modules private. Public fixtures must be authored.

## Compose, extend and emit

```text
python -m pcerecomp compose-history .local/capture/a.json .local/capture/b.json --out .local/history/base
python -m pcerecomp compose-history .local/capture/new.json --baseline-history .local/history/base/history.json --out .local/history/extended
python -m pcerecomp emit-history .local/history/extended/history.json --out .local/native/extended --partition-layout stable
```

Every destination must be new. Its parent must already be an ordinary directory
for composition. Existing destinations are refused, including symlinks. Inputs
remain unchanged. Do not put an extension inside its baseline history, or emit
code inside the input history: that would violate its closed graph.

Without a baseline, all distinct input captures form stage zero. To establish an
explicit raw baseline, repeat `--baseline-input`:

```text
python -m pcerecomp compose-history .local/capture/new.json --baseline-input .local/capture/old-a.json --baseline-input .local/capture/old-b.json --out .local/history/from-raw
```

To migrate a retained version 1 or version 2 inline profile, or copy an admitted
history without asserting a new execution, omit new capture arguments:

```text
python -m pcerecomp compose-history --baseline-profile .local/profiles/retained.json --out .local/history/imported
python -m pcerecomp compose-history --baseline-history .local/history/imported/history.json --out .local/history/copied
```

`--baseline-input`, `--baseline-profile` and `--baseline-history` are mutually
exclusive baseline kinds. An invocation needs at least one original input or a
retained baseline. Retained profiles keep their existing admission limits; this
does not reinterpret an oversized or invalid profile as valid history.

`--capacity N` bounds the union to 1 through 65,536 instruction identities. If
omitted, a retained profile/history supplies its capacity; a fresh/raw baseline
uses 65,536. Reducing capacity cannot prune existing identities: it refuses when
the complete union does not fit. There is no history dry-run option.

`emit-history` accepts the same options as [capture
emission](CODE_CAPTURE.md): repeatable `--exclude-range ADDRESS:LENGTH`,
`--partition-size`, `--partition-layout balanced|stable`, `--single-unit`, and
`--native-span`. Balanced partition size is 1 through 4096, default 256. Stable
layout requires size 256 and multiple translation units; native spans require
stable layout. The direct emitter defaults to balanced layout. Generic
[project preparation](PREPARE_PROJECT.md) explicitly defaults to stable layout.

An exclusion removes an instruction when **any fetched physical byte** touches
the excluded range. History input bytes and accounting remain unchanged; the
manifest records the emission selection. Generated bodies contain translated
operations with source guards, not a per-opcode interpreter wrapper. Unchanged
stable units retain their exact C++ bytes when other units gain identities.

Legacy `emit-capture`, `emit-profile`, and observation-profile composition do
not silently accept history indexes. Select the explicit history command or
recipe `module.kind = "history"`.

## Complete identities and selection stages

Every instruction identity includes logical PC, all eight MPR bytes and all
fetched instruction bytes. Each physical fetch address is checked against the
logical address and MPR map. Same-PC code variants, otherwise-unused MPR
differences, page crossings and address wrap retain their complete identities.
A physical bank or logical PC alone cannot identify an overlay.

Original files are keyed by SHA256. Byte-identical inputs count once even when
supplied under different filenames. Distinct original files retain separate
provenance and historical hits even when they describe the same instructions.
Input order does not choose a winner: inputs and stages use canonical SHA
ordering, and catalogue identities sort by MPR, PC and bytes.

Stage zero retains every original baseline contribution. Each later stage
selects contributions only for complete identities absent from all preceding
stages. If several additions in one stage contain a new identity, the lowest
input SHA wins that identity's contribution. Importing or extending a staged
profile/history preserves its earlier stages and winners.

An exact duplicate addition creates no stage. A distinct new file with no new
identities remains in the raw archive and stage ledger with zero newly selected
rows. Its original hits still contribute to `historical_totals`.

The counters have different purposes:

| Field | Meaning |
| --- | --- |
| `historical_totals` | Sum of all distinct original inputs' native, interpreted and retired counts |
| `selected_historical_totals` | Hits from the contribution rows retained by the stage policy |
| `selection_counts` | Original, selected and omitted contribution counts |
| Per-input metadata | That original's ABI, origin, completeness, counters and content identity |

Overlapping execution windows are not automatically deduplicated. Selection
omission is a declared catalogue policy, not proof that two original hits were
the same execution. A stage ledger records declared provenance, not authenticated
producer activity or proof that a particular parent operation happened. Retain
the exact parent artifact and operation receipt when that relationship matters.

## Directory and admission contract

```text
history.json
captures/<original-sha256>.json
catalogue/<shard-sha256>.jsonl
```

The index contains bounded references and accounting, not base64 capture copies.
Raw files preserve the exact admitted original bytes. Shards contain canonical
compact JSON lines ending in LF. The index is canonical compact JSON with a
final LF. Catalogue shards are derived data; their hashes alone never establish
their truth.

Admission rereads original captures, validates their original metadata, decodes
their observations and reconstructs identity union, selected contributions,
counts and totals. It compares every derived catalogue line and the full ordered
catalogue digest. A changed index, raw file, shard, source mapping, stage ledger,
counter or contribution row refuses rather than trusting a cached summary.

The directory is a closed graph: exactly the index and its declared `captures/`
and `catalogue/` files are allowed. Missing, extra, linked, reparse-point,
hard-linked or nonregular graph files refuse. Index/raw/shard encodings and
canonical derived content are checked. Original captures must be UTF-8 without
a BOM or literal NUL; changing original whitespace changes their content SHA.

| Bound | History format 1 |
| --- | --- |
| Distinct original captures | 256 |
| Original path arguments per composition | 256, including explicit baseline arguments |
| Each original capture | 64 MiB |
| Aggregate raw transport | At most 256 × 64 MiB, or 16 GiB |
| Union identities | Declared capacity, maximum 65,536 |
| Selected contribution rows | 262,144 |
| Index | 1 MiB |
| Each catalogue shard | 4 MiB and at most 4096 identities |
| Each catalogue line | 64 KiB |

All bounds apply; the 16 GiB transport ceiling does not promise that every
combination within it fits identity or contribution limits, or that admission
uses constant memory. Captures and inline profiles retain their existing limits,
including the profile's 64 MiB aggregate original-byte and 128 MiB serialized
limits. History avoids that single embedded transport bottleneck; it is not
unlimited storage or relaxed capture validation.

Composition admits semantic inputs before allocating output and publishes
`history.json` last. I/O failures can retain partial new directories for
diagnosis. The index-last contract is not an atomic filesystem transaction.
Keep inputs immutable during use. Revalidation checks bytes and graph closure;
timestamps are not a substitute for content hashes.

## Python APIs and consumer bindings

```python
from pathlib import Path
from pcerecomp.history import compose_history, load_history
from pcerecomp.emitter import emit_history

history = compose_history(
    [Path(".local/capture/new.json")],
    Path(".local/history/next"),
    baseline_history=Path(".local/history/base/history.json"),
    capacity=65536,
)
history.revalidate()
manifest = emit_history(
    history.index_path, Path(".local/native/next"),
    partition_layout="stable",
)
```

`compose_history(input_paths, output, *, baseline_inputs=(),
baseline_profile=None, baseline_history=None, capacity=None)` returns an
`AdmittedHistory`. `load_history(path)` accepts the `history.json` path or its
directory and returns the same admitted type. `emit_history(history_path,
output, exclude_ranges=(), partition_size=256, single_unit=False,
partition_layout="balanced", native_span=False)` returns the module manifest.

An admitted object exposes `index_path`, `index_sha256`, `index`, `instructions`,
`input_metadata` (also `per_input_metadata`), `accounting`, `artifact_bindings`
and `artifacts`. Graph bindings include each relative name, absolute local path,
SHA256 and byte size. Treat these local paths as private. Data properties return
copies. `revalidate()` rereads every bound artifact and checks exact closed
graph membership; changed artifacts raise `ValueError`.

Emission admits the history once, uses the shared operation emitter, rechecks
the complete graph before publishing `module.json`, and rechecks at completion.
The manifest has `observation_history_sha256`,
`observation_history_format = "pce-observation-history-1"`,
`observation_history_schema = 1`, original `observation_inputs`, and the
accounting above. Capture, inline-profile and history source provenance are
mutually exclusive; no synthetic `code_capture_sha256` or profile hash is added.

A consumer binds the exact index and retains its entire graph:

```toml
[module.observation_history]
path = "observation-history/history.json"
sha256 = "REPLACE_WITH_EXACT_INDEX_SHA256"
```

This table accompanies the usual `[module.source]` and `[module.manifest]`
bindings and is mutually exclusive with `[module.observation_profile]`. Consumer
verification binds the index as `module_observation_history` and other files as
`module_history:<relative-name>`. Managed builds copy the graph into their
reserved `observation-history/` namespace and retain it in candidate checks.
Removing originals after emission is not a supported way to preserve provenance.

The [authored native workflow](../examples/native-workflow/README.md) exercises
real captures, a retained profile import, additive history, generic preparation,
official build/run, writable-code guards and a literal whole-RAM endpoint.
