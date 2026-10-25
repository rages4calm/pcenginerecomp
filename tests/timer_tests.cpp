#include "pce/runtime.hpp"
#include "timer_fixture.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <limits>
#include <tuple>
#include <vector>

namespace {
constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
constexpr unsigned ram=0x1F0000;
unsigned checks=0;
void require(bool value,const char* reason) {
    if(!value)throw std::runtime_error(reason);
    ++checks;
}
void initialize(pce::Bus& b,pce::Cpu& c,unsigned speed=3) {
    b=pce::Bus{};b.kind[0xF8]=pce::BankKind::ram;b.enable_interrupts();
    for(auto [at,value]:timer_program)(*b.bytes)[at]=value;
    (*b.bytes)[ram+0x1FFA]=0x50;(*b.bytes)[ram+0x1FFB]=0x28;
    c=pce::Cpu{};c.mpr=timer_mpr;c.clock_divisor=speed;c.p=pce::I;c.sp=0xFF;
}
void execute(pce::Bus& b,pce::Cpu& c,bool native,unsigned pc) {
    c.pc=static_cast<std::uint16_t>(pc);
    require((native?pce::generated_step(b,c,forever):pce::interpret_step(b,c,forever))==pce::Exit::executed,
            "Timer instruction did not execute in selected tier");
}
auto cpu_state(const pce::Cpu& c) {
    return std::tuple{c.a,c.x,c.y,c.p,c.sp,c.pc,c.mpr,c.mpr_latch,c.cycles,c.ticks,
        c.clock_divisor,c.native_steps,c.interpreter_steps,c.irq_sampled,c.irq_entries,c.irq_vector};
}
auto irq_state(const pce::Interrupts& t) {
    return std::tuple{t.enabled,t.timer_enabled,t.timer_pending,t.mask,t.external,t.timer_reload,
        t.timer_counter,t.timer_frozen_phase,t.master_ticks,t.timer_deadline,t.entries,t.reads,t.writes};
}
void reset_and_mirrors(pce::Bus& b) {
    pce::Cpu c;initialize(b,c);
    // Reset and same-state disabled writes do not start or precharge the divider.
    for(unsigned control:{0U,2U,0xFEU}) {
        b.write(c,0x0C01,static_cast<std::uint8_t>(control));
        require(!b.irq.timer_enabled && b.irq.timer_frozen_phase==0 && b.irq.timer_deadline==0,
                "Repeated disabled control changed reset divider phase");
    }
    for(unsigned reload=0;reload<256;++reload) {
        b.write(c,0x0C00,static_cast<std::uint8_t>(reload));
        require(b.irq.timer_reload==(reload&127) && b.irq.timer_counter==0 && b.irq.timer_frozen_phase==0,
                "Reload-only write changed disabled reset counter or phase");
    }
    c.ticks=1000000;b.sync(c);
    for(unsigned address=0x0C00;address<=0x0FFF;++address)for(unsigned latch:{0U,128U}) {
        b.io_latch=static_cast<std::uint8_t>(latch);
        require(b.read(c,static_cast<std::uint16_t>(address))==(127|latch),
                "Disabled reset timer mirror or high bus-latch bit mismatch");
    }
    require(!b.irq.timer_pending && !b.irq.timer_counter && !b.irq.timer_deadline && b.irq.timer_frozen_phase==0,
            "Reading or advancing disabled reset timer manufactured an edge");
    // Real power-on resets the divider independently of a pristine enable call.
    for(bool hucard:{false,true}) {
        std::vector<std::uint8_t> image(hucard?8192:262144,0xEA);
        image[0x1FFE]=0;image[0x1FFF]=0xE0;
        b=pce::Bus{};
        if(hucard)b.configure_hucard(image);else b.configure_system_card(pce::SystemCardProfile::super,image);
        b.enable_interrupts();b.irq.timer_frozen_phase=3072;b.power_on_cpu(c);
        c.mpr[0]=0xFF;
        require(b.irq.timer_frozen_phase==0 && !b.irq.timer_enabled && b.read(c,0x0C00)==255,
                "Reset startup failed to restore disabled zero phase and initial high latch");
    }
}
void read_boundaries(pce::Bus& b) {
    pce::Cpu c;initialize(b,c);
    // Every position in a full 3072-master-tick period, independent counter
    // values and the undriven latch bit. Disabled phase never follows time.
    for(unsigned remaining=1;remaining<=3072;++remaining)for(unsigned counter:{0U,1U,127U})for(unsigned high:{0U,128U}) {
        b.irq=pce::Interrupts{};b.irq.enabled=true;b.irq.timer_enabled=true;
        b.irq.timer_counter=static_cast<std::uint8_t>(counter);b.irq.timer_deadline=3072;
        c.ticks=3072-remaining;b.io_latch=static_cast<std::uint8_t>(high);
        const unsigned expected=counter==0 && remaining<=15?127:counter;
        require(b.read(c,0x0C00)==(expected|high),"Timer predictor cutoff or counter value mismatch");
        require(!b.irq.timer_pending && b.irq.timer_counter==counter && b.irq.timer_frozen_phase==0,
                "Timer read changed counter, frozen phase or pending IRQ");
    }
    for(bool native:{false,true})for(unsigned speed:{3U,12U})for(unsigned remaining:{0U,1U,15U,16U,3072U})for(unsigned pc:{0x2800U,0x2870U}) {
        initialize(b,c,speed);b.irq.timer_enabled=true;b.irq.timer_deadline=3072;
        b.irq.timer_reload=7;c.ticks=3072-remaining;
        execute(b,c,native,pc);
        const unsigned expected=remaining==0?7:remaining<=15?127:0;
        require(c.a==expected && c.cycles==5 && c.pc==pc+3,"LDA timer boundary value/cycle/PC mismatch");
        require(c.ticks==3072-remaining+5*speed && c.irq_entries==0,
                "Timer LDA changed CPU speed or delivered masked interrupt");
        require(c.native_steps==unsigned(native) && c.interpreter_steps==unsigned(!native),
                "Timer LDA did not retire exclusively in the selected tier");
        require(b.irq.timer_pending==(remaining<=5*speed),"Timer edge at LDA completion was lost or early");
    }
}
void controls_and_irq(pce::Bus& b) {
    for(bool native:{false,true})for(unsigned speed:{3U,12U})for(unsigned reload:{0U,1U,127U}) {
        pce::Cpu c;initialize(b,c,speed);c.a=static_cast<std::uint8_t>(reload);
        execute(b,c,native,0x2810);
        require(b.irq.timer_reload==reload && b.irq.timer_counter==0 && b.irq.timer_frozen_phase==0,
                "STA reload precharged the stopped divider");
        const auto start=c.ticks;c.a=1;execute(b,c,native,0x2820);
        require(b.irq.timer_deadline==start+3072 && b.irq.timer_counter==reload && b.irq.timer_frozen_phase==3072,
                "Timer enable did not load the new period and counter");
        c.a=3;execute(b,c,native,0x2820);
        require(b.irq.timer_deadline==start+3072,"Repeated enabled write restarted the divider");
        c.a=9;execute(b,c,native,0x2810);
        require(b.irq.timer_reload==9 && b.irq.timer_counter==reload && b.irq.timer_deadline==start+3072,
                "Running reload write changed current divider or counter");
        c.ticks=start+3072*(reload+1);b.sync(c);
        require(b.irq.timer_pending && b.irq.timer_counter==9,"Changed reload was not loaded by actual underflow");
        c.a=0;execute(b,c,native,0x2820);
        require(!b.irq.timer_enabled && b.irq.timer_pending && b.irq.timer_counter==9 &&
                b.irq.timer_frozen_phase==3072 && b.irq.timer_deadline==0,
                "Disable did not freeze a fresh divider or incorrectly acknowledged TIQ");
        c.a=0;execute(b,c,native,0x2830);
        require(!b.irq.timer_pending && b.irq.timer_frozen_phase==3072,"TIQ acknowledgement changed stopped phase");
        c.ticks+=1000000;b.sync(c);
        execute(b,c,native,0x2800);
        require(c.a==9 && b.irq.timer_counter==9 && b.irq.timer_frozen_phase==3072 && !b.irq.timer_pending,
                "Stopped timer phase followed elapsed guest time");
        c.a=0;execute(b,c,native,0x2810);c.a=1;
        const auto restart=c.ticks;execute(b,c,native,0x2820);
        require(b.irq.timer_counter==0 && b.irq.timer_deadline==restart+3072,"Re-enable retained stale counter/edge");
        c.ticks=restart+3072;b.sync(c);c.p=0;
        execute(b,c,native,0x2840);
        require(c.irq_entries==1 && c.irq_vector==0xFFFA && c.pc==0x2850 && b.irq.timer_pending,
                "Timer restart did not deliver priority TIQ without acknowledgement");
        c.a=0;execute(b,c,native,0x2830);execute(b,c,native,0x2850);
        require(c.rti_steps==1 && c.pc==0x2841 && c.sp==0xFF && !b.irq.timer_pending,
                "Timer handler acknowledgement/RTI failed to return to interrupted stream");
    }
    // A zero counter stopped after enable reads zero indefinitely, whereas
    // the untouched reset divider reads127 indefinitely.
    for(bool native:{false,true})for(unsigned speed:{3U,12U}) {
        pce::Cpu c;initialize(b,c,speed);execute(b,c,native,0x2800);
        require(c.a==127,"Untouched reset divider must read127 in actual guest LDA");
        c.a=1;execute(b,c,native,0x2820);c.a=0;execute(b,c,native,0x2820);
        c.ticks+=1000000;execute(b,c,native,0x2800);
        require(c.a==0 && !b.irq.timer_pending && b.irq.timer_frozen_phase==3072,
                "Stopped zero counter retained reset prediction or expired while disabled");
    }
}
void block_and_guards(pce::Bus& b) {
    for(bool native:{false,true})for(unsigned speed:{3U,12U}) {
        pce::Cpu c;initialize(b,c,speed);b.io_latch=0x80;
        std::fill_n(b.bytes->begin()+ram+0x200,4,0x55);
        execute(b,c,native,0x2860);
        require(std::all_of(b.bytes->begin()+ram+0x200,b.bytes->begin()+ram+0x204,[](auto v){return v==0;}),
                "Block timer reads polled counter instead of transfer-zero bus behavior");
        require(b.io_latch==0x80 && b.irq.reads==0 && b.irq.timer_frozen_phase==0 && !b.irq.timer_pending,
                "Block timer reads changed stopped phase, latch or register counters");
        require(c.cycles==41 && c.ticks==41*speed && c.block_bytes==4,"Timer-source block timing mismatch");
        initialize(b,c,speed);b.irq.timer_enabled=true;b.irq.timer_deadline=3072;c.ticks=3069;c.p=0;
        execute(b,c,native,0x2860);
        require(c.pc==0x2850 && c.irq_entries==1 && b.irq.timer_pending && c.block_bytes==4,
                "Timer IRQ was lost or block transfer did not complete before delivery");
    }
    for(unsigned phase:{0U,3072U})for(unsigned patch:{0U,1U,2U}) {
        pce::Cpu c;initialize(b,c);c.pc=0x2800;c.ticks=123;b.irq.timer_frozen_phase=static_cast<std::uint16_t>(phase);
        b.irq.timer_pending=true;b.irq.master_ticks=0;
        if(patch==0)(*b.bytes)[ram+0x800]^=1;
        else if(patch==1)c.mpr[7]^=1;
        const auto before_cpu=cpu_state(c);
        const auto before_irq=irq_state(b.irq);
        const auto result=pce::generated_step(b,c,patch==2?c.ticks:forever);
        require(result==(patch==2?pce::Exit::budget:pce::Exit::miss),"Timer native guard did not refuse changed source/mapping or deadline");
        require(cpu_state(c)==before_cpu && irq_state(b.irq)==before_irq,
                "Refused native timer instruction mutated CPU, divider, pending IRQ or counters");
    }
}
} // namespace

int main() {
    try {
        pce::Bus bus;reset_and_mirrors(bus);read_boundaries(bus);controls_and_irq(bus);block_and_guards(bus);
        std::cout<<checks<<" authored timer phase, MMIO, native/interpreted instruction, IRQ/block and guard expectations passed\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
