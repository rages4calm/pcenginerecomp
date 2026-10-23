#include "pce/runtime.hpp"
#include <limits>

namespace pce {
void Bus::clock_cpu(Cpu& cpu,unsigned cycles) {
    if(!cpu.clock_divisor || cycles>std::numeric_limits<std::uint64_t>::max()/cpu.clock_divisor ||
       cpu.cycles>std::numeric_limits<std::uint64_t>::max()-cycles ||
       cpu.ticks>std::numeric_limits<std::uint64_t>::max()-std::uint64_t(cycles)*cpu.clock_divisor)
        throw Fault("block CPU clock overflow");
    cpu.cycles+=cycles; cpu.ticks+=std::uint64_t(cycles)*cpu.clock_divisor;
    sync(cpu);
}
std::uint8_t Bus::read_block(Cpu& cpu,std::uint16_t address) {
    const auto pa=physical(cpu,address), offset=pa&8191;
    if((pa>>13)==255 && kind[255]==BankKind::io && offset>=0x800 && offset<0x1800) {
        sync(cpu); return 0; // Block reads do not poll PSG/timer/input/IRQ registers.
    }
    const auto value=read(cpu,address);
    if((pa>>13)==255 && kind[255]==BankKind::io && offset<0x400 && vdc.enabled)
        clock_cpu(cpu,1); // Ordinary access already charged one; blocks charge two.
    return value;
}
void Bus::write_block(Cpu& cpu,std::uint16_t address,std::uint8_t value) {
    const auto pa=physical(cpu,address);
    write(cpu,address,value);
    if((pa>>13)==255 && kind[255]==BankKind::io && (pa&8191)<0x400 && vdc.enabled)
        clock_cpu(cpu,1);
}
void interpret_block(Bus& bus,Cpu& cpu,std::uint8_t opcode) {
    const auto entry=cpu.pc;
    cpu.p &= static_cast<std::uint8_t>(~T);
    push(bus,cpu,cpu.y); push(bus,cpu,cpu.a); push(bus,cpu,cpu.x);
    // Real stack writes precede operand fetching. Aliases may change operands.
    std::uint16_t operands[3]{};
    for(unsigned i=0;i<3;++i) {
        const auto lo=bus.read(cpu,static_cast<std::uint16_t>(entry+1+2*i));
        const auto hi=bus.read(cpu,static_cast<std::uint16_t>(entry+2+2*i));
        operands[i]=static_cast<std::uint16_t>(lo|(unsigned(hi)<<8));
    }
    const unsigned length=operands[2] ? operands[2]:65536;
    auto source=operands[0], destination=operands[1];
    bus.clock_cpu(cpu,14);
    for(unsigned i=0;i<length;++i) {
        const auto value=bus.read_block(cpu,source);
        bus.write_block(cpu,destination,value);
        switch(opcode) {
        case 0x73: ++source; ++destination; break;
        case 0xC3: --source; --destination; break;
        case 0xD3: ++source; break;
        case 0xE3: ++source; destination=static_cast<std::uint16_t>(destination+(i%2 ? -1:1)); break;
        case 0xF3: source=static_cast<std::uint16_t>(source+(i%2 ? -1:1)); ++destination; break;
        default: throw Fault("invalid block-transfer operation");
        }
        bus.clock_cpu(cpu,6);
    }
    cpu.x=pop(bus,cpu); cpu.a=pop(bus,cpu); cpu.y=pop(bus,cpu);
    bus.clock_cpu(cpu,3);
    cpu.pc=static_cast<std::uint16_t>(entry+7);
    ++cpu.interpreter_block_steps; cpu.block_bytes+=length;
    bus.retire(cpu,0,false);
}
} // namespace pce
