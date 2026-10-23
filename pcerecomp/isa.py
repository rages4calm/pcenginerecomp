"""HuC6280 decoding. Instruction facts checked against MAME and Hudson docs.

All 256 slots have explicit metadata; unassigned opcodes are never executed
as NOPs. Metadata completeness is not execution support.
"""

from dataclasses import asdict, dataclass

_ROWS = """
BRK.imp ORA.idx SXY.imp ST0.imm TSB.zpg ORA.zpg ASL.zpg RMB0.zpg PHP.imp ORA.imm ASL.acc ILL.non TSB.abs ORA.abs ASL.abs BBR0.zrl
BPL.rel ORA.idy ORA.zpi ST1.imm TRB.zpg ORA.zpx ASL.zpx RMB1.zpg CLC.imp ORA.aby INA.imp ILL.non TRB.abs ORA.abx ASL.abx BBR1.zrl
JSR.abs AND.idx SAX.imp ST2.imm BIT.zpg AND.zpg ROL.zpg RMB2.zpg PLP.imp AND.imm ROL.acc ILL.non BIT.abs AND.abs ROL.abs BBR2.zrl
BMI.rel AND.idy AND.zpi ILL.non BIT.zpx AND.zpx ROL.zpx RMB3.zpg SEC.imp AND.aby DEA.imp ILL.non BIT.abx AND.abx ROL.abx BBR3.zrl
RTI.imp EOR.idx SAY.imp TMA.imm BSR.rel EOR.zpg LSR.zpg RMB4.zpg PHA.imp EOR.imm LSR.acc ILL.non JMP.abs EOR.abs LSR.abs BBR4.zrl
BVC.rel EOR.idy EOR.zpi TAM.imm CSL.imp EOR.zpx LSR.zpx RMB5.zpg CLI.imp EOR.aby PHY.imp ILL.non ILL.non EOR.abx LSR.abx BBR5.zrl
RTS.imp ADC.idx CLA.imp ILL.non STZ.zpg ADC.zpg ROR.zpg RMB6.zpg PLA.imp ADC.imm ROR.acc ILL.non JMP.ind ADC.abs ROR.abs BBR6.zrl
BVS.rel ADC.idy ADC.zpi TII.blk STZ.zpx ADC.zpx ROR.zpx RMB7.zpg SEI.imp ADC.aby PLY.imp ILL.non JMP.iax ADC.abx ROR.abx BBR7.zrl
BRA.rel STA.idx CLX.imp TST.imz STY.zpg STA.zpg STX.zpg SMB0.zpg DEY.imp BIT.imm TXA.imp ILL.non STY.abs STA.abs STX.abs BBS0.zrl
BCC.rel STA.idy STA.zpi TST.ima STY.zpx STA.zpx STX.zpy SMB1.zpg TYA.imp STA.aby TXS.imp ILL.non STZ.abs STA.abx STZ.abx BBS1.zrl
LDY.imm LDA.idx LDX.imm TST.izx LDY.zpg LDA.zpg LDX.zpg SMB2.zpg TAY.imp LDA.imm TAX.imp ILL.non LDY.abs LDA.abs LDX.abs BBS2.zrl
BCS.rel LDA.idy LDA.zpi TST.imx LDY.zpx LDA.zpx LDX.zpy SMB3.zpg CLV.imp LDA.aby TSX.imp ILL.non LDY.abx LDA.abx LDX.aby BBS3.zrl
CPY.imm CMP.idx CLY.imp TDD.blk CPY.zpg CMP.zpg DEC.zpg SMB4.zpg INY.imp CMP.imm DEX.imp ILL.non CPY.abs CMP.abs DEC.abs BBS4.zrl
BNE.rel CMP.idy CMP.zpi TIN.blk CSH.imp CMP.zpx DEC.zpx SMB5.zpg CLD.imp CMP.aby PHX.imp ILL.non ILL.non CMP.abx DEC.abx BBS5.zrl
CPX.imm SBC.idx ILL.non TIA.blk CPX.zpg SBC.zpg INC.zpg SMB6.zpg INX.imp SBC.imm NOP.imp ILL.non CPX.abs SBC.abs INC.abs BBS6.zrl
BEQ.rel SBC.idy SBC.zpi TAI.blk SET.imp SBC.zpx INC.zpx SMB7.zpg SED.imp SBC.aby PLX.imp ILL.non ILL.non SBC.abx INC.abx BBS7.zrl
""".split()

_LENGTH = {"imp": 1, "acc": 1, "non": 1, "imm": 2, "zpg": 2, "zpx": 2,
           "zpy": 2, "idx": 2, "idy": 2, "zpi": 2, "rel": 2, "abs": 3,
           "abx": 3, "aby": 3, "ind": 3, "iax": 3, "zrl": 3, "imz": 3,
           "izx": 3, "ima": 4, "imx": 4, "blk": 7}
BRANCHES = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"}
# Block transfers, interrupt entry/return and device operations remain explicit.
NATIVE = {0xEA, 0xA9, 0xA2, 0xA0, 0x85, 0x8D, 0xA5, 0xAD, 0x64, 0x9C,
          0xE8, 0xCA, 0xC8, 0x88, 0xAA, 0xA8, 0x8A, 0x98, 0xBA, 0x9A,
          0x18, 0x38, 0x58, 0x78, 0xD8, 0xF8, 0xB8, 0xF4, 0x62, 0x82,
          0xC2, 0x02, 0x22, 0x42, 0x53, 0x4C, 0x20, 0x60, 0x80,
          0x10, 0x30, 0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0}
BIT_OPCODES = frozenset(range(0x07, 0x100, 0x10))  # RMB0..7, SMB0..7
STACK_OPCODES = frozenset({0x08, 0x28, 0x48, 0x68, 0x5A, 0x7A, 0xDA, 0xFA})
NATIVE |= BIT_OPCODES | STACK_OPCODES
DATA_MNEMONICS = frozenset({"LDA", "LDX", "LDY", "STA", "STX", "STY", "STZ",
                            "ORA", "AND", "EOR", "ADC", "SBC", "CMP", "CPX", "CPY"})
DATA_OPCODES = frozenset(i for i, row in enumerate(_ROWS) if row.split(".")[0] in DATA_MNEMONICS)
NATIVE |= DATA_OPCODES
RMW_OPCODES = frozenset(i for i, row in enumerate(_ROWS)
                        if row.split(".")[0] in {"ASL", "LSR", "ROL", "ROR", "INC", "DEC", "INA", "DEA"})
INDIRECT_JUMP_OPCODES = frozenset({0x6C, 0x7C})
NATIVE |= RMW_OPCODES | INDIRECT_JUMP_OPCODES
TEST_OPCODES = frozenset(i for i, row in enumerate(_ROWS) if row.split(".")[0] in {"BIT", "TSB", "TRB", "TST"})
BIT_BRANCH_OPCODES = frozenset(range(0x0F, 0x100, 0x10))
NATIVE |= TEST_OPCODES | BIT_BRANCH_OPCODES | {0x44}  # BSR
NATIVE.add(0x43)  # TMA, including zero/multiple selector bits
NATIVE |= {0x54, 0xD4}  # CSL/CSH, including final-cycle speed transition
NATIVE |= {0x03, 0x13, 0x23}  # Dedicated VDC immediate writes, independent of MPRs


@dataclass(frozen=True)
class Instruction:
    pc: int
    physical: tuple[int, ...]
    data: tuple[int, ...]
    mnemonic: str
    mode: str
    target: int | None

    @property
    def next_pc(self):
        return (self.pc + len(self.data)) & 0xFFFF

    @property
    def native(self):
        return self.data[0] in NATIVE

    def report(self):
        return asdict(self) | {"native_supported": self.native}


def physical(pc: int, mpr: tuple[int, ...]) -> int:
    return (mpr[(pc & 0xFFFF) >> 13] << 13) | (pc & 0x1FFF)


def decode(read, pc: int, mpr: tuple[int, ...]) -> Instruction:
    pc &= 0xFFFF
    opcode = read(pc)
    mnemonic, mode = _ROWS[opcode].split(".")
    size = _LENGTH[mode]
    data = tuple(read((pc + n) & 0xFFFF) for n in range(size))
    target = None
    if mode in ("rel", "zrl"):
        offset = data[-1] if data[-1] < 128 else data[-1]-256
        target = (pc + size + offset) & 0xFFFF
    elif mnemonic in ("JMP", "JSR") and mode == "abs":
        target = data[1] | data[2] << 8
    return Instruction(pc, tuple(physical(pc+n, mpr) for n in range(size)), data, mnemonic, mode, target)


def listing(ins: Instruction) -> str:
    raw = " ".join(f"{x:02X}" for x in ins.data)
    args = " ".join(f"{x:02X}" for x in ins.data[1:])
    target = f" -> ${ins.target:04X}" if ins.target is not None else ""
    return f"{ins.physical[0]:06X} ${ins.pc:04X}  {raw:<20} {ins.mnemonic:<5} {args}{target}"
