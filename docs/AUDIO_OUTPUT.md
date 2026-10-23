# Audio output

The runtime can produce **44,100 Hz signed 16-bit stereo PCM** from PSG,
MSM5205 ADPCM and read-only CDDA sources. The optional SDL3 host can play it;
both runners can explicitly capture a bounded WAV. Runtime **ABI 13** includes
the new synthesis, decoder and output state. Rebuild runtime and generated
modules together. This is a digital reference profile, not a qualified model
of the console's analog output circuit or a complete game's sound.

## Runner controls

Append these options to a valid payload/mapping/firmware/disc invocation:

```text
--audio-output on
--audio-out .local/new-audio.wav --audio-frames 44100
```

The second line requests at most one second of WAV data. Audio files contain
PCM format 1, two channels, 16-bit little-endian samples at 44,100 Hz. Each
frame is one left/right pair. The output must be new and distinct from every
input or other output. Capture does not replace, append to or modify inputs.
Create its parent directory first; the runner does not create directories.

| Option/default | Behavior |
|---|---|
| Desktop, no audio option | Generate PCM and attempt the default SDL playback device |
| Headless, no audio option | Preserve the audio-disabled reference path |
| `--audio-output on` | Explicitly enable synthesis; desktop device-open failures are fatal |
| `--audio-output off` | Disable PCM production and device output |
| `--audio-out NEW_WAV` | Enable headless PCM unless explicitly disabled; capture requires audio enabled |
| `--audio-frames N` | Requires WAV output; 1..5,292,000 frames, default 1,323,000 (30 seconds), maximum 120 seconds |
| Desktop `--unthrottled on` | Mute device presentation while guest-clock PCM generation and explicit WAV capture continue |

The WAV limit caps capture, not guest execution. Later samples are omitted
and `wav_truncated` records that fact. Headless PCM generation does not open
an audio device. When the desktop's implicit default device cannot open, it
prints `PCE_AUDIO_DEVICE_UNAVAILABLE=...` and reports `device_open=false`;
it does not claim playback succeeded. Explicit `on` refuses that failure.
Unthrottled execution can run many guest seconds per host second, so speaker
output is muted in that mode. `audio_output.fast_forward_muted` reports the
policy. Muted device submissions count as dropped presentation frames; they
do not change source-frame counts, WAV samples or guest timing.

Consumer schema 1 optionally accepts `audio = "on"` or `"off"` in `[runtime]`.
Omitting it retains the selected runner's default. See [CONSUMER.md](CONSUMER.md).

## Clock and presentation ownership

`Bus::enable_audio_output()` enables the digital path before guest clocks
advance. `AudioOutput::advance_to()` schedules output from guest master ticks;
host audio consumption never advances the guest. CD transport, ADPCM events
and PSG clocks are advanced in timestamp order. `drain()` returns interleaved
numeric `int16_t` samples and leaves guest time unchanged.

The runtime queue holds at most **8,192 stereo frames**. If a consumer does
not drain it, the oldest frames are dropped and counted. The SDL host accepts
at most **4,410 frames** of pending stream input, clears stale queued input
on pause/resume and reports submissions, drops, clears and queue depth. That
bound describes SDL input storage, not operating-system/device latency.
The SDL audio thread never accesses guest state or decodes a disc sector.

Each source contributes one third of its signed digital value. ADPCM is mono
and contributes equally to both channels; PSG balance and CDDA's stereo
channels remain separate. The existing CD fader is applied to its selected
source before summation. Fixed gains, integer truncation and clipping are
presentation policy; they do not claim the original console's analog levels.

## Digital sources

**PSG.** The selected centered HuC6280A profile clocks six waveform channels
at one PSG cycle per six master ticks, with waveform, DDA, stereo balance,
noise and LFO state. Digital output uses a fixed integer gain table. Noise
and LFO clocks have authored expected-value tests; the live MCP comparison
described below checks waveform phase, not their hidden state or PCM. The
legacy register-storage path remains available with synthesis disabled.

**ADPCM.** The existing nibble-consumption events now update an unsigned
12-bit accumulator and adaptive index. The accumulator wraps modulo 4096;
it does not saturate. The raw signed PCM getter is `(accumulator - 2048) * 16`.
Actual pending-play start and soft reset initialize decoder state; stop holds
it. Decoding does not change port timing, length, IRQ or DMA decisions. This
preserves the digital 12-bit value and does not emulate the chip's 10-bit DAC
or analog filter.

**CDDA.** `SectorProvider::read_audio()` returns one sector of 1,176 interleaved
signed samples: 588 left/right frames, 2,352 bytes. CHDv5 AUDIO payloads are
converted explicitly from big-endian words to host numeric values. Disc LBA,
four-frame-padded CHD storage and stored/unstored pregaps remain distinct.
MODE1 data reads continue to reject AUDIO sectors. ISO remains data-only.

`audio_playable()` separately classifies the selected Gear playback profile.
Main audio regions play; stored audio-track pregaps play only when preceded
by another audio track. Data, unstored gaps and nonplayable lead-ins generate
explicit reference-defined silence. An unsupported provider, changed source
or genuine decode error still faults; those failures are never muted to zero.
`CddaPcmCache` retains one sector and invalidates it when the provider or LBA
changes. It does not extend the provider's lifetime.

The output stream uses a separate digital source cursor so all **588 frames
per audio sector** are consumed once, including loop, pause/resume and finite
stop boundaries. Guest seek, command, sector and IRQ timestamps remain owned
by the existing control timeline. Exact alignment with a reference emulator's
resampler or original hardware sample phase is not claimed.

## Diagnostics and verification

TCP status and final runner JSON contain `audio_output`: enable state, rate,
channel count, generated frames, nonzero counts per source and mixed output,
peak, PCM hash, discarded queue frames, WAV frames/truncation and desktop
device/queue/mute telemetry. The hash uses little-endian signed sample bytes,
independent of host byte order. Nonzero energy or a matching hash is evidence
about digital data, not proof someone heard correct sound.

Focused authored tests cover source clocks, signed literals, endian/channel
order, CHD padding/hunk boundaries, gaps, cache identity, decoder vectors,
mixer scheduling and bounded host/capture behavior. The expanded and clean
SDL builds pass all 27 suites / 252 Python tests; the clean default build
passes 25 suites with six desktop-only skips among 252 discovered Python tests.
The focused checks and separate consumer qualification are in [STATUS.md](STATUS.md).

The independent Geargrafx 1.8.4 adapter is:

```sh
python scripts/pcm_reference.py --exe .deps/geargrafx-oracle/Geargrafx.exe --probe build/pce-pcm-probe.exe --out .local/new-pcm-reference
```

It creates authored BIOS/BIN/CUE data and owns an isolated portable emulator
configuration, save directory and child process. The verified run matches
**56 raw CDDA stereo pairs / 112 scalar samples**: 40 audio pairs and 16
data-track silent pairs. Comparison uses Gear's observed LBA and the preceding
generated sample index with the fader disabled; it does not assume aligned seek/sample phases.
Another **24 settled PSG waveform-index checks** match at frequencies 64,
127 and 512, with checkpoints safely between bus-access/oscillator edges.
All authored inputs remain unchanged and the owned child/configuration stop
and clean up. Gear's MCP exposes no raw PSG/ADPCM decoder samples, so this
run does not establish PCM parity for those sources or their final mix.

The paced SDL device check separately submits **930,219 stereo frames** over
approximately 21 guest-clock-paced seconds. The device opens, fast-forward
mute is false, the input queue returns to zero, and pause flushing accounts
for 1,032 dropped presentation frames. Peak pending input is 1,591 frames;
the runtime source queue discards none. This establishes device-stream
acceptance/consumption, not a listening or analog loopback result. The test's
owned process exits cleanly. See [STATUS.md](STATUS.md) for final batch scope.

The complete retained 93,735-frame assisted Ys III TCP route also passes
with audio enabled: all 25 guest images and every original final guest JSON
value remain exact against the previous full-native run. It generates
69,095,406 PCM frames with PSG, ADPCM and CDDA activity, peak 13,000 and zero
runtime queue discard. Its WAV retains the bounded first 1,323,000 frames
(5,292,044 bytes), with truncation explicitly reported. Device output is
intentionally muted during this unthrottled run; its source measurements are
separate from the paced device-stream result and independent Gear sample oracle.
It adds no new assistance, progression or campaign-completion claim.

The adapter uses CUE for the independent sample comparison. The CHD provider
tests use an authored decoder ABI double to isolate byte order and geometry;
that double is not a compression decoder. Analog filtering, antialiasing,
reference resampling, physical output correctness and complete retail sound
remain separate qualification work.

## Primary sources and licenses

- [Geargrafx 1.8.4 CDDA samples](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/cdrom_audio_inline.h),
  [CHD sample order/mapping](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/cdrom_chd_image.cpp)
  [playable-region rules](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/cdrom_image.cpp)
  and [PSG digital profile](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_psg_inline.h):
  GPLv3, used as an external oracle and behavioral reference; no implementation
  code is copied into this toolkit.
- [libchdr](https://github.com/rtissera/libchdr): BSD-3-Clause primary CHD format/
  decoder source. It remains an explicitly selected optional dependency.
- [OKI MSM5205 datasheet, pages 3–4](https://elektronikjk.pl/elementy_czynne/IC/MSM5205.pdf):
  the original decoder/DAC and wrap behavior, hosted by a document mirror.
- [SDL3 audio streams](https://wiki.libsdl.org/SDL3/SDL_OpenAudioDeviceStream):
  API documentation for the optional zlib-licensed SDL playback dependency.

These references establish provenance and scoped expectations; they do not
turn the digital profile into hardware qualification.
