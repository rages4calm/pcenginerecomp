# Consumer projects

A consumer keeps its game-specific source, assets, configuration and output in
its own repository. It selects the general toolkit as a pinned dependency.
The toolkit provides CPU translation, guarded dispatch, device models and
headless/desktop hosts. A consumer owns its entry/load recipe, media identities,
native coverage targets, campaign testing and any game-specific assistance.

The public contract is `python -m pcerecomp.project` (Python 3.11+), consumer
TOML schema **1**, runtime ABI **16**, and the existing `pce-dev-1` TCP protocol.
No Python package dependency, installation, download or save write is implicit.
Run the Python commands from the toolkit checkout, or put that checkout on
`PYTHONPATH`; descriptor paths always resolve relative to the descriptor file.

## Start with an authored example

The [consumer example](../examples/consumer/README.md) generates a six-byte
authored CPU program and native translation in a new private output directory:

```sh
python examples/consumer/prepare.py .local/consumer-example
python -m pcerecomp.project verify .local/consumer-example/project.toml
python -m pcerecomp.project build .local/consumer-example/project.toml --build-dir .local/consumer-build
python -m pcerecomp.project run .local/consumer-example/project.toml --build-dir .local/consumer-build --receipt .local/consumer-run.json
```

Build needs CMake 3.20+ and a C++20 compiler. Use `--generator Ninja` or an
available native generator. Explicit package/toolchain paths may be passed as
`--cmake-arg=-DCMAKE_CXX_COMPILER=...`, `CMAKE_MAKE_PROGRAM`, `SDL3_DIR` or
`CMAKE_TOOLCHAIN_FILE`. The interface does not fetch them. These paths and
configure/build commands appear in the build receipt; a controlled build
environment remains the consumer's responsibility. Build output uses at most
two parallel compiler jobs. Choose a new build directory for each build.

For a desktop build, add `--desktop` and provide the SDL3 package path if it
is not already discoverable. On Windows the selected shared SDL runtime DLL
is copied beside the executable and included in `output_files` hashes. The
consumer can start without the SDK's `bin` directory on `PATH`; a changed
packaged DLL is refused by the execution receipt guard. Imported target scope,
single/multi-configuration mappings and static SDL selection are handled
without exporting third-party targets globally. CMake 3.20 remains the minimum.
That packaging correction retained ABI 13 and descriptor schema 1. The current
compatibility upgrade requires ABI 16, regenerated modules, updated revision/source
pins and a new build receipt. Keep previous immutable qualification receipts.

### Verify a Windows desktop package

Build-time SDK discovery and runtime DLL discovery are separate checks. A
successful link does not prove the resulting consumer can start independently
of the SDK. Qualify a fresh desktop build as follows:

1. Pin an immutable toolkit revision and exact source digest, verify the
   descriptor, and build into a new directory. Check that `output_files`
   includes both the executable and its selected shared `SDL3.dll`.
   Freeze the consumer's toolchain pin before starting the test, including
   when selecting an explicit revision override. Keep revision, source digest
   and ABI values stable through both verification calls: changing the
   manifest mid-run can change the verifier's identity record even when the
   selected toolkit source has not changed.
2. Start the consumer from an empty working directory with a child-only
   `PATH` containing neither SDK runtime directories nor the packaged `bin`
   directory. Keep system paths needed by Windows; do not change the owner's
   environment. Record the exact child `PATH` and any removed SDL driver
   overrides.
3. Inspect the running process's loaded `SDL3.dll` path and hash. They must
   identify the adjacent DLL bound by the build receipt. An executable hash,
   clean `PATH`, or successful TCP connection alone does not prove that DLL
   was selected. Recheck the packaged files after execution.
4. Through TCP, check status, controller input, guest and presentation
   captures, pause/resume and clean quit. Use a paced audio-enabled run to
   check device-open state, accepted/drained PCM, bounded queue depth and
   pause-flush drops. Keep unthrottled, speaker-muted route replay separate
   from playback evidence. TCP status can precede the main-thread audio
   drain: generated-minus-submitted frames may still be pending in the
   8,192-frame source queue. Check that bound and zero runtime discard
   separately from the SDL queue; require zero pending source frames at
   settled and final drain boundaries.
5. Retain exact commands, process exit status, loaded-module evidence,
   unchanged input hashes and owned-child cleanup with the consumer's
   private qualification receipts.

The official `project run` command performs its own receipt checks and has a
maximum 600-second wall bound. A consumer may use a separately bounded TCP
supervisor for a longer route, with official `project verify` and `project
build` bindings retained; report that as a direct supervised execution rather
than an official `project run` result. Neither method establishes listening,
analog output parity or complete-game compatibility.

## Descriptor

All keys shown below are required, except the explicitly marked audio options. Unknown top-level or contract-table keys,
invalid types, unsupported versions, missing files and hash mismatches stop
before execution. SHA256 values are lowercase, complete 64-character digests.
`tool.revision` is a complete lowercase Git commit, not a branch or tag.
`MODULE_SOURCE_SHA256`, `MANIFEST_SHA256` and other uppercase strings below
are placeholders to replace, not accepted values.

```toml
schema = 1
name = "my-consumer"

[tool]
path = "../pcenginerecomp"
revision = "COMPLETE_40_CHARACTER_COMMIT"
source_sha256 = "TOOL_SOURCE_SHA256"
runtime_abi = 16

[module.source]
path = "private/generated/module.cpp"
sha256 = "MODULE_SOURCE_SHA256"

[module.manifest]
path = "private/generated/module.json"
sha256 = "MANIFEST_SHA256"

[payload]
path = "private/program.bin"
sha256 = "PAYLOAD_SHA256"
physical_load = 1048576
pc = 16384
mpr = [255,248,128,129,130,131,132,0]

[runtime]
tier = "hybrid"
video = "continuous"
cd_unknown_status = "fault"
joypad = 2
region = "usa"
multitap = "off"
# Optional; omit to retain the selected runner's audio default.
audio = "off"

[limits]
steps = 2000000
ticks = 100000000
wall_seconds = 60
```

An optional asset table is exactly `path` plus `sha256`. Supported table names
are `bios`, `bram`, `toc`, `disc`, `libchdr` and `input_script`. BIOS must be
262,144 raw bytes; initial BRAM must be 2,048 raw bytes. `libchdr` requires a
disc. Media geometry, TOC semantics and input-script contents retain the
runtime's validation; descriptor verification establishes their file identity.

```toml
[bram]
path = "private/initial-bram.bin"
sha256 = "BRAM_SHA256"
```

There is one initial contiguous payload, which must fit the existing standard
CD/work RAM loader. PC is logical 16-bit; all eight MPR bytes are required.
The module source and manifest are pinned independently. Manifest schema 1,
runtime ABI 16 and a positive emitted native-site count are required; optional
emitter provenance fields are retained in the hash-pinned manifest. Initial
payload identity does not identify every later overlay. Generated dispatch
continues to guard logical PC, complete MPR mapping and exact fetched bytes.
The descriptor does not bypass those checks or claim a later overlay is known.

New observed-module manifests contain `translation_units` and
`generated_headers`, each an array of `{ "file": "basename", "sha256": "..." }`.
Retain the complete generated directory. Verification pins every listed file
in the build and execution receipts, including a single-unit module. Both
arrays must be present if either is supplied. Names must be portable direct
children of the manifest directory; duplicates, symlinks, missing entries and
stale hashes are refused. Manifests are bounded to 64 MiB. Older manifests
without either array retain the single-source contract. Descriptor schema
remains 1. ABI 16 requires newly generated modules and a matching runtime;
pin the new tool revision and exact source digest when upgrading. ABI-12/13/14/15
observation captures remain accepted for regeneration; compiled ABI-12/13/14/15
modules/objects are not compatible with ABI 16.

Supported runtime values are `native|hybrid`, `snapshot|continuous`,
`fault|gear-good`, `2|6` buttons, `usa|japan` and `off|on` multitap.
`gear-good` is an explicit unknown-command *response* profile; it does not
implement the unknown command's operation. Native tier refuses uncovered
execution rather than silently using the interpreter. Hybrid coverage is
reported from actual native/interpreted retirements.
The optional `[runtime] audio` key accepts `on|off` and passes the explicit
runner setting. If omitted, desktop attempts SDL playback while headless keeps
PCM disabled unless WAV capture is explicitly requested. Audio production,
device-open success and physical/audible correctness are separate results.
The descriptor's `qualified` result does not establish audio parity. See
[AUDIO_OUTPUT.md](AUDIO_OUTPUT.md) for the digital profile and capture bounds.
Optional `audio_profile = "raw"|"filtered"` and integer `audio_rate = 44100|48000`
require explicit `audio = "on"`. They default to raw 44.1 kHz; raw at 48 kHz is
refused. Optional `audio_timing = "gear"|"legacy"` also requires explicit audio
on. The default is `gear`, with corrected sample-edge and PSG held-DAC timing.
Select `legacy` explicitly to compare against prior PCM baselines. For example:

```toml
audio = "on"
audio_profile = "filtered"
audio_rate = 48000
audio_timing = "gear"
```

The filtered profile adds a versioned `audio_output.processing` object and
reports PCM/WAV hashes in the processed output domain. Raw source counters and
the separately recorded raw mixed hash remain in the original 44.1 kHz domain.
Keep those contracts separate when validating an upgrade. Gear timing adds
`audio_output.timing = "gear-v1"`; legacy timing retains the prior PCM report
shape. Timing can legitimately change PCM and raw-source activity/hash fields;
compare against a fresh reference with the same timing rather than demanding
an old PCM hash. Descriptor schema remains 1. ABI 16 requires re-emitting
compatible captures and rebuilding modules and runtime together. No DSP history
snapshot/resume format exists.

Limits are 1..20,000,000,000 dispatcher steps, 1..2^64âˆ’1 master ticks and
1..600 wall seconds. A block-transfer instruction can consume many guest
cycles; steps are not a replacement for the tick/wall bounds.

## Upgrade a consumer to ABI 16

Pin the new exact tool revision and source digest, set `runtime_abi = 16`,
re-emit retained ABI-12/13/14/15 observations with their original ABI labels,
and rebuild all generated translation units and the runtime. Descriptor and
capture schemas remain 1. The current capture table records BRK's ignored
signature as a second encoding byte; older runtimes could not retire BRK.
No capture-window fields change.

Preserve the previous qualified project and receipts. Recheck every MPR,
source identity, guard, exclusion and generated source hash; ABI migration
alone adds no native coverage. The normal runners now map F8 through FB as
aliases of the same 8 KiB. Guest/device code using formerly missing sprite
IRQs may legitimately change execution. Full generation reports can also show
new F9/FA/FB updates after WRAM writes. Diagnose such differences against the
[explicit compatibility contract](COMPATIBILITY.md), rather than deleting
fields or forcing old hashes to pass.

TCP and final JSON add the bounded `cd_unknown` diagnostic object described in
that contract. It is additive evidence, not a new CD response policy. Keep
strict faults, known unsupported commands, inherited assists and actual
native/interpreted work visible. Check presentation-on/off guest behavior and
retain the selected audio profile/rate/timing. This batch introduces no state
restore or host-save migration.

## Upgrade a consumer to ABI 15

This retained procedure documents the earlier ABI-15 audio/latch integration.
Use the ABI-16 procedure above for the current runtime.


Preserve the previous source pin, generated module, build/run receipts and
qualified route before changing a consumer. Keep those artifacts immutable;
new qualification belongs in a new private directory. Reuse original media
read-only and keep guest BRAM volatile. This upgrade introduces no save-state
migration format.

Pin a clean toolkit checkout by complete revision and source digest, then set
the descriptor's `tool.runtime_abi` to **15**. Retained observation captures
from ABI 12, 13 or 14 remain offline compiler inputs: preserve their original
bytes and recorded ABI. Do not change a capture's ABI label to make it look
new. Regenerate from that capture with the new emitter:

```sh
python -m pcerecomp emit-capture PRIVATE_CAPTURE --out NEW_PRIVATE_MODULE
```

Repeat the original `--exclude-range ADDRESS:LENGTH` options and partition
settings where applicable. Retain every generated translation unit and header,
update descriptor module/manifest hashes, and build in a fresh directory.
Old compiled objects cannot be reused. Compare the new manifest's input
identity, mappings, exclusions and site counts with the retained generation.
An ABI-only regeneration should conserve translated operations and guards;
it does not establish new native coverage or require an artificial native gain.

Audio timing needs an explicit migration decision. ABI 13's former output
path corresponds to `audio_timing = "legacy"`; the ABI-15 default is `gear`.
To verify preservation of a prior filtered 48 kHz baseline, use:

```toml
[runtime]
audio = "on"
audio_profile = "filtered"
audio_rate = 48000
audio_timing = "legacy"
```

Then qualify `audio_timing = "gear"` separately. Keep the same route, inputs,
module, controls and assistance journal. Guest state, source identities and
native/interpreted work should remain conserved across the timing change;
PCM hashes and source-activity fields can legitimately differ. Gear output
must report `audio_output.timing = "gear-v1"`; legacy output omits that field.
For a fresh zero-phase Gear run at guest tick `t`, source frames equal
`floor(t*44100/21477273)`; filtered 48 kHz output frames equal
`floor(source_frames*160/147)`. Check these relationships at checkpoints,
alongside the full raw-source and processed-output diagnostics.

A useful migration matrix compares explicit legacy PCM against the retained
baseline, new Gear PCM across fresh headless and desktop hosts, and audio-off
guest/native behavior against the enabled runs. Keep each timing/profile/rate
combination distinct. Compare complete image hashes, checkpoint/end states,
source identities and execution counters; compare PCM/WAV only within the
appropriate audio contract. Host-only telemetry needs separate checks. A WAV
bounded to the opening cannot establish later gameplay audio equality;
whole-stream and checkpoint PCM hashes provide that additional evidence.
Cross-host agreement is runtime regression evidence, not an independent
emulator or hardware oracle.

If the retained baseline recorded a bounded code-capture window and the new
run does not, first validate the original capture, its actual start boundary
and retirement totals. Then compare through an explicit projection of that
known observation-only metadata. Keep guest/source diagnostics and execution
totals intact; a broad removal of capture-related fields can hide a mismatch.
ABI regeneration itself does not require another retail capture.

Consumer wrappers must forward and validate timing rather than relying on
defaults. Reject conflicting descriptor/CLI selections and duplicate timing
flags. Timing/profile/rate options require explicitly enabled audio. Preserve
historical qualifiers with their original assumptions; an ABI upgrade needs
conservation checks rather than weakening a previous native-gain requirement.

Use official `project verify` and `project build` bindings for each descriptor.
A short official `project run` smoke and a longer TCP-supervised route prove
different scopes; retain the 600-second command limit and disclose the
supervisor's separate watchdog. On Windows, qualify the packaged SDL DLL from
an empty working directory and sanitized PATH, then check TCP pause/resume and
input at paced execution. Device acceptance does not establish listening.

## Exact source identity and development overrides

```sh
python -m pcerecomp.project identity ../pcenginerecomp
```

This reports the current Git revision and a digest of exact source bytes.
The digest includes root `CMakeLists.txt` and `.py`, `.cpp`, `.hpp`, `.h` and
`.cmake` files below `pcerecomp/`, `runtime/` and `cmake/`, including untracked
files of those types. `__pycache__`, tests, documentation and external build
outputs are excluded. Paths are sorted by their relative POSIX names; each
digest input is UTF-8 path, NUL, decimal byte count, NUL, exact file bytes.
Line endings therefore matter.

Matching HEAD alone does not establish source identity. A relevant dirty edit
invalidates a previously pinned source digest. For reviewed development code,
the consumer may deliberately pin the exact current digest. If the expected
commit differs, `--allow-revision-override` is additionally required on every
verify/build/run command. The override is recorded and **never relaxes the
source digest or ABI check**. Without Git metadata an exact digest can still
be checked, but revision verification requires that explicit override.
An enclosing parent repository's revision is not used as an export's identity.

A source change between build and execution invalidates the build receipt.
Changes while configuring/building are checked again before creating that
receipt. Source changes during execution mark the execution unqualified.
These are integrity checks on a cooperative local workspace, not an atomic
snapshot of concurrently edited files or a signed supply-chain attestation.
For publication use an isolated, immutable pinned checkout/export.

## CMake embedding

For a consumer that already manages its own CMake build:

```cmake
cmake_minimum_required(VERSION 3.20)
project(MyConsumer LANGUAGES CXX)
set(PCE_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(PCE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(PCE_BUILD_REFERENCE_PROBE OFF CACHE BOOL "" FORCE)
add_subdirectory("../pcenginerecomp" "tool")
pce_add_consumer(my-port MODULE "private/generated/module.cpp"
  MANIFEST "private/generated/module.json")
```

`pce_add_consumer(target MODULE source [MANIFEST manifest] [DESKTOP])` compiles
the selected generated module and links the shared host/runtime.
Without an explicit manifest it discovers a sibling `module.json` when present.
New manifests select and verify every translation unit/header; the entry
source alone is insufficient for a partitioned module. Repeated consumers of
the same canonical module/manifest share one object library in that CMake
build tree. Standalone headless and desktop hosts also share this compilation.
For a custom host, `pce_add_native_module(objects MODULE source [MANIFEST manifest])`
returns the object-library target to link. There is no persistent compiler cache.
It does not copy either. `DESKTOP` requires `PCE_BUILD_DESKTOP=ON` and an
installed/discovered SDL3 package; Windows shared SDL is copied beside the
consumer executable. A direct CMake invocation is an embedding API, **not** a
replacement for descriptor verification or execution receipts. The Python
build command generates a minimal wrapper that performs both in order.
Embedded toolkit tests default off through `PCE_BUILD_TESTS`, independently of
the parent's `BUILD_TESTING`. A consumer can keep its own tests enabled without
building the toolkit's standalone runners or test suite.

The build receipt binds descriptor/tool/module/input identities to the exact
executable SHA256 and every regular file beside it (including a copied SDL
DLL). Before run, these hashes and the original descriptor are rechecked.
This does not hash the complete system dynamic linker/compiler installation.

## TCP automation and execution receipts

```sh
python -m pcerecomp.project run path/to/project.toml --build-dir path/to/build --receipt path/to/new-run.json --dev-port 0 --start-paused
```

TCP needs continuous video. Port 0 requests an ephemeral loopback port;
`PCE_DEV_PORT=...` is printed immediately on inherited stderr. Connect using
[`scripts/dev_client.py`](../scripts/dev_client.py): status, five input slots,
pause, frame-step, RGB capture and clean quit use the existing
[development-server contract](DEV_SERVER.md). Screenshot files, input actions
and TCP assertion results belong in the consumer's additional evidence.
`--memory-write` explicitly enables guarded paused RAM edits; it is off by
default and never bypasses compare-before-write/range/source invalidation.
Receipts retain the host's debug-write counters, so assisted tests stay visible.

Run arguments are passed as an argument vector with `shell=False`. Every run
has descriptor step/tick/wall bounds plus a host-process timeout. The receipt
uses a new path and records exact command, binary/input/tool identities,
exit code, elapsed time, timeout, unchanged-input checks, actual native and
interpreted retirements/fraction, and the complete final host diagnostic JSON.
A failed or timed-out run is not marked qualified. Input BRAM changes remain
volatile; the original BRAM image is checked unchanged after execution.
Native-site counts alone never count as executed native work.

Add `--code-capture path/to/NEW-private-capture.json --capture-limit 16384` to
record bounded observed instruction identities for the next offline emission.
The parent directory must already exist; capacity is 1..65,536. The execution
receipt validates capture schema, identity mappings and retirement totals,
then records its hash, byte size, observation count and completeness/drop
counters. A malformed/missing capture cannot qualify; a valid incomplete
capture explicitly retains its drop counts. This is an observation set, not
proof all reachable code was discovered. Keep capture bytes private and use
the toolkit's `emit-capture` command to produce another guarded native module.

The receipt's `qualified` flag means the checked host exited successfully,
reported valid work counters and retained its pinned identities. It does not
mean hardware accuracy, independent Geargrafx agreement, full campaign,
authentic reset, audible correctness or persistent save compatibility. Keep independent
reference evidence separate and describe its actual scope. Private retail
payloads, generated game source, captures and receipts must stay outside public
commits; only authored fixtures belong in public tests/examples.
