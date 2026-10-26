# Read-only disc inputs

The runtime sector provider accepts cooked single-track ISO, supported CHDv5,
and a bounded BIN/CUE subset. CUE needs no decompression library. CHD retains
its explicit optional libchdr dependency. These readers do not modify inputs,
extract whole discs, access physical drives or implement missing CD commands.

## BIN/CUE subset

Supported CUE sheets use UTF-8 (optional BOM), `FILE ... BINARY`, sequential
tracks, and `MODE1/2048`, `MODE1/2352` or `AUDIO`. Single-file and multiple-file
images work. Quoted filenames and relative subdirectories are supported;
backslash separators normalize to `/`. Each referenced file must stay inside
the CUE directory after resolution. Absolute paths, parent traversal, duplicate
references and escaping links are rejected.

`INDEX 01` selects the stored track payload. Optional `INDEX 00` selects a
stored pregap; `PREGAP` inserts virtual frames without consuming file bytes.
Optional `POSTGAP` inserts virtual frames after the track's program payload,
also without consuming file bytes. It must appear once after `INDEX 01` and
before the next track/file; subsequent INDEX/PREGAP directives on that track
are refused. An explicit zero is accepted. Shared-file offsets remain
FILE-relative even though following disc positions move past the postgap.
The reader adds no implicit 150-sector gap: the lead-in is accounted for in
TOC/MSF responses. Track one must begin at file frame zero without a nonzero
pregap. Every file begins with its first declared segment at zero. A file
cannot mix 2048- and 2352-byte sector widths, although raw MODE1 and AUDIO can
share one 2352-byte file. Tracks must have payload beyond their pregap.

Data reads return 2048 user bytes. Raw MODE1 sectors require their sync header
and mode byte; this is not EDC/ECC validation. Audio reads decode stored BIN
samples as signed little-endian 16-bit stereo. CHD's distinct big-endian audio
conversion remains unchanged. Reading data as audio, audio as data, virtual
gaps or out-of-disc sectors fails explicitly. Stored AUDIO pregap samples can
be read; the existing playback gate admits them only after another AUDIO
track. Virtual gaps remain silent through that gate.

The subset rejects indices beyond 01, combined nonzero virtual and
stored pregaps, `FLAGS`, MODE2, WAVE/MP3/compressed audio and unknown commands.
Recognized text-only metadata and `REM` do not affect geometry; exact CUE bytes
still affect identity. Limits are 1 MiB of CUE text, 99 tracks/files, 8 GiB of
referenced binary data and leadout LBA 449,849. Malformed or unsupported layouts
are refused instead of inferred.

CUE leadout includes an explicit final `POSTGAP`, following the original
Beetle image-reader profile. The existing CHD profile follows Geargrafx and
excludes a final CHD postgap. These are explicit format/reference policies;
neither establishes physical-drive behavior. Inter-track postgaps move later
tracks in both formats. Gap frames never become additional stored payload.
Direct data reads there retain typed read errors, raw audio reads require
stored samples, and the existing playback gate supplies gap silence.

Syntax research follows the GNU ccd2cue
[CUE format](https://www.gnu.org/software/ccd2cue/manual/html_node/CUE-sheet-format.html)
and [INDEX description](https://www.gnu.org/software/ccd2cue/manual/html_node/INDEX-_0028CUE-Command_0029.html).
This supported subset is narrower than the complete format.

The original [Beetle image reader](https://github.com/libretro/beetle-pce-libretro/blob/b96c11e095b6a40a412d2da02766ae1c3f4fd539/mednafen/cdrom/CDAccess_Image.cpp)
supplies the direct POSTGAP comparison. The pinned
[Gear CUE reader](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/cdrom_cuebin_image.cpp)
supplies the separate equivalent-layout comparison. Their original source
bodies are built outside the runtime; neither is a toolkit dependency.

## Complete-image identity

Hashing a CUE sheet alone does not identify its track data. For CUE inputs,
`image_sha256` is SHA256 over this UTF-8 record (literal tabs and newlines):

```text
PCE-CUE-1
cue<TAB>CUE_BYTE_COUNT<TAB>CUE_FILE_SHA256
file<TAB>NORMALIZED_RELATIVE_NAME<TAB>FILE_BYTE_COUNT<TAB>FILE_SHA256
```

There is one `file` line per `FILE` declaration in declaration order and a
final newline. Counts are unpadded decimal, digests lowercase, and names are
relative to the CUE directory. Exact CUE and BIN bytes are covered; moving the
whole directory does not change the identity. Renaming a referenced file or
editing CUE formatting does. ISO and CHD keep their original whole-file SHA256.

Consumer schema 1 retains `[disc] path` and `sha256`; for CUE, `sha256` is this
complete-image identity. Verification discovers and pins every referenced
file as `disc_component:<relative-name>` in build/run bindings, alongside the
raw CUE hash. A changed component invalidates the retained build or run.
Source size/time checks surround runtime reads; these are mutation guards,
not a claim to detect an adversarial rewrite that restores file metadata.

## Tools

```sh
python -m pcerecomp inspect disc.cue --hash --out .local/disc.json
python -m pcerecomp toc disc.cue --out .local/disc.toc
python -m pcerecomp boot disc.cue --out .local/new-boot
```

Boot discovery retains the existing bounded IPL subset and requires one
supported data track. It is an extraction/analysis recipe, separate from real
System Card reset boot. Both hosts accept `--disc disc.cue`; consumer projects
use their ordinary pinned `[disc]` table. Output paths cannot replace a CUE or
any of its referenced files.

Authored fixture expectations, separately compiled Geargrafx media checks,
and native/interpreted command-stream checks have distinct scopes. TCP host
tests additionally execute a guest READ(6), verify all 2048 bytes in guest RAM,
consume status/message and quit through the normal development server. These
finite tests do not certify all CUE variants, physical seek timing or a game.

## Data-read failures and recovery

Runtime data providers distinguish explicit `SectorReadError` outcomes from
terminal `Fault` failures. Typed errors identify the exact requested LBA and
one of `out_of_range`, `wrong_data_track`, `unrecoverable_data` or
`media_data_error`. The CD command layer turns only those errors into CHECK
CONDITION with retained NEC sense context. A provider must not infer these
categories from an arbitrary exception message.

Built-in ISO/CHD/CUE providers check source identity before classifying an
attempted read and again before a typed error escapes. Invalid raw MODE1
headers are typed media errors; changed sources, host open/short reads,
unsupported configurations and opaque libchdr failures remain terminal.
Audio read/error contracts retain their prior behavior.

Before any new CHD hunk decode, the old cache identity is invalidated. If a
decoder overwrites its output and then fails, a later request for the old hunk
must decode it again. This keeps the existing one-hunk cache bound without
exposing mislabeled data. No sector from a failed decode is published.
See [CD_SENSE.md](CD_SENSE.md) for exact response, recovery and reference limits.
