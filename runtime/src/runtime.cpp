#include "pce/runtime.hpp"
#include <algorithm>

namespace pce {
std::optional<std::uint8_t> Bus::peek(std::uint32_t address) const {
    if(address >= bytes->size()) return std::nullopt;
    auto k=kind[address >> 13];
    if(k != BankKind::ram && k != BankKind::rom) return std::nullopt;
    return (*bytes)[address];
}
std::uint8_t Bus::read(const Cpu& cpu, std::uint16_t address) const {
    auto result=peek(physical(cpu,address));
    if(!result) throw Fault("unimplemented I/O or unmapped read at logical " + std::to_string(address));
    return *result;
}
void Bus::write(const Cpu& cpu, std::uint16_t address, std::uint8_t value) {
    const auto pa=physical(cpu,address);
    if(kind[pa >> 13] != BankKind::ram) throw Fault("write to ROM, unimplemented I/O, or unmapped bank");
    if((*bytes)[pa] != value) { (*bytes)[pa]=value; ++generation[pa >> 13]; }
}
void Bus::load(std::uint32_t address, const std::uint8_t* source, std::size_t count) {
    if(address > bytes->size() || count > bytes->size()-address) throw Fault("load exceeds physical address space");
    std::copy_n(source,count,bytes->begin()+address);
    if(count) for(std::size_t bank=address >> 13; bank <= (address+count-1) >> 13; ++bank) ++generation[bank];
}
void push(Bus& bus, Cpu& cpu, std::uint8_t value) { bus.write(cpu,0x2100|cpu.sp,value); --cpu.sp; }
std::uint8_t pop(Bus& bus, Cpu& cpu) { ++cpu.sp; return bus.read(cpu,0x2100|cpu.sp); }

Exit interpret_step(Bus& bus, Cpu& s, std::uint64_t deadline) {
    if(s.ticks >= deadline) return Exit::budget;
    const auto op=bus.read(s,s.pc);
    // Fetch all operands before touching guest state. Unsupported opcodes
    // return without fetching speculative operands or mutating the machine.
    unsigned size=1, cycles=2;
    switch(op) {
    case 0xA9: case 0xA2: case 0xA0: case 0x85: case 0xA5: case 0x64: case 0x53:
    case 0x80: case 0x10: case 0x30: case 0x50: case 0x70: case 0x90: case 0xB0: case 0xD0: case 0xF0:
        size=2; break;
    case 0x8D: case 0xAD: case 0x9C: case 0x4C: case 0x20: size=3; break;
    case 0xEA: case 0xE8: case 0xCA: case 0xC8: case 0x88: case 0xAA: case 0xA8:
    case 0x8A: case 0x98: case 0xBA: case 0x9A: case 0x18: case 0x38: case 0x58:
    case 0x78: case 0xD8: case 0xF8: case 0xB8: case 0xF4: case 0x62: case 0x82:
    case 0xC2: case 0x02: case 0x22: case 0x42: case 0x60: break;
    default: return Exit::unsupported;
    }
    const std::uint8_t lo=size>1 ? bus.read(s,static_cast<std::uint16_t>(s.pc+1)) : 0;
    const std::uint16_t word=size>2 ? lo | (bus.read(s,static_cast<std::uint16_t>(s.pc+2)) << 8) : lo;
    std::uint16_t next=static_cast<std::uint16_t>(s.pc+size);
    const auto old_t = s.p & T;
    (void)old_t; // no T-sensitive ALU operations in this tier
    switch(op) {
    case 0xA9: s.a=lo; s.nz(s.a); break;
    case 0xA2: s.x=lo; s.nz(s.x); break;
    case 0xA0: s.y=lo; s.nz(s.y); break;
    case 0x85: bus.write(s,0x2000|lo,s.a); cycles=4; break;
    case 0x8D: bus.write(s,word,s.a); cycles=5; break;
    case 0xA5: s.a=bus.read(s,0x2000|lo); s.nz(s.a); cycles=4; break;
    case 0xAD: s.a=bus.read(s,word); s.nz(s.a); cycles=5; break;
    case 0x64: bus.write(s,0x2000|lo,0); cycles=4; break;
    case 0x9C: bus.write(s,word,0); cycles=5; break;
    case 0xE8: ++s.x; s.nz(s.x); break;
    case 0xCA: --s.x; s.nz(s.x); break;
    case 0xC8: ++s.y; s.nz(s.y); break;
    case 0x88: --s.y; s.nz(s.y); break;
    case 0xAA: s.x=s.a; s.nz(s.x); break;
    case 0xA8: s.y=s.a; s.nz(s.y); break;
    case 0x8A: s.a=s.x; s.nz(s.a); break;
    case 0x98: s.a=s.y; s.nz(s.a); break;
    case 0xBA: s.x=s.sp; s.nz(s.x); break;
    case 0x9A: s.sp=s.x; break;
    case 0x18: s.p &= ~C; break;
    case 0x38: s.p |= C; break;
    case 0x58: s.p &= ~I; break;
    case 0x78: s.p |= I; break;
    case 0xD8: s.p &= ~D; break;
    case 0xF8: s.p |= D; break;
    case 0xB8: s.p &= ~V; break;
    case 0x62: s.a=0; break;
    case 0x82: s.x=0; break;
    case 0xC2: s.y=0; break;
    case 0x02: std::swap(s.x,s.y); cycles=3; break;
    case 0x22: std::swap(s.a,s.x); cycles=3; break;
    case 0x42: std::swap(s.a,s.y); cycles=3; break;
    case 0x53:
        for(unsigned bit=0; bit<8; ++bit) if(lo & (1U << bit)) s.mpr[bit]=s.a;
        cycles=5; break;
    case 0x4C: next=word; cycles=4; break;
    case 0x20:
        push(bus,s,static_cast<std::uint8_t>((next-1) >> 8));
        push(bus,s,static_cast<std::uint8_t>(next-1)); next=word; cycles=7; break;
    case 0x60: { auto low=pop(bus,s); next=static_cast<std::uint16_t>((low | (pop(bus,s) << 8))+1); cycles=7; break; }
    case 0xEA: case 0xF4: break;
    default: {
        bool take=op==0x80;
        if(op==0x10) take=!(s.p&N); if(op==0x30) take=s.p&N;
        if(op==0x50) take=!(s.p&V); if(op==0x70) take=s.p&V;
        if(op==0x90) take=!(s.p&C); if(op==0xB0) take=s.p&C;
        if(op==0xD0) take=!(s.p&Z); if(op==0xF0) take=s.p&Z;
        if(take) { next=static_cast<std::uint16_t>(next+static_cast<std::int8_t>(lo)); cycles=4; }
    }
    }
    if(op==0xF4) s.p |= T; else s.p &= ~T;
    s.pc=next; s.retire(cycles,false);
    return Exit::executed;
}

Exit step(Bus& bus, Cpu& s, std::uint64_t deadline, bool allow_interpreter) {
    auto result=generated_step(bus,s,deadline);
    if(result==Exit::miss) {
        ++s.guard_misses;
        if(allow_interpreter) return interpret_step(bus,s,deadline);
    }
    return result;
}
const char* exit_name(Exit status) {
    switch(status) {
    case Exit::executed: return "executed";
    case Exit::miss: return "guard_miss";
    case Exit::unsupported: return "unsupported_instruction";
    case Exit::budget: return "budget";
    }
    return "invalid";
}
} // namespace pce
