# Sources and dependency terms

The original compiler/runtime code is MIT licensed. No SNESRecomp,
PSXRecomp, Mesen, Mednafen, HuC, or N64Recomp implementation is vendored or
linked into the baseline runtime. Architecture research does not change the
licenses of those projects.

The opcode/mode matrix in `pcerecomp/isa.py` follows the instruction facts and
layout of MAME's `src/devices/cpu/h6280/6280dasm.cpp`, checked at commit
`da9333a2a5123012a939e78c3f2df7175ea7d100`. Its attribution and BSD terms are
retained in [licenses/MAME-HuC6280.txt](licenses/MAME-HuC6280.txt).
Execution bodies were written for this project; the MAME CPU implementation
is not included.

CHD decompression is optional and uses a separately acquired **libchdr** at
`47d794151b2b64f6aba60304e6480f4f5a2bc24b` (BSD-3-Clause). Its bundled LZMA,
miniz, zstd and dr_flac dependencies keep their own notices. The source and
binary stay in ignored `.deps/` when the opt-in bootstrap script is used.
Any future binary distribution including this dependency must carry its
actual dependency notices. The baseline source repository ships no libchdr
binary or source archive.

The optional independent-reference harness controls a separately supplied
Geargrafx executable (GPL-3.0) through its MCP interface. The emulator is not
linked into this runtime or redistributed in this source repository. Use a
dedicated portable instance under `.deps/`; its own license remains in force.

SNESRecomp and PSXRecomp currently use PolyForm Noncommercial 1.0.0.
N64Recomp uses MIT; N64ModernRuntime and Mesen use GPL terms. They are
research references, not an interchangeable pool of MIT code. See the
revision-linked [research register](docs/RESEARCH.md).

Disc images, System Card firmware, generated game translations, extracted
assets, traces containing code, and owner save data are not part of this
repository or covered by its license. No game compatibility or distribution
rights are implied by a successful build.
