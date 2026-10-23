#include "pce/runtime.hpp"
#include <limits>

namespace pce {
void Interrupts::advance_to(std::uint64_t ticks) {
    if(!enabled) return;
    if(ticks<master_ticks) throw Fault("CPU/timer clock regression");
    if(timer_enabled && timer_deadline && ticks>=timer_deadline) {
        const auto periods=1+(ticks-timer_deadline)/3072;
        if(periods<=timer_counter) timer_counter=static_cast<std::uint8_t>(timer_counter-periods);
        else {
            timer_pending=true;
            timer_counter=static_cast<std::uint8_t>(timer_reload-(periods-timer_counter-1)%(unsigned(timer_reload)+1));
        }
        if(periods>(std::numeric_limits<std::uint64_t>::max()-timer_deadline)/3072)
            throw Fault("timer clock overflow");
        timer_deadline+=periods*3072;
    }
    master_ticks=ticks;
}
void Bus::enable_interrupts() { irq=Interrupts{};irq.enabled=true;kind[255]=BankKind::io; }
std::uint8_t Bus::irq_requests() const {
    return static_cast<std::uint8_t>((irq.external&7)|(vdc.irq1?2:0)|(cd.irq2()?1:0)|(irq.timer_pending?4:0));
}
void Bus::sample_interrupt(Cpu& cpu) {
    if(irq.enabled) cpu.irq_sampled=static_cast<std::uint8_t>((cpu.p&I) ? 0:irq_requests()&~irq.mask);
}
void Bus::service_interrupt(Cpu& cpu) {
    if(!irq.enabled) return;
    const auto pending=cpu.irq_sampled;
    unsigned vector=0;
    if((pending&4) && (irq_requests()&4)) vector=0xFFFA;
    else if(pending&2) vector=0xFFF8;
    else if(pending&1) vector=0xFFF6;
    if(!vector) return;
    // Entry is part of the completed instruction's boundary, not another
    // native/interpreted opcode. Do not acknowledge level-sensitive sources.
    push(*this,cpu,static_cast<std::uint8_t>(cpu.pc>>8));
    push(*this,cpu,static_cast<std::uint8_t>(cpu.pc));
    push(*this,cpu,static_cast<std::uint8_t>(cpu.p&~B));
    cpu.p=static_cast<std::uint8_t>((cpu.p|I)&~(D|T));
    const auto low=read(cpu,static_cast<std::uint16_t>(vector));
    const auto high=read(cpu,static_cast<std::uint16_t>(vector+1));
    cpu.pc=static_cast<std::uint16_t>(low|(unsigned(high)<<8));
    cpu.irq_sampled=0;
    clock_cpu(cpu,8);
    cpu.irq_vector=static_cast<std::uint16_t>(vector); ++cpu.irq_entries; ++irq.entries;
}
} // namespace pce
