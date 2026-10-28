"""Direct load/store/ALU translations; no interpreter arithmetic helpers.

Address calculations retain guest widths and use the bus for each pointer byte.
Decimal arithmetic is nibble arithmetic, including non-BCD input digits.
"""


def data_body(ins):
    op = ins["mnemonic"]
    mode = ins["mode"]
    lo = ins["data"][1]
    word = lo | (ins["data"][2] << 8) if len(ins["data"]) == 3 else lo
    cycles = {"imm": 2, "zpg": 4, "zpx": 4, "zpy": 4,
              "abs": 5, "abx": 5, "aby": 5, "idx": 7, "idy": 7, "zpi": 7}[mode]
    code = f"unsigned cost={cycles}; "
    if mode in ("idx", "idy", "zpi"):
        pointer = f"static_cast<std::uint8_t>({lo}+s.x)" if mode == "idx" else str(lo)
        code += f"auto pointer={pointer}; auto low=bus.read(s,0x2000|pointer); "
        code += "auto high=bus.read(s,0x2000|static_cast<std::uint8_t>(pointer+1)); "
        code += "auto address=static_cast<std::uint16_t>((low|(high<<8))" + ("+s.y" if mode == "idy" else "") + "); "
    elif mode != "imm":
        address = {"zpg": str(0x2000 | lo), "zpx": f"0x2000|static_cast<std::uint8_t>({lo}+s.x)",
                   "zpy": f"0x2000|static_cast<std::uint8_t>({lo}+s.y)", "abs": str(word),
                   "abx": f"static_cast<std::uint16_t>({word}+s.x)",
                   "aby": f"static_cast<std::uint16_t>({word}+s.y)"}[mode]
        code += f"auto address={address}; "
    if op.startswith("ST"):
        value = {"STA": "s.a", "STX": "s.x", "STY": "s.y", "STZ": "0"}[op]
        return code + f"cost=bus.write_timed(s,address,{value},cost);", "cost"
    if op.startswith("LD") and mode == "imm":
        reg = op[-1].lower()
        return code + f"s.{reg}={lo}; s.nz(s.{reg});", "cost"
    code += f"std::uint8_t operand={lo if mode == 'imm' else 'bus.read(s,address)'}; "
    if op.startswith("LD"):
        reg = op[-1].lower()
        return code + f"s.{reg}=operand; s.nz(s.{reg});", "cost"
    if op in ("CMP", "CPX", "CPY"):
        reg = {"CMP": "a", "CPX": "x", "CPY": "y"}[op]
        code += f"s.p=static_cast<std::uint8_t>((s.p&~C)|(s.{reg}>=operand ? C:0)); s.nz(static_cast<std::uint8_t>(s.{reg}-operand));"
        return code, "cost"
    transfer = op in ("ADC", "AND", "EOR", "ORA")
    if transfer:
        code += "bool transfer=s.p&T; auto dest=static_cast<std::uint16_t>(0x2000|s.x); "
        code += "std::uint8_t left=transfer ? bus.read(s,dest):s.a; if(transfer) cost+=3; "
    else:
        code += "std::uint8_t left=s.a; "
    if op in ("AND", "EOR", "ORA"):
        operator = {"AND": "&", "EOR": "^", "ORA": "|"}[op]
        code += f"auto result=static_cast<std::uint8_t>(left {operator} operand); "
    else:
        # Arithmetic is emitted as statements, not delegated to the interpreter.
        code += "int carry=s.p&C; int result; "
        code += "if(s.p&D) { ++cost; "
        if op == "ADC":
            code += "int digits=(left&15)+(operand&15)+carry; if(digits>=10) digits+=6; "
            code += "result=(left&240)+(operand&240)+(digits>=16 ? 16:0)+(digits&15); if(result>=160) result+=96; "
        else:
            code += "int digits=(left&15)-(operand&15)-(1-carry); bool borrow=digits<0; if(borrow) digits-=6; "
            code += "result=(left&240)-(operand&240)-(borrow ? 16:0)+(digits&15); if(result<0) result-=96; "
        code += "} else { "
        code += "result=left+operand+carry; " if op == "ADC" else "result=left-operand-(1-carry); "
        overflow = "~(left^operand)" if op == "ADC" else "(left^operand)"
        code += f"s.p=static_cast<std::uint8_t>((s.p&~V)|(({overflow}&(left^result)&128) ? V:0)); }} "
        carry_out = "result>255" if op == "ADC" else "result>=0"
        code += f"s.p=static_cast<std::uint8_t>((s.p&~C)|({carry_out} ? C:0)); "
    code += "auto value=static_cast<std::uint8_t>(result); "
    code += "if(transfer) bus.write(s,dest,value); else s.a=value; " if transfer else "s.a=value; "
    return code + "s.nz(value);", "cost"
