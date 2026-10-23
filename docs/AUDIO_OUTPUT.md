# Audio output

The runtime can produce **44,100 Hz signed 16-bit stereo PCM** from PSG,
MSM5205 ADPCM and read-only CDDA sources. The optional SDL3 host can play it;
both runners can explicitly capture a bounded WAV. Runtime **ABI 13** includes
the synthesis, decoder and output state. The latest PSG correction preserves
that layout: rebuild the runtime; compatible ABI-13 generated modules can be
reused. Older-ABI modules require regeneration. This is a digital reference profile, not a qualified model
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
noise and LFO state. Digital output uses a fixed integer gain table. Ordinary
waveform periods **1–5** use the mean of all 32 waveform entries to suppress
instantaneous ultrasonic aliases. The centered mean numerator is
`2 * sum(waveform) - 31 * 32`; the unipolar numerator omits the offset.
Each side applies its channel gain, divides by 32 with nearest rounding
(ties away from zero), then the PSG sums its channels and halves with truncation
toward zero. This PSG output subsequently enters the separate one-third-per-source
PCM mixer. Oscillator phase still advances normally. No cached sum or new
state is introduced, so every waveform write is immediately visible.

Period zero means 4,096 clocks and does not select the mean. Periods 6 and
above retain instantaneous samples. Noise and DDA bypass the mean, as do
configured LFO source/destination channels and channel 1 held by the LFO
trigger. Other channels remain eligible during modulation. The legacy
register-storage path remains available with synthesis disabled.

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
mixer scheduling and bounded host/capture behavior. The current expanded-module
SDL build passes all **27 suites / 273 Python tests**, including **732 PSG**
and **20,828 mixer** expectations. A clean public-source default build passes
**25 suites**, with seven desktop-only skips among the same 273 Python tests.
The focused checks and separate consumer qualification are in [STATUS.md](STATUS.md).

### Independent digital source checks

Enable the authored probes explicitly; external reference code is not needed
for normal builds or tests:

```sh
cmake -S . -B build-reference -G Ninja -DCMAKE_BUILD_TYPE=Release -DPCE_BUILD_REFERENCE_PROBE=ON
cmake --build build-reference --target pce-pcm-probe pce-adpcm-probe
python scripts/psg_reference.py --gear-source /path/to/Geargrafx/src --miniz /path/to/miniz --probe build-reference/pce-pcm-probe.exe --out .local/new-psg-reference
python scripts/adpcm_pcm_reference.py --exe .deps/geargrafx-oracle/Geargrafx.exe --gear-source /path/to/Geargrafx/src --probe build-reference/pce-adpcm-probe.exe --out .local/new-adpcm-reference
```

Use the executable suffix appropriate to the host. The PSG source adapter
needs a GCC-compatible `g++` (or `--compiler` path) and `miniz.h`. It requires
unmodified Geargrafx 1.8.4 source at commit
`1c62a549328241518101f5be5bf3e6840b96ea5d`, verifies each source hash, and
compiles a separate oracle executable in the new output directory. Its
**3,262 authored cases / 49,258 stereo pairs** exactly match the runtime,
including six waveform indices and two noise seeds per observation. Cases
cover both DAC profiles, waveform periods, fractional means at all gains,
side balance, DDA, noise and LFO. Each observation follows a positive
oscillator-clock advance: this does not qualify Gear's cached DAC output
immediately after a zero-clock register write or CPU bus-access phases.
The previous runtime fails the same mean-sensitive plan; the corrected one
passes. All external source and probe identities are checked again at closeout.

The ADPCM adapter uses the pinned Windows Geargrafx 1.8.4 binary in an isolated
portable configuration under `.deps/`. It reads, but never loads or patches,
the emulator's v44 save states. An exact, unique authored 64 KiB RAM marker,
header/build checks and agreement with public device fields precede access
to serialized predictor, adaptive index and 16.16 clock phase. An ordinary
upstream `src` directory or the flattened research cache supplies the pinned
layout references; executable and source identities are mandatory.

Its **18 cases / 108 main checkpoints** cover all 16 playback rates,
predictor wrap and index clamps, nibble order, address wrap, lengths, IRQ flags and
running phase. Five further continuous stop/restart/reset checkpoints use
one initial probe state, and 131 raw states are checked overall. The held
digital value remains `(predictor - 2048) * 16`; no ADPCM runtime decoder
change was required. A finite-end vector deliberately records distinct
stopped-phase residues: Gear 186,918, runtime 55,846, a difference of two
master ticks. Both values follow independently checked clock rules; the
reference retains its final whole six-tick CPU callback while the runtime
stops at the exact integer tick. This is a narrow documented difference,
not a claim of equal stopped phase or general bus-edge timing.
The owned emulator process stops and temporary configuration is removed;
authored media, probe, binary and reference sources remain unchanged.

Both adapters verify digital source behavior before output filtering,
resampling, source mixing or device presentation. The authored adapters and
wrapper are distributed; GPL emulator implementation files remain external
inputs, never copied into or linked with the toolkit runtime.

### Corrected-profile Ys III regression

A fresh headless TCP replay of the same assisted **93,735-frame** route
matches all 25 guest image hashes, 25 checkpoint states, every original final
guest diagnostic and the original native/interpreted counts. Source and input
identities remain stable before and after execution; the owned child stops.
It uses the same 709 RAM transactions / 723 changed bytes, IPL entry, volatile
BRAM and explicit `gear-good` unknown-command response profile. No additional
assistance or campaign progression is introduced.

All source/mixed audio counters remain exact against the earlier profile:
**69,095,406 stereo frames**, nonzero PSG 27,644,755, ADPCM 4,030,681, CDDA
49,762,727 and mixed 65,958,163; peak 13,000, PCM hash
**7,177,686,580,420,813,080**, zero runtime queue discard. The first 1,323,000
WAV frames retain SHA256
`ee86382ebc96da7833c3b6fe36dd6b8c7703cc9a8f85d00e3f1d6d25b123d40f`.
The waveform-mean correction is exercised by authored ultrasonic vectors;
this retail route establishes regression compatibility, with no observed
PCM change or audible-improvement claim. Neither route reproducibility nor
the source oracles qualify mixed output against hardware.

The rebuilt packaged Ys III desktop consumer independently matches the
same complete route and digital output. Its separate paced TCP probe submits
**710,526 frames** to the default device, with fast-forward mute false,
zero runtime discard, **2,680 pause-flush drops**, peak queue **1,583** and
final queue zero. Timestamped paused snapshots at least 0.15 seconds apart
retain guest/PCM state; resume advances normally. Both runs verify the live
adjacent SDL DLL's identity without SDK or packaged `bin` on the child PATH,
from an empty working directory. The full replay intentionally mutes
fast-forward device output. All **116 consumer tests** and **137 independent
evidence checks** pass; the latter rehashes 487 actual artifacts. This is
packaged stream acceptance/consumption and regression evidence, not listening,
analog loopback or independent mixed-PCM parity. Owned test children stop.

### Retained CDDA and presentation checks

The separate live Geargrafx 1.8.4 CDDA adapter is:

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
and clean up. Gear's MCP exposes no raw PSG/ADPCM decoder samples; the separate
source/save-state adapters above establish their stated digital scopes.

The paced SDL device check separately submits **930,219 stereo frames** over
approximately 21 guest-clock-paced seconds. The device opens, fast-forward
mute is false, the input queue returns to zero, and pause flushing accounts
for 1,032 dropped presentation frames. Peak pending input is 1,591 frames;
the runtime source queue discards none. This establishes device-stream
acceptance/consumption, not a listening or analog loopback result. The test's
owned process exits cleanly. See [STATUS.md](STATUS.md) for final batch scope.

The earlier retained 93,735-frame assisted Ys III TCP route passes
with audio enabled: all 25 guest images and every original final guest JSON
value remain exact against the previous full-native run. It generates
69,095,406 PCM frames with PSG, ADPCM and CDDA activity, peak 13,000 and zero
runtime queue discard. Its WAV retains the bounded first 1,323,000 frames
(5,292,044 bytes), with truncation explicitly reported. Device output is
intentionally muted during this unthrottled run; its source measurements are
separate from the paced device-stream result and independent Gear sample oracle.
It adds no new assistance, progression or campaign-completion claim. Its
PCM hash and WAV describe the earlier instantaneous PSG profile; the fresh
corrected-profile regression above independently reproduces their values.

The adapter uses CUE for the independent sample comparison. The CHD provider
tests use an authored decoder ABI double to isolate byte order and geometry;
that double is not a compression decoder. Analog filtering, full-band antialiasing,
reference resampling, physical output correctness and complete retail sound
remain separate qualification work.

## Primary sources and licenses

- [Geargrafx 1.8.4 CDDA samples](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/cdrom_audio_inline.h),
  [CHD sample order/mapping](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/cdrom_chd_image.cpp)
  [playable-region rules](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/cdrom_image.cpp)
  and [PSG digital profile](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_psg_inline.h):
  GPLv3, used as an external oracle and behavioral reference; no implementation
  code is copied into this toolkit.
- [Pinned Geargrafx PSG source](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_psg_inline.h)
  and [ADPCM decoder/state serialization](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/adpcm.cpp):
  GPLv3 external oracle and layout references for the new authored adapters.
- [libchdr](https://github.com/rtissera/libchdr): BSD-3-Clause primary CHD format/
  decoder source. It remains an explicitly selected optional dependency.
- [OKI MSM5205 datasheet, pages 3–4](https://elektronikjk.pl/elementy_czynne/IC/MSM5205.pdf):
  the original decoder/DAC and wrap behavior, hosted by a document mirror.
- [SDL3 audio streams](https://wiki.libsdl.org/SDL3/SDL_OpenAudioDeviceStream):
  API documentation for the optional zlib-licensed SDL playback dependency.

These references establish provenance and scoped expectations; they do not
turn the digital profile into hardware qualification.
