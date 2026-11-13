# Independently verified declaration source sets

For later live RAM/CD source epochs rather than initial boot assets, use the
separate [paused overlay interface](LIVE_OVERLAYS.md). It retains source
provenance and conservative candidates without inventing retired observations.

`pce-declared-source-set-1` combines numeric instruction entries from several
independently authenticated sources. A native RAM program can call a separately
declared firmware routine without first recording that call. Declarations stay
unexecuted compiler inputs; optional genuine observation history stays separate.

## Closed numeric graph

```json
{
  "format": "pce-declared-source-set-1",
  "schema": 1,
  "kind": "declared",
  "execution_evidence": false,
  "sources": [
    {"id":"program","asset":"payload","path":"declared-sources/program.json","sha256":"0000000000000000000000000000000000000000000000000000000000000000"},
    {"id":"firmware","asset":"bios","path":"declared-sources/firmware.json","sha256":"0000000000000000000000000000000000000000000000000000000000000000"}
  ]
}
```

Replace each zero digest with that member JSON file's exact SHA256. Members are
unchanged [ROM](DECLARED_ROOTS.md) or [boot-source](BOOT_SOURCE_DECLARATIONS.md)
declarations. Each contains its own raw image digest, mapping contract and numeric
roots. No raw source bytes, absolute paths, capture hits or checkpoint origins
are embedded in the graph. Source sets cannot contain nested source sets.

IDs are unique lowercase portable identifiers, matching
`[a-z][a-z0-9_-]{0,63}`. Each member path is exactly `declared-sources/ID.json`,
relative to the set manifest. That member directory must contain exactly the
listed ordinary single-link files with ordinary parents. Extra files/directories,
links, path traversal, duplicate IDs, hash mismatches and unknown fields refuse.
The parent may hold other consumer artifacts; the owned member namespace is closed.

Limits: one to 64 members; 64 MiB combined manifest/member numeric bytes;
1,048,576 total roots; and 1,048,576 distinct instruction identities including
optional history. Existing source-image and emitter bounds still apply. No
entries are silently dropped. File hashes/closure are rechecked at admission,
copy and use boundaries. Numeric copy reads are bounded and hash checked.

## Explicit external assets

Members name `cartridge`, `bios` or `payload` roles. The caller supplies an
explicit role-to-image map; the image paths are not stored in numeric members.
Each member independently decodes its source, every fetched offset and full
logical PC/MPR/physical/code identity. Members using the same role must agree on
its raw image hash. The compiler unions identical instruction keys while
retaining every member's provenance and overlapping membership counts.

Each member derives all fetched bytes of an instruction from its own image.
Instructions whose fetch bytes span different assets cannot be expressed by
these single-source member formats and refuse explicitly.

Consumers support only the roles actually present in their boot recipe:

| Boot recipe | Source contract |
| --- | --- |
| HuCard reset | `cartridge`, matching profile/header/encoding |
| System Card reset | `bios`, `kind="system-card"`, matching Standard/Super profile |
| Explicit RAM payload | `payload`, matching physical load; optional `bios` with `kind="bios"` and its 32-bank sandbox window |

A compiler admission alone does not authorize a different consumer map. Incompatible
roles, source loads or firmware profiles refuse during preparation/verification.
Source images remain immutable external boot assets, never mutable module files.

## Compose, validate and emit

```sh
python -m pcerecomp compose-roots --source program:payload:.local/program.json --source firmware:bios:.local/firmware.json --source-image payload=.local/program.bin --source-image bios=.local/firmware.bin --out .local/source-set
python -m pcerecomp declared-roots .local/source-set/roots.json --source-image payload=.local/program.bin --source-image bios=.local/firmware.bin
python -m pcerecomp emit-roots .local/source-set/roots.json --source-image payload=.local/program.bin --source-image bios=.local/firmware.bin --out .local/native-set --partition-layout stable
```

Destinations must be new. `--source` splits only its first two colons, preserving
Windows drive paths. `--source-image` bindings are repeatable and unique. They
are mutually exclusive with the existing single-source `--image` option.
Add `--history` for an admitted history graph; original observations, ABIs,
stages and counters retain their original producer. Declared-only entries gain
no fabricated hits. Overlapping observed keys retain their authentic hit fields.

Python: `source_sets.compose_source_set(members, output, source_images)`;
`declarations.load_declarations(path, source_images=...)` and
`load_compilation(path, source_images=..., observation_history=...)`;
`emitter.emit_declarations(path, None, output, source_images=..., ...)`.
Composition members have exactly `id`, `asset`, `path`. Admissions expose
`format`, member metadata, source/overlap metadata, artifact bindings and explicit
`revalidate()`. Composition copies exact numeric JSON bytes, never media.

## Consumer and state contracts

Use normal `[module] kind="declared"` preparation with `path` naming the set
manifest. Keep the explicit boot/payload, optional BIOS, runtime and limit recipe.
Preparation copies the exact numeric graph into `declarations/`; descriptor
verification rederives all members and checks their boot roles and manifest
provenance. Build inputs and checkpoint context include every member.

[Managed builds](INCREMENTAL_BUILDS.md) own/archive the complete numeric graph.
Member tampering refuses before compilation. Annotation-only changes can retain
compiled objects while changing provenance and checkpoint context. Runtime ABI 29
and checkpoint encoding are unchanged; exact-build checkpoint compatibility is
not relaxed. Old single-source formats and their default emission bytes remain.

This supplies explicit entries, not cross-member reachability, live overlay
recovery, a firmware-service stub or a whole-game native guarantee. Generated
operations retain ordinary live fetch guards, including writable RAM sources.
`discover-roots` remains a ROM-only analysis interface and refuses this format.

## Catalogue and gap reports

`native_catalog.load_native_catalog(manifest, declarations, source_images=...)`
reconstructs the exact declared/observed union and closed numeric graph. New
source-set provenance uses `pce-native-catalog-3` and the reviewed
`declared-source-set-abi29-v1` selection contract; existing single-source
catalogues retain their earlier contracts. Provenance retains every numeric
member and external asset hash without absolute paths. An explicit old ROM
contract cannot be used to backdate a source-set module.

`native-gaps` accepts the same repeatable `--source-image ASSET=PATH` bindings
alongside `--observations SET_MANIFEST` and optional `--history`. The bindings
are mutually exclusive with `--image`; ordinary observed-only reports need
neither. Actual closed captures distinguish declared/emitted/exercised and
declared/emitted/unexercised keys. A reconstructed catalogue alone does not
qualify generated code, a linked binary, native execution or whole-game coverage.

Managed numeric member sync, root/member copies and archive parsing use bounded
reads and hash/size checks. Numeric parsing/copy buffers retain explicit allocation
bounds if files grow; the supported byte limits remain explicit.

## Qualification

The [authored workflow](../examples/source-sets/README.md) supplies its own RAM
and firmware bytes. Its 256 preset mapping windows execute all 5,888 declared
keys, with literal CPU/MPR/clocks/full-RAM and encoded-hit checks. Independent
Geargrafx CPU/source-byte/full-WRAM/CD-RAM windows pass separately. Real managed
generations retain member provenance and object reuse; thirty prior single-source
emissions stay byte-identical. Fresh Rondo TCP/checkpoints regress the existing
observed module, not retail use of source sets. See [current status](STATUS.md).
