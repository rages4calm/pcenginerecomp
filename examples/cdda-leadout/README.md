# Last-track CD audio through TCP

This authored example has one MODE1 data track and 24 short stereo PCM tracks.
The final audio track is 25, begins at LBA 50, and ends at leadout LBA 52.
Fixture firmware sends D8 to track 25, drains its response, then sends D9 to
BCD track 26 using guest port writes and ACK handshakes.

```sh
python examples/cdda-leadout/workflow.py create .local/cdda-leadout-example
python examples/cdda-leadout/workflow.py qualify .local/cdda-leadout-example --generator Ninja
```

Add compiler, Ninja and SDL paths using repeated `--cmake-arg=...` when needed.
Qualification builds hidden desktop consumers with SDL dummy video/audio and
software rendering. It does not use the physical GPU or speaker.

Reference discovery genuinely executes all three modes and records source
identities. The native consumer must execute those routes with zero interpreter
fallback. Mode 1 keeps looping the last two sectors while BUSY; modes 2 and 3
stop at the final sector and drain their appropriate GOOD replies. The
controller seeds a checked data-mode byte and release gate; guest code and
media are never patched.

Each route saves a checkpoint with the leadout command admitted. Independent
fresh native/reference hosts restore an exact byte copy under the same producer.
Paused WRAM, guest RGB and statuses must agree, with only execution counters
and documented transient presentation/WAV-history differences projected.
Complete canonical HOST and CORE reports compare cold endpoints, ignoring
exactly four named CORE tier counters. Digital stereo WAV data must match
between tiers, and restored output must equal the uninterrupted suffix.

This is a bounded internal authored workflow, not retail-game migration,
hardware timing or physical-output qualification. See
[address and compatibility boundaries](../../docs/CD_AUDIO_LEADOUT.md).
