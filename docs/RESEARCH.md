# Research register — 22 October 2026

The design was informed by current primary documentation and pinned source
inspection. [references.lock.json](references.lock.json) records examined
repository revisions and file digests. These are research identities, not
vendored dependencies. Sources were read; the upstream recompilers were not
independently rebuilt or their game-compatibility claims revalidated here.

Searches for `pcenginerecomp`, PC Engine static recompilation and HuC6280
recompilers did not identify an established general-purpose static tool to
adopt. That is a search result, not proof no prototype exists. Relevant
emulators, disassemblers, development tools and a new firmware project do
exist. PC-FX's V810 is a different platform and is outside this baseline.

## Recompiler patterns worth carrying forward

| Source | Observed pattern | Decision for this project |
|---|---|---|
| [SNESRecomp](https://github.com/RetroPortingToolKit/snesrecomp/tree/be6a01d35bc9c37c550022124ca0df042e12e3c4) | Separate analysis/emission, shared runner, interpreter bridge, coverage and reference diagnostics | Keep compiler/runtime separate; preserve guest semantics and label execution evidence |
| [SNESRecomp IR](https://github.com/RetroPortingToolKit/snesrecomp/blob/be6a01d35bc9c37c550022124ca0df042e12e3c4/recompiler/v2/ir.py) | Explicit state transformations rather than relying only on expression-string state | Start with inspectable instruction records; design typed lowering before complex optimizations |
| [Native/interpreter boundary](https://github.com/RetroPortingToolKit/snesrecomp/blob/be6a01d35bc9c37c550022124ca0df042e12e3c4/docs/MULTI_TIER.md) | Return-stack and native-caller contracts matter at tier transitions | Preserve the guest stack; initially dispatch each instruction instead of assuming host-call pairing |
| [Widescreen patterns](https://github.com/RetroPortingToolKit/snesrecomp/blob/be6a01d35bc9c37c550022124ca0df042e12e3c4/docs/WIDESCREEN_PATTERNS.md) and [rollback](https://github.com/RetroPortingToolKit/snesrecomp/blob/be6a01d35bc9c37c550022124ca0df042e12e3c4/docs/ROLLBACK.md) | Presentation and networking have game/state-specific requirements | Make these extension tracks with reference and compatibility gates |
| [PSXRecomp architecture](https://github.com/RetroPortingToolKit/psxrecomp/blob/e3705227b56721112c35106780878b41cea2daa0/docs/ARCHITECTURE.md) | Generated game code, hardware runtime, swappable services and independent oracle | Keep device behavior and service replacement distinct from CPU translation |
| [Overlay execution model](https://github.com/RetroPortingToolKit/psxrecomp/blob/e3705227b56721112c35106780878b41cea2daa0/docs/EXECUTION_MODEL.md) and [AOT sharding](https://github.com/RetroPortingToolKit/psxrecomp/blob/e3705227b56721112c35106780878b41cea2daa0/docs/AOT_SHARDING.md) | RAM-loaded code is a first-class problem; stale native translations need invalidation | Treat disc-loaded RAM overlays and source-byte guards as baseline requirements |
| [PSX code provider](https://github.com/RetroPortingToolKit/psxrecomp/blob/e3705227b56721112c35106780878b41cea2daa0/runtime/src/code_provider.c) | Compiler requests are asynchronous batch work rather than a synchronous dispatch operation | Future overlay compilation belongs outside the guest execution path |
| [N64Recomp](https://github.com/N64Recomp/N64Recomp/tree/ffb39cdad1da5de07eaaa48bd1db4a89a7986771) | Literal source translation, metadata-driven discovery and overlay lookups | Generate readable host source; do not assume function discovery is automatic |
| [N64ModernRuntime](https://github.com/N64Recomp/N64ModernRuntime/tree/cdf5abbd5026fef5c364c676e4667c45e42b6863) | Runtime libraries, platform callbacks and renderer selection are separate responsibilities | Keep the eventual desktop shell and renderer outside the core CPU/compiler |

The important limitation is that MIPS, 65816 and HuC6280 have different
instruction and memory models. There is no benefit in inheriting SNES
width-state rules, PS1 BIOS call handling or N64 library replacement
assumptions without a corresponding PCE contract.

## Hardware and boot references

1. [HuC6280 CPU hardware description](https://magicengine.com/mkit/doc_hard_cpu.html)
   documents the eight 8 KiB MPR pages and 21-bit physical addressing.
2. [MAME HuC6280 opcode decoder](https://github.com/mamedev/mame/blob/da9333a2a5123012a939e78c3f2df7175ea7d100/src/devices/cpu/h6280/6280dasm.cpp)
   supplies a full opcode/mode map, including block and immediate-test forms.
   Its BSD attribution is retained for the adapted metadata.
3. [HuC instruction reference](https://github.com/pce-devel/huc/wiki/HuC6280-Instruction-Set)
   is useful for unusual instructions, but ambiguous/unverified entries need
   checks against implementations and eventually hardware. An ordinary 65C02
   suite is not a HuC6280 oracle.
4. [Mesen CPU instructions](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp)
   independently clarify such cases as clear-register flag preservation,
   stack use, special instructions and the phase of a speed change.
5. [Mesen CPU implementation](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.cpp)
   and [memory manager](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceMemoryManager.cpp)
   are reference implementations for future bus and scheduling work. None of
   their GPL code is linked into this runtime.
6. [System Card IPL notes](https://github.com/pce-devel/huc/blob/54f5c73606c1e7142e8095c727cab2767e2b3cb3/examples/asm/elmer/doc/syscard-cd-ipl.txt)
   describe the boot-loader flow, MPR setup and initial program parameters.
   The reference disassembly itself is not bundled.
7. [llvm-mos PCE target](https://llvm-mos.org/wiki/PCE_target) and its
   [pce-mkcd implementation](https://github.com/llvm-mos/llvm-mos-sdk/blob/327de902ffc49f8455ca5447b7682bc77be5de05/utils/pce-mkcd/pce-mkcd.cc)
   provide a second practical source for IPL parameter endianness, RAM bank
   layouts and authored homebrew input generation. This SDK targets the
   original machine; it is not a host static recompiler.
8. [MAME CD layout code](https://github.com/mamedev/mame/blob/da9333a2a5123012a939e78c3f2df7175ea7d100/src/lib/util/cdrom.cpp)
   distinguishes physical/logical disc time and padded CHD frames. The
   baseline parser tests stored and virtual pregaps separately.

Research found several reasons to reject shortcuts: the T flag is not an
ordinary spare status bit; block transfers have special register/stack and
timing behavior; TAM/TMA are not interchangeable fixed bank accesses; and
CSL/CSH have a speed-change phase within the instruction. These need focused
semantics before native support. The baseline explicitly omits them where
their full behavior is not implemented.

## Useful existing tools

| Tool | Why it helps | Integration / limitations |
|---|---|---|
| [libchdr](https://github.com/rtissera/libchdr/tree/47d794151b2b64f6aba60304e6480f4f5a2bc24b) | Established CHD decompression, including CD codecs | Optional, pinned, project-local backend; four-hunk cache; exercised on the local input |
| [MAME chdman](https://docs.mamedev.org/tools/chdman.html) | Independent inspection, verification and ranged extraction | Useful external cross-check; not installed or required by this baseline |
| [Geargrafx](https://github.com/drhelius/Geargrafx/tree/57c257dda25f441fff3c63a63bbc4ba7cbb713e3) and its [MCP interface](https://github.com/drhelius/Geargrafx/blob/57c257dda25f441fff3c63a63bbc4ba7cbb713e3/MCP_README.md) | Headless execution, stepping, registers, memory and hardware traces through MCP | Optional isolated reference process; see the exact current check in [REFERENCE.md](REFERENCE.md) |
| [Mesen2](https://github.com/SourMesen/Mesen2/tree/b9fa69ddc6d0a331fb103fdb5eef6904305703c2) | PCE debugger, CPU/PPU state and a separately developed implementation | Candidate second oracle; no adapter or executable session was run here |
| [Beetle PCE](https://github.com/libretro/beetle-pce-libretro/tree/b96c11e095b6a40a412d2da02766ae1c3f4fd539) | Mednafen-derived reference with CD/SuperGrafx support | Candidate device/frame/audio oracle; use the accurate PCE core rather than assume Fast is equivalent |
| [HuC](https://github.com/pce-devel/huc/tree/54f5c73606c1e7142e8095c727cab2767e2b3cb3) | Compiler/assembler ecosystem and hardware/CD examples | Candidate authored diagnostic producer; not used as a host recompilation backend |
| [llvm-mos SDK](https://github.com/llvm-mos/llvm-mos-sdk/tree/327de902ffc49f8455ca5447b7682bc77be5de05) | Modern original-target C/assembly, linking and CD building | Useful for reproducible synthetic programs after toolchain pinning |
| [huc6280disasm](https://github.com/andlabs/huc6280disasm/tree/b5c9178faaabef0412b6a8c683c12fe8b6172c12) | Existing bank-aware disassembly work | GPL research/cross-check candidate; implementation is not copied into the MIT frontend |
| [PCE_Soundtest](https://github.com/pce-devel/PCE_Soundtest/tree/a3c987d6caefe90d7abbd082002a823d22946af4) | Authored test for HuC6280/6280A sound differences | Future audio/hardware revision qualification; not a CPU conformance suite |
| [oss-pce-cd-bios](https://github.com/mao2009/oss-pce-cd-bios/tree/f90c16b6ca7b3cd6f0ee66935aa08d43c329628d) | Open System Card work, synthetic CD-to-RAM diagnostics and Geargrafx evidence patterns | Development firmware, explicitly not an established compatible BIOS; investigate collaboration/reuse by file and license |
| [SDL3](https://wiki.libsdl.org/SDL3/README-migration) | Portable future window, gamepad and audio host | Planned; no SDL dependency or desktop renderer added to the core yet |

Geargrafx 1.8.4 was obtained as a portable development dependency and its
archive SHA256 checked against GitHub's release-asset digest. It runs only
on synthetic input in this project. The current main-source research pin
and the release executable are distinct identities; they must not be
conflated.

## Tooling decisions and unresolved research

Context7 was used to resolve `/kitware/cmake` and check target C++20 features,
CTest registration and Python interpreter discovery against current CMake
documentation. Hardware facts come from source/hardware documentation,
rather than treating a library-documentation search as an ISA oracle.

A generic 6502 decoder or an unsupported Ghidra/IDA processor assumption
would lose HuC6280-specific instructions and mapping context. The project's
small explicit decoder is the baseline. Reverse-engineering integrations
can be added once their CPU language and bank model are verified.

Still open: exact System Card revision/calling conventions; broader IPL
addressing and loader behavior; independent cycle and IRQ evidence; real
hardware CPU edge cases; CD command/event ordering; audio revision behavior;
SGX/Arcade Card profiles; and a supported public diagnostic corpus. No
single reference emulator will settle every hardware dispute.

The license boundary also affects architecture: the two requested frameworks
currently use PolyForm Noncommercial terms, while several emulator references
use GPL. This project takes design lessons, retains the BSD opcode notice,
and keeps independent GPL reference processes outside its MIT runtime.
