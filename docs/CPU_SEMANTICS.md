# CPU execution contracts

The native emitter and interpreter implement the following HuC6280
instructions. Both use the same architectural state and bus, but independently
written operation bodies. These contracts describe instruction-level behavior;
bus phases, wait states and interrupt delivery are still outside the sandbox.

| Instructions | Operation | Flags after retirement | CPU cycles |
|---|---|---|---|
| RMB0..RMB7 | Read logical `$2000 + operand`, clear selected bit, write that byte | T cleared; other flags preserved | 7 |
| SMB0..SMB7 | Read logical `$2000 + operand`, set selected bit, write that byte | T cleared; other flags preserved | 7 |
| PHA / PHX / PHY | Write register to `$2100 + SP`, then decrement the byte SP | T cleared; other flags preserved | 3 |
| PHP | Write `(P OR $10) AND $DF` to the stack, then decrement SP | T cleared; other live flags preserved | 3 |
| PLA / PLX / PLY | Increment byte SP, read `$2100 + SP`, store in register | N/Z from value; T cleared; others preserved | 4 |
| PLP | Increment byte SP, read status, restore `saved AND $EF` | T and other actual flags restored; live B represented as zero | 4 |

SP wraps modulo 256 in both directions. Stack and zero-page accesses go
through **MPR1**, including aliases and remapping; the physical work-RAM bank
is not hardcoded into instruction bodies. Ordinary instructions following
PLP clear T in the usual way. T-sensitive ALU operations consume the entry
T value as described below.

## Load/store and ALU addressing

All encodings of LDA/LDX/LDY, STA/STX/STY/STZ, ORA/AND/EOR, ADC/SBC and
CMP/CPX/CPY are implemented in both execution tiers (97 encodings, including
nine previously supported load/store encodings). The batch adds 88 opcodes,
bringing that batch's execution support to 159; the subsequent RMW/JMP batch
brings support to 191, and the bit-test/branch/BSR batch brings it to 221.

| Mode | Effective address / operand | Base CPU cycles |
|---|---|---|
| Immediate | Fetched operand byte | 2 |
| Zero page | `$2000 OR operand` | 4 |
| Zero page X/Y | `$2000 OR ((operand + index) AND $FF)` | 4 |
| Absolute | Fetched little-endian word | 5 |
| Absolute X/Y | `(word + index) AND $FFFF` | 5 |
| `(zp,X)` | Read word at zero-page `(operand + X) AND $FF` | 7 |
| `(zp),Y` | `(word read at zero-page operand + Y) AND $FFFF` | 7 |
| `(zp)` | Read word at zero-page operand | 7 |

Both pointer bytes remain in logical `$2000..$20FF`; the high byte following
`$20FF` comes from `$2000`. Every data/pointer access uses its actual MPR.
There is no extra page-crossing cycle for these HuC6280 forms. These modes
apply only where the instruction encoding provides them. Block transfers,
interrupts, TMA, speed control and device-port instructions remain unfinished.

Loads update N/Z; stores preserve flags except ordinary T clearing.
Comparisons update N/Z from byte subtraction and set C when the register
is at least the operand. They preserve V, ignore D and do not use T's memory
destination.

## T mode and decimal arithmetic

Incoming T affects **ADC, AND, EOR and ORA only**. The ordinary operand is
read first. The other input comes from logical `$2000 OR X`, and the result
is written there while A is preserved. N/Z and arithmetic flags describe
that result. T adds three cycles and clears at retirement. SBC always uses
A, even with T set. SET and PLP can supply T for exactly the next instruction;
an intervening ordinary instruction consumes it without invoking memory mode.

ADC/SBC use incoming C and update C/N/Z. Binary arithmetic also computes V.
With D set, they perform nibble adjustment, preserve incoming V, derive N/Z
from the adjusted byte and add one cycle. Decimal and T surcharges combine
for ADC. Non-BCD input nibbles have defined byte-level behavior here; they
are not rejected or converted through an assumed valid decimal number.
The two tiers use separate arithmetic bodies. The exhaustive tests include
all byte pairs, C/D/T/V combinations and both tiers, with a separate digit
model for expected decimal results.

## Shifts, rotates, INC/DEC and indirect JMP

The RMW/JMP batch adds 32 encodings: ASL/LSR/ROL/ROR each have accumulator,
zero-page, zero-page X, absolute and absolute X forms; INC/DEC have four
memory forms each plus accumulator INA/DEA; JMP adds `(absolute)` and
`(absolute,X)` forms. Previously supported INX/INY/DEX/DEY remain unchanged.

| Family | Result and flags | CPU cycles |
|---|---|---|
| ASL / LSR | Shift byte left/right; shifted-out bit goes to C; N/Z from byte result | Accumulator 2; zero-page forms 6; absolute forms 7 |
| ROL / ROR | Rotate through incoming C; shifted-out bit becomes new C; N/Z from result | Accumulator 2; zero-page forms 6; absolute forms 7 |
| INC / DEC / INA / DEA | Add/subtract one modulo 256; update N/Z and preserve C | Accumulator 2; zero-page forms 6; absolute forms 7 |
| JMP `(abs)` / `(abs,X)` | Read a little-endian target through the bus; assign PC without fetching target code | 7 |

These operations clear T and do not invoke T's memory destination. D does
not alter them; V and the remaining unrelated flags are preserved. RMW
indexing follows the same byte/word wrapping rules as load/store addressing,
with no indexed page-crossing surcharge. Memory forms read and write the
same effective byte and preserve A; accumulator forms do not access data RAM.
This is an instruction-level effect, not a claim about hardware dummy accesses.

JMP's pointer is the encoded word, plus X for the indexed form, modulo
65,536. Its high byte comes from `(pointer + 1) AND $FFFF`, with each byte
using its own MPR. There is no NMOS 6502 same-page high-byte wrap. Pointer
bytes stay live data in generated code, so table changes take effect without
regeneration. Static CFG discovery still reports an unresolved indirect edge;
runtime support does not establish a static target or compile that target.

## Bit tests, bit branches and BSR

| Family | Operation and flags | CPU cycles |
|---|---|---|
| BIT, including immediate | N/V from operand bits 7/6; Z from `(A AND operand)==0` | Immediate 2; zero-page forms 4; absolute forms 5 |
| TSB / TRB | Store `old OR A` / `old AND NOT A`; N/V from original memory; Z from the stored result | Zero page 6; absolute 7 |
| TST | N/V from memory; Z from `(immediate mask AND memory)==0`; A unchanged | Zero-page forms 7; absolute forms 8 |
| BBR0..7 / BBS0..7 | Read selected zero-page bit; branch if clear/set; flags preserved except T | Not taken 6; taken 8 |
| BSR | Push the operand address high byte then low byte; branch relative to next PC | 8 |

All clear T without invoking a T-mode destination; unrelated flags remain
unchanged. In particular, HuC6280 BIT immediate updates N/V, and TSB/TRB's Z
describes the stored result, unlike ordinary 65C02 expectations. Decimal mode
does not change these operations. TST uses three or four fetched bytes and
zero-page/absolute X wrapping as appropriate. Both tiers fetch/guard the
complete instruction before performing its operation.

Bit-branch displacement is signed and relative to PC after all three bytes.
BSR uses the same signed-byte convention with its two-byte length, preserves
registers, and wraps SP through the normal guest stack. RTS adds one to BSR's
saved operand address to recover the next instruction. Native CFG discovery
retains BSR call and return-site edges; it does not prove that a call returns.

## B and T representation

PHP clears T before creating the saved status byte and sets its B marker.
PLP may restore T; it is deliberately exempt from the ordinary retirement
clear. The restored status uses B=0 internally, matching Geargrafx 1.8.4 and
Mesen. MAME instead keeps B=1 internally. This representation difference was
detected by a failing Geargrafx comparison during implementation, investigated
in the pinned sources, and resolved without masking debugger status bits.
This is not a claim that an emulator's internal representation is a hardware
register implementation. Saved PHP status still contains B=1.

No runtime struct/layout or native-module ABI change is needed: these
opcodes previously exited as unsupported. Runtime ABI remains 1. Old
generated modules do not acquire new instruction bodies automatically;
regenerate them to gain native coverage. The updated interpreter can still
handle supported instructions that an older module did not emit.

## Faults and mutation safety

Unmapped or device stack/zero-page/data accesses remain explicit fatal bus
faults, and writes to ROM are rejected. A pull can read ROM, as any ordinary
mapped read can. A fault does not retire an instruction; it is not a resumable
transaction and does not promise rollback of a partially advanced SP.

Native source and mapping guards run before the instruction body. Tests cover
modified bit operands, correct fallback to their current address, MPR1
stack remapping, a second logical alias of work RAM, and writes observed
through that alias. Per-bank generations change only when stored bytes change;
an unchanged bit value still retires the instruction with its normal cycles.
The data tests also cover T source/destination aliases, SET/PLP sequences,
ROM write refusal, mutated absolute operands and interpreter fallback across
a 16-bit indexed-address wrap. No fault retires an instruction; arithmetic
flags changed before a failed write are not rolled back.

## Evidence

The C++ suite checks 92,160 independently expected bit/stack cases in
addition to the full native/interpreter comparison matrix. It covers every
incoming status byte for bit operations, every byte to push/pull, SP
`$00/$01/$FE/$FF`, negative/zero preservation, cycle totals and both clock
divisors. Additional focused tests check faults, ROM access, aliases, source
guards and PLP → PHP / PLP → NOP sequences.

The data batch adds 7,340,032 independently expected arithmetic/logic cases
and 340 load/store addressing cases. ADC/SBC sweep every pair of operand
bytes and all 16 C/D/T/V combinations in each tier; logical operations and
comparisons sweep every byte pair under four flag contexts. The full
internal comparison matrix now has 14,144 cases across 221 opcodes.

The RMW/JMP batch checks 3,932,160 expected-value cases: every input byte
and incoming status byte for all 30 RMW encodings in both tiers. The matrix
covers zero-page wrapping, absolute page crossings, carry-in/out, unaffected
flags, T non-redirection, both clock divisors, neighbors and write generations.
Another 16,384 expected indirect-JMP cases cover status preservation,
multiple indices/targets and a deliberately different NMOS-style high byte.
Additional source-guarded native fixture sites exercise pointer and indexed
address wrap at `$FFFF`, crossing `$3FFF/$4000` between MPRs, mutable jump
tables, missing high-pointer bytes, RMW ROM/device faults and operand mutation.

The bit-test/branch/BSR batch adds 4,849,664 expected bit-test cases and
2,228,224 expected branch/BSR cases across both tiers. These cover all byte
pairs under four flag contexts for memory BIT/TSB/TRB, every byte/status
combination for TST's compiled mask and BIT's compiled immediate, every
zero-page byte/status for bit branches, and all SP/status pairs for BSR.
Additional tests cover mutable TST masks, ROM/device faults and interpreted
signed target/fetch wrap. Fixed native immediates/masks are `$20`/`$55`;
this does not claim all possible native immediate encodings were tested.

The optional Geargrafx MCP suite uses four base vectors per opcode with
explicit zero-page and popped values. Each stack opcode has four more
directed vectors. The vector tests require both original states of every
bit and all four saved B/T combinations for PLP. See
[REFERENCE.md](REFERENCE.md) for the actual run results and limits.

## Primary references

- [HuC instruction reference](https://github.com/pce-devel/huc/wiki/HuC6280-Instruction-Set):
  opcode encodings, operation descriptions, flags and instruction cycle counts.
- [Geargrafx 1.8.4 opcode implementation](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_opcodes.cpp)
  and [CPU helpers](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_inline.h):
  independent runtime behavior, T clearing and status restoration.
- [Geargrafx arithmetic helpers](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_opcodes_inline.h):
  production HuC6280 T/decimal behavior; the `GG_TESTING` 65C02 alternatives
  are deliberately not the oracle configuration.
- [Geargrafx timing metadata](https://github.com/drhelius/Geargrafx/blob/1c62a549328241518101f5be5bf3e6840b96ea5d/src/huc6280_timing.h):
  all 97 data, 32 RMW/JMP and 30 bit-test/branch/BSR base totals agree in source-level checks; live cycle parity
  remains outside the reference adapter's scope.
- [Mesen status setter](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.h)
  and [instructions](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp):
  independent source cross-check; Mesen was not executed in this batch.
- [MAME HuC6280 source](https://github.com/mamedev/mame/blob/da9333a2a5123012a939e78c3f2df7175ea7d100/src/devices/cpu/h6280/h6280.cpp):
  instruction totals and the alternative live-B representation.

No GPL CPU implementation is copied or linked into this runtime. The
reference emulator remains a separately supplied process.
