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
