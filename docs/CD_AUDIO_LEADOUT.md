# Last-track CD audio boundaries

Track-mode D8/D9 addresses now recognize exactly the track immediately after
the attached TOC's last track as its leadout LBA. For a 25-track disc this is
BCD `$26`, rather than an invalid track lookup. No firmware service or
title-specific exception is involved.

D9 retains its inclusive end convention: leadout becomes `leadout_lba - 1`,
the final playable sector. Modes 1–3 retain their existing loop, completion and
immediate-status behavior; mode 0 retains its stop behavior. No source read
past the attached media is needed.

D8 has separate start admission. A start at or beyond leadout produces the
toolkit's existing CHECK CONDITION `$05/$25`, preserving the audio timeline
except for the normal command counter. The existing status/message profile
echoes `$02` in both bytes. The inspected Geargrafx profile instead returns GOOD
without starting playback. This difference is explicit, not exact D8 status parity.

Malformed BCD, unsupported addressing modes and tracks farther beyond the
immediately following boundary still stop explicitly. The reference cores
disagree on those cases; this fix introduces no blanket clamp. BCD `$99` remains
a valid last-track address, but track 100 cannot be encoded in one valid BCD
byte. `$AA` is not invented as an audio sentinel.

## Verification

Authored control tests cover normal/next-track and decimal boundaries, 99-track
limits, real port selection/CDB/ACK/status/message exchange, IRQ clearing and
retry after a rejected start. Typed checkpoint tests cover pending seeks,
paused resumes and playback across modes, timing profiles and output formats.
CORE state and future digital PCM must remain identical after restoration.
ABI 29 and checkpoint encoding are unchanged; ordinary source/binary identity
restrictions still apply across SDK builds.

A fresh headless original Geargrafx build covers 38 device cases, including
28 D9 cases with TOCs of 1, 2, 25 and 99 tracks. Known D9 stop, phase,
loop/completion and source-frame behavior agree. PCM also matches authored
literals. Raw engine clocks are retained separately, and the D8 status
difference above is explicit. This is emulator-reference evidence, not hardware
certification.

The [reusable TCP example](../examples/cdda-leadout/README.md) boots authored
firmware with a 25-track CUE, sends the last-track D9 shape that motivated the
fix, and checks compiled native/reference execution plus exact-build restores.
Its digital PCM checks use dummy/software drivers, with no physical-speaker or
GPU claim. No retail input is needed.

## Port adoption

Rebuild a consumer with the updated runtime to adopt the fix. Existing pinned
SDKs and running hosts are not changed automatically. Keep old checkpoints with
their original packages; unchanged ABI numbering does not grant cross-SDK state
portability. Actual game loader/audio routes still need qualification under
their new producer package. The original failed Ys III discovery route remains
failed until separately retested by that consumer.
