# Bit and stack execution contracts

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
PLP clear T in the usual way. A later T-sensitive ALU implementation must
consume its entry T value; those ALU operations are not implemented here.

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

Unmapped or device stack/zero-page accesses remain explicit fatal bus
faults, and writes to ROM are rejected. A pull can read ROM, as any ordinary
mapped read can. A fault does not retire an instruction; it is not a resumable
transaction and does not promise rollback of a partially advanced SP.

Native source and mapping guards run before the instruction body. Tests cover
modified bit operands, correct fallback to their current address, MPR1
stack remapping, a second logical alias of work RAM, and writes observed
through that alias. Per-bank generations change only when stored bytes change;
an unchanged bit value still retires the instruction with its normal cycles.

## Evidence

The C++ suite checks 92,160 independently expected bit/stack cases in
addition to the full native/interpreter comparison matrix. It covers every
incoming status byte for bit operations, every byte to push/pull, SP
`$00/$01/$FE/$FF`, negative/zero preservation, cycle totals and both clock
divisors. Additional focused tests check faults, ROM access, aliases, source
guards and PLP → PHP / PLP → NOP sequences.

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
- [Mesen status setter](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.h)
  and [instructions](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/PCE/PceCpu.Instructions.cpp):
  independent source cross-check; Mesen was not executed in this batch.
- [MAME HuC6280 source](https://github.com/mamedev/mame/blob/da9333a2a5123012a939e78c3f2df7175ea7d100/src/devices/cpu/h6280/h6280.cpp):
  instruction totals and the alternative live-B representation.

No GPL CPU implementation is copied or linked into this runtime. The
reference emulator remains a separately supplied process.
