#include "pce/runtime.hpp"
#include "irq_fixture.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <tuple>

static constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
static constexpr unsigned ram=0x1F0000;
static void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
static pce::Exit execute(pce::Bus& b,pce::Cpu& s,bool native,std::uint64_t deadline=forever){
    return native?pce::generated_step(b,s,deadline):pce::interpret_step(b,s,deadline);
}
static void initialize(pce::Bus& b){
    b=pce::Bus{};b.kind[0xF8]=pce::BankKind::ram;b.enable_interrupts();
    for(auto [pa,value]:irq_program)(*b.bytes)[pa]=value;
    for(unsigned offset:{0x1FF6U,0x1FF8U,0x1FFAU}){
        (*b.bytes)[ram+offset]=offset==0x1FF6?0:offset==0x1FF8?0x70:0x80;
        (*b.bytes)[ram+offset+1]=0x29;
    }
}
static auto state(const pce::Cpu& s){
    return std::tuple{s.a,s.x,s.y,s.sp,s.p,s.pc,s.mpr,s.mpr_latch,s.ticks,s.cycles,
                     s.native_steps,s.interpreter_steps,s.irq_sampled,s.irq_entries,s.irq_vector,s.rti_steps};
}
static unsigned vector_for(unsigned requests){return requests&4?0xFFFA:requests&2?0xFFF8:requests&1?0xFFF6:0;}
static unsigned target_for(unsigned vector){return vector==0xFFFA?0x2980:vector==0xFFF8?0x2970:0x2900;}

static unsigned entry_matrix(pce::Bus& b){
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U}){
        initialize(b);
        for(unsigned flags=0;flags<256;++flags)for(unsigned mask=0;mask<8;++mask)for(unsigned requests=0;requests<8;++requests){
            pce::Cpu s;s.mpr=irq_mpr;s.pc=0x2800;s.p=flags;s.sp=flags;s.a=0x51;s.x=0xA3;s.y=0x7E;
            s.clock_divisor=speed;s.mpr_latch=0x93;
            b.irq.mask=mask;b.irq.external=requests;b.irq.timer_pending=false;
            b.irq.master_ticks=0;
            // Timer priority is conditional on the live request, including a
            // real timer source. Keep it asserted for the entry matrix.
            b.irq.timer_pending=(requests&4)!=0;
            const auto entries=b.irq.entries;
            const unsigned eligible=(flags&4)?0:requests&~mask;
            const unsigned vector=vector_for(eligible),post_flags=flags&0xDF;
            require(execute(b,s,native)==pce::Exit::executed,"IRQ matrix NOP did not execute");
            require(s.a==0x51 && s.x==0xA3 && s.y==0x7E && s.mpr==irq_mpr && s.mpr_latch==0x93,"IRQ changed general registers or MPR identity");
            require(s.native_steps==unsigned(native) && s.interpreter_steps==unsigned(!native),"IRQ entry retired a fabricated CPU instruction");
            require(s.cycles==(vector?10U:2U) && s.ticks==s.cycles*speed,"IRQ eight-cycle timing or speed expectation");
            require(s.irq_entries==unsigned(vector!=0) && b.irq.entries==entries+unsigned(vector!=0),"IRQ entry accounting");
            if(vector){
                require(s.pc==target_for(vector) && s.irq_vector==vector && s.sp==((flags+253)&255),"IRQ vector priority or stack pointer expectation");
                require(s.p==((post_flags|4)&~8U),"IRQ I/D/T flag expectation");
                require((*b.bytes)[ram+0x100+flags]==0x28 && (*b.bytes)[ram+0x100+((flags+255)&255)]==1 &&
                        (*b.bytes)[ram+0x100+((flags+254)&255)]==(post_flags&0xEF),"IRQ PC high/low/status stack order or wrap");
            }else require(s.pc==0x2801 && s.sp==flags && s.p==post_flags,"masked or I-disabled IRQ changed execution");
            ++checks;
        }
    }
    return checks;
}

static unsigned rti_matrix(pce::Bus& b){
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U}){
        initialize(b);
        for(unsigned flags=0;flags<256;++flags)for(unsigned stack=0;stack<256;++stack){
            pce::Cpu s;s.mpr=irq_mpr;s.pc=0x2840;s.p=0xFF;s.sp=stack;s.clock_divisor=speed;s.a=0x35;s.x=0xAC;s.y=0x71;
            b.irq.master_ticks=0;
            (*b.bytes)[ram+0x100+((stack+1)&255)]=flags;
            (*b.bytes)[ram+0x100+((stack+2)&255)]=static_cast<std::uint8_t>(stack^0xB6);
            (*b.bytes)[ram+0x100+((stack+3)&255)]=static_cast<std::uint8_t>(flags^0xD9);
            require(execute(b,s,native)==pce::Exit::executed,"RTI fixture did not execute");
            require(s.pc==((stack^0xB6)|((flags^0xD9)<<8)) && s.p==(flags&0xEF) && s.sp==((stack+3)&255),"RTI exact PC/status/SP expectation");
            require(s.a==0x35 && s.x==0xAC && s.y==0x71 && s.mpr==irq_mpr,"RTI changed unrelated state");
            require(s.cycles==7 && s.ticks==7*speed && s.rti_steps==1 && s.irq_entries==0 &&
                    s.native_steps==unsigned(native) && s.interpreter_steps==unsigned(!native),"RTI timing/retirement expectation");
            ++checks;
        }
    }
    return checks;
}

static unsigned sampling(pce::Bus& b){
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U}){
        initialize(b);b.irq.external=2;pce::Cpu s;s.mpr=irq_mpr;s.pc=0x2810;s.p=4;s.clock_divisor=speed;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2811 && !s.irq_entries && s.p==0,"CLI did not delay IRQ through its own instruction");
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2970 && s.irq_entries==1 && s.cycles==12,"pending IRQ did not follow the instruction after CLI");
        require((*b.bytes)[ram+0x1FE]==0x12 && (*b.bytes)[ram+0x1FD]==0,"CLI-delayed entry stacked wrong post-NOP PC/P");++checks;
        initialize(b);b.irq.external=2;s=pce::Cpu{};s.mpr=irq_mpr;s.pc=0x2820;s.p=8;s.clock_divisor=speed;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2970 && s.p==4 && s.irq_entries==1 && (*b.bytes)[ram+0x1FD]==12,
                "SEI suppressed an IRQ already sampled with entry I clear");++checks;
        initialize(b);b.irq.external=1;s=pce::Cpu{};s.mpr=irq_mpr;s.pc=0x2830;s.p=4;s.sp=0xFE;s.clock_divisor=speed;
        (*b.bytes)[ram+0x1FF]=0x28;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2831 && s.p==0x28 && !s.irq_entries,"PLP did not retain restored T or delay newly enabled IRQ");
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2900 && s.p==4 && (*b.bytes)[ram+0x1FD]==8,"PLP IRQ delay/next-op T clear/stack status");++checks;
        initialize(b);b.irq.external=2;s=pce::Cpu{};s.mpr=irq_mpr;s.pc=0x2840;s.p=4;s.sp=0xFC;s.clock_divisor=speed;
        (*b.bytes)[ram+0x1FD]=0x20;(*b.bytes)[ram+0x1FE]=0;(*b.bytes)[ram+0x1FF]=0x28;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2800 && s.p==0x20 && !s.irq_entries,"RTI did not retain restored T or delayed I sample");
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2970 && s.p==4 && s.rti_steps==1 && s.irq_entries==1,"IRQ level did not retrigger after RTI delay");++checks;
        initialize(b);b.irq.external=2;s=pce::Cpu{};s.mpr=irq_mpr;s.pc=0x2840;s.p=0;s.sp=0xFC;s.clock_divisor=speed;
        (*b.bytes)[ram+0x1FD]=0xAC;(*b.bytes)[ram+0x1FE]=0;(*b.bytes)[ram+0x1FF]=0x28;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2970 && s.p==0x84 && s.sp==0xFC &&
                s.cycles==15 && s.rti_steps==1 && s.irq_entries==1 && (*b.bytes)[ram+0x1FD]==0xAC &&
                (*b.bytes)[ram+0x1FE]==0 && (*b.bytes)[ram+0x1FF]==0x28,
                "RTI setting I suppressed an entry-sampled IRQ or stacked wrong restored state");++checks;
        initialize(b);b.irq.external=2;s=pce::Cpu{};s.mpr=irq_mpr;s.pc=0x2960;s.p=0;s.clock_divisor=speed;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2970 && (*b.bytes)[ram+0x1FD]==0x20 && s.p==4,"SET IRQ must stack newly set T before clearing live T");++checks;
        initialize(b);b.irq.external=2;s=pce::Cpu{};s.mpr=irq_mpr;s.pc=0x2850;s.a=2;s.p=0;s.clock_divisor=speed;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2970 && b.irq.mask==2,"mask write retroactively suppressed sampled IRQ");++checks;
        initialize(b);b.irq.external=2;b.irq.mask=2;s=pce::Cpu{};s.mpr=irq_mpr;s.pc=0x2850;s.a=0;s.p=0;s.clock_divisor=speed;
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2853 && b.irq.mask==0 && !s.irq_entries,"mask clear accepted IRQ without entry sample");
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2970 && s.irq_entries==1,"mask-clear delay did not end after following instruction");++checks;
    }
    return checks;
}

static unsigned boundaries(pce::Bus& b){
    unsigned checks=0;
    for(bool native:{false,true}){
        initialize(b);b.irq.external=7;b.irq.timer_pending=true;pce::Cpu s;s.mpr=irq_mpr;s.pc=0x2800;s.p=0;
        const auto before=state(s);const auto generation=b.generation;const auto entries=b.irq.entries;
        require(execute(b,s,native,0)==pce::Exit::budget && state(s)==before && b.generation==generation && b.irq.entries==entries,
                "deadline changed IRQ sample/stack/state");++checks;
        require(execute(b,s,native,1)==pce::Exit::executed && s.pc==0x2980 && s.ticks==30,"IRQ could not finish past instruction-entry deadline");++checks;
    }
    for(unsigned page=0;page<8;++page){
        initialize(b);b.irq.external=2;pce::Cpu s;s.mpr=irq_mpr;s.pc=0x2800;s.p=0;s.mpr[page]^=1;
        const auto before=state(s);const auto generation=b.generation;
        require(pce::generated_step(b,s,forever)==pce::Exit::miss && state(s)==before && generation==b.generation && !b.irq.entries,
                "native MPR miss entered IRQ or sampled line");++checks;
    }
    initialize(b);b.irq.external=2;pce::Cpu s;s.mpr=irq_mpr;s.pc=0x2800;s.p=0;(*b.bytes)[ram+0x800]=0x38;
    const auto before=state(s);
    require(pce::generated_step(b,s,forever)==pce::Exit::miss && state(s)==before && !b.irq.entries,"native byte miss entered IRQ");++checks;
    require(pce::step(b,s,forever)==pce::Exit::executed && s.pc==0x2970 && s.irq_entries==1 && s.interpreter_steps==1 &&
            s.native_steps==0 && (*b.bytes)[ram+0x1FD]==1,"mutated fallback did not stack actual opcode status");++checks;
    // Stack and vectors use their independently selected MPRs, not physical
    // constants or the native module's former mapping.
    initialize(b);b.kind[0x81]=pce::BankKind::ram;b.kind[0x82]=pce::BankKind::ram;b.irq.external=1;
    s=pce::Cpu{};s.mpr=irq_mpr;s.mpr[1]=0x81;s.mpr[7]=0x82;s.pc=0x2800;s.p=0;s.sp=0;
    (*b.bytes)[0x102800]=0xEA;(*b.bytes)[0x105FF6]=0x34;(*b.bytes)[0x105FF7]=0x12;
    require(pce::interpret_step(b,s,forever)==pce::Exit::executed && s.pc==0x1234 && s.sp==0xFD &&
            (*b.bytes)[0x102100]==0x28 && (*b.bytes)[0x1021FF]==1 && (*b.bytes)[0x1021FE]==0,
            "IRQ did not translate stack MPR1 and vector MPR7 independently");++checks;
    return checks;
}

static unsigned registers_timer(pce::Bus& b){
    unsigned checks=0;
    for(unsigned alias:{0x1400U,0x17FCU,0x9400U})for(unsigned value=0;value<256;++value){
        initialize(b);pce::Cpu s;s.mpr=irq_mpr;s.mpr[4]=0xFF;b.irq.external=3;b.irq.timer_pending=true;
        b.write(s,alias+2,value);
        require(b.irq.mask==(value&7) && b.read(s,alias+2)==value,"IRQ mask high latch or mirror expectation");
        const unsigned expected=(value&0xF8)|7;
        require(b.read(s,alias+3)==expected,"IRQ request did not preserve upper latch bits");
        b.write(s,alias+3,value);require(!b.irq.timer_pending && b.irq.external==3 && b.read(s,alias+3)==((value&0xF8)|3),"IRQ acknowledge did not clear only timer");
        b.write(s,alias,value^0xAA);require(b.irq.mask==(value&7) && b.read(s,alias+1)==(value^0xAA),"undriven IRQ registers changed mask or failed to return latch");
        ++checks;
    }
    for(unsigned speed:{3U,12U})for(unsigned reload:{0U,1U,0x7FU}){
        initialize(b);pce::Cpu s;s.mpr=irq_mpr;s.clock_divisor=speed;
        b.write(s,0x0C00,reload);b.write(s,0x0C01,1);
        require(b.irq.timer_enabled && b.irq.timer_counter==reload && b.irq.timer_deadline==3072,"timer start did not load counter and 3072-master period");
        s.ticks=3071;b.sync(s);require(!b.irq.timer_pending && b.irq.timer_counter==reload,"timer decremented before first edge");
        s.ticks=3072;b.sync(s);require(b.irq.timer_counter==(reload?reload-1:0) && b.irq.timer_pending==(reload==0),"timer first decrement/reload expectation");
        s.ticks=3072ULL*(reload+1);b.sync(s);require(b.irq.timer_pending && b.irq.timer_counter==reload,"timer full period did not latch request and reload");
        b.write(s,0x1403,0);require(!b.irq.timer_pending,"timer IRQ acknowledgement did not clear request");
        b.write(s,0x0C01,0);const auto held=b.irq.timer_counter;s.ticks+=100000;b.sync(s);
        require(!b.irq.timer_enabled && b.irq.timer_counter==held && !b.irq.timer_pending,"disabled timer advanced or manufactured request");++checks;
    }
    for(bool native:{false,true}){
        initialize(b);pce::Cpu s;s.mpr=irq_mpr;s.pc=0x2800;s.p=0;
        b.write(s,0x0C00,0);b.write(s,0x0C01,1);s.ticks=3069;b.sync(s);
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2801 && b.irq.timer_pending && !s.irq_entries,
                "timer asserted during instruction was delivered without a boundary sample");
        require(execute(b,s,native)==pce::Exit::executed && s.pc==0x2980 && s.irq_entries==1,"timer was not delivered after next sample");++checks;
    }
    initialize(b);pce::Cpu clock;clock.mpr=irq_mpr;
    b.write(clock,0x0C00,0);b.write(clock,0x0C01,1);
    clock.ticks=3056;b.sync(clock);require(b.read(clock,0x0C00)==0,"timer early read prediction began before final 15 master ticks");
    clock.ticks=3057;b.sync(clock);require(b.read(clock,0x0FFF)==0x7F,"timer zero-counter read prediction missing in final 15 master ticks");++checks;
    initialize(b);clock=pce::Cpu{};clock.mpr=irq_mpr;
    b.write(clock,0x0C00,2);b.write(clock,0x0C01,1);clock.ticks=3072;b.sync(clock);
    b.write(clock,0x0C00,7);b.write(clock,0x0C01,3);
    require(b.irq.timer_counter==1 && b.irq.timer_deadline==6144,"reload/control rewrite restarted live timer");
    clock.ticks=9216;b.sync(clock);require(b.irq.timer_counter==7 && b.irq.timer_pending,"changed reload was not applied at subsequent underflow");++checks;
    // Partitioning elapsed guest time must not lose timer edges or requests.
    pce::Bus whole,parts;initialize(whole);initialize(parts);pce::Cpu one,many;one.mpr=many.mpr=irq_mpr;
    whole.write(one,0x0C00,3);whole.write(one,0x0C01,1);parts.write(many,0x0C00,3);parts.write(many,0x0C01,1);
    one.ticks=1234567;whole.sync(one);
    for(unsigned t=137;t<1234567;t+=137){many.ticks=t;parts.sync(many);}many.ticks=1234567;parts.sync(many);
    require(whole.irq.timer_counter==parts.irq.timer_counter && whole.irq.timer_pending==parts.irq.timer_pending &&
            whole.irq.timer_deadline==parts.irq.timer_deadline,"timer elapsed-time partition changed state");++checks;
    return checks;
}

int main(){
    try{pce::Bus b;const auto e=entry_matrix(b),r=rti_matrix(b),s=sampling(b),g=boundaries(b),t=registers_timer(b);
        std::cout<<e<<" independent IRQ-entry cases, "<<r<<" RTI status/stack cases, "<<s<<" sampling sequences, "<<g<<" guard/mapping/deadline groups and "<<t<<" IRQ-register/timer groups passed\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
