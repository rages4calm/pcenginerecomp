# Authored capture-to-native workflow

This example exercises the supported toolkit pipeline without a commercial game,
System Card dump, private scripts, or another project's files. It creates its own
256 KiB test card. The generated card, captures, modules and receipts belong in
an ignored local directory.

From the toolkit root, with a built `pce-headless` runner and CMake on `PATH`:

```powershell
python examples/native-workflow/workflow.py capture .local/my-native-workflow --runner build/pce-headless.exe
python examples/native-workflow/workflow.py prepare .local/my-native-workflow
python examples/native-workflow/workflow.py qualify .local/my-native-workflow --generator Ninja
python examples/native-workflow/workflow.py probe .local/my-native-workflow
```

Choose a new output directory. Capture and build inputs remain read-only after
creation. `qualify` also accepts repeatable `--cmake-arg=-DNAME=value` arguments
supported by the official project builder, for example an explicit C++ compiler
or Ninja path. Keep the toolkit revision and source unchanged between preparation
and qualification; a changed pin requires a fresh preparation/build directory.

`capture` executes two bounded 200/202-instruction windows in the interpreter
through the real headless host and saves original captures plus process output.
It checks every observed logical PC, eight-register MPR map, physical source
address, byte sequence and hit count against an authored boundary plan. There
are 27 identities across five full MPR contexts, including System Card ROM
aliases and two byte variants at the same writable-RAM PC under the same map.

The guest sets up RAM and its stack, copies a six-byte routine from ROM with
`TII`, calls it with `JSR`, changes its immediate operand from `$11` to `$2A`, and
calls it again. Both variants must execute. A finite `INX`/`BRA` loop gives a
repeatable endpoint. This tests actual writable code rather than relabelling an
interpreter run as native work.

`prepare` first creates the retained inline observation profile from the genuine
200-instruction capture. It imports that profile into a self-contained history
and appends the genuine 202-instruction capture as a later discovery stage. The
second window adds no identities: both originals and all 402 historical
interpreter hits remain present, while selected contributions remain the first
window's 200 hits. The generic `prepare-project` API emits translated C++, copies
the exact history graph and writes a pinned native consumer descriptor.
Preparation alone is neither compilation nor execution evidence.

`qualify` uses the official project builder and runner. The expected result is
200 actual native retirements, zero interpreter retirements and zero source
guard misses. `probe` compiles a small checker against that build's runtime
archive and the same generated module. It checks every canonical work-RAM byte,
then starts a separate run and host-writes an uncaptured `$7F` operand before
the first RAM routine call. Native-only dispatch must refuse that third source
variant without retiring an instruction or changing CPU clocks. This mutation
is a developer-assisted negative test, not a guest execution capture.

The endpoint expectations are literal, independently counted from this program:

| Window | PC | A | X | Y | SP | P | CPU cycles | Master ticks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 200 | `$E035` | 64 | 87 | 0 | 255 | 4 | 677 | 2238 |
| 202 | `$E035` | 64 | 88 | 0 | 255 | 4 | 683 | 2256 |

The prefix executes 27 instructions in 159 cycles. Its first 21 cycles run at
the slow 12-tick divider; `CSH` uses two slow cycles and one fast cycle. The
remaining 173 instructions in the 200-window are 87 two-cycle `INX` operations
and 86 four-cycle `BRA` operations. Thus `159 + 87*2 + 86*4 = 677` cycles and
`677*3 + 23*9 = 2238` ticks. The full MPR map is
`FF F8 00 00 00 00 00 40`.

Canonical 8 KiB work RAM is zero except `$0030..$0032 = 2A 11 2A`, stack residue
`$01FD..$01FF = FF 27 E0`, and final routine
`$0200..$0205 = A9 2A 8D 30 20 60`. The stack contains the block-transfer's saved
X and the second call's return address. The separate C++ probe compares all
8192 bytes, not just these selected locations.

This is bounded compiler/runtime and provenance qualification. It does not
claim independent emulator parity, broad console compatibility, frame rendering
or game progression. Failed process/build/probe logs remain in their original
directory. No ROM, capture, generated game source or receipt should be committed.
