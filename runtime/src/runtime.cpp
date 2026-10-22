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

namespace {
enum class DataOp { none, ora, and_, eor, adc, sta, lda, cmp, sbc,
                    ldx, ldy, stx, sty, stz, cpx, cpy };
enum class Mode { immediate, zp, zpx, zpy, absolute, absx, absy, indx, indy, indirect };
struct DataInstruction { DataOp op=DataOp::none; Mode mode=Mode::immediate; };

DataInstruction data_instruction(std::uint8_t opcode) {
    // Eight regular instruction families, plus the irregular X/Y/zero forms.
    const auto low=opcode&31;
    Mode mode;
    switch(low) {
    case 1: mode=Mode::indx; break; case 5: mode=Mode::zp; break;
    case 9: mode=Mode::immediate; break; case 13: mode=Mode::absolute; break;
    case 17: mode=Mode::indy; break; case 18: mode=Mode::indirect; break;
    case 21: mode=Mode::zpx; break; case 25: mode=Mode::absy; break;
    case 29: mode=Mode::absx; break;
    default: goto irregular;
    }
    if(opcode!=0x89) {
        constexpr DataOp families[]={DataOp::ora,DataOp::and_,DataOp::eor,DataOp::adc,
                                    DataOp::sta,DataOp::lda,DataOp::cmp,DataOp::sbc};
        return {families[opcode>>5],mode};
    }
irregular:
    switch(opcode) {
    case 0xA2: return {DataOp::ldx,Mode::immediate};
    case 0xA6: return {DataOp::ldx,Mode::zp};
    case 0xB6: return {DataOp::ldx,Mode::zpy};
    case 0xAE: return {DataOp::ldx,Mode::absolute};
    case 0xBE: return {DataOp::ldx,Mode::absy};
    case 0xA0: return {DataOp::ldy,Mode::immediate};
    case 0xA4: return {DataOp::ldy,Mode::zp};
    case 0xB4: return {DataOp::ldy,Mode::zpx};
    case 0xAC: return {DataOp::ldy,Mode::absolute};
    case 0xBC: return {DataOp::ldy,Mode::absx};
    case 0x86: return {DataOp::stx,Mode::zp}; case 0x96: return {DataOp::stx,Mode::zpy};
    case 0x8E: return {DataOp::stx,Mode::absolute};
    case 0x84: return {DataOp::sty,Mode::zp}; case 0x94: return {DataOp::sty,Mode::zpx};
    case 0x8C: return {DataOp::sty,Mode::absolute};
    case 0x64: return {DataOp::stz,Mode::zp}; case 0x74: return {DataOp::stz,Mode::zpx};
    case 0x9C: return {DataOp::stz,Mode::absolute}; case 0x9E: return {DataOp::stz,Mode::absx};
    case 0xE0: return {DataOp::cpx,Mode::immediate}; case 0xE4: return {DataOp::cpx,Mode::zp};
    case 0xEC: return {DataOp::cpx,Mode::absolute};
    case 0xC0: return {DataOp::cpy,Mode::immediate}; case 0xC4: return {DataOp::cpy,Mode::zp};
    case 0xCC: return {DataOp::cpy,Mode::absolute};
    default: return {};
    }
}
unsigned data_size(Mode mode) {
    return mode==Mode::absolute || mode==Mode::absx || mode==Mode::absy ? 3 : 2;
}
void execute_data(Bus& bus, Cpu& s, DataInstruction ins, std::uint8_t lo,
                  std::uint16_t word, unsigned& cycles) {
    std::uint16_t address=0;
    cycles=4;
    switch(ins.mode) {
    case Mode::immediate: cycles=2; break;
    case Mode::zp: address=0x2000|lo; break;
    case Mode::zpx: address=0x2000|((lo+s.x)&255); break;
    case Mode::zpy: address=0x2000|((lo+s.y)&255); break;
    case Mode::absolute: address=word; cycles=5; break;
    case Mode::absx: address=static_cast<std::uint16_t>(word+s.x); cycles=5; break;
    case Mode::absy: address=static_cast<std::uint16_t>(word+s.y); cycles=5; break;
    default: {
        unsigned pointer=lo;
        if(ins.mode==Mode::indx) pointer=(pointer+s.x)&255;
        const auto low=bus.read(s,static_cast<std::uint16_t>(0x2000|pointer));
        const auto high=bus.read(s,static_cast<std::uint16_t>(0x2000|((pointer+1)&255)));
        address=static_cast<std::uint16_t>(low+256*high+(ins.mode==Mode::indy ? s.y:0));
        cycles=7; break;
    }
    }
    switch(ins.op) {
    case DataOp::sta: bus.write(s,address,s.a); return;
    case DataOp::stx: bus.write(s,address,s.x); return;
    case DataOp::sty: bus.write(s,address,s.y); return;
    case DataOp::stz: bus.write(s,address,0); return;
    default: break;
    }
    const auto operand=ins.mode==Mode::immediate ? lo:bus.read(s,address);
    switch(ins.op) {
    case DataOp::lda: s.a=operand; s.nz(s.a); return;
    case DataOp::ldx: s.x=operand; s.nz(s.x); return;
    case DataOp::ldy: s.y=operand; s.nz(s.y); return;
    case DataOp::cmp: case DataOp::cpx: case DataOp::cpy: {
        const auto reg=ins.op==DataOp::cmp ? s.a:ins.op==DataOp::cpx ? s.x:s.y;
        s.p=static_cast<std::uint8_t>((s.p&~C)|(reg>=operand ? C:0));
        s.nz(static_cast<std::uint8_t>(reg-operand)); return;
    }
    default: break;
    }
    const bool transfer=(s.p&T) && ins.op!=DataOp::sbc;
    const auto destination=static_cast<std::uint16_t>(0x2000|s.x);
    const auto left=transfer ? bus.read(s,destination):s.a;
    if(transfer) cycles+=3;
    std::uint8_t result;
    switch(ins.op) {
    case DataOp::ora: result=left|operand; break;
    case DataOp::and_: result=left&operand; break;
    case DataOp::eor: result=left^operand; break;
    default: {
        const bool subtract=ins.op==DataOp::sbc;
        const unsigned right=subtract ? operand^255U:operand;
        int sum=left+right+(s.p&C);
        if(s.p&D) {
            ++cycles;
            int low=(left%16)+(right%16)+(s.p&C);
            if(subtract) { if(low<16) low-=6; }
            else if(low>9) low+=6;
            sum=(left&0xF0)+(right&0xF0)+(low>15 ? 16:0)+(low&15);
            if(subtract) { if(sum<256) sum-=96; }
            else if(sum>159) sum+=96;
        } else {
            const bool overflow=(~(left^right)&(left^sum)&0x80)!=0;
            s.p=static_cast<std::uint8_t>((s.p&~V)|(overflow ? V:0));
        }
        s.p=static_cast<std::uint8_t>((s.p&~C)|(sum>255 ? C:0));
        result=static_cast<std::uint8_t>(sum); break;
    }
    }
    if(transfer) bus.write(s,destination,result); else s.a=result;
    s.nz(result);
}
enum class RmwOp { none, asl, rol, lsr, ror, inc, dec };
struct RmwInstruction { RmwOp op=RmwOp::none; unsigned size=1; bool indexed=false; };
RmwInstruction rmw_instruction(std::uint8_t opcode) {
    switch(opcode) {
    case 0x0A: return {RmwOp::asl}; case 0x2A: return {RmwOp::rol};
    case 0x4A: return {RmwOp::lsr}; case 0x6A: return {RmwOp::ror};
    case 0x1A: return {RmwOp::inc}; case 0x3A: return {RmwOp::dec};
    default: break;
    }
    const unsigned form=opcode&31;
    if(form!=6 && form!=14 && form!=22 && form!=30) return {};
    RmwOp operation;
    switch(opcode>>5) {
    case 0: operation=RmwOp::asl; break; case 1: operation=RmwOp::rol; break;
    case 2: operation=RmwOp::lsr; break; case 3: operation=RmwOp::ror; break;
    case 6: operation=RmwOp::dec; break; case 7: operation=RmwOp::inc; break;
    default: return {};
    }
    return {operation,(form&8) ? 3U:2U,(form&16)!=0};
}
void execute_rmw(Bus& bus, Cpu& s, RmwInstruction ins, std::uint8_t lo,
                 std::uint16_t word, unsigned& cycles) {
    const bool accumulator=ins.size==1;
    const unsigned index=ins.indexed ? s.x:0;
    const auto address=static_cast<std::uint16_t>(ins.size==2 ? 0x2000|((lo+index)&255):word+index);
    const unsigned value=accumulator ? s.a:bus.read(s,address);
    unsigned result=value;
    switch(ins.op) {
    case RmwOp::asl: result=value<<1; break;
    case RmwOp::rol: result=(value<<1)|(s.p&C); break;
    case RmwOp::lsr: result=value>>1; break;
    case RmwOp::ror: result=(value>>1)|((s.p&C)<<7); break;
    case RmwOp::inc: result=value+1; break;
    case RmwOp::dec: result=value-1; break;
    default: throw Fault("invalid internal RMW operation");
    }
    const auto byte=static_cast<std::uint8_t>(result);
    if(accumulator) s.a=byte; else bus.write(s,address,byte);
    if(ins.op!=RmwOp::inc && ins.op!=RmwOp::dec) {
        const bool carry=ins.op==RmwOp::asl || ins.op==RmwOp::rol ? (value&128)!=0:(value&1)!=0;
        s.p=static_cast<std::uint8_t>((s.p&~C)|(carry ? C:0));
    }
    s.nz(byte);
    cycles=accumulator ? 2:ins.size==2 ? 6:7;
}
} // namespace

Exit interpret_step(Bus& bus, Cpu& s, std::uint64_t deadline) {
    if(s.ticks >= deadline) return Exit::budget;
    const auto op=bus.read(s,s.pc);
    // Fetch all operands before touching guest state. Unsupported opcodes
    // return without fetching speculative operands or mutating the machine.
    unsigned size=1, cycles=2;
    const auto data=data_instruction(op);
    const auto rmw=rmw_instruction(op);
    if(data.op!=DataOp::none) size=data_size(data.mode);
    else if(rmw.op!=RmwOp::none) size=rmw.size;
    else switch(op) {
    case 0x53:
    case 0x07: case 0x17: case 0x27: case 0x37: case 0x47: case 0x57: case 0x67: case 0x77:
    case 0x87: case 0x97: case 0xA7: case 0xB7: case 0xC7: case 0xD7: case 0xE7: case 0xF7:
    case 0x80: case 0x10: case 0x30: case 0x50: case 0x70: case 0x90: case 0xB0: case 0xD0: case 0xF0:
        size=2; break;
    case 0x4C: case 0x20: case 0x6C: case 0x7C: size=3; break;
    case 0xEA: case 0xE8: case 0xCA: case 0xC8: case 0x88: case 0xAA: case 0xA8:
    case 0x8A: case 0x98: case 0xBA: case 0x9A: case 0x18: case 0x38: case 0x58:
    case 0x78: case 0xD8: case 0xF8: case 0xB8: case 0xF4: case 0x62: case 0x82:
    case 0xC2: case 0x02: case 0x22: case 0x42: case 0x60: break;
    case 0x08: case 0x28: case 0x48: case 0x68: case 0x5A: case 0x7A: case 0xDA: case 0xFA: break;
    default: return Exit::unsupported;
    }
    const std::uint8_t lo=size>1 ? bus.read(s,static_cast<std::uint16_t>(s.pc+1)) : 0;
    const std::uint16_t word=size>2 ? lo | (bus.read(s,static_cast<std::uint16_t>(s.pc+2)) << 8) : lo;
    std::uint16_t next=static_cast<std::uint16_t>(s.pc+size);
    if(data.op!=DataOp::none) execute_data(bus,s,data,lo,word,cycles);
    else if(rmw.op!=RmwOp::none) execute_rmw(bus,s,rmw,lo,word,cycles);
    else switch(op) {
    case 0x07: case 0x17: case 0x27: case 0x37: case 0x47: case 0x57: case 0x67: case 0x77:
    case 0x87: case 0x97: case 0xA7: case 0xB7: case 0xC7: case 0xD7: case 0xE7: case 0xF7: {
        const auto address=static_cast<std::uint16_t>(0x2000|lo);
        const auto value=bus.read(s,address);
        const auto mask=1U << ((op >> 4) & 7);
        bus.write(s,address,static_cast<std::uint8_t>(op & 0x80 ? value | mask : value & ~mask));
        cycles=7; break;
    }
    case 0x48: push(bus,s,s.a); cycles=3; break;
    case 0xDA: push(bus,s,s.x); cycles=3; break;
    case 0x5A: push(bus,s,s.y); cycles=3; break;
    case 0x08:
        // T is cleared before the status copy; the saved B bit is always set.
        push(bus,s,static_cast<std::uint8_t>((s.p | B) & ~T)); cycles=3; break;
    case 0x68: s.a=pop(bus,s); s.nz(s.a); cycles=4; break;
    case 0xFA: s.x=pop(bus,s); s.nz(s.x); cycles=4; break;
    case 0x7A: s.y=pop(bus,s); s.nz(s.y); cycles=4; break;
    case 0x28:
        // PLP restores T. Do not run the ordinary end-of-instruction clear.
        // B is a stack-status marker, not a persistent restored flag.
        s.p=static_cast<std::uint8_t>(pop(bus,s) & ~B); cycles=4; break;
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
    case 0x6C: case 0x7C: {
        const auto pointer=static_cast<std::uint16_t>(word+(op==0x7C ? s.x:0));
        const auto low=bus.read(s,pointer);
        const auto high=bus.read(s,static_cast<std::uint16_t>(pointer+1));
        next=static_cast<std::uint16_t>(low+256*high); cycles=7; break;
    }
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
    if(op==0xF4) s.p |= T; else if(op!=0x28) s.p &= ~T;
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
