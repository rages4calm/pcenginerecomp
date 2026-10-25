"""Emit direct C++ statements, never a call to the interpreter per opcode."""
import json
from pathlib import Path

from .isa import NATIVE, DATA_OPCODES, RMW_OPCODES, INDIRECT_JUMP_OPCODES, TEST_OPCODES, BIT_BRANCH_OPCODES, BLOCK_OPCODES
from .data_ops import data_body


def body(ins: dict) -> tuple[str, str]:
    op, *args = ins["data"]
    lo = args[0] if args else 0
    word = (lo | args[1] << 8) if len(args) > 1 else lo
    next_pc = (ins["pc"] + len(ins["data"])) & 0xFFFF
    cycles = "2"
    code = ""
    if op == 0x00:
        # BRK's signature byte is part of its encoding/source identity, but
        # the reference CPU does not read it as an operand. Stack writes can
        # alias the subsequently read vector, so keep those accesses ordered.
        code = (f"push(bus,s,{next_pc >> 8}); push(bus,s,{next_pc & 255}); "
                "push(bus,s,static_cast<std::uint8_t>((s.p|B)&~T)); "
                "s.p=static_cast<std::uint8_t>((s.p|I)&~(D|T)); "
                "auto low=bus.read(s,0xFFF6); auto high=bus.read(s,0xFFF7); "
                "s.pc=static_cast<std::uint16_t>(low|(unsigned(high)<<8));")
        next_pc, cycles = None, "8"
    elif op in BLOCK_OPCODES:
        # Latch the operation, but fetch operands after genuine stack writes.
        # This is direct generated execution, not an interpreter call.
        code = "s.p &= ~T; push(bus,s,s.y); push(bus,s,s.a); push(bus,s,s.x); "
        for index, name in enumerate(("source", "destination", "encoded_length")):
            address = (ins["pc"] + 1 + 2*index) & 65535
            code += f"auto {name}_lo=bus.read(s,{address}); auto {name}_hi=bus.read(s,{(address+1)&65535}); "
            code += f"std::uint16_t {name}=static_cast<std::uint16_t>({name}_lo|(unsigned({name}_hi)<<8)); "
        code += "unsigned length=encoded_length ? encoded_length:65536; bus.clock_cpu(s,14); "
        code += "for(unsigned i=0;i<length;++i) { auto value=bus.read_block(s,source); bus.write_block(s,destination,value); "
        code += {0x73: "++source; ++destination;", 0xC3: "--source; --destination;", 0xD3: "++source;",
                 0xE3: "++source; destination=static_cast<std::uint16_t>(destination+(i%2 ? -1:1));",
                 0xF3: "source=static_cast<std::uint16_t>(source+(i%2 ? -1:1)); ++destination;"}[op]
        code += " bus.clock_cpu(s,6); } s.x=pop(bus,s); s.a=pop(bus,s); s.y=pop(bus,s); bus.clock_cpu(s,3); "
        code += "++s.native_block_steps; s.block_bytes+=length;"
        cycles = "0" # Clocks progressed inside the operation; retire it once.
    elif op in DATA_OPCODES:
        code, cycles = data_body(ins)
    elif op in BIT_BRANCH_OPCODES:
        bit = 1 << ((op >> 4) & 7)
        test = f"(bus.read(s,{0x2000|lo})&{bit}) {'!=' if op&128 else '=='} 0"
        code = f"bool taken={test}; s.pc=taken ? {ins['target']}:{next_pc};"
        next_pc, cycles = None, "(taken ? 8:6)"
    elif op in TEST_OPCODES:
        mode, name = ins["mode"], ins["mnemonic"]
        address_lo = args[1] if name == "TST" else lo
        address_word = args[1] | (args[2] << 8) if name == "TST" and len(args)==3 else word
        if mode == "imm":
            code = f"std::uint8_t value={lo}; "
        else:
            address = (f"0x2000|static_cast<std::uint8_t>({address_lo}+s.x)" if mode in ("zpx", "izx") else
                       str(0x2000|address_lo) if mode in ("zpg", "imz") else
                       f"static_cast<std::uint16_t>({address_word}+s.x)" if mode in ("abx", "imx") else str(address_word))
            code = f"auto address={address}; auto value=bus.read(s,address); "
            cycles = "7" if name=="TST" and mode in ("imz", "izx") else "8" if name=="TST" else "4" if mode in ("zpg", "zpx") else "5"
        result = "value&s.a" if name=="BIT" else f"value&{lo}" if name=="TST" else "value|s.a" if name=="TSB" else "value&static_cast<std::uint8_t>(~s.a)"
        code += f"auto result=static_cast<std::uint8_t>({result}); "
        if name in ("TSB", "TRB"):
            code += "bus.write(s,address,result); "
            cycles = "6" if mode=="zpg" else "7"
        code += "s.p=static_cast<std::uint8_t>((s.p&~(N|V|Z))|(value&(N|V))|(result==0 ? Z:0));"
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
        if lo:
            code += " s.mpr_latch=s.a;"
        cycles = "5"
    elif op == 0x43:
        if lo:
            combined = "|".join(f"s.mpr[{i}]" for i in range(8) if lo & (1 << i))
            code = f"s.mpr_latch=static_cast<std::uint8_t>({combined}); "
        code += "s.a=s.mpr_latch;"
        cycles = "4"
    elif op == 0x4C:
        next_pc, cycles = word, "4"
    elif op == 0x20:
        ret = (next_pc-1) & 0xFFFF
        code = f"push(bus,s,{ret >> 8}); push(bus,s,{ret & 255});"
        next_pc, cycles = word, "7"
    elif op == 0x44:
        ret = (next_pc-1)&0xFFFF
        code = f"push(bus,s,{ret>>8}); push(bus,s,{ret&255});"
        next_pc, cycles = ins["target"], "8"
    elif op == 0x40:
        code = "s.p=static_cast<std::uint8_t>(pop(bus,s)&~B); auto low=pop(bus,s); auto high=pop(bus,s); s.pc=static_cast<std::uint16_t>(low|(unsigned(high)<<8)); ++s.rti_steps;"
        next_pc, cycles = None, "7"
    elif op == 0x60:
        code = "auto low=pop(bus,s); auto high=pop(bus,s); s.pc=static_cast<std::uint16_t>((low | (high << 8))+1);"
        next_pc, cycles = None, "7"
    elif ins["mnemonic"] in ("BRA", "BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"):
        condition = {"BRA": "true", "BPL": "!(s.p & N)", "BMI": "s.p & N", "BVC": "!(s.p & V)",
                     "BVS": "s.p & V", "BCC": "!(s.p & C)", "BCS": "s.p & C", "BNE": "!(s.p & Z)", "BEQ": "s.p & Z"}[ins["mnemonic"]]
        code = f"bool taken={condition}; s.pc=taken ? {ins['target']} : {next_pc};"
        next_pc, cycles = None, "(taken ? 4 : 2)"
    elif op in (0x03, 0x13, 0x23):
        port = {3:0, 19:2, 35:3}[op]
        code = f"bus.write_vdc({port},{lo});"
        cycles = "5"
    elif op in (0x54, 0xD4):
        cycles = "3"
    elif op not in (0xEA, 0xF4):
        raise ValueError(f"No native emitter for opcode {op:02X}")
    if op not in (0x28, 0x40):  # PLP restores T from the stack instead of clearing it.
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
             '#include <algorithm>', 'namespace pce {', 'static_assert(abi_version == 21);',
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
        lines.append("bus.begin_instruction(s);")
        statements, cycles = body(ins)
        lines.append(statements)
        retirement = f"bus.retire_speed(s,{12 if ins['data'][0]==0x54 else 3},true)" if ins['data'][0] in (0x54,0xD4) else f"bus.retire(s,{cycles},true)"
        lines.append(f"{retirement}; return Exit::executed; }}")
    lines += ['default: return Exit::miss;', '}', '}', '} // namespace pce', '']
    path.write_text("\n".join(lines), encoding="utf-8")
    manifest = {"schema": 1, "runtime_abi": 21, "snapshot_sha256": analysis["snapshot_sha256"],
                "native_instructions_emitted": count, "execution_evidence": False,
                "guards": ["full_mpr_snapshot", "exact_source_bytes_per_instruction", "instruction_deadline"],
                "unsupported_policy": "return to dispatcher, then bounded interpreter or explicit trap"}
    (output / "module.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return manifest


def emit_capture(capture: dict, output: Path, capture_sha256: str | None = None, exclude_ranges=(),
                 partition_size=256, single_unit=False):
    """Emit independent observed interpretations, guarded by full mapping and bytes.

    Unlike CFG emission, overlapping entries and same-PC byte variants are legal:
    every observation was independently retired. No fallthrough is inferred.
    """
    import hashlib
    from itertools import groupby
    from .capture import validate_capture, integer

    instructions = validate_capture(capture)
    partition_size = integer(partition_size, 4096, 'partition size', 1)
    if not isinstance(single_unit, bool):
        raise ValueError('Single-unit selection must be boolean')
    if not isinstance(exclude_ranges, (list, tuple)) or len(exclude_ranges) > 256:
        raise ValueError('Emission exclusions require at most 256 physical ranges')
    exclusions = set()
    for span in exclude_ranges:
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ValueError('Emission exclusion must be (physical start, length)')
        start = integer(span[0], 0x1fffff, 'excluded physical start')
        length = integer(span[1], 0x200000-start, 'excluded physical length', 1)
        exclusions.add((start, length))
    exclusions = sorted(exclusions)
    excluded, selected = [], []
    for ins in instructions:
        removed = any(start <= address < start+length
                      for address in ins['physical'] for start, length in exclusions)
        (excluded if removed else selected).append(ins)
    if capture_sha256 is None:
        capture_sha256 = hashlib.sha256(json.dumps(capture, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (not isinstance(capture_sha256, str) or len(capture_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in capture_sha256)):
        raise ValueError('Capture SHA256 must be 64 lowercase hexadecimal characters')
    if output.exists() or output.is_symlink():
        raise ValueError('Capture emission requires a new output directory')
    supported = [ins for ins in selected if ins['data'][0] in NATIVE]
    groups = [(mpr, list(items)) for mpr, items in groupby(supported, key=lambda ins: ins['mpr'])]
    preamble = ['// Generated private code-bearing source from bounded retired observations.',
                '#include "pce/runtime.hpp"', '#include <algorithm>', 'namespace pce {',
                'static_assert(abi_version == 21);']

    translated_body_count = 0

    def instruction_cases(items):
        nonlocal translated_body_count
        result = ['switch(s.pc) {']
        for pc, variants in groupby(items, key=lambda ins: ins['pc']):
            variants = list(variants)
            # A full MPR identity and logical PC determine the physical fetch
            # address of each byte. An opcode fixes its decoded length. Reading
            # each byte once and switching on an injective operand key is an
            # exact source guard, not a content hash or generation shortcut.
            result += [f'case {pc}: {{',
                       f'const auto opcode=bus.peek({variants[0]["physical"][0]});',
                       'if(!opcode) return Exit::miss;', 'switch(*opcode) {']
            for op, candidates in groupby(variants, key=lambda ins: ins['data'][0]):
                candidates = list(candidates)
                result.append(f'case {op}: {{ // {candidates[0]["mnemonic"]} {candidates[0]["mode"]}')
                terms = []
                for index, address in enumerate(candidates[0]['physical'][1:]):
                    result += [f'const auto operand_{index}=bus.peek({address});',
                               f'if(!operand_{index}) return Exit::miss;']
                    terms.append(f'(std::uint64_t(*operand_{index}) << {8*index})')
                result.append('const std::uint64_t operand_key=' + (' | '.join(terms) or '0') + ';')
                result.append('switch(operand_key) {')
                bodies = {}
                for ins in candidates:
                    statements, cycles = body(ins)
                    retirement = f'bus.retire_speed(s,{12 if op==0x54 else 3},true)' if op in (0x54, 0xD4) else f'bus.retire(s,{cycles},true)'
                    key = sum(value << (8*index) for index, value in enumerate(ins['data'][1:]))
                    bodies.setdefault((statements, retirement), []).append(key)
                for (statements, retirement), keys in bodies.items():
                    result += [f'case {key}ULL:' for key in keys]
                    result += ['{', 'bus.begin_instruction(s);', statements,
                               f'{retirement}; return Exit::executed; }}']
                    translated_body_count += 1
                result += ['default: return Exit::miss;', '}', '}']
            result += ['default: return Exit::miss;', '}', '}']
        return result + ['default: return Exit::miss;', '}']

    # Keep variants together: a PC chooses its own exact-source interpretation.
    # Contexts never share a chunk, even when physical source banks coincide.
    partitions = []
    context_parts = []
    for _, items in groups:
        indices, current = [], []
        for _, variants in groupby(items, key=lambda ins: ins['pc']):
            variants = list(variants)
            if current and len(current) + len(variants) > partition_size:
                indices.append(len(partitions)); partitions.append(current); current = []
            current.extend(variants)
        if current:
            indices.append(len(partitions)); partitions.append(current)
        context_parts.append(indices)

    partitioned = not single_unit and len(supported) > partition_size
    files = {}
    lines = preamble.copy()
    if partitioned:
        declarations = ['// Generated private module declarations.', '#pragma once',
                        '#include "pce/runtime.hpp"', 'namespace pce {']
        for index, items in enumerate(partitions):
            name = f'captured_part_{index}'
            declarations.append(f'Exit {name}(Bus&, Cpu&);')
            unit = preamble + [f'Exit {name}(Bus& bus, Cpu& s) {{']
            unit += instruction_cases(items) + ['}', '} // namespace pce', '']
            files[f'module_part_{index:04d}.cpp'] = '\n'.join(unit)
        declarations += ['} // namespace pce', '']
        files['module_parts.hpp'] = '\n'.join(declarations)
        # Include declarations before opening the pce namespace.
        lines.insert(3, '#include "module_parts.hpp"')
    else:
        for index, (_, items) in enumerate(groups):
            lines += [f'static Exit captured_context_{index}(Bus& bus, Cpu& s) {{']
            lines += instruction_cases(items) + ['}']
    lines += ['Exit generated_step(Bus& bus, Cpu& s, std::uint64_t deadline) {',
              'if(s.ticks >= deadline) return Exit::budget;',
              'std::uint64_t mapping=0;',
              'for(unsigned i=0;i<8;++i) mapping|=std::uint64_t(s.mpr[i])<<(8*i);',
              'switch(mapping) {']
    for context, (mpr, _) in enumerate(groups):
        mapping = sum(value << (8 * i) for i, value in enumerate(mpr))
        if not partitioned:
            lines.append(f'case {mapping}ULL: return captured_context_{context}(bus,s);')
            continue
        lines += [f'case {mapping}ULL: {{', 'switch(s.pc >> 8) {']
        pages = {}
        for index in context_parts[context]:
            for ins in partitions[index]:
                pages.setdefault(ins['pc'] >> 8, {})[index] = ins['pc']
        for page, candidates in sorted(pages.items()):
            lines.append(f'case {page}:')
            candidates = sorted(candidates.items())
            for index, last_pc in candidates[:-1]:
                lines.append(f'if(s.pc <= {last_pc}) return captured_part_{index}(bus,s);')
            lines.append(f'return captured_part_{candidates[-1][0]}(bus,s);')
        lines += ['default: return Exit::miss;', '}', '}']
    lines += ['default: return Exit::miss;', '}', '}', '} // namespace pce', '']
    files['module.cpp'] = '\n'.join(lines)
    translation_units = ['module.cpp'] + sorted(name for name in files if name.endswith('.cpp') and name != 'module.cpp')
    headers = sorted(name for name in files if name.endswith('.hpp'))
    identities = lambda names: [{'file': name, 'sha256': hashlib.sha256(files[name].encode('utf-8')).hexdigest()} for name in names]
    manifest = {
        'schema': 1, 'runtime_abi': 21, 'code_capture_sha256': capture_sha256,
        'capture_runtime_abi': capture['runtime_abi'],
        'translation_units': identities(translation_units), 'generated_headers': identities(headers),
        'partition_size': partition_size, 'partitioned': partitioned,
        'dispatch_strategy': 'full_mpr_pc_opcode_operand_key',
        'translated_body_count': translated_body_count,
        'largest_partition_instructions': max((len(part) for part in partitions), default=0) if partitioned else len(supported),
        'native_instructions_emitted': len(supported), 'native_contexts': len(groups),
        'observed_instructions': len(instructions), 'execution_evidence': False,
        'capture_complete': capture['complete'], 'capture_retired_instructions': capture['retired_instructions'],
        'capture_dropped_instructions': capture['dropped_instructions'],
        'capture_unreadable_instructions': capture['unreadable_instructions'],
        'captured_native_hits': sum(ins['native_hits'] for ins in instructions),
        'captured_interpreted_hits': sum(ins['interpreted_hits'] for ins in instructions),
        'excluded_physical_ranges': [{'start': start, 'length': length} for start, length in exclusions],
        'excluded_observations': len(excluded),
        'excluded_retired_hits': sum(ins['native_hits'] + ins['interpreted_hits'] for ins in excluded),
        'unsupported_observations': len(selected) - len(supported),
        'guards': ['full_mpr_snapshot', 'exact_source_bytes_per_instruction', 'instruction_deadline'],
        'unsupported_policy': 'return to dispatcher, then bounded interpreter or explicit trap',
        'scope': 'observed identities only; capture is private code-bearing data, not a save state or complete CFG',
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, text in files.items():
        (output / name).write_text(text, encoding='utf-8', newline='\n')
    (output / 'module.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest
