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
    sample_interrupt(cpu);
}
std::uint8_t Bus::read_block(Cpu& cpu,std::uint16_t address) {
    const auto pa=physical(cpu,address), offset=pa&8191;
    if((pa>>13)==255 && kind[255]==BankKind::io && offset<0x400 && vdc.enabled &&
       vdc.raster.enabled && vdc.queued_cpu_accesses) {
        clock_cpu(cpu,2); // Block transfers inject both fixed cycles before the read.
        wait_vdc(cpu,offset&3,false);
        return vdc.read(offset);
    }
    if((pa>>13)==255 && kind[255]==BankKind::io && offset>=0x800 && offset<0x1800) {
        sync(cpu); return 0; // Block reads do not poll PSG/timer/input/IRQ registers.
    }
    const auto value=read(cpu,address);
    if((pa>>13)==255 && kind[255]==BankKind::io && offset<0x400 && vdc.enabled)
        clock_cpu(cpu,1); // Ordinary access already charged one; blocks charge two.
    return value;
}
void Bus::wait_vdc(Cpu& cpu,unsigned port,bool writing) {
    if(!vdc.raster.enabled || !vdc.queued_cpu_accesses)return;
    sync(cpu);
    if(!vdc.vram_wait_required(port,writing))return;
    // The maximum finite DMA is 65,536 words, plus SATB interference and a
    // frame's access-window delay. Eight longest VCE frames bound starvation
    // without inventing a successful transfer for a malformed device state.
    constexpr std::uint64_t maximum_wait=8ULL*1365*263;
    std::uint64_t waited=0;
    // A read enters only for a queued prefetch, but once entered the VDC
    // drains both queues, including a write left behind by read priority.
    while(vdc.has_pending_vram()) {
        if(waited>=maximum_wait)throw Fault("VDC queued access did not obtain a slot within eight frames");
        if(cpu.ticks>std::numeric_limits<std::uint64_t>::max()-3 ||
           cpu.vdc_wait_ticks>std::numeric_limits<std::uint64_t>::max()-3)
            throw Fault("VDC wait clock overflow");
        cpu.ticks+=3;cpu.vdc_wait_ticks+=3;waited+=3;
        sync(cpu);
        sample_interrupt(cpu);
    }
}
unsigned Bus::write_vdc(Cpu& cpu,unsigned port,std::uint8_t value) {
    if(!vdc.enabled)throw Fault("VDC profile is disabled");
    if(!vdc.raster.enabled || !vdc.queued_cpu_accesses) {
        write_vdc(port,value);
        return 5;
    }
    clock_cpu(cpu,2);
    wait_vdc(cpu,port,true);
    vdc.write(port,value);
    clock_cpu(cpu,1);
    return 2;
}
void Bus::write_block(Cpu& cpu,std::uint16_t address,std::uint8_t value) {
    const auto pa=physical(cpu,address);
    write(cpu,address,value);
    if((pa>>13)==255 && kind[255]==BankKind::io && (pa&8191)<0x400 && vdc.enabled)
        clock_cpu(cpu,1);
}
unsigned Bus::write_block_timed(Cpu& cpu,std::uint16_t address,std::uint8_t value,
                                unsigned remaining_base) {
    const auto pa=physical(cpu,address);
    remaining_base=write_timed(cpu,address,value,remaining_base);
    if((pa>>13)==255 && kind[255]==BankKind::io && (pa&8191)<0x400 && vdc.enabled)
        clock_cpu(cpu,1); // read/write adds the first fixed cycle; blocks need two.
    return remaining_base;
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
        const auto remaining=bus.write_block_timed(cpu,destination,value,6);
        switch(opcode) {
        case 0x73: ++source; ++destination; break;
        case 0xC3: --source; --destination; break;
        case 0xD3: ++source; break;
        case 0xE3: ++source; destination=static_cast<std::uint16_t>(destination+(i%2 ? -1:1)); break;
        case 0xF3: source=static_cast<std::uint16_t>(source+(i%2 ? -1:1)); ++destination; break;
        default: throw Fault("invalid block-transfer operation");
        }
        bus.clock_cpu(cpu,remaining);
    }
    cpu.x=pop(bus,cpu); cpu.a=pop(bus,cpu); cpu.y=pop(bus,cpu);
    bus.clock_cpu(cpu,3);
    cpu.pc=static_cast<std::uint16_t>(entry+7);
    ++cpu.interpreter_block_steps; cpu.block_bytes+=length;
    bus.retire(cpu,0,false);
}
} // namespace pce
