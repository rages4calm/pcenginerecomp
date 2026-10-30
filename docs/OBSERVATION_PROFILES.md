# Mixed-ABI observation profiles

An observation profile is a private catalogue of exact instruction identities
from one or more original capture files. Supported offline inputs retain their
original ABI 12 through 26 labels. The generated module targets current ABI 26.
Composition neither changes those historical labels nor converts checkpoints,
certifies an ABI migration, or establishes a newly executed run.

Profiles contain original game or firmware code bytes, including base64 copies
of the original files. Keep profiles, captures and generated modules private.
Public tests use authored instructions only.

## Compose and emit

```text
python -m pcerecomp compose-observations .local/capture/original.json .local/capture/new-run.json --out .local/profiles/combined.json
python -m pcerecomp emit-profile .local/profiles/combined.json --out .local/native/combined --partition-layout stable
```

Both destinations must be new. Composition admits all inputs and checks union
capacity before creating its output. Existing files, hard links and symlinks
are never overwritten. The source files remain unchanged. Emission accepts
the same exclusions, partitioning and opt-in native-span options as
[`emit-capture`](CODE_CAPTURE.md). A capture and a profile are different input
formats: each command refuses the other format.

Every union key includes logical PC, **all eight MPR bytes**, and every fetched
instruction byte. Physical addresses are checked against the decoder and MPR
mapping. Same-PC byte variants, otherwise-unused MPR differences, overlapping
instructions, page crossings and logical-address wrap remain distinct where
their complete keys differ. Exact duplicate raw inputs count once, even under
different filenames. Distinct files with identical decoded instructions remain
separate provenance inputs and contribute their own historical hits.

Input order does not affect the profile. Inputs sort by SHA256, identities by
MPR/PC/bytes, and contributions by input SHA256. There is no last-file-wins
policy or silent truncation. An existing profile is not a composition input;
recompose its retained original captures when adding observations.

## Version 1 contract

The `format` is `pce-observation-profile-1`, `schema` is 1, and
`execution_evidence` is always false. There is deliberately no top-level
capture ABI or checkpoint origin.

| Field | Meaning |
|---|---|
| `capacity` | Maximum unique identities in this union |
| `inputs` | SHA256-sorted `{sha256, size_bytes, raw_base64}` records holding exact original capture bytes |
| `observations` | Canonical capture identity fields, summed historical tier hits, and per-input `contributions` |
| `historical_totals` | Checked sums of original native/interpreted hits and retired counts |

Each contribution contains `input_sha256`, `native_hits` and
`interpreted_hits`. Reloading decodes canonical base64, rehashes exact bytes,
strictly validates every original capture, rebuilds the entire union, and
compares identities, contributions and totals. Original schema, ABI, capacity,
loss counters, completeness and optional checkpoint origin stay inside their
unchanged raw input. A reserialized capture has a different raw identity even
when its decoded observations are equal.

Admission requires complete, lossless captures. Unknown fields, unsupported
ABIs, duplicate JSON keys, noninteger numeric tokens, nonfinite values, invalid
physical mappings, mismatched raw hashes and fabricated contribution or total
fields refuse explicitly. All counts and checked additions fit unsigned
64-bit integers. Checkpoint-prefix counters remain input metadata and are not
added to historical suffix work.

| Bound | Version 1 limit |
|---|---|
| Input path arguments / distinct provenance inputs | 256 |
| Individual raw capture | 64 MiB |
| Total distinct original raw bytes | 64 MiB |
| Union identities | 1 through 65,536 capacity; an empty observed union is allowed |
| Per-input identity contributions | 262,144 total |
| Serialized profile file | 128 MiB |

`--capacity N` lowers the union bound; it never discards identities. Metadata
bounds apply even when many inputs share the same keys. Excess refuses before
output creation. The byte limits are format admission bounds, not a claim
about peak Python memory consumption.

## Emission and consumer projects

The emitter shares the established guarded translation core with
`emit-capture`: it generates direct C++ operations with full MPR, logical-PC,
source-byte and deadline guards. Unsupported operations still miss to the
configured dispatcher policy. Composition adds no interpreted runtime path,
guest patches or inferred control-flow edges.

The schema-1 module manifest records `observation_profile_sha256`, format and
schema, `observation_inputs` with code-free original input metadata, and
explicitly historical totals. Its `runtime_abi` describes generated code.
It does not manufacture `capture_runtime_abi`, a single capture checkpoint,
or current-ABI retirement evidence. Exclusion hit counts are historical input
sums as well. Retain the exact input profile alongside build evidence: its
hash binds all raw bytes and per-identity contributions. The module manifest
does not embed the full profile, and the consumer build interface does not
automatically copy or authenticate that separately retained file.

An input SHA proves which bytes were supplied, not that the input's claimed
execution actually occurred. Historical sums can include overlapping sessions
or a preexisting catalogue; the composer cannot deduplicate execution events
across distinct files. A lossless input only describes its retained window,
not complete program coverage. Emission keeps `execution_evidence: false`.
Compilation, actual native/interpreted execution, game progression and audio
checks require separate receipts. New modules require their own cold execution
and exact-module checkpoint qualification.

## Python API

```python
from pathlib import Path
from pcerecomp.observations import (
    compose_observation_profile, load_observation_profile,
    validate_observation_profile, observation_profile_provenance,
)
from pcerecomp.emitter import emit_observation_profile

profile = compose_observation_profile(
    [Path('.local/capture/original.json'), Path('.local/capture/new-run.json')],
    capacity=65536,
)
# Or load an already written profile and bind its exact original file bytes:
profile, digest = load_observation_profile(Path('.local/profiles/combined.json'))
manifest = emit_observation_profile(
    profile, Path('.local/native/combined'), digest, partition_layout='stable',
)
```

Validation returns canonical decoder-derived translation records. Provenance
inspection returns original per-input metadata without instruction bytes.
When an in-memory emitter call omits the digest, it hashes canonical compact
JSON; that digest is not the hash of an independently pretty-printed file.
Pass the loader's digest when binding a retained file. A caller-supplied digest
must identify the caller's actual artifact; the in-memory API cannot verify a
file it was not given.

## Verification scope

Frozen implementation `42910a2a9fdffb978d5eaafa713edc7dbd7ccc9f` passes the
fresh SDL Release build and required checker: 1,360 Python tests without skips,
65 C++ suites and 12 fresh-process audio checkpoint cases. Thirty-three new
authored tests cover the profile, CLI and emitter. A separately compiled
mixed-18/26 module executes all five supported identities as five native
instructions with zero interpretation; expected registers, 12 cycles, 36 ticks
and explicit mapping/source/deadline misses are checked. Its generated span
entry is compiled but not exercised by that test.

Frozen independent review rejects 25 altered profiles and confirms legacy
generated source preservation across six emission configurations. Private
consumer-input qualification preserves 57,545 older identities and adds 23,
with a 57,568-key union. That consumer check composes and emits only; its input
hit totals are historical and its new game module is not compiled or executed
by that check. See [current status](STATUS.md) for the exact proof boundaries.
