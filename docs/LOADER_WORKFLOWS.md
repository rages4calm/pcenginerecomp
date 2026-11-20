# Loader discovery and portable consumer workflows

The loader, build and rewind workflows draw on gminustwo's RondoRecomp with
permission. The implementations use exact source guards and retain original
execution receipts. They support runtime ABI 29.
[RondoRecomp source](https://github.com/gminustwo/RondoRecomp/tree/c94048bc790f7b4680365721a84da9d567b68280)
· [Attribution](../licenses/RondoRecomp-notice.txt)

## Run a guest loader, then discover its RAM code

`sweep-loaders` runs a consumer-specified guest routine from an existing
**same-build checkpoint**. Independent passes start each group in a fresh owned
process from that checkpoint. Cumulative passes use one process and execute
groups in order. The consumer plan supplies the loader details for the title.

```sh
python -m pcerecomp sweep-loaders consumer/project.toml --build-dir consumer-build --checkpoint-dir .local/checkpoints --checkpoint baseline.pcec --plan loader.json --out .local/loader-reference
```

This JSON plan uses values from the
[original authored example](../examples/loader-sweep/README.md).

```json
{
  "format": "pce-loader-sweep-1", "schema": 1,
  "groups": [1, 2], "passes": ["independent", "cumulative"],
  "loader": {
    "pc": 59136, "mpr": [255, 248, 128, 129, 0, 0, 0, 0],
    "a": "group", "x": 0, "y": 0, "p": 4,
    "return_pc": 16128, "return_mpr_mask": 255
  },
  "snapshot": {
    "ranges": [[1048576, 65536], [2031616, 8192]],
    "code_ranges": [[1048576, 20]], "entries": [16384]
  },
  "limits": {
    "instructions": 2000000, "ticks": 20000000, "seconds": 60,
    "states": 10000, "contexts": 256
  }
}
```

Each A/X/Y selector accepts a byte or `"group"`. Each MPR accepts a byte or
`null` to preserve the current value. The return mask must bind the target PC's
MPR slot. Use distinct group bytes and allow at most 256 total epochs across
the selected passes. Specify finite work limits.

The driver writes a two-byte RTS frame to the RAM backing the stack, sets SP to
FD and seeds the declared PC, registers and MPRs through paused compare-and-set
commands. The wire journal records this developer assistance. A successful probe
reaches the return PC with the requested MPR mapping and SP at FF. These checks
establish the requested instruction boundary. Routine closure and natural game
progression require separate evidence.

Each successful window closes a repeated paused RAM snapshot and derives
bounded candidates from the explicit code ranges/entries. An ordered library
retains each distinct epoch and original package binding. Identical closed source
graphs share one library member. The sweep records every original call, snapshot
and epoch along with its `library_epoch` reference. Retired observations come
from the guest capture. Bound exhaustion, capture loss and faults fail
explicitly and leave partial work in the original journal.

Reference execution is the default. To qualify already translated loader code,
repeat with `--native` using that new native build's own checkpoint. Checkpoints
from a different generated package are not interchangeable.

### TCP instruction windows

The headless host exposes `write_cpu`, `run_until` and `reference_until`.
CPU edits require both reference and memory-write host opt-ins, an exclusively
remote quiescent pause and an exact 15-byte expected seed. The seed order is
PC little-endian, A, X, Y, SP, P, then eight MPR bytes. No counters are writable.

Instruction windows select a target PC/MPR mask and bounded instructions/ticks.
They stop at an instruction boundary after at least one retirement, independently
of the ordinary socket polling cadence. Terminal states distinguish `reached`,
`instruction_limit` and `tick_limit`. An exhausted window stays paused and is not
a successful return. Reference policy must be selected before dispatch, as with
existing reference-frame controls. Mutation, capture inspection and checkpoints
require the window to have stopped. Ordinary frame control rejects an active
window; `pause` cancels it.

The Python `DevClient.write_cpu()` and `run_until()` validate their inputs and
report exhaustion/timeouts as errors. Instruction windows are host policy, not
new guest checkpoint fields or a change to ABI 29.

## Feed real discovery back into a fresh consumer

```sh
python -m pcerecomp prepare-feedback prepare.toml .local/loader-reference/independent-0000/capture.jsonl .local/loader-reference/cumulative/capture.jsonl --out .local/feedback
```

`prepare-feedback` composes genuine supplied captures with the recipe's original
capture/profile/history. Declared, static-discovery and overlay roots remain a
separate source class. Original files and receipts are not overwritten. The
result is a new pinned consumer and an admission receipt with `compiled=false`
and `executed=false`; build it through the ordinary consumer interface and then
qualify the actual native executable. Selecting a capture is not evidence that
all code in the resulting module has run.

## Share handling of known immediate variants

Consumer recipes can set `operand_sharing = true` in `[module]`; emission commands
also accept `--operand-sharing`. The default remains off and preserves existing
emission bytes.

For immediate LDA/LDX/LDY, ORA/AND/EOR, ADC/SBC and CMP/CPX/CPY, admitted same-PC
byte variants can share one translated body that reads the live guarded operand.
Full PC, MPR, physical/source identity and the exact admitted byte cases still
control dispatch. **An unadmitted immediate still misses**, even when its opcode
has a shared body. There is no interpreter call per emitted opcode or wildcard
permission for future RAM contents. The manifest records
`exact_admitted_immediates_v1`; catalogue readers validate this capability.

All three partition layouts retain exact catalogue membership. The compiled
test covers 385 independently expected CPU/T/decimal/full-WRAM/cycle cases and
unknown-source refusal. An authored 2,816-key example reduces 2,816 bodies to 11
and generated C++ from 1,056,738 to 43,890 bytes. One concurrent-host Clang O2
object-build sample took 4.54 versus 0.65 seconds. This demonstrates that bounded
case, not whole-game build speed or runtime performance.

## Export a player-side source kit

```sh
python -m pcerecomp export-port-kit setup-profile.json --out .local/my-port-kit
python -m pcerecomp verify-port-kit .local/my-port-kit
python .local/my-port-kit/setup_port.py --out .local/player-port --compiler-root compiler-sdk --asset bios=player-bios.pce --asset disc=player-disc.iso
```

The profile (`pce-port-setup-1`) contains numeric source declarations, allowed
media hashes, asset placeholders, a finite baseline route and a loader plan.
The example generates its profile from original synthetic firmware/disc data.
Retail profiles belong to consumer projects. They must not contain game bytes,
captured code, private paths or owner saves. The toolkit does not download media,
install tools, find personal files or invent missing boot services.

Export copies the relevant source SDK, scripts/notices, numeric profile and a
launcher into a closed hash inventory. A Git-free SDK retains its exporter pin
in `pce-sdk.json` and recomputes its complete relevant source fingerprint. This
is a verified-byte snapshot with an asserted exporter revision, **not remote
authorship authentication**. The kit needs Python 3.11+.

For a supplied compiler SDK, add `--toolchain-root compiler-sdk` when exporting.
The entire explicitly supplied tree is copied byte-for-byte, including empty
files, executable permissions and notices. It must contain `bin/clang++`,
`bin/cmake`, `bin/ninja` (with `.exe` on Windows) and actual license notices.
Distribution rights remain the distributor's responsibility; the presence of a
license file is not an automatic license audit. No third-party compiler is
included in this source repository.

The launcher verifies the immutable kit, checks exactly the supplied known media
hashes before output writes, builds a numeric bootstrap consumer, runs the real
guest baseline and loader discovery, prepares feedback and compiles a native
consumer. Its receipt distinguishes executed discovery from the **as-yet
unqualified final native package**. This is a CLI source/setup foundation, not a
finished GUI installer or a universal one-click port generator. Output must be
outside the kit. The compiled package can be tested with the ordinary TCP and
same-build checkpoint interfaces.

## Compressed guest rewind for consumer hosts

`pce/rewind.hpp` supplies `pce::RewindTimeline(context_sha256, payload_bytes,
frames)`. `capture(bus, cpu, context)` stores the current encoded guest checkpoint
and reversible XOR/zero-run/literal transitions; `available()`, `bytes()` and
`peek(frames)` expose its retained history, and `restore(bus, cpu, frames,
context)` validates and restores before consuming that history. A new capture
after restore creates a new branch.

Context must match exactly. States are bounded to 16 MiB, history payload to
512 MiB and transitions to 108,000. The payload limit counts encoded checkpoint
and delta bytes, not allocator/container/hash-string overhead. An oversized
transition drops older history while retaining the bounded current state;
an oversized current state refuses. Digest, format and context mismatches
refuse. The existing checkpoint wire format is unchanged.

This API restores guest state only. The consumer host must reset presentation
and queued audio, manage input/replay cursors, and begin new capture/observer
epochs without presenting restored counters as new forward work. No rewind UI,
desktop hotkey, netplay rollback or transparent external-save rollback is implied.
Original variable-size codec, malformed packet, bounded history and encoded
CPU/RAM restore tests qualify this API.

## Qualification boundary

The authored workflow executes real CD reads, two RAM code sectors and four
independent/cumulative loader windows. Each native call retires 346,130 translated
instructions with zero interpreted work. Literal returned CPU, complete WRAM
and CD-RAM, source-library feedback and same-build references pass. Unmodified
Geargrafx independently matches all four CPU/MPR/full-RAM endpoints.

The separate Rondo TCP regression uses a guarded overlay/history module with
operand sharing enabled. It checks a bounded boot/file/introduction route and
same-build checkpoint forks; it does not qualify every retail loader group,
action gameplay, hardware timing or a whole title. Generic loader attribution,
broader indirect/asynchronous flow analysis and broader player/hardware
qualification remain open.
