# Extended capture and history workflow

This opt-in path addresses [issue #11](https://github.com/rages4calm/pcenginerecomp/issues/11):
a banked program can execute more than 65,536 distinct full instruction identities.
That count is a host discovery bound, not the CPU's address-space size or a reason
to merge identities. A key retains logical PC, all eight MPRs and fetched bytes;
physical source addresses are validated. Same-PC byte variants and otherwise-unused
MPR differences remain distinct. Native-only misses stop; hybrid misses remain
actual interpreted work.

## Choose the larger format explicitly

On either freshly built host, append:

```text
--code-capture NEW-private-capture.jsonl --capture-profile extended --capture-limit 262144
```

`legacy` remains the default, with capacity 1..65,536 and raw-file bound 64 MiB.
Explicit `--capture-profile legacy` produces the same legacy capture bytes as
omitting the option under the same execution. `extended` permits capacity
1..1,048,576 and writes format 2 framed JSONL, bounded to 512 MiB. Its default
capacity is still 16,384: select a larger capacity for a larger discovery window.
A profile without a capture path, duplicate flags and out-of-range values refuse.
Rebuild the host and use the updated parser/client; an old host does not acquire
new options through an ABI label.

For an embedded C++ host, select the profile explicitly as the third constructor
argument; existing two-argument calls remain legacy:

```cpp
pce::CodeCapture capture(path, 1048576, pce::CodeCapture::Profile::extended);
```

The official consumer runner exposes the same option:

```text
python -m pcerecomp.project run .local/consumer/project.toml --build-dir .local/consumer-build --code-capture .local/captures/discovery.jsonl --capture-profile extended --capture-limit 262144 --receipt .local/runs/discovery.json
```

The Python `project.command_for` and `project.run` interfaces take
`capture_profile="legacy"` by default. A fresh receipt checks requested schema,
format, capacity, ABI, origin, actual tier counts and final raw-file SHA closure.
Extended receipts add `code_capture.capture_profile="extended"`,
`capture_schema=2` and `capture_format="pce-code-capture-2"`; legacy successful
receipt shapes and
argument defaults remain unchanged. Neither a good exit nor a full identity
capacity alone establishes complete coverage: inspect `complete`, drops,
unreadable retirements and actual native/interpreted work.

## Compose a version 2 history

```text
python -m pcerecomp compose-history .local/captures/discovery.jsonl --history-version 2 --capacity 262144 --out .local/histories/base
python -m pcerecomp emit-history .local/histories/base/history.json --out .local/native/base --partition-layout stable
python -m pcerecomp compose-history .local/captures/later.jsonl --baseline-history .local/histories/base/history.json --capacity 524288 --out .local/histories/later
```

Create parent directories first; destinations must be new. `history_version=None`
in Python and an omitted CLI version select v1 without a retained history, or
inherit the retained history's version. Explicit version 2 promotes an admitted
v1 history or inline profile; originals, stages and selected/historical work
remain intact. Capacity of a retained baseline is inherited unless explicitly
changed: promotion does not silently enlarge it. New v2 histories default to
1,048,576 capacity. Version downgrade refuses, even for a small catalogue.

Version1 histories and both inline profile formats retain their original limits
and do not admit format 2 captures. Re-encoding an incomplete capture or truncating
it at an invented boundary does not repair its provenance. Recapture a bounded
lossless window with enough capacity, then compose complete originals. The
additive policy keeps zero-novel originals and avoids duplicating selected overlap;
it does not infer which overlapping windows represent separate execution.

`compose_history(..., history_version=2, capacity=262144)` and
`emit_history(...)` are the corresponding Python APIs. `load_history` validates
both versions and recomputes all catalogue content from raw originals.
See [history admission](OBSERVATION_HISTORY.md) for graph/tamper rules.

For generic preparation, select the new format explicitly:

```toml
[module]
kind = "history"
path = "../histories/base/history.json"
history_version = 2
capacity = 262144
partition_layout = "stable"
```

An admitted v2 history can also retain its version and capacity through preparation
by omitting both options. Request explicit version 2 when setting a capacity
above 65,536 in a preparation recipe. A new extended capture input requires explicit
version 2. Every descriptor still uses consumer schema 1 and runtime ABI 29;
complete graph bindings and source pins are required.

Managed builds permit checked v1-to-v2 promotion and nondecreasing v2 capacity,
while retaining previous raw hashes, normalized stage prefix and policy. They
archive complete original graphs. Shrinking, dropping inputs, altering prior
selection or downgrading refuses before compiler/mutation. Unchanged generated
C++ can reuse objects; new observation bindings still change checkpoint context.
This does not upgrade a workspace across SDK source pins or import old checkpoints.

## Choose a compilation layout

Stable layout is useful for managed changed-unit reuse, but many sparse full-MPR
contexts can create many files. For a fresh larger catalogue, balanced layout
with a larger explicit partition size can reduce repeated compiler header work:

```text
python -m pcerecomp emit-history .local/histories/base/history.json --out .local/native/balanced --partition-layout balanced --partition-size 4096
```

Or select `partition_layout = "balanced"` and `partition_size = 4096` in the
preparation module table. This preserves every guarded identity; it does not
promise stable changed-unit reuse. Keep stable layout for the managed producer,
which requires its stable partition contract. In the private SF2 catalogue,
190,243 identities across 1100 full MPR contexts emit 7538 stable units or 1101
balanced units. These are one catalogue's generation counts, not a general
compile-time or guest-speed benchmark. Generation, compilation and execution
remain separate evidence.

## Format 2 wire contract

The exact first line is:

```json
{"format":"pce-code-capture-2","schema":2}
```

It ends with LF. The second line is a JSON header with exactly `runtime_abi`,
`capacity`, `dropped_instructions`, `unreadable_instructions`,
`retired_instructions` and `complete`, plus optional original `checkpoint_origin`
and `execution_policy`. It has no observation array and no repeated format/schema.
Each next line is one ordinary six-field observation: `pc`, `mpr`, `physical`,
`data`, `native_hits`, `interpreted_hits`.

A required exact terminal footer is `{"record":"end","observations":N}` plus LF,
where N is the actual observation count. No extra bytes or trailing records are
accepted. Each record is at most 64 KiB; the whole original is at most 512 MiB.
Records require UTF-8 without BOM/NUL, exact fields, unique JSON keys and integer
numeric tokens. The parser rejects nonfinite values, unknown records, duplicate
identities, invalid mappings, bad counts, incomplete footer/framing and unsupported
producer/format combinations. Format 2 currently requires an ABI 29 producer.
The host writes checked bounded records only at closure; a missing terminal footer
is never a successful capture. There is no whole-file host serialization string.

`load_capture(path)` detects exact framing and returns a validated dictionary
plus SHA256 of the original wire bytes. `parse_capture_bytes(raw)` is the strict
bytes API. An unframed object claiming schema 2 is not a substitute. The normalized
Python view has schema 2, format `pce-code-capture-2` and `observations`; its JSON
re-serialization is not the original artifact hash. Keep raw originals unchanged.

Live TCP summaries remain schema 1. Extended capture adds the exact pair
`capture_schema:2` and `capture_format:"pce-code-capture-2"`; missing/incoherent
pairs refuse. Pagination remains at most 256 rows per response. `capture_history()`
uses admitted metadata for larger offsets and retains epoch/tier/loss checks.
Direct `capture_sources(..., capture_profile="extended")` explicitly permits an
offset above 65,536; its default local bound remains legacy. Live rows remain
code-free metadata; do not treat them as encoded raw captures.

## Combined limits and qualification

| Bound | Legacy capture/history v1 | Extended capture/history v2 |
| --- | --- | --- |
| Capture capacity | 65,536 | 1,048,576 |
| Original raw file | 64 MiB | 512 MiB |
| Distinct history originals | 256 | 256 |
| Aggregate history raw transport | 16 GiB | 128 GiB |
| History union capacity | 65,536 | 1,048,576 |
| Selected history contributions | 262,144 | 4,194,304 |
| History index | 1 MiB | 1 MiB |
| Catalogue shard | 4 MiB /4096 identities | 4 MiB /4096 identities |
| Catalogue line | 64 KiB | 64 KiB |

All limits apply together. This is not constant-memory admission, unlimited
storage or a guarantee that every million-site module fits independent module
manifest/generated-source/toolchain bounds. Project verification retains the
64 MiB module-manifest byte bound while v2 has explicit larger site/unit count
ceilings. Native catalogue admission retains its separate 64 MiB per generated
artifact and 512 MiB aggregate generated-artifact bounds; those are admission
bounds, not a global source-byte cap for ordinary compilation.
The optional extended `native-gaps --capture-profile extended` report uses its
own version 2 format, maximum 1,048,576 discovered identities and 512 MiB aggregate
raw inputs; default reports retain the 64 MiB/65,536 legacy limits. It remains
declared membership, not compiled or executed proof.

The authored end-to-end workflow actually compiles and executes 73,701 native
instructions with zero interpreted retirements and zero guard misses. Every
captured identity matches across ten full MPR contexts; literal registers,
147,456 CPU cycles and 442,368 master ticks agree. Its legacy control retains
65,536 identities and explicitly drops 8165 retirements; extended capture has
zero loss. A quiet hidden SDL dummy-device run also captures all 73,701 real
interpreted identities and matches headless state/clocks/encoded sources.
No final RAM endpoint was measured for this scale fixture.

At code `608e68eeb3b62a8ff5976690f40e95587c3e1bd7`, the final SDL build and required
check pass **1,944 Python tests without skips, 74 C++ suites and 12 fresh-process
audio cases**. All 724 tracked inputs remain unchanged through verification.
The SDK has 93 source files, SHA256
`9e77b82e058a36ba4a846893b27bba3baf13997a0df5a156a4d0f471da91ca14`.

A private SF2 test uses the exact image SHA reported in issue #11 and an explicit
Japan/SF2-board recipe. Two cold no-input 3,600-frame interpreter runs match all
six sampled paused guest states, full 8192-byte work RAM and the final completed
256x240 guest image. Each retires 100,397,977 interpreted instructions at
1,292,382,000 master ticks. Legacy capture reaches 65,536 identities and drops
8,815,634 retirements; extended capacity 1,048,576 retains 190,243 identities with
zero drops or unreadable instructions.

The complete 190,243-site history compiles through the official consumer builder
in 1101 balanced module units. A fresh official native-only replay and a separate
captured native replay each retire **100,397,977 native / zero interpreted / zero
guard misses** at frame 3600 and the same raw tick count. The second run's complete
extended capture (capacity 262,144) matches every full encoded identity and each
per-identity hit count after the explicit interpreted-to-native tier relation.
All six sampled states, full work RAM and final completed image match, with only
documented tier/block/guard counters and the ephemeral development port normalized.
This is bounded same-runtime tier/collector parity, not an original-emulator,
hardware, audio or full-campaign qualification. The downstream scripted-play and
18,000-frame routes remain separate rerun work. Commercial inputs, captures,
generated sources and private images are not published.

The [public authored extended workflow](../examples/extended-capture/README.md)
provides a commercial-data-free reproduction. Broader title and hardware behavior
still require their own evidence. CPU/device semantics, guest checkpoint encoding
and runtime ABI 29 are unchanged; exact build/SDK compatibility still applies.
