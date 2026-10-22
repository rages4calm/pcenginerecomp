"""Emit direct C++ statements, never a call to the interpreter per opcode."""
import json
from pathlib import Path

from .isa import NATIVE, DATA_OPCODES, RMW_OPCODES, INDIRECT_JUMP_OPCODES
from .data_ops import data_body


def body(ins: dict) -> tuple[str, str]:
    op, *args = ins["data"]
    lo = args[0] if args else 0
    word = (lo | args[1] << 8) if len(args) > 1 else lo
    next_pc = (ins["pc"] + len(ins["data"])) & 0xFFFF
    cycles = "2"
    code = ""
    if op in DATA_OPCODES:
        code, cycles = data_body(ins)
    elif op in RMW_OPCODES:
        mode, name = ins["mode"], ins["mnemonic"]
        accumulator = mode in ("imp", "acc")
        if accumulator:
            code = "auto value=s.a; "
        else:
            address = {"zpg": str(0x2000 | lo),
                       "zpx": f"0x2000|static_cast<std::uint8_t>({lo}+s.x)",
                       "abs": str(word), "abx": f"static_cast<std::uint16_t>({word}+s.x)"}[mode]
            code = f"auto address={address}; auto value=bus.read(s,address); "
            cycles = "6" if mode in ("zpg", "zpx") else "7"
        expression = {"ASL": "value*2", "LSR": "value/2", "ROL": "value*2+(s.p&C)",
                      "ROR": "value/2+((s.p&C)*128)", "INC": "value+1", "INA": "value+1",
                      "DEC": "value-1", "DEA": "value-1"}[name]
        code += f"auto result=static_cast<std::uint8_t>({expression}); "
        code += "s.a=result; " if accumulator else "bus.write(s,address,result); "
        if name in ("ASL", "LSR", "ROL", "ROR"):
            carry = "value>=128" if name in ("ASL", "ROL") else "value&1"
            code += f"s.p=static_cast<std::uint8_t>((s.p&~C)|(({carry}) ? C:0)); "
        code += "s.nz(result);"
    elif op in INDIRECT_JUMP_OPCODES:
        pointer = str(word) if op == 0x6C else f"static_cast<std::uint16_t>({word}+s.x)"
        code = f"auto pointer={pointer}; auto low=bus.read(s,pointer); "
        code += "auto high=bus.read(s,static_cast<std::uint16_t>(pointer+1)); s.pc=static_cast<std::uint16_t>(low|(high<<8));"
        next_pc, cycles = None, "7"
    elif op & 0x0F == 0x07:
        mask = 1 << ((op >> 4) & 7)
        operation = f"value | {mask}" if op & 0x80 else f"value & {255 ^ mask}"
        code = f"auto value=bus.read(s,{0x2000 | lo}); bus.write(s,{0x2000 | lo},static_cast<std::uint8_t>({operation}));"
        cycles = "7"
    elif op in (0x48, 0xDA, 0x5A):
        reg = {0x48: "a", 0xDA: "x", 0x5A: "y"}[op]
        code = f"push(bus,s,s.{reg});"
        cycles = "3"
    elif op == 0x08:
        code = "push(bus,s,static_cast<std::uint8_t>((s.p | B) & ~T));"
        cycles = "3"
    elif op in (0x68, 0xFA, 0x7A):
        reg = {0x68: "a", 0xFA: "x", 0x7A: "y"}[op]
        code = f"s.{reg}=pop(bus,s); s.nz(s.{reg});"
        cycles = "4"
    elif op == 0x28:
        code = "s.p=static_cast<std::uint8_t>(pop(bus,s) & ~B);"
        cycles = "4"
    elif op in (0xE8, 0xCA, 0xC8, 0x88):
        reg = "x" if op in (0xE8, 0xCA) else "y"
        change = "++" if op in (0xE8, 0xC8) else "--"
        code = f"{change}s.{reg}; s.nz(s.{reg});"
    elif op in (0xAA, 0xA8, 0x8A, 0x98, 0xBA, 0x9A):
        dest, src = {0xAA: ("x", "a"), 0xA8: ("y", "a"), 0x8A: ("a", "x"),
                     0x98: ("a", "y"), 0xBA: ("x", "sp"), 0x9A: ("sp", "x")}[op]
        code = f"s.{dest}=s.{src};" + (f" s.nz(s.{dest});" if op != 0x9A else "")
    elif op in (0x18, 0x38, 0x58, 0x78, 0xD8, 0xF8, 0xB8):
        flag = {0x18: 1, 0x38: 1, 0x58: 4, 0x78: 4, 0xD8: 8, 0xF8: 8, 0xB8: 64}[op]
        code = f"s.p {'|=' if op in (0x38, 0x78, 0xF8) else '&= ~'} {flag};"
    elif op in (0x62, 0x82, 0xC2):
        # HuC6280 clear-register instructions leave N/Z unchanged.
        code = f"s.{ {0x62: 'a', 0x82: 'x', 0xC2: 'y'}[op] }=0;"
    elif op in (0x02, 0x22, 0x42):
        a, b = {0x02: ("x", "y"), 0x22: ("a", "x"), 0x42: ("a", "y")}[op]
        code = f"std::swap(s.{a},s.{b});"
        cycles = "3"
    elif op == 0x53:
        code = " ".join(f"s.mpr[{i}]=s.a;" for i in range(8) if lo & (1 << i))
        cycles = "5"
    elif op == 0x4C:
        next_pc, cycles = word, "4"
    elif op == 0x20:
        ret = (next_pc-1) & 0xFFFF
        code = f"push(bus,s,{ret >> 8}); push(bus,s,{ret & 255});"
        next_pc, cycles = word, "7"
    elif op == 0x60:
        code = "auto low=pop(bus,s); auto high=pop(bus,s); s.pc=static_cast<std::uint16_t>((low | (high << 8))+1);"
        next_pc, cycles = None, "7"
    elif ins["mnemonic"] in ("BRA", "BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"):
        condition = {"BRA": "true", "BPL": "!(s.p & N)", "BMI": "s.p & N", "BVC": "!(s.p & V)",
                     "BVS": "s.p & V", "BCC": "!(s.p & C)", "BCS": "s.p & C", "BNE": "!(s.p & Z)", "BEQ": "s.p & Z"}[ins["mnemonic"]]
        code = f"bool taken={condition}; s.pc=taken ? {ins['target']} : {next_pc};"
        next_pc, cycles = None, "(taken ? 4 : 2)"
    elif op not in (0xEA, 0xF4):
        raise ValueError(f"No native emitter for opcode {op:02X}")
    if op != 0x28:  # PLP restores T from the stack instead of clearing it.
        code += " s.p |= T;" if op == 0xF4 else " s.p &= ~T;"
    if next_pc is not None:
        code += f" s.pc={next_pc};"
    return code, cycles


def emit(analysis: dict, output: Path):
    if analysis["schema"] != 1:
        raise ValueError("Unsupported analysis schema")
    if any(x["reason"] == "overlapping_instruction" for x in analysis["unresolved"]):
        raise ValueError("Refusing ambiguous overlapping instructions; supply a corrected snapshot")
    output.mkdir(parents=True, exist_ok=True)
    path = output / "module.cpp"
    if path.exists():
        raise ValueError("Output module exists; choose an empty output directory")
    lines = ['// Generated private source; regenerate from the snapshot.', '#include "pce/runtime.hpp"',
             '#include <algorithm>', 'namespace pce {', 'static_assert(abi_version == 1);',
             'Exit generated_step(Bus& bus, Cpu& s, std::uint64_t deadline) {',
             'if(s.ticks >= deadline) return Exit::budget;',
             'static constexpr std::array<std::uint8_t,8> expected_mpr{' + ','.join(str(v) for v in analysis["mpr"]) + '};',
             'if(s.mpr != expected_mpr) return Exit::miss;', 'switch(s.pc) {']
    count = 0
    for ins in analysis["instructions"]:
        if ins["data"][0] not in NATIVE:
            continue
        count += 1
        lines.append(f"case {ins['pc']}: {{ // {ins['mnemonic']} {ins['mode']}")
        for address, value in zip(ins["physical"], ins["data"]):
            lines.append(f"if(bus.peek({address}) != std::optional<std::uint8_t>{{{value}}}) return Exit::miss;")
        statements, cycles = body(ins)
        lines.append(statements)
        lines.append(f"s.retire({cycles},true); return Exit::executed; }}")
    lines += ['default: return Exit::miss;', '}', '}', '} // namespace pce', '']
    path.write_text("\n".join(lines), encoding="utf-8")
    manifest = {"schema": 1, "runtime_abi": 1, "snapshot_sha256": analysis["snapshot_sha256"],
                "native_instructions_emitted": count, "execution_evidence": False,
                "guards": ["full_mpr_snapshot", "exact_source_bytes_per_instruction", "instruction_deadline"],
                "unsupported_policy": "return to dispatcher, then bounded interpreter or explicit trap"}
    (output / "module.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return manifest
