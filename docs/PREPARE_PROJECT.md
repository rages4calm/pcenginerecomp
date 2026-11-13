# Prepare a pinned native consumer

`prepare-project` turns an explicit recipe and admitted compiler inputs into a
new, verified [consumer project](CONSUMER.md). It handles original captures,
retained inline profiles, [content-addressed histories](OBSERVATION_HISTORY.md)
and [source-qualified declarations](DECLARED_ROOTS.md) through one supported
interface. It writes a translated C++ module, pinned consumer descriptor,
preparation receipt and, when observations are supplied, a self-contained history.

Preparation does not capture execution, compile, launch a host, download a
dependency, install anything, change media, write a save or promote a package.
The receipt explicitly has `execution_evidence = false`, `compiled = false`
and `executed = false`. Native instruction sites emitted are not native work
executed. Build and runtime qualification are separate steps.

For extended captures or an observed-history catalogue above 65,536 identities, select
`module.history_version = 2` and the explicit desired capacity. An existing v2
history can inherit its version/capacity when omitted. See
[larger-catalogue preparation and promotion](EXTENDED_CAPTURE.md).
Declaration and combined-union limits are separate. Pure declarations accept
no history version/capacity options.


## Independently verified declaration members

[Declared source sets](SOURCE_SETS.md) combine exact numeric members from
compatible boot assets into one guarded native module. Each member retains its
own source role, raw-file hash and mapping contract; media stays external.
Preparation, descriptor checks and managed archives bind the complete numeric
graph. Optional observation history retains its original execution provenance.
Automatic live CD overlay recovery remains open; runtime ABI 29 is unchanged.

## Declared RAM payload and firmware sources

The explicit [boot-source format](BOOT_SOURCE_DECLARATIONS.md) now admits standard
RAM payloads and Standard/Super System Card ROM through the same declaration,
emission, preparation and verification interfaces. Raw offsets, source-role and
load/profile bindings retain complete PC/MPR/physical/code identity. WRAM mirrors
and the Super RAM aperture are explicit; changed live RAM still meets dynamic
source guards. Old ROM declarations and ABI 29 remain unchanged. Automatic live
CD overlay recovery remains a separate gap; explicit composition is covered above.


## Prepare declared or mixed instruction entries

For source-qualified read-only HuCard entries, select `[module] kind = "declared"`
and `path = "roots.json"`, with optional `history_path = "history/history.json"`.
Keep the normal explicit HuCard-reset boot/cartridge recipe. The source image
and its profile/header/encoding must match. History version/capacity options
require an actual history input; a pure declaration creates no empty history.

Preparation copies the exact numeric file to `declarations/roots.json`, retains
any complete original history and binds both independently in the descriptor
and receipt. Media remains read-only at its original location. No declared entry
is relabelled as a capture hit. For [static-discovery](STATIC_DISCOVERY.md) outputs,
this declared-only path binds expanded roots. To also retain and admit the original
seed/derivation graph, select `kind = "discovery"` with the report/directory as
`path`. Preparation owns its exact three-file graph without a duplicate roots file;
builds and managed generations retain the extra binding. See
[discovery consumers](DISCOVERY_CONSUMERS.md), the [full declaration contract](DECLARED_ROOTS.md) and
[authored example](../examples/declared-roots/README.md).

## Use an explicit recipe

```text
python -m pcerecomp prepare-project .local/recipes/my-consumer.toml --out .local/prepared/my-consumer
python -m pcerecomp.project verify .local/prepared/my-consumer/project.toml
python -m pcerecomp.project build .local/prepared/my-consumer/project.toml --build-dir .local/build/my-consumer --generator Ninja
python -m pcerecomp.project run .local/prepared/my-consumer/project.toml --build-dir .local/build/my-consumer --receipt .local/runs/my-consumer.json
```

Create parent directories first and choose new preparation, build and receipt
destinations. Paths in a preparation recipe resolve relative to that recipe.
Generated descriptor paths resolve relative to the generated descriptor. Media
stays in its declared original location; only its path and identity are recorded.
Keep every media file and toolkit source pin stable through qualification.

This complete System Card recipe has no title-specific addresses:

```toml
schema = 1
format = "pce-consumer-prepare-1"
name = "my-native-consumer"

[module]
kind = "history"
path = "../history/base/history.json"
capacity = 65536
partition_layout = "stable"
partition_size = 256
native_span = false
exclude_ranges = []

[boot]
mode = "system-card-reset"
profile = "standard"

[bios]
path = "../inputs/system-card.pce"
# Optional lowercase full SHA256: when omitted, preparation computes and pins it.
# sha256 = "REPLACE_WITH_EXACT_SHA256"

[runtime]
tier = "native"
video = "continuous"
audio = "off"
cd_unknown_status = "fault"
joypad = 2
region = "usa"
multitap = "off"

[limits]
steps = 200000
ticks = 10000000
wall_seconds = 30
```

The paths above identify private inputs you supply; the toolkit does not ship
firmware. `module.kind` is exactly `capture`, `profile`, `history`, `declared` or
`discovery` and must match the admitted contents. The static input forms are described above.
For a history, `path` may name its index or its
directory. An original capture becomes a new stage-zero history. An inline
profile import preserves exact originals and its existing selection ledger.
A history import preserves the full admitted graph and stages. No new execution
is claimed and historical ABIs are not relabelled.

For observation inputs, `capacity` is optional. Legacy history v1 accepts
1 through 65,536 identities; opt-in v2 supports up to 1,048,576 under its separate
count/byte bounds. Omit it to inherit a retained profile/history capacity;
legacy raw captures use 65,536. Smaller capacity refuses an oversized observed
union rather than dropping identities. Declaration and combined-union bounds
remain separate; see [declared roots](DECLARED_ROOTS.md).

Partition layout defaults to `stable`, size 256. Stable layout requires size
256. Balanced and shared layouts accept sizes 1 through 4096. Opt-in
`partition_layout = "shared"` reuses entire identical guarded 64-PC helpers across
full MPR contexts and packs them into target-sized units; see [shared emission](SHARED_EMISSION.md).
It retains all source identities and original provenance. `native_span = true`
enables the optional generated span interface and requires stable layout. The recipe
has no single-unit option. `exclude_ranges` contains at most 256 pairs of
physical start and byte length, for example `[[1048576, 16]]`; instructions
touching any byte in an excluded range are omitted from emitted coverage.
The original history remains intact.

`tier = "native"` uses native-only execution and stops when an executed source
identity has no accepted translation. `"hybrid"` allows the existing interpreter
fallback and reports actual work separately. Choosing `"native"` is a requested
policy, not proof of complete coverage before the consumer executes.

## Boot and asset choices

A recipe selects exactly one `[boot]` or `[payload]` table. System Card reset
requires `[bios]`; `boot.profile` is `"standard"` or `"super"`. Optional
`arcade_card = "duo"` requires the super profile. Reset follows the declared
firmware's reset vector; preparation does not invent a title entry point or
bypass firmware interaction.

For HuCard reset, replace the System Card `[boot]` and `[bios]` with:

```toml
[boot]
mode = "hucard-reset"
profile = "base"
header = "none"
encoding = "linear"

[cartridge]
path = "../inputs/game.pce"
```

HuCard profiles are `base`, `sf2` and `populous`; header choices are `none` and
`copier512`; encodings are `linear` and `bit-reversed`. Board selection is
explicit. HuCard boot excludes CD/BIOS/BRAM assets and requires the fault policy
for unknown CD commands. See the [consumer contract](CONSUMER.md) for board and
media validation details.

For an explicitly loaded payload, omit `[boot]` and supply every entry field:

```toml
[payload]
path = "../inputs/program.bin"
physical_load = 1048576
pc = 16384
mpr = [255, 248, 128, 129, 130, 131, 132, 0]
```

Payload physical load is within `$000000..$1FFFFF`, PC is within `$0000..$FFFF`,
and all eight MPR bytes are required. These values are the consumer's declared
loading recipe, not inferred game addresses. Payload bytes and any supplied
media are hashed and verified.

The payload must be nonempty and fit entirely within standard CD/work RAM
(physical banks `$80..$87` or `$F8`); a physical address in the overall
21-bit range alone is insufficient.

Optional asset tables use the same shape as `[bios]`: required `path`, optional
`sha256`. Supported names are `bios`, `bram`, `toc`, `disc`, `libchdr`,
`input_script` and `cartridge`; the selected boot/runtime still constrains which
combinations are valid. A CUE disc pins its descriptor-plus-track identity
through the existing read-only CUE provider. Other assets pin their exact file
bytes. Optional BRAM is an immutable input snapshot; preparation does not create
a mutable persistence session.

Runtime options use the existing descriptor contract, including video
`snapshot|continuous`, joypad `2|6`, region `usa|japan`, multitap `off|on`, audio
`on|off` and the opt-in audio, VDC, native-span and CD profiles. The required
runtime fields are `tier`, `video`, `cd_unknown_status`, `joypad`, `region` and
`multitap`. Keep audio explicit when playback is outside qualification scope.
See [consumer projects](CONSUMER.md) for detailed profile compatibility rather
than assuming an option overrides media requirements.

Limits are finite: `steps` is 1 through 20,000,000,000, `ticks` is 1 through
`2**64 - 1`, and `wall_seconds` is 1 through 86,400. The project runner retains
its outer watchdog. See [finite sessions](SESSION_LIMITS.md).

## SDK pin and output contract

The recipe's SDK is the toolkit executing preparation. By default its current
Git revision, source digest and ABI are pinned into the generated descriptor.
The optional `[sdk]` accepts `revision` and `allow_revision_override` for an
explicit vendored or differently identified checkout:

```toml
[sdk]
revision = "REPLACE_WITH_40_LOWERCASE_HEX_COMMIT"
allow_revision_override = false
```

This is a template placeholder, not an accepted commit. Omit the entire table
for a normal Git checkout. A differing or unavailable Git revision needs an
explicit override and a full selected revision; exact source digest checks
remain mandatory. An override does not change the source digest, permit a
different runtime ABI, or establish compatibility. Later verify/build/run
commands need their own explicit override when the selected revision differs.

Successful output is:

```text
project.toml
prepare-receipt.json
module/module.cpp
module/module.json
module/<generated headers and partition units>
observation-history/history.json
observation-history/captures/<sha256>.json
observation-history/catalogue/<sha256>.jsonl
```

The descriptor pins generated artifacts, exact original history and media, and
the toolkit revision/source/ABI. Consumer verification readmits the graph and
checks its manifest membership. The receipt binds the original recipe and
observation source, generated descriptor, history index and verified consumer
inputs. Local receipts contain personal filesystem paths; keep them private.

Preparation refuses existing output paths, including symlinks. It admits the
selected observation format and declared assets before creating output, then
rechecks the input recipe, originals, all copied graph artifacts, media and
toolkit identity at closure. Invalid later options or I/O failures can leave a
partial **new** directory for diagnostics; existing destinations and original
inputs are preserved. Output is not an atomic transaction and partial output
must not be treated as prepared. A successful receipt is written last.
An output inside its original history graph is refused before allocation;
preparation cannot add unlisted content to that read-only closed graph.
Partition ranges, stable-layout size, exclusion count and finite numeric limits
are also checked before allocation.

## Python API and authored end-to-end proof

```python
from pathlib import Path
from pcerecomp.prepare import prepare_project

receipt = prepare_project(
    Path(".local/recipes/my-consumer.toml"),
    Path(".local/prepared/my-consumer"),
)
assert receipt["prepared"] and not receipt["executed"]
```

`prepare_project(spec_path, output)` returns a JSON-safe receipt and raises
`ValueError` or `OSError` on refusal. The dedicated module command is also
available as `python -m pcerecomp.prepare SPEC --out DIR`. Recipe format is
`pce-consumer-prepare-1`, schema 1; unknown keys and unsupported types refuse.
There are no hidden defaults for boot entry addresses, ROM discovery or package
selection.

The [authored native workflow](../examples/native-workflow/README.md) provides
the full sequence with no commercial media. It captures a guest-driven RAM
code change under identical PC/MPR identity, imports the retained baseline,
prepares and builds the official consumer, executes native-only, compares a
literal whole-RAM endpoint and proves an uncaptured third source variant
refuses without retirement. Its evidence is bounded toolkit qualification,
not a claim that any commercial title or complete campaign is certified.
