# CD audio control and position timeline

This document describes the functional CD-DA command/position profile, with
a clocked drive state and fader. Separately enabled [digital audio output](AUDIO_OUTPUT.md)
reads actual CDDA sectors, mixes PSG/ADPCM/CDDA PCM and can supply SDL playback
or bounded WAV capture. Control/timeline success alone does not qualify music
playback. Input media remains read-only; a TOC alone supplies no samples.

## Commands and addressing

The ten-byte commands `$D8` (start position), `$D9` (end position), `$DA`
(pause) and `$DD` (position Q response) use the existing command/ACK transport.
They require attached, validated TOC metadata; a missing medium produces
CHECK CONDITION `$02`. No track positions or payload bytes are synthesized
from a title-specific address.

For D8/D9, CDB byte 9 bits 6–7 select the position form:

| Form | Address |
|---|---|
| `$00` | Unsigned 24-bit LBA from bytes 3, 4 and 5, most significant first |
| `$40` | BCD absolute minute, second and frame from bytes 2, 3 and 4; subtract the 150-frame lead-in |
| `$80` | BCD track number in byte 2; use that track's INDEX 01 LBA, with track zero selecting LBA zero |

Malformed BCD, seconds at least 60, frames at least 75, lead-in addresses,
unrepresented tracks and form `$C0` fault explicitly. D8 at or beyond leadout
returns CHECK CONDITION. Geargrafx instead ignores that invalid D8 with GOOD;
this stricter input response is a documented difference.

D8 sets start/current position, resets the sector fraction and chooses PAUSED
when byte 1 is zero or PLAYING for any other value. Its default end is the
last sector of the disc. The transport enters BUSY (phase 8, BSY asserted,
REQ/CD/IO clear) until the seek deadline; successful completion then produces
the ordinary GOOD status/IRQ handshake.

D9 byte 1 selects end behavior. Mode 0 stops the timeline and returns GOOD.
Mode 1 sets a looping end and keeps the transport BUSY. Mode 2 sets an end
which stops and produces GOOD status when reached. Mode 3 sets a stopping end
and returns GOOD immediately while the timeline continues. Other modes fault.
The requested end clamps to the final sector of the disc. A paused timeline
resumes after a separate playback delay. DA pauses at the current sector,
cancels sector progression and returns GOOD.

## Clock and completion contract

Seek latency is a deterministic **150 ms profile**, or 3,221,590 master ticks.
It deliberately differs from Geargrafx's distance-dependent seek model and
its separation of seek/status from audible playback. Resume from PAUSED uses
the source-corroborated 224 ms delay, or 4,810,909 master ticks. No hardware
seek timing or 44.1 kHz sample phase is claimed.

PLAYING advances at 75 sectors per second using a rational master-clock
remainder: a sector interval is 286,363 ticks plus accumulated remainder
48/75, for exactly 21,477,273 ticks per 75 intervals. PAUSED, IDLE and STOPPED
do not advance. The end sector is inclusive. After passing it, STOP becomes
STOPPED, LOOP returns to the original start, and IRQ becomes STOPPED plus
ordinary SCSI GOOD status. The latter asserts the existing status/message
IRQ source; there is no invented CD-audio interrupt bit.

Bus reset stops the audio timeline; starting a data READ selects IDLE.
Selection for a new command does not itself stop an established audio
timeline. Device events run at guest deadlines through the CD scheduler,
separately from host presentation. Counter overflow and clock regression
remain explicit faults.

## Position response and fader

DD schedules ten DATA IN bytes after 3,000 master ticks, using the same
manual/automatic ACK machinery as other bounded responses:

1. Audio state: PLAYING `$00`, IDLE `$01`, PAUSED `$02`, STOPPED `$03`.
2. ADR/control: `$01` for audio, `$41` for data.
3. BCD track number.
4. Index `$01`.
5. Three BCD relative minute/second/frame bytes.
6. Three BCD absolute minute/second/frame bytes, including the 150-frame lead-in.

During an active playing seek, DD reports PAUSED at the previous head
position. IDLE reports the data-read head; other states report the retained
audio position. Track selection uses attached INDEX 01 boundaries. Real
subchannel packets, pregap index-zero history and captured Q parity are not
provided by this TOC-based response.

Register `$180F` retains the full fader byte. Bit 3 enables fading, bit 1
selects ADPCM rather than CD-DA, and bit 2 selects fast rather than slow.
A write restarts the fade at the current CD clock. Gain decreases linearly
from 1 to 0 over 2.5 seconds (53,693,182 ticks) or 6.5 seconds (139,602,274
ticks). Disabled or unselected paths retain gain 1. The digital mixer applies
this gain to the selected decoded source; its fixed source gains are host
presentation policy, not the console's original analog levels.

CDDA PCM uses a separate source cursor to consume 588 stereo frames per sector
without duplicating or dropping source frames at rounded sector-clock edges.
Pause/resume preserves that cursor; seek, explicit stop, reset and READ idle
invalidate active playback appropriately. Audio stops and loops do not change
the guest control deadlines described above. See [AUDIO_OUTPUT.md](AUDIO_OUTPUT.md)
for read-only source classification, cache bounds and exact proof limits.

## References and evidence

Local authored expectations cover command modes, literal Q response bytes,
BCD/address validation, BUSY/seek transitions, rational sector cadence,
pause/resume, inclusive stopping/looping, status completion and all fader
bytes on both target paths. These expectations are independent of a live
emulator run. Completed independent-reference scope, where available, is
reported separately in [REFERENCE.md](REFERENCE.md).

The current suite has 7,134 checks including the explicit unknown-command
response policy. Unknown IDs fault by default. Optional
`--cd-unknown-status gear-good` selects the pinned Geargrafx/Mesen GOOD-response
quirk and records its use; known unsupported operations still fault. That
policy supplies no unknown command operation or hardware qualification.
Current retail menu-to-story evidence depends on this explicit profile.

The pinned [Geargrafx SCSI commands](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp),
[audio control/timeline](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_audio_inline.h),
[audio state](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_audio.h)
and [fader](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_inline.h)
provide the selected control behavior. [Mesen SCSI commands](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/CdRom/PceScsiBus.cpp)
cross-check addressing and responses. Exact seek/sample phase, physical
subchannel behavior and audible output remain outside this profile. The
implementation is original; no GPL audio implementation is copied or linked.
