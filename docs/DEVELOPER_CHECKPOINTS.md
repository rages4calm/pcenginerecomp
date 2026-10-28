# Developer checkpoints

An opt-in developer checkpoint saves a paused machine for continuation in a
**fresh run of the exact build and input recipe**. This implements the diagnostic
checkpoint interface without changing runtime ABI 25. It does not define a
portable game-save format, an emulator-state importer, in-process rewind,
rollback or cross-module migration. CD BRAM persistence remains a separate
interface; see [PERSISTENCE.md](PERSISTENCE.md).

## Explicit startup and private files

Append these options to a valid continuous-video headless or desktop invocation:

```text
--dev-port 0 --dev-start-paused on
--checkpoint-dir EXISTING_PRIVATE_DIRECTORY
--checkpoint-context REVIEWED_CONTEXT_SHA256
```

The directory must already exist. The reviewed context is a lowercase 64-digit
SHA256 binding the tool/source/module/input/runtime recipe; it is not an
arbitrary session name. The consumer runner computes it from its verified
project descriptor when `--checkpoint-dir` is supplied. Raw host callers own
that reviewed context binding. The host additionally fingerprints its executable,
adjacent DLLs, actual media/firmware/input files and selected machine profiles.
Changes to any binding require a new reset-based run and checkpoint.

While quiescently paused, use the existing local client connection:

```python
from scripts.dev_client import DevClient

with DevClient(port) as client:
    client.call("save_checkpoint", name="frontier-001.pcec")
```

`name` is a portable `.pcec` basename within the startup-selected directory,
not a network-selected path. Traversal, separators, alternate streams, reserved
names, links and oversized names are refused. Save creates a **new file
exclusively** and never replaces a checkpoint. A failed write retains its
incomplete new artifact for diagnosis. Keep these files private: they contain
firmware/game memory, code, saves and device data. Never commit or distribute
them with toolkit source or public native packages.

Start a new invocation with the same exact bindings and
`--checkpoint-load frontier-001.pcec`. Alternatively, call
`client.call("load_checkpoint", name="frontier-001.pcec")` during its initial
quiescent pause. Loading requires zero fresh retirements, no started code
capture, no new WAV frames, no previous checkpoint import and no BRAM export.
Once a run has executed, a new process is required. Consumer checkpoint startup
requires paused TCP mode. A load leaves the fresh host paused until explicitly
stepped or resumed.

Finite step and tick allowances apply to the new execution window; imported
absolute guest clocks/frame numbers and lifetime counters remain intact. A
new output path or finite run limit does not change machine compatibility.

## Machine and host state

The schema uses explicit fixed-width little-endian fields, strict booleans,
bounded arrays/strings and exact IEEE float bits for finite DSP history.
Object padding, native pointers, streams, locks, allocator internals and raw
C++ object representations never enter the file. Schema, ABI, exact identity,
length and SHA256 integrity are checked before decoding a bounded payload.
The complete temporary machine and immutable configuration are validated
before the live machine is replaced. Rejection leaves live guest state intact.
The digest checks file integrity; it is not authentication of files from an
untrusted author.

The field inventory includes:

- CPU registers/flags, PC, all eight MPRs, transfer latch, clocks, sampled IRQs,
  retirement/wait counters, complete storage/kinds/generations, mapper ROM and
  latch, optional Arcade Card RAM/ports/shifter and BRAM contents/protection.
- VDC/VCE registers, VRAM/SAT, queued CPU accesses, DMA and deadlines, raster
  phases, scroll/write/fetch latches, decoded sprite rows, partial RGB frame and
  completed historical frame, sequence and guest timestamp.
- CD command/data/status/message phases, ACK and automatic ACK deadline,
  partial command and response buffers, pending sector loads/retries/sense,
  drive position, TOC/provenance, CDDA seek/play/stop/fader deadlines, source
  cursor, readable sample holds/latch and rational sample phase.
- ADPCM RAM, pending ports/DMA, nibble/decoder state, sample phase and IRQs;
  every PSG waveform/oscillator/noise/LFO/held-DAC field; PCM ring contents and
  indices, presentation profile, exact filter/FIR history and resampler phase,
  legacy CDDA cursor and cached sector samples.
- Guest controller configuration/latches/snapshots plus host scripted/remote
  masks, input-recipe position, assisted-edit counts and source WAV marker.

Read-only sector providers are reconstructed through the fresh run's normal
checked media setup. Cursor/cache bindings reconnect only to that exact
configured provider. Empty bindings remain empty. Stale or foreign provider
bindings refuse explicitly. Save/load performs no guest sector-provider reads, clock advance,
input consumption, IRQ acknowledgement, FIFO drain or pending PCM drain.
Provider decompression/file-handle caches are recreated; the logical retained
CDDA sample cache is serialized exactly.
The host separately rehashes source files to detect changed input bindings.

SDL windows, GPU textures, device audio queues, local controller handles,
network sockets/request buffers, pacing anchors and host wall timers are
recreated. Release local desktop buttons before checkpoint I/O and use
TCP/script inputs for reproducible fixtures. The restored remote mask is
subject to the normal disconnect-clears-input behavior.

## Audio and evidence boundaries

The guest PCM queue is saved exactly, including its ordering and wrap indices.
Pausing does not drain it. A fresh output window may therefore begin by
consuming samples that were already pending at the checkpoint. Its provenance
records the imported pending-frame count and source WAV marker; a new WAV does
not claim to contain a replay of the complete prefix. SDL's already submitted
host-device queue is disposable presentation state.
The final report's `checkpoint.audio_origin.pending_pcm_frames` and
`checkpoint.audio_origin.source_wav_frames` retain these two imported markers;
they are separate from newly written WAV frames.

A resumed run reports the checkpoint digest and imported absolute
clock/frame/native/interpreted counts separately from newly executed window
counts. Consumer qualification uses the new window's work. Code capture records
its checkpoint origin and only the newly observed suffix; it cannot promote an
imported prefix into fresh full-reset native evidence. An exact state round-trip
establishes continuation behavior, not hardware accuracy, analog/audio parity
or whole-game native coverage.

## Verification scope

Authored tests exercise repeated pure saves, fresh reconstructed machines,
active device boundaries, exact state/PCM continuation, ring wrap, corrupted
or truncated input, immutable-profile mismatch and explicit source-binding
refusal. Reference-engine verification and isolated retail TCP continuation are
separate gates. See [STATUS.md](STATUS.md) for the current batch's executed
checks, source pins, actual native/interpreted work and remaining limitations.

Cross-build or module migration, arbitrary in-process state replacement,
owner/emulator state import, rewind, rollback, automatic checkpointing and
portable end-user saves remain future interfaces. Support for a new device or
profile requires a complete field inventory, immutable binding checks and
continuation tests before checkpoints can accept it.
