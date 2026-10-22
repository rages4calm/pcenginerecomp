# Private System Card firmware

The sandbox accepts an optional, explicitly supplied **raw 256 KiB System
Card ROM**. The loader checks length and maps physical banks `$00..$1F` as
read-only ROM. It never downloads firmware, patches it, supplies substitute
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
instruction sites, emits 775 supported sites and retains 47 unresolved
records. Static discovery is distinct from execution coverage.

The resulting module retires **30 native instructions**, reaches real
firmware through `$E05A`, and yields at **TMA at `$FC63`**. Hybrid execution
reports the same state and an explicit unsupported-instruction stop. BSR
was added after the real firmware path exposed it. No BIOS call was stubbed.

This starts at the extracted program entry with the sandbox's zeroed RAM and
explicit MPRs. It is not a console reset, a post-BIOS boot state, or a game
boot. There is no extra System Card RAM profile, authentic RAM mirrors,
VDC/VCE/PSG/CD bus, BRAM locking or IRQ/scheduler implementation. TMA and
its MPR/bus-latch semantics remain unsupported. Those limits prevent a
playability claim even though firmware instructions now execute.

Public tests use an authored synthetic ROM to prove service call/return,
read-only protection, exact image length and unchanged inputs. They do not
embed the owner's BIOS or rely on its files being present. Native dispatch
checks current instruction bytes and mapping; private snapshot hashes bind
the generation inputs. Regenerate private translations for a different BIOS.
