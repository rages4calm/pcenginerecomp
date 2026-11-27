# Observed disc byte origins

Enable host diagnostics with `--disc-origin on` on the raw runner, or
`--disc-origin` on consumer `run` and `launch-plan`. Python callers can pass
`disc_origin=True`. Use scalar native execution with native span 1.

The observer records absolute cooked-sector byte offsets for supported
byte-preserving paths from CD READ DATA IN into RAM. An offset is
`LBA * 2048 + byte_index`. The read-only sector provider and normal CD
handshake still supply every byte. The recorder follows supported loads,
register transfers, stores, stack copies and block-transfer bus accesses.
Writes clear the previous destination origin before adding an established
new origin. Arithmetic and unsupported register effects discard metadata.

This design draws on Fabiano Gelain's MIT PCERecomp origin tracker.
The toolkit implementation uses its own runtime hooks and stores diagnostics
outside the serialized machine. [Reference implementation](https://github.com/Fabiano-Gelain/PCERecomp/blob/1b9d25ab1c099a405f1b1b0a6add67889db6cc02/runtime/cd/origin.h)

## Paused inspection

At a quiescent remote pause, request 1–256 bytes by physical address.

```python
report = client.disc_origins(0x100000, 32)
print(report["epoch"], report["offsets"])
```

The response includes schema 1, tracking epoch, address, length, observed
read/write counts and one offset or `null` for each requested byte.
The query uses side-effect-free RAM inspection. Source bytes must still match
the recorded value. Canonical RAM backing resolves supported WRAM mirrors.
ROM, device registers and RAM without observed ancestry return unknown.

A successful checkpoint restore starts a new diagnostic epoch. Existing
RAM origins become unknown and subsequent CD reads can establish new origins.
The checkpoint retains its exact guest machine state. Paused RAM edits erase
the affected tags even if the replacement bytes equal the old bytes. CPU
seeding also resets diagnostics. Ordinary runtime loads invalidate overwritten
ranges. Embedded hosts that modify backing storage directly must call
`DiscOrigin::invalidate` for that range.

Offsets describe observed byte ancestry within the bound process and media.
They are a separate report from paused RAM source graphs. Code admission still
uses complete PC, MPR and live source-byte guards. Tracking does not establish
unseen loader paths, full control flow or complete game coverage.
