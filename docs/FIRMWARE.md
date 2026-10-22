# Private System Card firmware

The sandbox accepts an optional, explicitly supplied **raw 256 KiB System
Card ROM**. The loader checks length and maps physical banks `$00..$1F` as
read-only ROM and enables the [limited CD-control/volatile-BRAM profile](CD_CONTROL.md).
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

The ABI-3 module retires **48 native instructions**, reaches real firmware
through `$E05A`, and passes the former TMA stop at `$FC63`. A subsequent TAM
sets MPR4 and the transfer latch to `$F7`. The next full-mapping native guard
yields at **CSL at `$FC8F`**. Hybrid executes CSL and the former `$1807` stop,
then returns from the BRAM routine, retiring **48 native plus 31 interpreted
instructions**. The new bus fault is at `$FCC7`: STA to logical `$0000`,
physical `$1FE000`, the unimplemented VDC select port. The failed write does
not retire. Final accounting is divisor 3, 366 CPU cycles and 2,313 master
ticks. Separate 52/79-step checkpoints prove the unlock write occurred and
the later `$1803` read locked BRAM again. The idle control profile recorded
one write and one read. No BIOS call or VDC register was stubbed.

This starts at the extracted program entry with the sandbox's zeroed RAM and
explicit MPRs and a zero transfer latch. It is not a console reset, a post-BIOS
boot state, or a game boot. There is no extra System Card RAM profile, authentic RAM mirrors,
VDC/VCE/PSG, CD transport/audio or IRQ/scheduler implementation. BRAM is
unformatted, zero-filled and volatile; no owner save is used or written. CSL/CSH use
the split-cycle model documented in CPU_SEMANTICS.md; device clock phases
and speed-dependent waits remain unfinished. Those limits prevent a
playability claim even though firmware instructions now execute.

Public tests use an authored synthetic ROM to prove service call/return,
read-only protection, exact image length and unchanged inputs. They do not
embed the owner's BIOS or rely on its files being present. Native dispatch
checks current instruction bytes and mapping; private snapshot hashes bind
the generation inputs. Regenerate private translations for a different BIOS.
