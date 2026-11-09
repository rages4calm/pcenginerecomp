# Declared roots alongside a real observed history

This authored example compiles code that its discovery run never executes. It
keeps numeric declarations separate from real retirement evidence, then checks a
later actual native call. No commercial game, firmware, installation or save is used.

From a committed, frozen toolkit checkout with a current headless runner, CMake
and a C++20 compiler:

```sh
python examples/declared-roots/workflow.py capture .local/my-declared-example --runner build/pce-headless
python examples/declared-roots/workflow.py prepare .local/my-declared-example
python examples/declared-roots/workflow.py qualify .local/my-declared-example --generator Ninja
python examples/declared-roots/workflow.py probe .local/my-declared-example
```

Use `build/pce-headless.exe` on Windows. Choose a new output directory. Explicit
compiler/build-tool settings may be forwarded with repeatable
`--cmake-arg=-DNAME=value` arguments to `qualify`. The probe uses the compiler and
runtime archive from that official consumer build. Keep all source and inputs
unchanged between stages; failed outputs remain for diagnosis.

## Authored control flow

The 8192-byte test card resets at logical `$E000`. It initializes MPR1 to `$F8`,
selects fast speed, sets SP to `$FF`, and polls WRAM `$2000`:

```text
LDA #$F8; TAM #$02; CSH; LDX #$FF; TXS
loop: LDA $2000; BEQ loop
      JSR $E040; BRA loop
$E040: LDA #42; STA $2001; STZ $2000; RTS
```

WRAM starts at zero, so the actual 100-instruction discovery window contains
seven identities and never reaches the JSR, following BRA or four routine
instructions. Six explicit numeric roots describe those instruction entries
using PC, all eight MPRs, selector zero and per-byte decoded-ROM offsets. The
source SHA/profile/header/encoding are bound. The declaration file has no opcode
bytes, retirement counts or checkpoint origin and does not claim execution.

`prepare` retains the exact real prefix as a history and composes it with those
six declarations into 13 guarded source identities. The original history remains
100 interpreted retirements. Compiling declarations does not increase that total.

## Actual execution checks

`qualify` uses the official preparation/build/run interfaces. Its cold 100-step
native-only run retires 100 native instructions with zero fallback or guard misses.
Its complete capture still contains only the seven observed identities: all six
declarations remain unexecuted in that window.

`probe` compiles a checker against the exact official runtime archive and module.
It first repeats the same 100 native instructions and compares all 8192 WRAM bytes
to zero. It then performs an explicitly developer-assisted WRAM flag write of one,
which does not retire guest instructions or change guest clocks. Ten subsequent
actual native instructions call the previously unexecuted routine and return to
the poll loop. All six declaration-only entries now appear with one actual native
hit each in a new real capture. The original history and declarations stay unchanged.

| Window | Retirements | PC | A / X / Y | SP / P | CPU cycles | Master ticks |
| --- | --- | --- | --- | --- | --- | --- |
| Cold prefix | 100 native | `$E00B` | 0 / 255 / 0 | 255 / 6 | 442 | 1407 |
| Triggered prefix + suffix | 110 native | `$E00B` | 0 / 255 / 0 | 255 / 6 | 488 | 1545 |

The five setup operations cost 14 cycles. The prefix then retires 48 five-cycle
LDA operations and 47 four-cycle taken branches: `14 + 48*5 + 47*4 = 442`.
Reset starts slow; the first nine cycles use divider 12 and the other 433 use
divider 3: `9*12 + 433*3 = 1407`. The ten suffix instructions cost 46 fast cycles.
These expectations are counted from the authored plan, not copied from results.

The final canonical WRAM is zero except byte 1 = 42, stack byte `$01FE = $0F`
and `$01FF = $E0`. The checker compares every byte. The stack contains the JSR
return address `$E00F`; RTS resumes at `$E010`.

A separate negative mode changes the routine's immediate operand in an in-memory
copy of the test card before configuring its sandbox. The original file remains
unchanged. After 104 real native retirements, dispatch at `$E040` refuses this
undeclared operand with one guard miss and no additional retirement or clocks.
This is a developer-assisted negative test, not a newly admitted source or a
qualified consumer using changed media.

This example establishes bounded compiler/runtime and provenance behavior. It
makes no independent emulator/hardware, player-input or game-completion claim.
Each numeric row declares one instruction entry; routine closure and reachability
are not inferred. See [declared-root input](../../docs/DECLARED_ROOTS.md).
