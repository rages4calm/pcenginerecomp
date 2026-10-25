# Explicit BRAM persistence

The toolkit offers opt-in persistent **2,048-byte CD backup memory** without
changing guest BRAM accesses or the runtime ABI. The default remains volatile.
Neither host discovers saves, formats memory, writes an installation directory,
nor bypasses System Card or game initialization. A new namespace starts blank;
only authentic guest writes can turn it into a formatted save.

## Raw host interface

Both hosts accept `--bram-out NEW_RAW_2048_FILE`. An existing CD/BRAM attachment
is required; the option does not add hardware. Existing `--bram INPUT` stays a
read-only seed. Export copies the lower 2 KiB of physical bank `$F7` directly,
even while the guest has locked that bank. It does not read guest ports,
unlock BRAM, advance clocks or alter source generations.

The output must be a new file in an existing directory, separate from every
input and output. The host writes a temporary file, flushes it, then publishes
the complete image without replacing an existing destination. Unsupported
instructions, guest faults, wall-time interruption and failed output
finalization do not publish BRAM. Step/tick budgets and orderly TCP/window quit
are eligible successful stops. Force termination cannot promise an export.
This is a raw export primitive, not automatic repeated saving or a save state.

## Consumer sessions

The checked consumer runner additionally accepts all three options together:

```sh
python -m pcerecomp.project run PRIVATE_PROJECT.toml --build-dir PRIVATE_BUILD --receipt NEW_RECEIPT.json --save-root EXISTING_SAVE_DIRECTORY --save-namespace player-one --save-contract LOWERCASE_SHA256
```

`save-contract` is the SHA256 of the consumer's documented mod/save-layout
contract. It is an explicit compatibility decision, not a compiler version.
The toolkit combines it with exact firmware/disc/TOC identities and the declared
System Card boot profile. Ordinary compiler rebuilds and expanded native
coverage do not invalidate a compatible save. Changed media, firmware, hardware
profile or save contract do. Consumers must change this contract when a mod
changes save interpretation; the toolkit cannot infer that from native code.

Sessions currently require explicit System Card reset boot. Descriptor `bram`
seeds and sessions are mutually exclusive: import/migration needs its own
reviewed policy. HuCard persistent RAM and emulator save-state formats are not
provided by this interface. Receipts and captures must be outside the save root.

The caller supplies an existing directory and a safe namespace. No default
owner path is selected. Each namespace has a persistent lock file and a schema-1
JSON envelope containing namespace, compatibility digest, payload digest and
exact base64 BRAM. Malformed, oversized, mismatched or damaged envelopes stop
before guest execution; they are never replaced with blank memory. Links and
non-regular entries are refused. The lock is held by the operating system,
released after normal exit or process termination, and coordinates all sessions
using that namespace even if their compatibility digests differ.

An existing save becomes an isolated read-only raw seed. The guest exports into
the session's private directory. The consumer runner commits only after a
successful eligible stop, verified boot provenance, unchanged pinned inputs,
runtime source/build outputs and any requested code capture. The initial seed
must also remain unchanged. Publication rechecks the previous envelope,
flushes the new envelope and atomically creates/replaces it. Exceptions or
unqualified execution do not implicitly commit. The receipt separately records
save-session identity and publication outcome; changing save contents are not
immutable descriptor assets.

## Library interface

```python
from pathlib import Path
from pcerecomp.saves import BramSession

with BramSession(Path("explicit-existing-directory"), "player-one", compatibility_sha256) as session:
    # Add --bram session.seed_path only when not None.
    # Add --bram-out session.output_path to the host command.
    # Run and qualify the consumer before explicitly publishing:
    metadata = session.commit()
```

The low-level caller is responsible for guest-run qualification. Exiting the
context never commits. There is no automatic save import, reset, recovery,
formatting or compatibility migration.

## Failure and reference boundaries

Atomic publication prevents observers from seeing a partially written envelope.
File data is flushed before publication. POSIX additionally flushes the save
directory; Windows does not claim power-loss durability of the directory entry.
A failure after publication cannot undo an already visible complete save.
Locks protect cooperating sessions; entry checks detect accidental external
edits, not hostile filesystem races. A receipt-write failure after publication
also cannot roll back a completed save. Keep ordinary backups for recovery;
this interface does not silently restore or delete user saves.

Geargrafx's pinned host code saves/loads the same raw 2 KiB backing storage
independently of guest protection. Its default reset preformats BRAM, unlike
this toolkit's deliberate blank reset. Its title-derived filenames and direct
output truncation are not adopted. Reference comparisons qualify guest memory
behavior and payload bytes; host atomicity, locking and identity rules are
tested separately. Persistence alone does not prove a game's SAVE/LOAD flow or
that its startup warning has disappeared.

## Queued VDC integration regression

`tests/test_queued_persistence.py` builds an entirely authored native System
Card consumer, without retail input. A real 128-word VRAM DMA blocks the CPU
VRAM read before guest code copies independently expected data into BRAM,
increments its counter and locks the device. Two actual consumer save-session
processes recover counter values 1 then 2 with exact 2 KiB payload/envelope
checks. A third volatile process restarts at 1 and leaves the saved envelope
unchanged. Each executes 200 native instructions, zero interpreted instructions
and zero guard misses, with 128 completed DMA words and nonzero VDC waits.
Windows execution uses the packaged runtime on a PATH without compiler/SDK
folders. The two persistent launches also produce complete, loss-free actual
ABI-labelled source captures.

The fixture's byte-counter layout is an authored test contract, not a System
Card filesystem or a retail game's save format. Authored translation metadata
is kept separate from actual execution evidence. This tests queued device work
alongside the existing persistence interface; it introduces no runtime ABI or
machine save-state format change.

## Retail guest SAVE/LOAD qualification

Queued VDC timing is separately exercised through a real game SAVE and LOAD
on a private copy of authenticated, BIOS-formatted blank backup memory.
Formatting is an explicit recipe prerequisite, consistent with the
[US game manual, printed page 12](https://www.tg-16.com/contributors/arjak/Ys_III/Ys_III.pdf).
This adds no automatic formatting or owner-save discovery to the runtime.
The test creates a new private slot, changes progress with ordinary combat,
then confirms LOAD and checks canonical RAM and the restored scene. A menu
preview can show saved HUD values before the load has actually happened;
menu appearance alone is not restoration evidence.

The finalized native/interpreter exports are byte-identical. Differences from
the blank seed describe changed byte positions, not a measured write count or
record length. Independent Geargrafx cases check semantic restoration using
their declared postboot seeds; their differing headers are not a byte-parity
oracle for the native BIOS-formatted image. See [STATUS.md](STATUS.md) for the
finite route and field values. Guest backup memory remains distinct from CPU,
video, audio and queued-access machine state; no emulator save-state format is
introduced by this qualification.

A separate fresh-process smoke test imports the successful SAVE run's raw
export through an explicit read-only seed, recognizes the created file and
restores its saved town progress. This supplementary run uses both native and
interpreted execution; it is not a cold native/interpreter parity qualification.
The export is produced at orderly successful quit under the existing host
contract. These tests do not establish disk publication at the instant of the
guest SAVE command, repeated autosaving or crash/power-loss durability.
