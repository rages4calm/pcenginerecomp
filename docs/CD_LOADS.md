# Offline CD load declarations

An explicit CD load map supplies guarded native instruction identities before
every room or overlay has been visited. The map belongs to the consumer:
verified disc coordinates, direct-copy layout and instruction roots stay outside
the shared runtime. This is a separately typed static source, not a fabricated
paused RAM snapshot, boot payload, observed origin report or execution capture.

The v1 path supports ISO, supported BIN/CUE, and CD CHDv5 through an explicitly
selected libchdr. It reads cooked 2048-byte MODE1 sectors using the existing
media readers. CUE binds its complete component closure and composite image
identity. CHD uses disc LBAs, not compressed storage frames or hunk offsets.
The exact TOC must describe the original media, and CHD pins the selected
decoder. Media files remain external; copied declaration graphs and managed
archives retain numeric maps and digests rather than duplicated discs.

## Numeric map

The optional [shared RAM/CD analyzer](RAM_CD_ANALYSIS.md) expands explicit roots
through authenticated branches and bounded calls/returns. Its recorded policy
and data exclusions are rederived on admission. Without that opt-in, each root
continues to declare one instruction as described below.

An input `pce-cd-load-map-1` JSON object has these exact fields:

| Field | Meaning |
| --- | --- |
| `format`, `schema` | `pce-cd-load-map-1`, integer `1`. |
| `coordinate` | `disc-lba-mode1-2048-v1`: disc LBAs excluding the 150-frame lead-in. |
| `policy` | `explicit-contiguous-byte-copy-v1`. Other transforms are refused. |
| `media` | `format` (`iso`, `cue`, `chd`), complete `image_sha256`, exact `toc_sha256`, and `libchdr_sha256` only for CHD. |
| `groups` | One to 256 explicitly alternative load groups. |

Each group has a portable lowercase `id`, all eight `mpr` bytes, `loads` and
sorted unique `roots`. Each root is a logical PC declaring **one instruction**.
The reader derives its complete instruction length, physical fetch addresses,
bytes, load-relative offsets and cooked disc-byte offsets. It refuses a fetch
outside that group's authenticated copied bytes. There is no inferred routine
traversal, call closure, asynchronous IRQ closure or weak-pointer admission.

Each load has these exact fields:

| Field | Meaning |
| --- | --- |
| `id` | Portable lowercase identifier, unique within the group. |
| `lba` | Disc LBA of the first cooked sector. |
| `byte_offset` | Offset 0..2047 within that sector. |
| `sectors` | Exactly `ceil((byte_offset + length) / 2048)`, at most 33. |
| `length` | Number of contiguous bytes copied, 1..65536. |
| `destination` | Canonical physical RAM start. |
| `sha256` | SHA256 of the copied bytes only, excluding leading/trailing sector padding. |

Destinations must fit entirely inside standard CD RAM `$100000..$10FFFF` or
canonical WRAM `$1F0000..$1F1FFF`. Mirrored WRAM destinations are refused;
instruction fetches through WRAM mirrors retain their original full MPR and
physical fetch identities while finding bytes in canonical storage. Within
one group both copied source-byte extents and destination extents must be
disjoint. Multiple loads in that group may supply one instruction across a
boundary. Different groups can place different source versions at the same RAM
address; they are never merged into an imaginary simultaneous RAM image.

Group/load IDs are 1..64 lowercase characters beginning with a letter, followed
by letters, digits, `_` or `-`. There are at most 64 loads per group, 1,048,576
roots and 64 MiB of copied bytes across the full map. Numeric artifact graphs
are bounded to 64 MiB. The reader refuses audio sectors, gaps, incomplete data,
source changes, links/reparse inputs, missing MPRs, overlapping definitions,
wrong media or TOC and uncertain/extra fields. Decompression, relocation,
interleaving, ordered overwrites, Arcade/Super RAM destinations, file-table
inference, script pointers and guessed entries are unsupported in v1.

## Declare, emit and prepare

```sh
python -m pcerecomp declare-cd-loads private-map.json --disc game.iso --toc game.toc --out private-declarations
python -m pcerecomp verify-cd-loads private-declarations/roots.json --disc game.iso --toc game.toc
python -m pcerecomp emit-cd-loads private-declarations/roots.json --disc game.iso --toc game.toc --out private-module
```

Use `--libchdr PATH` for CHD. Generate the TOC with the existing `toc` command.
The declaration output contains `roots.json` (`pce-declared-cd-loads-1`) and an
exact copy of the original numeric `cd-load-map.json`. Admission rederives all
stored mappings and source identities from the original media; editing derived
facts or repinning a changed graph cannot skip that derivation.

`emit-cd-loads --history ORIGINAL_HISTORY_DIRECTORY` adds genuine observations
through the same admitted union used by other declaration formats. Static
roots have no invented hit fields. An overlapping observed identity retains
only its real historical hit counts. New native catalogue format 5 and the
`declared-cd-loads-abi29-v1` selection contract distinguish these sources from
boot images, source sets and live overlay libraries. Existing live byte guards,
unsupported-opcode handling and CPU/Bus ABI 29 remain unchanged.

For a normal consumer preparation recipe select `module.kind = "cd-loads"`,
point `module.path` to the declaration `roots.json`, and supply the actual
`disc`, `toc` and optional `libchdr` assets. Startup remains an explicit System
Card reset or payload recipe. A CD load declaration does not initialize RAM or
pretend to be that boot payload. Optional `module.history_path` binds real
history. Preparation, project verification, managed rebuild inputs and numeric
archives bind both declaration files and the external media closure.

Generic `declared-roots`, `emit-roots` and `native-gaps` also accept repeatable
`--cd-source disc=PATH --cd-source toc=PATH`, plus `--cd-source libchdr=PATH`
for CHD. `project.declaration_arguments(checked)` selects the exact verified
source arguments for generic catalogue admission and re-emission. The helper
does not itself perform new admission or grant checkpoint migration.

## Qualification and references

The [authored workflow](../examples/cd-loads/README.md) declares two alternative
CD sources before executing their original guest loader. It compares actual
CD READ RAM bytes with independent literal expectations and then exercises
native/reference and exact-build checkpoint routes. Separate CUE and optional
genuine CD CHD consumers run native/reference loader routes as well; their
reader, preparation, build and execution evidence remain separately reported.

For a retail game, cross-check a map against the actual original loader before
treating it as verified title coverage. Successful decoding is not evidence
that an arbitrary pointer is code, or that a declaration was executed. Branch,
mapping, return and write diagnostics remain explicit unresolved facts.

PCERecomp's [disc-map design](https://github.com/Fabiano-Gelain/PCERecomp/blob/1b9d25ab1c099a405f1b1b0a6add67889db6cc02/tools/recomp/pcerecomp/discmap.py)
informed this source class. Its file families and weak-pointer rules are not
automatically imported. This implementation uses this toolkit's own readers,
declaration admission and compiler; no peer source was copied. Numeric Ys I/II
loader knowledge is not reused as another game's facts.
