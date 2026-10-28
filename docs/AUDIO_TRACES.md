# Comparing audio in matching domains

`python -m pcerecomp.audio_trace EXPECTED ACTUAL` compares bounded, code-free
stereo S16 traces. It reports the first unequal frame/channel and preserves
both engine identities. Different fixtures, cases, first frames, gains,
timings, filter stages, rates or resamplers are refused. Nothing is silently
filtered, rescaled, aligned or truncated to obtain equality.

```sh
python -m pcerecomp.audio_trace .local/new-psg-pipeline/sta-abs-3/gear-raw.trace.json .local/new-psg-pipeline/sta-abs-3/native-raw.trace.json --output .local/new-raw-comparison.json
python -m pcerecomp.audio_trace .local/new-psg-pipeline/sta-abs-3/gear-filtered.trace.json .local/new-psg-pipeline/sta-abs-3/native-filtered.trace.json
```

Exit codes: 0 equal, 1 unequal samples/length, 2 invalid or incompatible.
`--output` exclusively creates a new file. Each input is bounded to 32 MiB
and 100,000 frames. Duplicate JSON keys, nonfinite constants, booleans in
numeric fields, invalid digests, ordinal overflow and malformed samples fail.

## The previously retained 144 differences

The earlier probe compared Geargrafx's actual `EndFrame` output with toolkit
raw mixer output. Gear's `EndFrame` applies a binary32 DC blocker. Dividing
by three accounts for mixer headroom, but does not remove that filter.

An authored transition has pre-half source sums `-10571`, then `+10571`.
Raw half-scaled output truncates to `-5285`, then `+5285`; Gear's DC blocker
produces `-5285`, then `+5293`. After the separate one-third headroom the
second values are `1761` and `1764`. All 144 retained later values are exactly
explained by this distinction. Changing chip gain to eliminate them would
introduce an error. Raw output and the existing filtered profile stay intact.

For filtered consumer output, explicitly select:

```toml
[runtime]
audio = "on"
audio_profile = "filtered"
audio_rate = 48000
audio_timing = "gear"
```

Use 44100 for the direct Gear HPF comparison: resampling at that rate is an
identity. The toolkit's 48 kHz FIR is a separate design with 31 source frames
of causal latency. See [audio output](AUDIO_OUTPUT.md).

## Trace schema 1

The exact top-level fields are `schema`, `format`, `engine`, `fixture_sha256`,
`case`, `domain`, `first_frame`, `samples`. Format is `pce-audio-trace-1`.
Engine fields are `name`, complete Git `revision`, `source_sha256` and
`binary_sha256`. Samples are `[left, right]` pairs, beginning at the one-based
global output ordinal `first_frame`. Producers must establish actual source
phase and bind fixture/engine files separately; valid metadata alone does not
authenticate an engine or establish independent execution.

| Domain field | Contract |
|---|---|
| `stage` | `psg-raw`, `psg-hpf`, `mixed-raw`, `mixed-filtered`, `resampled-filtered` |
| `timing` | `gear-v1` or `legacy-v1` global rational output edges |
| `source_rate` | 44100 |
| `output_rate` | 44100; 48000 only for the resampled stage |
| `gain_divisor` | Explicit post-stage divisor 1 or 3; mixed/resampled require 3 |
| `latency_source_frames` | Zero for identity; 31 for the declared 48 kHz FIR |
| `resampler` | `identity-v1` or `fir64x160-q30-v1` |

These fields describe samples already projected by a producer. The comparer
does not apply gain or transform the signal. Producers retain unaltered source
observations and identify projections. A PSG-only comparison must establish
that other mixer sources are silent, rather than assume it.

## Verification

`scripts/psg_pipeline_reference.py` executes actual authored instructions in
separately compiled original Gear, toolkit native code and the interpreter.
It retains original channel buffers before `EndFrame`, actual HPF output,
toolkit raw/filtered PCM, full source identity, clocks and work counts. Each
case continues for 2,048 source frames through four 512-frame drains. Matched
raw and filtered pairs apply the same explicit one-third headroom. Original
values before projection remain retained.

No toolkit source observer exists inside the first instruction: its first
pre-half sum is independently expected, never labeled directly observed.
Subsequent held sums and all output frames are actually read. Decimal gain
and binary32 HPF expectations, source/binary hashes, original Git blobs and
stdout/trace associations are checked independently. Changed-copy controls
exercise domain and provenance refusal.

`pce-psg-pipeline-tests` checks authored DAC/gain/balance values, wave/noise/LFO
edges, odd half-samples, unclipped filter histories, DC decay and independent
direct-convolution 48 kHz expectations. The fresh-process helper restores
authored audio payloads with partial source phases, queues and DSP history.
These device fixtures retire zero guest instructions. Retail TCP checkpoints
provide separate complete-machine continuation evidence; see [STATUS.md](STATUS.md).

Runtime ABI 26, generated operations, output defaults and checkpoint payload
schema 1 remain unchanged. Exact-build state bindings still require fresh
checkpoints when the reviewed build/recipe changes; there is no migration.

The original reference is [Geargrafx's PSG implementation](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_psg.cpp),
compiled separately under its license. Other cores disagree on selected noise,
LFO and reset behavior. This declared digital profile does not establish
hardware, analog, listening or complete-game parity.
