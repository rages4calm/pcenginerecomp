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
bringing total execution support to 159.

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
apply only where the instruction encoding provides them. Indirect JMP,
read/modify/write shifts/rotates and INC/DEC, BIT/TSB/TRB/TST, bit branches,
block transfers and interrupts remain separate unfinished families.

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
internal comparison matrix has 10,176 cases across 159 opcodes.

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
  all 97 data base totals agree in a source-level check; live cycle parity
  remains outside the reference adapter's scope.
- [Mesen status setter](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.h)
  and [instructions](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp):
  independent source cross-check; Mesen was not executed in this batch.
- [MAME HuC6280 source](https://github.com/mamedev/mame/blob/da9333a2a5123012a939e78c3f2df7175ea7d100/src/devices/cpu/h6280/h6280.cpp):
  instruction totals and the alternative live-B representation.

No GPL CPU implementation is copied or linked into this runtime. The
reference emulator remains a separately supplied process.
