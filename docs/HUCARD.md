# Base HuCard startup — ABI 18

HuCard and System Card startup are distinct hardware recipes. The base HuCard
profile maps a supplied cartridge ROM, initializes the named deterministic
reference state, reads its actual reset vector and executes guest code. It
supplies no BIOS, preloaded program, forced PC or firmware service.

## Explicit ROM input

```sh
build/pce-headless --hucard-reset base cartridge.pce 100000 30000000 hybrid --rom-header none --rom-encoding linear --video-output continuous
```

The SDL host accepts the same grammar and ordinary input, audio, TCP, capture
and limit options. All eight initial MPRs are zero; the vector at ROM offsets
`$1FFE/$1FFF` selects the logical entry. Initial A/X/Y/SP are zero, P is `$04`,
speed divisor is 12 and clocks are zero under `gear-deterministic-zero-v1`.
This is a reproducible emulator-reference policy, not an electrical power-on
or warm-reset claim. Startup metadata reports this initial state separately
from the final CPU and executed native/interpreted counts.

Dump interpretation is explicit:

| Option | Values | Meaning |
|---|---|---|
| `--rom-header` | `none` (default), `copier512` | Preserve all bytes, or skip exactly 512 opaque header bytes |
| `--rom-encoding` | `linear` (default), `bit-reversed` | Use each ROM byte directly, or reverse its eight bits independently |

There is no size-based header detection, padding, region-based conversion or
checksum database. Both options are rejected outside HuCard startup. Decoded
ROM data must be 8 KiB aligned, from 8 KiB through 1 MiB. The raw input hash
includes any declared header; decoded ROM identity is recorded separately.
Tests cover conversion independently. Gear comparisons use already decoded
authored ROMs and do not establish the dump-conversion policy.

## Selected memory map

ROM occupies physical banks `$00..$7F`. Storage aliases resolve to the original
ROM bank, while code captures and native guards retain the mapped physical
address, logical PC, full MPR context and exact instruction bytes.

| Decoded ROM | Physical bank `b < $40` | Physical bank `b >= $40` |
|---|---|---|
| 384 KiB / 48 banks | `b & $1F` | `$20 + (b & $0F)` |
| 512 KiB / 64 banks | `b & $3F` | `$20 + (b & $1F)` |
| 768 KiB / 96 banks | `b & $3F` | `$40 + (b & $1F)` |
| Other supported sizes | `b % ROM_bank_count` | `b % ROM_bank_count` |

This is the selected Geargrafx/Mesen standard compatibility map. In particular,
512 KiB cartridges have multiple physical board layouts; these formulas do
not certify a unique hardware decode. Loader patches advance every affected
ROM-alias generation, and native execution still checks current source bytes.

Banks `$F8..$FB` mirror one 8 KiB work RAM. Bank `$FF` routes base VDC/VCE,
PSG, timer, interrupt and controller ports. There is no CD RAM at `$80..$87`,
BRAM at `$F7`, CD transport or ADPCM. Absent memory reads return `$FF`; ROM and
absent-memory writes are ignored. HuCard `$1800..$1FFF` reads return `$FF` and
writes preserve the I/O latch. The controller's CD-absent bit is set. Base
PSG-only digital audio uses the existing mixer without enabling CD hardware.

`base` is an explicit board declaration. Populous RAM, SF2 banking, SuperGrafx,
Arcade Card and CD add-ons require separate profiles and are not implemented
by this mode. The tool does not infer those requirements from a title or CRC.
Existing unsupported video/bus semantics still fault explicitly.

## Analysis and native promotion

```sh
python -m pcerecomp hucard cartridge.pce --out .local/new-hucard --rom-header none --rom-encoding linear
python -m pcerecomp analyze .local/new-hucard/snapshot.toml --out .local/hucard-analysis.json
```

The first command writes private `mapped-rom.bin`, `snapshot.toml` and
`cartridge.json` with raw/decoded/mapped hashes, the selected map and reset
vector. Its output directory must be new. It neither boots a game nor treats
every ROM byte as executable. CFG discovery begins only at the vector; TAM
and unresolved indirect control flow retain their normal barriers.

For actual mapping contexts observed during bounded execution:

```sh
build/pce-headless --hucard-reset base cartridge.pce 100000 30000000 hybrid --code-capture .local/hucard-observed.json --capture-limit 65536
python -m pcerecomp emit-capture .local/hucard-observed.json --out .local/hucard-module
```

Captures and translated source contain cartridge code and remain private.
Emission is separate from compilation and execution. Guard misses, unseen
source and unsupported semantics remain visible; a sampled route does not
establish full-game native coverage.

## Consumer schema 1

Keep the usual pinned `[tool]`, `[module]`, `[runtime]` and `[limits]` tables.
Use runtime ABI **18**, a matching rebuilt module, and this startup recipe:

```toml
[boot]
mode = "hucard-reset"
profile = "base"
header = "none"
encoding = "linear"

[cartridge]
path = "private/cartridge.pce"
sha256 = "RAW_FILE_SHA256"
```

`[payload]`, BIOS, disc/TOC/libchdr and BRAM assets conflict with this recipe.
`runtime.cd_unknown_status` must be `fault`; normal audio and input-script
settings remain available. Verification pins the raw file and independently
checks typed initial metadata against the decoded vector and declared profile.
The runtime cannot attach CD/ADPCM to a configured base HuCard bus.

ABI-12 through ABI-17 observations remain valid offline inputs with their
original labels. Re-emit for ABI 18 and rebuild the module and runtime; old
binary objects are incompatible with the new bus layout. Snapshot and System
Card recipes retain their existing semantics. No persistent save/state
migration, live installation or owner-save discovery is introduced.

See [reference scope](REFERENCE.md#hucard-references---abi-18),
[consumer builds](CONSUMER.md) and [current verification](STATUS.md).
