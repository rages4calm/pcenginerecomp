# Qualifying native CD startup

CD consumers use the same translated-operation compiler as HuCards, with an
explicit System Card/disc recipe. Firmware startup and CD-loaded RAM overlays
must both be covered. One PC or physical bank does not identify an overlay:
keep every logical PC, full MPR mapping, fetched source address and byte variant.
Never replace firmware with an invented successful service to make startup pass.

## Capture and build

Build the toolkit and start a fresh headless host with your own immutable inputs:

```text
build/pce-headless --system-card-reset super private/system-card.pce 1000000000 15000000000 hybrid --disc private/game.chd --libchdr private/libchdr.dll --video-output continuous --audio-output off --joypad-region japan --dev-reference on --dev-port 0 --dev-start-paused on --wall-seconds 300 --code-capture private/startup.jsonl --capture-profile extended --capture-limit 262144
```

Use `.exe` on Windows and the correct decoder library for your platform. Select
region, hardware, firmware, media and bounds deliberately; the example values
are a finite test recipe, not defaults for every CD game. Supply libchdr only
where the chosen media provider needs it. Create output parents first and use
new output names. Capture/log/recipe paths are private, never public artifacts.

The owned process announces its TCP port on stderr. Use `DevClient` for a finite
recorded input/frame schedule, choosing `advance(..., reference=True)` before
the first dispatch. Each advance accepts at most 600 frames; split longer waits
explicitly. Firmware prompts, game menus and input sampling are guest behavior:
a transport ACK alone does not prove a menu action or playable character movement.
Require a complete original capture with zero lost/unreadable retirements and
preserve the input hashes, producer, input sequence and actual tier counters.

Prepare a native consumer from the capture using a recipe such as:

```toml
schema = 1
format = "pce-consumer-prepare-1"
name = "my-native-cd-window"

[module]
kind = "capture"
path = "startup.jsonl"
history_version = 2
capacity = 262144
partition_layout = "balanced"
partition_size = 512

[boot]
mode = "system-card-reset"
profile = "super"

[bios]
path = "system-card.pce"

[disc]
path = "game.chd"

[libchdr]
path = "libchdr.dll"

[runtime]
tier = "native"
video = "continuous"
audio = "off"
cd_unknown_status = "fault"
joypad = 2
region = "japan"
multitap = "off"

[limits]
steps = 1000000000
ticks = 15000000000
wall_seconds = 300
```

Run [preparation](PREPARE_PROJECT.md), then the official [consumer builder](CONSUMER.md).
Both bind the actual toolkit revision and source digest; do not repin a successful
receipt to later code. Captures retain their original provenance, and preparation
owns a complete observation history. A compiled module is not execution proof.

## Compare actual work and state

Use [validated launch plans](LAUNCH_PLANS.md) for two fresh processes of the same
candidate: explicitly selected interpreter reference and native-only execution.
Replay the same cold schedule without importing an older executable's checkpoint.
Compare the complete original source keys and per-key hit counts under the
explicit [encoded tier relation](RAW_AUDIT_INTEGRATION.md), not live source IDs
joined by array index. Native success needs positive native retirements, zero
interpretation and zero guard misses throughout the declared window.

Retain paused status before and after memory inspection and use
[paused observation validation](PAUSED_OBSERVATIONS.md). The additive
[`read_memory_block`](DEV_SERVER.md) command reads at most 65536 RAM/ROM bytes
per request. Work RAM occupies physical `$1F0000..$1F1FFF`. Under the super
profile, CD RAM occupies `$0D0000..$10FFFF`; inspect it in four bounded blocks.
Do not apply that map to other hardware profiles without checking their mapping.
These reads do not acknowledge MMIO, unlock BRAM, change source generations or
advance guest clocks. Multiple requests still need a quiescent interval; they
are not a transaction or a replacement for before/after status evidence.

Compare actual CPU/MPR/device/raster fields, selected memory and completed RGB.
Name every omitted transport/policy field. Per-tier counters remain independently
checked even if their sum is used to compare execution state. Recorded interpreter
endpoints are internal expectations, not independently authored retail literals.
Completed-frame capture may lag current input; inspect actual scene/action evidence.

Save a candidate-owned [checkpoint](DEVELOPER_CHECKPOINTS.md), then launch fresh
reference/native forks of that exact build and replay a finite suffix. Check the
same origin digest/prefix and newly executed work separately. Same ABI alone does
not authorize migration across binaries, source pins or media identities.

## Scope of the current retail check

The expanded private Japanese Rondo window covers authentic System Card reset,
disc startup, opening scenes, title, normal file creation and new-game introduction.
It executes 404,669,933 native instructions, zero interpreted work and zero guard
misses, matching 25,621 full source identities/hits. Seventeen paused stages agree
with the generic-host original and a same-candidate reference on compared state,
all 8 KiB WRAM/all 256 KiB CD RAM and completed RGB. Own-build checkpoint forks
each execute 59,672 instructions and match 753 source identities. Host audio is off.

The first strict boot-to-title window is separately qualified. Starting a new game
then reached a firmware drain/recovery path sending `$FF`; the strict exploration
stopped and remains a failed receipt. For the expanded cold capture and both
candidate runs, change the recipe and capture flag to `nec-invalid` explicitly.
That existing [error-response profile](CD_UNKNOWN.md) frames ten actual bytes and
returns CHECK CONDITION/sense. It supplies no supported `$FF` operation or guessed
firmware service. The expanded route records one rejected packet, no GOOD shortcut,
33 READ commands/373 sectors and no read errors. Do not mutate a qualified recipe
or reuse its checkpoints across this profile change: prepare a new candidate and
capture its own cold reference/native route.

These are finite internal compiler/runtime parity results. Separate fresh Geargrafx
fixtures qualify selected settled CD-control, SCSI, TOC and VDC behavior; rebuilt
original Gear/Beetle invalid-command fixtures retain their explicit raw differences.
They do not establish external Rondo timing/picture or hardware parity. This is
not a finished port, campaign, playable-character/combat, save/load or audio-quality
qualification. Later direction/attack/jump input windows still show introduction
scenes; transport acceptance alone is not action proof. Runtime ABI 29 and guest/
checkpoint payload semantics are unchanged. See [status](STATUS.md) for the producer.
