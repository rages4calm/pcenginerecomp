# Declared RAM payload and System Card sources

For later live RAM/CD source epochs rather than initial boot assets, use the
separate [paused overlay interface](LIVE_OVERLAYS.md). It retains source
provenance and conservative candidates without inventing retired observations.

The explicit `pce-declared-boot-roots-1` format describes instruction entries
recovered from an exact raw boot source. It extends the [declaration interface](DECLARED_ROOTS.md)
to standard-RAM payloads and System Card firmware. It contains numeric source
offsets, not opcode bytes, observed hits or checkpoint origins. It does not infer
reachability, routines, disc extraction, live overlay loads or later RAM contents.

The original `pce-declared-roots-1` HuCard format remains supported unchanged.
Runtime lowering, ABI 29 and checkpoint encoding are unchanged. The new source
contract changes SDK/build identity; existing checkpoints retain their original
exact-build compatibility requirements.

## Numeric source contract

```json
{
  "format": "pce-declared-boot-roots-1",
  "schema": 1,
  "kind": "declared",
  "execution_evidence": false,
  "image": {
    "kind": "payload",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "physical_load": 1048576
  },
  "roots": [
    {"pc": 16384, "mpr": [255,248,128,129,130,131,132,0], "selector": 0, "source_offsets": [0,1]}
  ]
}
```

Replace the zero digest with the exact lowercase SHA256 of the raw source file.
Each row names one decoded instruction, with all eight MPRs, selector zero and
one to seven offsets. `source_offsets` index the raw file bytes, not logical or
guest physical addresses. Every fetched byte must agree with the mapping and
decoder, including a logical page crossing or 16-bit PC wrap. Identical duplicate
rows refuse; identical underlying bytes in distinct mapped contexts retain their
full physical/MPR identity. No header removal or bit conversion is implicit.

For a payload, `image` has exactly `kind`, `sha256` and `physical_load`.
The nonempty contiguous input must fit the existing explicit sandbox loader:
CD RAM physical `$100000..$10FFFF` (banks `$80..$87`) or base WRAM
`$1F0000..$1F1FFF` (bank `$F8`). It cannot cross outside those supported ranges.
WRAM fetches through MPR banks `$F8..$FB` resolve the same backing source bytes,
while the mapped physical address stays in the compiled identity. Unloaded RAM,
other memory, devices and guessed zero-fill refuse as code sources.

For firmware, replace `image` with exactly:

```json
{"kind":"system-card","sha256":"0000000000000000000000000000000000000000000000000000000000000000","profile":"super"}
```

The source must be raw 256 KiB firmware. `profile` is `standard` or `super`.
ROM banks `$00..$7F` select the 32-bank image mirrors; on Super System Card,
`$68..$7F` are RAM and cannot supply firmware declarations. RAM, absent banks
and I/O never become ROM just because a corresponding raw offset exists.
The profile is an explicit hardware role, independent of a filename or BIOS CRC.

All top-level/image/root fields and primitive types are exact. Booleans are not
integers. Sources and numeric files must be ordinary single-link files with
ordinary parents. Existing declaration limits apply (64 MiB numeric file,
1,048,576 roots/combined identities); source-role size/range limits are narrower.
Hashes, sizes and complete inputs are revalidated at admission and use boundaries.
A file-size change between metadata and source snapshot refuses explicitly.
Decoder buffers read at most the admitted size plus one sentinel byte; later
source growth refuses without an unbounded allocation.

## Optional BIOS in the explicit payload sandbox

The existing payload host can also bind a raw 256 KiB `[bios]` asset. Numeric
firmware members for that host use exactly `{"kind":"bios","sha256":"..."}`:
only physical ROM banks `$00..$1F` are authenticated. This mapping is distinct
from `system-card-reset` and its Standard/Super mirrors. `kind = "system-card"`
cannot be used to invent those mirrors in a payload sandbox.

Use [source sets](SOURCE_SETS.md) to combine the payload and BIOS members.
Consumer verification checks each role against the actual boot recipe. This
adds compiler source contracts; it does not alter existing runtime maps or
simulate firmware services.

## Validate, emit and prepare

```sh
python -m pcerecomp declared-roots .local/roots.json --image .local/source.bin
python -m pcerecomp emit-roots .local/roots.json --image .local/source.bin --out .local/native-source
```

The existing Python APIs `declarations.load_declarations`, `load_compilation`
and `emitter.emit_declarations` accept the new format through their unchanged
path/image arguments. The admitted object exposes its actual `format` and
role-specific `source_metadata`. Validation and emission are not execution.
Old readers reject the new format instead of silently treating it as HuCard ROM.
ROM `discover-roots` also refuses it before creating output; this contract is
explicit numeric entry declaration, not automatic writable-code discovery.

Use `[module] kind = "declared"` in the supported [preparation recipe](PREPARE_PROJECT.md).
For a payload, retain the complete `[payload]` path, physical load, PC and MPR
recipe. For firmware, use `[boot] mode = "system-card-reset"`, the matching
standard/super profile and `[bios]` asset. Other required runtime/limit fields
remain unchanged. Preparation and descriptor verification bind the declarations
to that exact source digest, size, role, profile/load and actual boot asset.
Moving the declared load or changing the firmware profile cannot repurpose an
otherwise valid module. Numeric roots are copied; source media stays read-only
at its original location. No source image is disguised as a mutable module file.

An optional admitted observation history composes normally. Original capture
bytes, ABIs, counters and origins remain untouched; declared-only entries have
no hit fields. The declaration's source image attests its own entries, not the
whole image behind every independent historical observation.

## Runtime and managed builds

Generated C++ contains translated operations and ordinary live per-instruction
source/MPR/deadline guards. A payload declaration authenticates bytes in its boot
input; RAM remains writable. A later changed opcode/operand can hit another
admitted identity or refuse the native-only guard. Supported hybrid execution can
interpret unseen code. File admission never replaces actual runtime source reads
or supplies an invented firmware service.

[Managed stable builds](INCREMENTAL_BUILDS.md) copy/archive the exact numeric
annotation alongside optional original history, with the boot source remaining a
fixed asset. Annotation-only changes can reuse compiled objects when generated
code is identical. Source/provenance bindings and checkpoint context still change;
this is not permission to reuse an incompatible state. Archived annotation or
source tampering refuses before compilation. Shared emission is also supported,
but the managed stable builder retains its stable-layout requirement.

Each admission currently authenticates one boot source, optionally combined with
observations. Multi-source static composition, authenticated later CD overlays,
RAM reachability inference and asynchronous IRQ analysis remain separate work.

## Qualification and references

The [reusable authored workflow](../examples/boot-sources/README.md) has no game
or real BIOS dependency. Eight CD RAM banks, four WRAM aliases, 128 Standard
firmware contexts and 104 Super firmware contexts produce 244 preset windows.
All 5,558 distinct declared keys execute; 5,612 instructions retire per native
or interpreter tier (shared WRAM continuations explain the difference).
Each window has 23 instructions / 80 cycles, with 942 payload or 960 firmware
ticks from explicit speed presets. The four official cold paths are separate.
Every literal CPU/MPR boundary, complete WRAM, bank-varying data tag and exact
encoded source/hit count passes. Positive native runs have zero interpreter work
or guard misses. Four changed-source negatives retire five native instructions,
then refuse once without refusal-time guest effects. Windows probes use a
system-only PATH and bind the official runtime archive/header/DLLs.

Fresh unmodified Geargrafx 1.8.4 passes all 244 original CPU/full-WRAM endpoints,
eight complete CD RAM source endpoints and 5,612 CPU/MPR/source-byte points.
Explicit authored MMI profiles select Standard or Super hardware; disjoint ROM
helpers leave all analyzed code bytes identical. Authored firmware deliberately
has an unknown BIOS CRC; this is not a retail BIOS validation. Original endpoints
are retained losslessly and independently reviewed after closure.

Two actual managed payload generations each run 23 native instructions. Reordering
only numeric entries reuses all 30 compiled objects, preserves exact archived
annotation bytes and changes checkpoint context. Archive tampering refuses before
the compiler. Six previous pure/mixed ROM emission cases byte-match the prior
SDK across balanced/stable/shared layouts. Rondo TCP/checkpoints regress separately
using its existing observed module; they do not establish retail use of this new
declaration format. No external guest-clock, bus/device, hardware or whole-title
qualification is claimed here.

Mapping behavior was checked against [Geargrafx 1.8.4 memory mapping](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/memory.cpp),
[Mesen's pinned PCE memory manager](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceMemoryManager.cpp)
and [Geargrafx's MCP interface](https://github.com/drhelius/Geargrafx/blob/1.8.4/MCP_README.md).
These are semantic references; no incompatible reference implementation is copied.
