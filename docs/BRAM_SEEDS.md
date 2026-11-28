# Explicit first-run backup-memory seeds

A port can opt into a preformatted **2 KiB developer seed** for a new isolated
save namespace. The default remains blank/unformatted. An existing valid save
always takes precedence, including a saved all-zero image; a corrupt envelope
remains an error instead of being silently reformatted.

```sh
python -m pcerecomp.project run PORT/project.toml --build-dir BUILD \
  --receipt PRIVATE/run.json --save-root PRIVATE/saves --save-namespace port \
  --save-contract SAVE_LAYOUT_SHA256 --save-initial-bram formatted
```

The selected save directory must already exist. Supply the normal explicit
save/mod compatibility digest. The policy is available to embedded consumers as
`BramSession(root, namespace, digest, initial_bram="formatted")` and to
`project.run(..., save_initial_bram="formatted")`. Accepted policies are exactly
`blank` and `formatted`. The formatted choice requires an explicit complete
persistent session; it does not change ordinary host defaults or descriptor
BRAM assets. Persistent sessions still require System Card reset boot and reject
a descriptor seed, reference-enabled runs and checkpoint-loaded runs.

The initial image contains `48 55 42 4D 00 88 10 80` followed by 2,040 zero bytes,
SHA256 `7e631b4e463a04481939fde974cd341a1478af8c1f75350fd73c94a3430a0887`.
This matches the small initial layout in
[Beetle PCE](https://github.com/libretro/beetle-pce-libretro/blob/974fe085a9842be2069afc95beaf469a90e9ae44/mednafen/pce/huc.cpp#L30).
Geargrafx's [initial header](https://github.com/drhelius/Geargrafx/blob/03de98dcb94d83cec763959936463b06fc440c00/src/memory.h#L161)
instead advertises `$A000`. This explicit option does not claim exact Gear
header parity or factory hardware contents. Thanks to
[Arthur's proposal](https://github.com/rages4calm/pcenginerecomp/issues/53) and
[RetroRecomp](https://github.com/ArthurReboulSalze/RetroRecomp) for identifying the
port-startup use case.

Entering a session only creates a private read-only seed, not a saved envelope.
`project.run` publishes only after a qualified orderly configured run; direct
`BramSession` callers own qualification and must call `commit()` explicitly.
The existing locks, compatibility checks, atomic publication and failed-run
preservation remain unchanged. Receipts distinguish the requested `initial_bram`
policy, actual `seed_origin` (`blank`, `formatted` or `saved`), actual
`seed_payload_sha256` and `previous_payload_sha256`. A new formatted seed is
never labeled a previously persisted save.

The policy is intentionally absent from save compatibility identity so changing
it cannot invalidate or replace an existing compatible save. The actual input
bytes still bind the host's checkpoint identity; choosing a different initial
image does not grant state portability. This is not authentication of a game's
SAVE format or a migration service.

The [authored consumer example](../examples/bram-session/README.md) tests complete
guest BRAM readback, native/reference TCP execution, checkpoint suffixes, explicit
native export/commit/reopen and refusal without saved-data replacement. It uses
original reset firmware and synthetic media, never an owner's save or retail BIOS.
