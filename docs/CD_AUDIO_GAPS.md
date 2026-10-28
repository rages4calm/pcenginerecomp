# CD audio start admission at program gaps

The selected Gear-compatible `$D8` profile admits a new audio start only when
the requested in-range LBA belongs to a program track. An authoritative
`SectorProvider::program_track()` result with no track preserves the existing
audio state instead of starting a new seek into the gap. This is a shared
media/transport rule, with no title-specific addresses or firmware services.

The lookup distinguishes program admission from sample readability. A data
program is a valid start position even though its audio samples are silent.
Stored INDEX 00 audio can be readable through `audio_playable()` while still
lying outside a program range; requesting a new start there is ignored.
Virtual pregaps and postgaps are also non-program positions when the attached
provider authoritatively classifies them.

## Preserved state and controller response

For an ignored in-range gap request, the entire audio/source state is retained:
play/pause/stop state, start/current/end positions, drive head, seek origin and
deadlines, sector fraction, end behavior, source cursor, held/captured samples,
fader and DSP/cache/queue histories. No sector is read and no guest clock is
advanced by admission. The audio command epoch is unchanged because source
observers also use it to identify actual timeline mutations. The transport's
ordinary CDB/port diagnostics still describe the received request.
Accepted DD queries retain their existing command accounting; an ignored D8
does not represent a newly admitted audio-engine command.

The controller applies its separate decision:

| D8 mode | Existing seek | Immediate result |
|---|---|---|
| Zero (paused start) | None | GOOD status; existing audio state is retained |
| Zero | Pending | BUSY; the original seek remains pending |
| Nonzero (playing start) | Either | BUSY; no replacement seek is created |

A retained seek can complete BUSY normally. With no retained completion event,
an ignored playing start can remain BUSY indefinitely. This is an explicit
reference-engine quirk, not a fabricated successful seek. Finite diagnostics
must inspect that state and use their host wall/step bounds; the runtime does
not invent a guest deadline to escape it. Later `$DA` pause or `$D9` stop/end
commands operate on the retained audio state through their ordinary transport.

Unknown program-range metadata is different from a known gap. Metadata-only
TOCs and custom providers returning unavailable metadata retain the earlier
start approximation; they do not manufacture non-program classifications.
Unknown-with-index, out-of-range indices and indices inconsistent with the TOC
are rejected before changing audio state. Program data/audio starts retain the
existing fixed 150 ms seek profile.

The existing leadout policy remains distinct: D8 at or beyond leadout produces
the toolkit's CHECK CONDITION, whereas the pinned Gear controller returns GOOD
without starting audio. Invalid BCD/address forms also retain explicit toolkit
refusals. These controls are recorded as differences, not exact parity cases.

## Checkpoints and observation order

Runtime ABI **25** and the checkpoint core schema remain unchanged. The rule
reuses the existing provider lookup and audio fields. Exact-build identities
still prevent loading a checkpoint made by a different tool/runtime binary;
qualification creates fresh candidate checkpoints and restores them only into
the same build. [Developer checkpoints](DEVELOPER_CHECKPOINTS.md) retain pending
seeks and the complete source/DSP state on both sides of an ignored request.

Guest I/O uses `Bus::read`/`write` and retirement synchronization. Source
observers run on every `Bus::sync`, including a same-tick call with no new audio
sample, so an admitted command is observed before the next port operation can
replace its CDB. Low-level functional test helpers that call
`CdControl::audio_command()` directly must preserve that synchronization order
when PCM is enabled. Batching direct unsynchronized helper calls bypasses the
guest interface and is not evidence of a guest-reachable command race.

## Verification scope

The authored device suite checks all 256 D8 mode bytes, idle/playing/paused/
stopped states, retained seeks, six program-gap positions, LBA/MSF addressing,
data/audio program admission, known/unknown/invalid provider results, eventless
BUSY, retained completion and DA/D9 recovery. Separate clock-created fixtures
exercise pending seeks, active CDDA/ADPCM/PSG, filtered 48 kHz FIR histories and
fresh checkpoint restoration under Gear and legacy output timing. A same-time
bus-observation regression uses six source phases around a naturally finished
cursor and verifies the independently expected next audio sample.

Authored state/time-only continuation equality is internal evidence. Actual
independent reference results, source pins, raw event records and finite
retail TCP scope are reported separately in [STATUS.md](STATUS.md).

The original reference is pinned Geargrafx commit
`1c62a549328241518101f5be5bf3e6840b96ea5d`:

- [StartAudio admission and timeline changes](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_audio_inline.h)
- [D8 controller status/BUSY decision](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp)
- [Program-range track lookup](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_image.cpp)

Its GPL implementation is compiled separately for reference verification; no
implementation bodies are copied into the toolkit runtime. The chosen profile
does not establish hardware consensus, captured Q behavior or seek-time parity.
