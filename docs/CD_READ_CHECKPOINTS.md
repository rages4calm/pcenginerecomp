# CD READ checkpoint continuation

This qualification exercises checkpoints during an active CD READ command,
including acknowledgement and sector-buffer boundaries. It extends the
earlier checkpoint tests, which seeded partial transport fields directly.
The new reference path creates its pending states through CD port operations.
Retail input is not needed for the public fixtures.

## Transport and state contract

READ `$08` uses the selected bounded, read-only sector provider. A checkpoint
must preserve the partially received command, phase/signals, data latch,
response buffer and index, outstanding sector address/count, pending load and
automatic ACK deadlines, retained drive position, IRQ sources and counters.
Saving or restoring must not acknowledge a byte, fetch a sector, advance a
clock or complete an event.

The restoring process constructs its own provider through normal checked
configuration. The decoded machine binds to that provider; it never restores
a pointer or file/decompression cache from the creating process. Buffered
response bytes belong to the checkpoint. Later sector loads use the newly
configured provider at the retained address and deadline.

The fixture distinguishes accepted data from pending data: a held ACK can
remove REQ while retaining the already sampled byte; the falling edge can
present the next byte. Reading the automatic-ACK port samples the old byte
before starting its pulse. An occupied response buffer postpones another
sector load. Reset and command reselection have their own cancellation rules;
restoring must not resurrect work those operations discarded.

Checkpoint schema **1**, runtime ABI **26** and exact-build restrictions remain
unchanged. A new executable, module, media identity or runtime profile requires
a newly qualified checkpoint. These tests add no cross-build state migration.

## Independent reference and fixture boundaries

The original Geargrafx reference remains separately compiled from pinned
commit `1c62a549328241518101f5be5bf3e6840b96ea5d`. Its original transport code
is used without transplanting its implementation into the toolkit. The
transport implementation and inline-header Git blobs also match upstream
`16417e983c5b47ab8358ee91f75c155f208391a7` checked on 29 October 2026.
See the [original reference source](https://github.com/drhelius/Geargrafx/tree/1c62a549328241518101f5be5bf3e6840b96ea5d/src).

The comparison is an explicit emulator profile. Host-supervised device waits
and port operations do not establish electrical bus phases, distance-dependent
drive timing, hardware correctness or cross-core CPU retirement parity.
Independent authored values are required in addition to agreement between
toolkit execution paths. No reference-emulator checkpoint is imported.

## Verification record

The direct-device suite creates its pending states with actual port commands,
then checks **616,524 expectations across 40 cases**. It covers manual and
automatic acknowledgement, pending first/next sector loads, an occupied
buffer's retry, a separately retained final data byte, reset/reselection,
partial command ACK/REQ, STATUS-to-MESSAGE and bus release. It checks literal
payload bytes, absolute event deadlines, provider LBA order and calls, pure
save/load, destination provider binding and transactional rejection. These
fixtures retire **zero guest instructions**; both stored CPU speed values are
tested as checkpoint metadata.

The separate original-reference pipeline uses host-supervised real guest
LDA/STA operations in native and interpreted toolkit execution. The supervisor
selects the authored PC/accumulator and clock waits explicitly. This establishes
port-operation continuation, not an autonomous guest program or original-Gear
CPU execution. Per-source captures preserve logical PC, all eight MPRs, physical
fetch addresses, bytes and actual execution-tier hit counts.

Its 32-case matrix crosses eight cut points, manual/automatic DATA IN ACK and
both CPU divisors. The cut points are partial command, pending first load,
mid-response REQ, the actual instruction-end ACK state, the last first-sector
byte retained across another buffer fill, occupied-buffer retry, held reset
and reselection. At slow speed the automatic ACK pulse has already expired
when the read instruction ends; the literal expectations require that state.
They do not label it as a held ACK.

Toolkit cut expectations include phase/signals, ACK, buffer position, pending
sector work, relative deadlines, head, IRQ, partial command, data latch and
retry/read counts, plus the full paused fetched-source identity. Original
Gear supplies a separate live cut observation and payload/status/message
result. Its observer executes **zero guest CPU instructions**. The original
core's checkpoint format is never loaded into the toolkit.

Six authored port-instruction sites actually retire. The static CFG also
compiles six terminating branch loops, which are not executed by this
supervisor; their presence is compilation evidence only. The paused cut source
is inspected with pure code peeks, separately from retired-source captures.

Fresh reference execution from frozen implementation
`235b7ee74c2eb8585396c971e165327ec0d4aa0e` passes all **32 cases** and **64 fresh
restores**. The toolkit retires **443,710 native** and a separate **443,710
interpreted instructions**, with zero fallback in the native runs. Per tier,
that total includes 17,506 creating-prefix instructions, 213,102 uninterrupted
suffix instructions and 213,102 newly executed restoring-suffix instructions;
the imported prefix is never counted as fresh work.

There are **562,952 independent literal checks**, **160 execution joins**
(32 original-reference and 128 toolkit processes), **1,182 artifact bindings**
and **130 verified original Git blobs**. The auditor refuses **10 written
altered receipts**, then requalifies the preserved original. It reconstructs
the authored ROM/header/media and deterministically re-emits the trusted
fixture in a temporary directory to check the static module. It does not run
a guest during that audit.

All actual execution stderr must remain empty. Successful build diagnostics
are retained and hashed, with successful process results required; a CMake
object-path warning is not a guest error. The first frozen reference attempt
completed execution but failed the earlier auditor's empty-build-stderr rule. Its failed
audit epoch remains preserved. The corrected frozen pin has a separate fresh
execution, not a relabeled earlier run.

Runtime ABI **26**, relevant source count **78**, relevant-code SHA-256
`8b83f573f36dc00e3e84cf81302854d9ba7eafdcdc3389f6fecd2e6bbbc1ce0f`.
The digest differs from the prior batch because CMake adds a required test
target; runtime/emitter source remains unchanged.

The test-only follow-up `b2f45bef5545e2926080a44cc24874c36fa8e5ee` corrects an
existing runner test's expected suite count. Its full required
`python scripts/check.py` passes **1,194 Python tests without skips, 61 C++
suites and 12 fresh-process audio cases**, including both SDL dummy-host suites.
The native binaries were freshly built from `235b7ee`, with identical native
source, CMake and relevant-code identity. The earlier count-assertion failure
is preserved separately; it is not relabeled as a passing full run.

The separate retail regression uses the previously bound ABI 26 diagnostic
executable. It creates a new exact-build checkpoint at the established street
dialogue and compares a bounded ordinary-input continuation with two fresh
restoring processes. All three endpoints reach frame **23,735**, with the
dialogue dismissed and HP 20. Each restored 424-frame segment executes
**13,546,923 new native instructions and 36 interpreted instructions**. It
imports a separate prefix of **674,792,526 native and 28 interpreted
instructions**. Guest/device/PCM status, source identity, work RAM and pixels
match at the retained observations. Raw response IDs, SDL presentation
telemetry and checkpoint provenance differ legitimately; provenance counters
are separately checked against cumulative work.
This is a finite continuation test, not complete Ys III migration or campaign
qualification. These tests leave the consumer's selected ABI 18 package
untouched; its separate combat work does not qualify this ABI 26 migration.

See [developer checkpoints](DEVELOPER_CHECKPOINTS.md),
[state-aware TCP routes](STATE_ROUTES.md), [CD transport](CD_CONTROL.md) and
[current status](STATUS.md).
