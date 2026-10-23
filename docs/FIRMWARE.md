# Private System Card firmware

The sandbox accepts an optional, explicitly supplied **raw 256 KiB System
Card ROM**. The loader checks length and maps physical banks `$00..$1F` as
read-only ROM and enables the [clocked CD-control/volatile-BRAM profile](CD_CONTROL.md)
and [clocked single-VDC profile](VDC.md).
It never downloads firmware, patches it, supplies substitute
services, or writes settings/saves. Firmware bytes and translations belong
under ignored `.local/`, never in a public package.

```sh
build/pce-headless .local/title/boot.bin 0x100000 0x4000 255,248,128,129,130,131,132,0 100000 2000000 hybrid --bios .local/firmware/syscard3-usa.pce
```

Use `pce-headless.exe` on Windows. Load/entry/MPRs must come from your actual
snapshot. Without `--bios`, the original firmware-free sandbox behavior is
preserved. Headered, truncated and oversized images are rejected; the loader
does not strip headers or claim that every correctly sized file is authentic.

The locally supplied unmodified USA v3.0 image has these identities:

| Property | Value |
|---|---|
| Bytes | 262144 |
| MD5 | `0754f903b52e3b3342202bdafb13efa5` |
| SHA1 | `d02611d99921986147c753df14c7349b31d71950` |
| SHA256 | `cadac2725711b3c442bcf237b02f5a5210c96f17625c35fa58f009e0ed39e4db` |

Its size/MD5 match the USA v3.0 entry documented by
[RetroPie](https://github.com/RetroPie/RetroPie-Docs/blob/master/docs/PC-Engine.md).
SHA1/SHA256 were computed locally for reproducibility. Two supplied font
extension patches (USA/Japan) were hashed separately and excluded from the
baseline. Their filenames are not independent verification of patch content.

## What the local firmware experiment proves

A private combined snapshot binds the initial Ys III payload and clean USA
firmware by SHA256. At a 1,024-instruction analysis limit it discovers 785
instruction sites, emits all 785 supported sites and retains 47 unresolved
records. Static discovery is distinct from execution coverage.

The regenerated ABI-6 module still begins with **48 native instructions**,
reaches real firmware through `$E05A`, and passes the former TMA stop at
`$FC63`. A subsequent TAM sets MPR4 and the transfer latch to `$F7`; the next
full-mapping native guard yields at **CSL at `$FC8F`**. The mapping barrier
remains real: this batch does not turn the module into a multi-context
native dispatcher. Hybrid fallback executes the actual firmware through the
former BRAM-control and VDC-select faults.

The clocked run uses the generic bus profile's Geargrafx-reference initial
geometry: HDR `$001F`, VDR `$00EF`, other VDC registers zero, divider 4 and
262 lines. This is deliberately defined analysis state, not an authentic
console reset or reconstructed IPL state. With zero HSR the horizontal
machine can advance a vertical counter more than once per VCE scanline;
the VDR value is not a claim that the guest has displayed 240 rendered lines.

The current bounded run retires **12,207 native plus 13,614 interpreted
instructions** (25,821 total), using 90,099 cycles / 271,512 master ticks.
It passes the VBlank polling loop, returns to further translated code and
passes the former `$1801` port fault at `$E923`. Actual firmware writes supply
a complete ten-byte directory/TOC command (`$DE`). Dispatch stops explicitly
at **logical `$EA4A`**, while the guest drops ACK through `$1802`, because
that command and its media response are unsupported. No command packet or
generated retail code is published. There is no fabricated TOC response,
successful disc read or game boot.

The run observes one VBlank event. The next implementation needs real disc
metadata and a bounded DATA IN response/acknowledgement path. The sandbox
does not treat the extracted initial program as proof that a mounted drive
can answer arbitrary commands. All six pinned original/derived input hashes
remain unchanged.

### Retained raster-only checkpoint evidence

The preceding ABI-5 run stopped at the former `$1801` fault after **162 native
plus 13,614 interpreted instructions** (13,776 total), recording 13,614 native
guard misses. It established the following raster observations; these are
retained earlier evidence, rather than totals from the current ABI-6 run.

At that stop the CPU reports 55,146 cycles / 166,653 master ticks, divisor 3,
A `$81`, X `$03`, Y `$01`, SP `$F6`, P `$81`. Video time equals CPU time:
frame 0, line 122, horizontal master-clock position 123 and VDC dot 30.
The VDC observed one enabled VBlank event, no raster-comparison events,
4,524 status/data reads and four writes. Final selection, CR, status and
local IRQ1 are zero/clear. There was no forced status toggle or invented
firmware service.

Both runs are capped at 100,000 instructions and 2,000,000 master ticks.
Adjacent execution checkpoints show the event and real acknowledgement:

| Retired instructions | Native / interpreted | Master ticks | Observation |
|---|---|---|---|
| 13,651 | 48 / 13,603 | 165,177 | No VBlank event, status clear |
| 13,652 | 48 / 13,604 | 165,189 | One VBlank event, status `$20`, local IRQ1 asserted |
| 13,653 | 48 / 13,605 | 165,207 | Guest status read clears the flag and local IRQ1 |
| 13,663 | 49 / 13,614 | 165,330 | Native execution resumes at the returned mapping |

The 165,189 value is a post-instruction observation, not an exact device-event
timestamp; the event arose within that instruction interval. A shorter
100,000-tick run still reaches its budget at 100,011 ticks with no VBlank
event, preserving the documented one-instruction deadline overshoot. The
native-only route still yields at `$FC8F` after 48 instructions / 678 ticks.

This starts at the extracted program entry with sandbox RAM, explicit MPRs
and a zero transfer latch. It is neither a console reset nor a post-BIOS
boot state. There is no complete System Card RAM profile, authentic RAM
mirrors, palette/renderer, PSG, CD sector/audio backend, timer or CPU interrupt
entry. CD selection/REQ/ACK and TEST UNIT READY are implemented in an explicit
reference profile. An unmasked pending IRQ1 or IRQ2 stops explicitly. VRAM
remains synchronous, with no display contention or DMA. BRAM is unformatted, zero-filled and
volatile; no owner save is used or written. CSL/CSH use the split-cycle model
in CPU_SEMANTICS.md. Device access phases remain an instruction-level
approximation even though the independent raster clock is master-tick based.
Those limits prevent a playability claim.

All six original/derived inputs in the private receipt, including the CHD,
extracted boot payload, clean firmware and two excluded patched firmware
images, retain their pinned hashes after execution.
The earlier untimed VDC experiment remains retained historical evidence;
its repeated polling was not further boot progress. A preliminary all-zero
video-geometry run is private exploratory evidence and is not the primary
qualification described above.

Public tests use an authored synthetic ROM to prove service call/return,
read-only protection, exact image length and unchanged inputs. They do not
embed the owner's BIOS or rely on its files being present. Native dispatch
checks current instruction bytes and mapping; private snapshot hashes bind
the generation inputs. Regenerate private translations for a different BIOS.
