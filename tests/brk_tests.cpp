// Authored BRK expectations, independent of the interpreter/native comparison.
#include "pce/runtime.hpp"
#include "brk_fixture.hpp"
#include <iostream>
#include <limits>
#include <tuple>

namespace {
constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
unsigned checks=0;
void require(bool okay,const char* why){++checks;if(!okay)throw std::runtime_error(why);}
template<class F> void refuses(F action,const char* why){bool fault=false;
    try{action();}catch(const pce::Fault&){fault=true;}require(fault,why);}
auto state(const pce::Cpu& s){return std::tuple{s.a,s.x,s.y,s.p,s.sp,s.pc,s.mpr,s.mpr_latch,s.cycles,s.ticks,
    s.native_steps,s.interpreter_steps,s.irq_entries,s.irq_vector,s.irq_sampled,s.rti_steps};}
pce::Exit step(pce::Bus& b,pce::Cpu& s,bool native,std::uint64_t deadline=forever){
    return native?pce::generated_step(b,s,deadline):pce::interpret_step(b,s,deadline);}
void initialize(pce::Bus& b){b=pce::Bus{};
    for(unsigned bank:{0xF8U,0xF9U,0x81U})b.kind[bank]=pce::BankKind::ram;
}
void restore(pce::Bus& b,const pce::Cpu& s){
    for(auto [pa,value]:brk_program)(*b.bytes)[pa]=value;
    for(auto [offset,target]:{std::pair{0xFFF6U,0x2900U},std::pair{0xFFF8U,0x2920U},std::pair{0xFFFAU,0x2940U}}){
        (*b.bytes)[pce::Bus::physical(s,offset)]=target&255;
        (*b.bytes)[pce::Bus::physical(s,offset+1)]=target>>8;
    }
}
void one(pce::Bus& b,bool native,unsigned divisor,unsigned flags,unsigned sp,
         std::uint16_t pc,const std::array<std::uint8_t,8>& mapping){
    pce::Cpu s;s.mpr=mapping;s.pc=pc;s.p=flags;s.sp=sp;s.a=0x63;s.x=0xA7;s.y=0x3B;s.mpr_latch=0xC5;
    s.clock_divisor=divisor;restore(b,s);
    const auto resume=static_cast<std::uint16_t>(pc+2);
    const auto stack=[&](unsigned slot){return (*b.bytes)[pce::Bus::physical(s,static_cast<std::uint16_t>(0x2100|(slot&255)))];};
    require(step(b,s,native)==pce::Exit::executed,"BRK did not execute");
    require(s.pc==brk_handler && s.sp==((sp+253)&255),"BRK mapped vector or wrapped stack pointer");
    require(stack(sp)==(resume>>8) && stack(sp-1)==(resume&255) && stack(sp-2)==((flags|pce::B)&~pce::T),
        "BRK stack order/PC+2/B/T or entry-D preservation");
    require(s.p==((flags|pce::I)&~(pce::D|pce::T)),"BRK live I/D/T flags");
    require(s.a==0x63 && s.x==0xA7 && s.y==0x3B && s.mpr==mapping && s.mpr_latch==0xC5,"BRK unrelated registers/mapping");
    require(s.cycles==8 && s.ticks==8*divisor && s.native_steps==unsigned(native) &&
        s.interpreter_steps==unsigned(!native) && !s.irq_entries && !s.rti_steps,"BRK retirement/cycles fabricated a hardware IRQ");
    require(step(b,s,native)==pce::Exit::executed,"BRK target RTI did not execute");
    require(s.pc==resume && s.sp==sp && s.p==(flags&~(pce::B|pce::T)),"BRK/RTI exact return/status/stack restoration");
    require(s.cycles==15 && s.ticks==15*divisor && s.native_steps==2*unsigned(native) &&
        s.interpreter_steps==2*unsigned(!native) && s.rti_steps==1 && !s.irq_entries,"BRK/RTI clocks or extra IRQ retirement");
}
void matrices(){
    pce::Bus b;
    for(bool native:{false,true})for(unsigned speed:{3U,12U}){
        initialize(b);
        for(unsigned flags=0;flags<256;++flags)for(unsigned sp=0;sp<256;++sp)
            one(b,native,speed,flags,sp,0x2800,brk_contexts[0]);
        for(const auto& context:brk_contexts)for(auto pc:brk_sites)
            for(unsigned flags:{0U,255U,0x28U,0xD7U})for(unsigned sp:{0U,1U,2U,0x10U,0x80U,0xFEU,0xFFU})
                one(b,native,speed,flags,sp,pc,context);
    }
}
void sampled_irq(){
    pce::Bus b;
    for(bool native:{false,true})for(unsigned speed:{3U,12U})for(unsigned flags:{0U,4U,8U,0x20U,0xFFU})
        for(unsigned requests=0;requests<8;++requests)for(unsigned mask:{0U,1U,2U,4U,7U}){
        initialize(b);b.enable_interrupts();b.irq.external=requests;b.irq.timer_pending=(requests&4)!=0;b.irq.mask=mask;
        pce::Cpu s;s.mpr=brk_contexts[0];s.pc=0x2800;s.p=flags;s.sp=0xFF;s.clock_divisor=speed;restore(b,s);
        const unsigned pending=flags&pce::I?0:requests&~mask;
        const unsigned vector=pending&4?0xFFFA:pending&2?0xFFF8:pending&1?0xFFF6:0;
        const unsigned target=vector==0xFFFA?0x2940:vector==0xFFF8?0x2920:brk_handler;
        require(step(b,s,native)==pce::Exit::executed,"BRK with sampled IRQ did not execute");
        require(s.cycles==(vector?16U:8U) && s.ticks==s.cycles*speed && s.pc==target &&
            s.sp==(vector?0xF9:0xFC) && s.irq_entries==unsigned(vector!=0) && b.irq.entries==unsigned(vector!=0),
            "BRK dropped or fabricated a previously sampled IRQ");
        require(s.native_steps==unsigned(native) && s.interpreter_steps==unsigned(!native),"BRK pending IRQ retired another opcode");
        if(vector){require((*b.bytes)[0x1F01FC]==0x29 && (*b.bytes)[0x1F01FB]==0 &&
            (*b.bytes)[0x1F01FA]==(((flags|pce::I)&~(pce::D|pce::T))&~pce::B),"post-BRK IRQ stacked the wrong return/status");}
    }
}
void guards_and_faults(){
    pce::Bus b;pce::Cpu s;
    for(bool native:{false,true}){
        initialize(b);s=pce::Cpu{};s.mpr=brk_contexts[0];s.pc=0x2800;s.p=0xFF;restore(b,s);
        const auto before=state(s);
        require(step(b,s,native,0)==pce::Exit::budget && state(s)==before,"BRK deadline produced stack/vector effects");
        s.ticks=1;require(step(b,s,native,1)==pce::Exit::budget && s.sp==255,"equal BRK deadline entered instruction");
        require(step(b,s,native,2)==pce::Exit::executed && s.cycles==8 && s.ticks==25,"BRK failed whole-instruction budget crossing");
    }
    initialize(b);s=pce::Cpu{};s.mpr=brk_contexts[0];s.pc=0x2800;restore(b,s);
    (*b.bytes)[pce::Bus::physical(s,0x2801)]^=1;const auto before=state(s);
    require(pce::generated_step(b,s,forever)==pce::Exit::miss && state(s)==before,"BRK signature guard mutated guest before miss");
    require(pce::interpret_step(b,s,forever)==pce::Exit::executed && s.pc==brk_handler,"ignored BRK signature became an operand");
    initialize(b);s=pce::Cpu{};s.mpr=brk_contexts[1];s.pc=0x3FFF;restore(b,s);b.kind[0xF9]=pce::BankKind::unmapped;
    require(pce::generated_step(b,s,forever)==pce::Exit::miss,"BRK native guard accepted unreadable signature");
    require(pce::interpret_step(b,s,forever)==pce::Exit::executed && s.pc==brk_handler,"interpreter polled unreadable BRK signature");
    // Signature maps to VDC MMIO, while opcode/stack/vector stay ordinary RAM.
    initialize(b);s=pce::Cpu{};s.mpr=brk_contexts[0];s.pc=0x3FFF;restore(b,s);s.mpr[2]=0xFF;
    b.kind[0xFF]=pce::BankKind::io;b.enable_vdc();b.vdc.status=0x3F;
    require(pce::interpret_step(b,s,forever)==pce::Exit::executed && !b.vdc.reads && b.vdc.status==0x3F && s.cycles==8,
        "BRK signature caused an unintended VDC read/wait/status acknowledgement");
    for(bool native:{false,true}){
        initialize(b);s=pce::Cpu{};s.mpr=brk_contexts[2];s.pc=0x2800;restore(b,s);b.kind[0x81]=pce::BankKind::unmapped;
        refuses([&]{step(b,s,native);},"unmapped BRK vector invented an interrupt destination");
        require(!s.native_steps && !s.interpreter_steps && s.sp==0xFC,"faulted BRK retired or hid preceding stack writes");
    }
    for(unsigned op:{0x0BU,0x1BU,0x2BU,0x33U,0x3BU,0x4BU,0x5BU,0x5CU,0x63U,0x6BU,0x7BU,
        0x8BU,0x9BU,0xABU,0xBBU,0xCBU,0xDBU,0xDCU,0xE2U,0xEBU,0xFBU,0xFCU}){
        initialize(b);s=pce::Cpu{};s.mpr=brk_contexts[0];s.pc=0x2800;s.p=0xFF;restore(b,s);
        (*b.bytes)[pce::Bus::physical(s,s.pc)]=op;const auto old=state(s);
        require(pce::interpret_step(b,s,forever)==pce::Exit::unsupported && state(s)==old,"reserved opcode silently executed as NOP");
    }
}
}
int main(){try{matrices();sampled_irq();guards_and_faults();
    std::cout<<checks<<" authored BRK/RTI status/stack/vector/speed/alias/IRQ/guard expectations passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
