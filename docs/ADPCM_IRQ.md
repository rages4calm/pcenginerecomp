# ADPCM HALF/END CPU interrupt qualification

For DMA driven by actual CD READ commands and fresh checkpoint restoration,
see [coupled CD/ADPCM checkpoints](CD_ADPCM_CHECKPOINTS.md). That matrix checks
device IRQ-line state; the CPU delivery evidence below remains separate.

The authored suite extends device IRQ coverage to the ADPCM sources at CD
`$1802/$1803`, using ordinary HuC6280 guest instructions. It does not add or
change a CPU/device policy. Native translations retain full logical PC,
eight-MPR, physical-fetch and source-byte guards; no interpreter-per-opcode
wrapper supplies native work.

## Sources and acknowledgements

CD source enables are `$04` for ADPCM HALF and `$08` for END. These are device
**enable** bits, while CPU `$1402` bits disable CPU interrupt inputs. Either
active enabled ADPCM source raises CPU IRQ2 and uses vector `$FFF6`. VDC IRQ1
uses `$FFF8` and wins when both were sampled and neither is CPU-masked.

The fixture deliberately distinguishes two existing threshold rules:

- CPU ADPCM read completion decrements a nonzero length, then asserts HALF
  when the new length is **less than** `$8000`.
- Playback consumes the second nibble of a byte, decrements length, then
  asserts HALF when the new length is **at most** `$8000`.
- A CPU read with zero length asserts END and clears HALF.
- A CPU write with zero length asserts HALF and END before incrementing length.

Reading status does not acknowledge these latched sources. Disabling their
CD source-enable bits lowers the CPU line without clearing active sources.
ADPCM control bit 4 reloads length and clears END, retaining HALF. Control bit 7
resets the ADPCM read/write state and clears both sources. A request sampled
before the instruction can still cause IRQ2 entry when that instruction lowers
the live line. This is the existing aggregate CPU profile, not an electrical
IRQ-pin sampling claim.

## Authored guest program

The 48 cases run at both fixed CPU speeds. Guest opcodes set all MPRs, clear
8 KiB WRAM, set the stack, reset/configure ADPCM, create an actual read/write or
playback completion, and select both mask layers. No host write seeds an IRQ,
ADPCM length, playback phase, DMA counter or response deadline. Original Gear
uses its public BIOS/media loading with explicitly selected Standard CD
hardware, deterministic zero reset and no expanded Card RAM. The tiny CUE/BIN
is authored and contains no retail data. No CD command is issued.

Measured suffixes cover HALF, END, combined sources, the threshold control,
CPU mask, device enable, I flag, sampled-source retention across disable/reset/
reload, a held line reentering after RTI, wrapped stacks, and competition with
a real one-word VDC VRAM-DMA IRQ1. The handler acknowledges its own device;
it does not fabricate a successful interrupt return or device status.

Each case has 48 measured retirements plus a separately accounted guest primer.
Independent expectations include 36 CPU/device fields, complete WRAM/stack
SHA-256, actual vectors and exact per-source hits. The primer's TII stack
residue is preserved. A native source/deadline guard must not change CPU,
WRAM, bank generations or the compared device state.

## Original calls and clocks

The separate original Gear executable retains CPU, IRQ, ADPCM, CD and VDC
callbacks. Its journal preserves every instruction's fetched bytes and full
mapping, actual original continuation calls, returned/internal ticks and each
hardware-clock span. Per-call kernels distinguish internally clocked spans
from the wrapper's remaining-clock drain. Block transfers retain the exact
`14 + 6*N + 3` cycle cadence and `N+2` original calls; those calls do not become
extra retired instructions.

The existing fast CSH discrepancy remains visible: the authored prefix is
18 master ticks shorter in original Gear than in the toolkit. Both raw prefix
origins are independently checked. Completed measured states and elapsed
suffix clocks agree; no callback or duration is adjusted to force equality.
Original ADPCM callbacks must witness the actual threshold/read/write cause,
and the CPU IRQ callback order must match the independently expected vectors.

Reproduce with a new private output and existing pinned dependencies:

```text
python scripts/adpcm_irq_reference.py --gear-source PINNED_GEAR --tool-source PINNED_TOOL --out .local/adpcm-irq-reference --compiler CLANG --cmake CMAKE --ninja NINJA --library LIBCHDR --library LZMA --library MINIZ --library ZSTD
```

The baseline authored C++ selftest and Python admission tests need no external
core or retail inputs. See [STATUS.md](STATUS.md) for exact frozen source pins
and final qualification counts. This suite does not qualify sprite/raster IRQ
collisions, timer priority against ADPCM, dynamically coincident VRAM stalls,
raw bus phases, analog output or additional retail-library compatibility.
