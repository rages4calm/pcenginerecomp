# CD position replies and program ranges

The known `$DD` command returns the existing ten-byte Gear-profile position
response. ABI 25 adds a pure sector-provider program-range lookup so a gap
does not inherit the preceding track's type, number and relative time.
This is synthesized position metadata, not captured raw subchannel Q.

Built-in ISO, CHD and BIN/CUE providers distinguish program payload from
non-program positions using their actual parsed geometry. ISO has one data
program range. CUE excludes both stored and virtual pregaps and all postgaps.
CHD excludes parsed stored/virtual pregaps and inter-track postgaps; its
existing final-postgap/leadout policy is unchanged.

`SectorProvider::program_track(lba)` returns `ProgramTrackLookup`:

| Result | Meaning |
|---|---|
| `known=false`, no index | This provider supplies no program-range metadata |
| `known=true`, no index | Geometry authoritatively classifies this LBA outside all program ranges |
| `known=true`, index | Zero-based index of the containing program track in the attached TOC |

Lookup does not read/decode a sector, update an audio/sector cache, move a
drive head or advance guest clocks. Built-in providers retain their source
identity checks; a changed source remains a terminal fault. These host file
checks do not make the method an emulated disc read.

A metadata-only TOC or custom provider returning unavailable metadata keeps
the previously declared nearest-INDEX-01 approximation. Missing metadata is
never treated as a verified gap. Providers returning an unknown result with
an index, an out-of-range track, a track before its start or beyond the next
track's INDEX 01 are refused explicitly.

For a known non-program position, the selected Gear profile returns control
`$01`, track `$00`, index `$01` and relative `00:00:00`; the absolute time
still comes from the current LBA plus the 150-frame lead-in. That unusual
track/index combination is pinned emulator behavior. It does not claim
hardware index-00 reporting or Red Book subchannel conformance. Program
responses retain their actual data/audio control, track number and relative
offset. Audio state and seek-origin selection are unchanged.

For example, let a four-sector data track occupy LBAs 0-3 and let the next
track start at LBA 6 after a two-sector pregap. A successful READ of LBA 3
naturally advances the idle head to LBA 4. The expected `$DD` reply is:

```text
01 01 00 01 00 00 00 00 02 04
```

The former INDEX-only lookup instead reported the preceding data track and
relative frame 4: `01 41 01 01 00 00 04 00 02 04`. A fresh original-core and
pre-fix native/interpreter pilot reproduces this exact counterexample without
writing the head from the host.

## Verification

`pce-cd-position-tests` uses authored ISO/CUE geometry and an authored CHD
decoder fixture. It checks program boundaries, stored/virtual pregaps,
postgaps, direct DD bytes, seek-origin classification, unavailable metadata,
invalid custom-provider results, source changes and pure inspection. The
synthetic CHD check establishes parsed geometry, not real compressed decoding.

`scripts/cd_position_reference.py` separately builds the pinned original
Geargrafx core. Its authored matrix uses plain, virtual-pregap and stored-
INDEX00 CUE layouts; data/audio tails; first-track lengths 4, 74 and 75; both ACK
paths; and both toolkit CPU speeds. Actual successful READs establish the
head, then the supervisor consumes DD DATA IN, status and message bytes.
Expected payloads and complete ten-byte replies are calculated independently.
Toolkit port operations execute real translated or interpreted instructions,
with full PC/MPR/physical-byte identity and exact per-source counts. The
supervisor selects PC/A and advances declared waits, so this is not a
guest-only CPU-timing or electrical-bus proof.

Direct original Gear POSTGAP semantics, captured subchannels, physical drive
timing, firmware behavior and whole-game compatibility remain separate.

The frozen ABI25 run passes all 18 layouts: 144 original cases and 288 cases
per toolkit tier. Actual work is 1,795,968 native instructions with zero
fallback, an equal separate interpreter run and 288 pure guards. All 180
actual positive datasets requalify; 27 corrupted copies are rejected without
changing 1,206 bound inputs. The direct provider suite has 260 checks.
See [source pins and current qualification](STATUS.md).
The original source is
[Gear position handling](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/scsi_controller.cpp)
and its
[program-range lookup](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_image.cpp).
Its GPL implementation stays in a separate executable; no implementation
bodies are copied into the toolkit runtime.

ABI 25 requires regenerated native modules and rebuilt consumers because the
provider interface changes. This interface upgrade itself introduces no mutable
guest-state field or snapshot format. Later exact-build
[developer checkpoints](DEVELOPER_CHECKPOINTS.md) reconstruct the checked
provider and preserve guest transport/audio state without dumping provider
objects; cross-build migration remains unimplemented. Existing TOC-only recipes
retain their approximation; attaching
a built-in provider selects its authoritative program-range metadata.
