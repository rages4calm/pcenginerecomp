# Source-qualified register evaluation

Opt-in register evaluation preserves useful facts through arithmetic between a
ROM load and a bank change or indexed jump. It derives static candidates; it
does not replace generated operations with constants or predict writable memory.

```sh
python -m pcerecomp discover-roots seeds.json --image card.pce --rom-range 0:22 --rom-data-range 256:1 --alu-facts --out new-register-graph
```

These short code/data ranges are explicit permissions, not a complete game recipe.
Try the complete [authored native workflow](../examples/register-eval/README.md)
without a game or BIOS. Python callers pass `alu_facts=True` to `discover_roots`.
Only actual booleans are accepted. Omission/false preserves old policies and
artifact bytes. Data ranges, vector ranges, call depth and table limits remain
separate options with their existing bounds and source restrictions.

## Abstract operations and status

Each seed starts with unknown A/X/Y and carry/decimal/transfer (C/D/T) facts.
Register values are bytes or null; status facts are integer 0/1 or null.
The analyzer does not assume reset status or invent a declaration precondition.
Existing loads, register transfers/swaps, clears, increment/decrement and TMA
facts compose with these additional operations:

- ADC/SBC with known operands, carry and decimal mode.
- AND/ORA/EOR with known accumulator/operand and destination mode.
- Accumulator ASL/LSR and carry-dependent ROL/ROR.
- Binary CMP/CPX/CPY carry results, independent of decimal mode.
- Explicit CLC/SEC, CLD/SED and SET status transitions.

Immediate operands come from the instruction. Non-immediate ALU/compare operands
require separate `rom_data_ranges` permissions, with each indirect pointer byte
and terminal value independently bound under exact image/header/encoding/mapper/
MPR sources. Their addressing uses the existing ROM-data resolver. Code or vector
permission does not grant operand permission. RAM, I/O, undriven and Populous
writable sources remain unknown. See [ROM data permissions](ROM_DATA.md).

Decimal inference accepts only valid packed-BCD bytes (each nibble 0..9).
It evaluates decimal integer addition/subtraction, modulo 100, with decimal
carry/no-borrow. Invalid BCD operands remain unknown facts; runtime instructions
still execute their existing semantics. Unknown carry/decimal facts likewise
lose the dependent result. This is an explicit analysis restriction, not a
runtime opcode stub or a fault injected into guest execution.

SET-routed ADC/AND/ORA/EOR preserve A and operate on untracked direct-page memory.
They clear T afterward; ADC's resulting carry stays unknown. Unknown T joins
both possible destinations conservatively. SBC uses A independently of T under
the existing [Geargrafx 1.8.4 source contract](https://github.com/drhelius/Geargrafx/blob/1.8.4/src/huc6280_opcodes_inline.h)
and [Beetle source contract](https://github.com/libretro/beetle-pce-libretro/blob/master/mednafen/pce/huc6280.cpp).
No reference implementation was copied; arithmetic is independently written.

Ordinary instructions clear T; SET sets it; PLP/RTI restore unknown status.
Memory shifts invalidate carry without changing A. Other existing register-fact
barriers remain conservative, including stack-restored registers and block saves.
Facts from predecessors join component by component: disagreement becomes unknown
and retracts stale dependent bank/vector candidates. Table-index edge injection
preserves C/D/T. Branches are not pruned from inferred status; N/Z/V are not
abstractly tracked. General status-stack, interrupts, writable memory and routine
closure remain separate capabilities.

## Graph and consumer contract

The new policy is `bounded-source-qualified-register-eval-v1` with literal
`options.alu_facts: true`. It can compose existing ROM-load, vector, table and
bounded synchronous-call policies. Older readers reject the new identifier.
The exact three-file seed/roots/report closure remains unchanged.

Every retained node keeps the existing incoming `register_facts` and adds
incoming `flag_facts` (c/d/t). Its `register_evaluation` records outgoing registers,
outgoing flags and a reason when a supported fact cannot be inferred. Reasons
include unknown operand/accumulator/carry/decimal/transfer, invalid BCD, untracked
transfer destination, memory-shift carry and restored status. Successful reads
and partial/failed pointer prefixes remain in `rom_alu_operand`, separately from
ordinary `rom_data_load` witnesses.

Summary `register_evaluations` counts retained analysis states; the separate
`resolved_rom_alu_operands` / `unknown_rom_alu_operands` count retained operand
records. These are not guest work. A fact refusal is distinct from a later
control frontier, such as TAM needing unknown A.

Admission rederives all reads, register/status results, edges, counts and options
from original seeds and bound image. Edited metadata plus recomputed hashes cannot
authenticate a graph. Copying and [consumer preparation](DISCOVERY_CONSUMERS.md)
preserve the exact closure without invented execution hits. Generated operations
continue to use live CPU/bus state and ordinary full source/MPR guards.

## Verification and limits

Frozen `911ef040a1f527a10da01e456d860d66a1f9c5b4` passes **2,200 Python tests
without skips, 74 C++ suites and 12 fresh-process audio cases**, with all 780
tracked inputs unchanged. SDK SHA256
`45b406b5ccd1d785aaee8f283cae72e4d7efedafa92ab1b71e8c215741bbc3ef`
covers 96 source files. Later publication changes are Markdown only.

Ten evaluator tests check 501,568 independently expected binary/valid-BCD/logic/
comparison/shift cases plus status and unknown-fact checks. Twelve discovery tests
cover bank recovery, conservative carry/T joins, status restoration, 48 ALU memory
addressing combinations, permissions, table/call composition, exact copying,
strict options and tamper rederivation. Three workflow tests include compilation
and native execution. Twenty-four legacy graphs are byte-identical to `459eb199`;
that reader separately rejects the new policy.

The authored main route expands seven candidates to 24 and executes all 24
natively, with zero interpretation or guards, 88 cycles and 1056 master ticks.
Separate native/reference main probes and 280-case matrices match literal full
CPU/flags/MPR/clocks, all 8192 WRAM bytes and exact encoded source identities/hits.
The matrix executes 1992 instructions per tier. All 2016 derived source identities
are exercised across these separate windows, not one continuous guest route.
The combined 281-seed graph retains 109 ROM-operand and two ROM-load witnesses.

A changed private operand copy changes the actual native decimal result without
fallback. Changed bank/instruction-source copies stop after seven/fourteen native
respectively, each zero interpreted/one guard, with no added guest work/clocks
or memory effects at refusal. Original inputs stay unchanged. Windows probes
link the official archive and checked packaged DLLs without SDK PATH.

Fresh Geargrafx 1.8.4 independently matches all 281 authored main/matrix cases on
CPU/PC/flags/MPR and full WRAM. All 1,678 known outgoing register/status
components match those independent endpoints; eight T-ADC carry facts stay
intentionally unknown. The reference bootstrap preserves every compiled source
byte and operand witness. Reference-only bootstrap and host presets are
separate. Failed harness setup attempts retain their failed status; they are not
qualification. This does not establish external clocks, bus/devices, audio/video,
retail or hardware parity.

A separate fresh Rondo TCP/checkpoint regression repeats boot/file creation/
introduction: 404,669,933 native/zero interpreted/zero guards, 25,621 exact keys/hits,
17 reported-state/full-WRAM/full-CD-RAM/completed-RGB samples, plus matching
59,672-instruction/753-key same-build checkpoint forks. Imported 379,716,149-native
prefix work remains separate. Raw paired journals/no writes, full memory bytes
and independent PNG CRC/pixel decoding pass after closure. Original captures and
expectations keep their producers. This is not retail register-evaluation policy
qualification, playable action or full-game/audio/hardware evidence. Host audio
is off and Ys III remains parked.

Runtime C++/emitter, ABI 29 and checkpoint encoding are unchanged. New source,
package or build contexts still need fresh exact-build checkpoints.

Qualification here uses Windows x64 LLVM-MinGW/Ninja. Other host/compiler paths
were not qualified by this batch.
