# Private System Card firmware

The sandbox accepts an optional, explicitly supplied **raw 256 KiB System
Card ROM**. The loader checks length and maps physical banks `$00..$1F` as
read-only ROM and enables the [limited CD-control/volatile-BRAM profile](CD_CONTROL.md)
and [functional single-VDC profile](VDC.md).
It never downloads firmware, patches it, supplies substitute
services, or writes settings/saves. Firmware bytes and translations belong
under ignored `.local/`, never in a public package.

```sh
build/pce-headless .local/title/boot.bin 0x100000 0x4000 255,248,128,129,130,131,132,0 1000 100000 hybrid --bios .local/firmware/syscard3-usa.pce
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

The regenerated ABI-4 module retires **48 native instructions**, reaches
real firmware through `$E05A`, and passes the former TMA stop at `$FC63`.
A subsequent TAM sets MPR4 and the transfer latch to `$F7`; the next full-mapping
native guard still yields at **CSL at `$FC8F`**. Native-only execution stops
there; hybrid fallback executes the real firmware through the former `$1807`
and `$FCC7` faults, including the VDC select/data writes.

A 1,000-step hybrid run retires **48 native plus 952 interpreted instructions**,
ending at `$FCDD` after 4,050 CPU cycles / 13,365 master ticks. CR contains
`$0008`; the VDC recorded 306 reads and two writes, with no VRAM changes.
The firmware first waits for vblank to clear, then loops on a status read
at `$FCD8`, AND #`$20` at `$FCDB`, and a backward BEQ at `$FCDD` waiting for
vblank to become set. The functional profile has no raster event generator,
so this is now the blocker rather than a bus fault.

A longer run bounded by 10,000 steps and 100,000 ticks ends on the tick budget
at `$FCDB`, after **48 native plus 8,172 interpreted instructions** and 8,172
guard misses. It reports 32,932 CPU cycles / 100,011 master ticks, divisor 3,
2,713 VDC reads and two writes, and no VRAM changes. The final instruction
crosses the deadline under the documented instruction-boundary budget rule.
Repeated polling is not further boot progress. No BIOS service, vblank event
or VDC register was stubbed to advance execution. Original CHD, boot payload,
clean firmware and the two excluded patched firmware inputs retain their
verified hashes.

This starts at the extracted program entry with the sandbox's zeroed RAM and
explicit MPRs and a zero transfer latch. It is not a console reset, a post-BIOS
boot state, or a game boot. There is no extra System Card RAM profile, authentic RAM mirrors,
VCE/PSG, renderer, CD transport/audio or IRQ/scheduler implementation. The
VDC profile implements synchronous register/VRAM operations only. BRAM is
unformatted, zero-filled and volatile; no owner save is used or written. CSL/CSH use
the split-cycle model documented in CPU_SEMANTICS.md; device clock phases
and speed-dependent waits remain unfinished. Those limits prevent a
playability claim even though firmware instructions now execute.

Public tests use an authored synthetic ROM to prove service call/return,
read-only protection, exact image length and unchanged inputs. They do not
embed the owner's BIOS or rely on its files being present. Native dispatch
checks current instruction bytes and mapping; private snapshot hashes bind
the generation inputs. Regenerate private translations for a different BIOS.
