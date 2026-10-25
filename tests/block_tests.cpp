#include "pce/runtime.hpp"
#include "block_fixture.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <tuple>
#include <vector>

static constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
static constexpr unsigned ram=0x1F0000;
static void require(bool value,const char* why) {if(!value)throw std::runtime_error(why);}
static void initialize(pce::Bus& b,unsigned seed=0) {
    b.kind.fill(pce::BankKind::unmapped);b.kind[0xF8]=pce::BankKind::ram;
    for(unsigned i=0;i<8192;++i)(*b.bytes)[ram+i]=static_cast<std::uint8_t>(i*37+(i>>8)*13+seed*17);
    for(auto [pa,value]:block_program)(*b.bytes)[pa]=value;
    b.generation.fill(0);
}
static auto cpu_state(const pce::Cpu& s) {
    return std::tuple{s.a,s.x,s.y,s.sp,s.p,s.pc,s.mpr,s.mpr_latch,s.cycles,s.ticks,s.clock_divisor,
                      s.native_steps,s.interpreter_steps,s.guard_misses,
                      s.native_block_steps,s.interpreter_block_steps,s.block_bytes};
}
static BlockCase find(unsigned op,unsigned source,unsigned destination,unsigned length) {
    for(auto c:block_cases)if(c.op==op && c.source==source && c.destination==destination && c.length==length)return c;
    throw std::runtime_error("missing authored block instruction");
}

// Independent byte-array model. This deliberately uses no runtime memory,
// addressing, stack, instruction or clock helpers to compute expected values.
struct Expected {
    std::array<std::uint8_t,8192> memory;
    unsigned a,x,y,sp,p,pc,count=0,changes=0;
    std::uint8_t read(unsigned address)const{return memory[address%8192];}
    void write(unsigned address,unsigned value) {
        auto& old=memory[address%8192];if(old!=value){old=static_cast<std::uint8_t>(value);++changes;}
    }
    void push(unsigned value){write(0x2100+sp,value);sp=(sp+255)%256;}
    unsigned pop(){sp=(sp+1)%256;return read(0x2100+sp);}
    void transfer(unsigned op) {
        push(y);push(a);push(x);
        const unsigned source=read(pc+1)+256*read(pc+2);
        const unsigned destination=read(pc+3)+256*read(pc+4);
        count=read(pc+5)+256*read(pc+6);if(!count)count=65536;
        for(unsigned n=0;n<count;++n) {
            const unsigned from=(source+(op==0xC3?65536-n:op==0xF3?n%2:n))%65536;
            const unsigned to=(destination+(op==0xC3?65536-n:op==0xD3?0:op==0xE3?n%2:n))%65536;
            const auto value=read(from);write(to,value);
        }
        x=pop();a=pop();y=pop();p&=~32U;pc=(pc+7)%65536;
    }
};

static unsigned independent(pce::Bus& b) {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U})for(unsigned context=0;context<4;++context)
    for(const auto c:block_cases) {
        initialize(b,context);
        pce::Cpu s;s.mpr=block_mpr;s.pc=c.pc;s.a=0x24;s.x=0;s.y=3;
        constexpr unsigned flags[]={0,0xFF,0x20,0x24};constexpr unsigned stacks[]={0,1,0xFF,0x73};
        s.p=flags[context];s.sp=c.pc<0x2800?static_cast<std::uint8_t>(c.pc+5):stacks[context];
        s.clock_divisor=speed;s.mpr_latch=0xAD;s.cycles=19;s.ticks=19*speed;
        // Gear re-fetches block opcodes between byte steps. Keep its authored
        // zero-count TAI opcode stable when the destination spans all RAM.
        if(c.op==0xF3 && c.length==0){(*b.bytes)[ram+0x300]=0xF3;(*b.bytes)[ram+0x301]=0xF3;}
        Expected expected;std::copy_n(b.bytes->begin()+ram,8192,expected.memory.begin());
        expected.a=s.a;expected.x=s.x;expected.y=s.y;expected.sp=s.sp;expected.p=s.p;expected.pc=s.pc;
        expected.transfer(c.op);
        const auto exit=native?pce::generated_step(b,s,forever):pce::interpret_step(b,s,forever);
        require(exit==pce::Exit::executed,"block fixture instruction did not execute");
        require(s.a==expected.a && s.x==expected.x && s.y==expected.y && s.sp==expected.sp && s.p==expected.p && s.pc==expected.pc,
                "block stack/register/status/PC expectation");
        require(std::equal(expected.memory.begin(),expected.memory.end(),b.bytes->begin()+ram),
                "block address direction, alias, overlap, wrap or zero-count payload expectation");
        const auto cycles=19+17+6*expected.count;
        require(s.cycles==cycles && s.ticks==static_cast<std::uint64_t>(cycles)*speed,
                "block 17+6*n timing or speed expectation");
        require(b.generation[0xF8]==expected.changes,"block writes did not record actual changed bytes");
        require(s.mpr==block_mpr && s.mpr_latch==0xAD,"block changed MPR identity/latch");
        require(s.native_steps==(native?1U:0U) && s.interpreter_steps==(native?0U:1U),"block retired more than one instruction");
        require(s.native_block_steps==(native?1U:0U) && s.interpreter_block_steps==(native?0U:1U) && s.block_bytes==expected.count,
                "block completion and payload accounting");
        ++checks;
    }
    return checks;
}

static unsigned boundaries(pce::Bus& b) {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U}) {
        const auto c=find(0xF3,0x2300,0x2400,17);initialize(b);
        pce::Cpu s;s.mpr=block_mpr;s.pc=c.pc;s.p=0xFF;s.ticks=30;s.cycles=10;s.clock_divisor=speed;
        const auto before=cpu_state(s);const std::vector<std::uint8_t> memory(b.bytes->begin(),b.bytes->end());const auto generation=b.generation;
        require((native?pce::generated_step(b,s,30):pce::interpret_step(b,s,30))==pce::Exit::budget,
                "block deadline was not checked before all effects");
        require(cpu_state(s)==before && std::equal(memory.begin(),memory.end(),b.bytes->begin()) && b.generation==generation,"block deadline changed state");++checks;
        require((native?pce::generated_step(b,s,31):pce::interpret_step(b,s,31))==pce::Exit::executed,
                "block instruction did not complete atomically after allowed entry");
        require(s.ticks==30+(17+6*17)*speed,"block entry-only deadline/atomic completion contract");++checks;
    }
    for(unsigned offset=0;offset<7;++offset) {
        const auto c=find(0x73,0x2300,0x2400,17);initialize(b);
        pce::Cpu s;s.mpr=block_mpr;s.pc=c.pc;s.p=0xFF;
        (*b.bytes)[ram+(c.pc&8191)+offset]^=1;
        const std::vector<std::uint8_t> memory(b.bytes->begin(),b.bytes->end());const auto before=cpu_state(s);const auto generation=b.generation;
        require(pce::generated_step(b,s,forever)==pce::Exit::miss,"block native source byte mutation not rejected");
        require(cpu_state(s)==before && std::equal(memory.begin(),memory.end(),b.bytes->begin()) && generation==b.generation,"block source miss had effects");++checks;
    }
    for(unsigned page=0;page<8;++page) {
        const auto c=find(0xE3,0x2300,0x2400,17);initialize(b);pce::Cpu s;s.mpr=block_mpr;s.pc=c.pc;s.mpr[page]^=1;
        const auto before=cpu_state(s);const std::vector<std::uint8_t> memory(b.bytes->begin(),b.bytes->end());
        require(pce::generated_step(b,s,forever)==pce::Exit::miss,"block native full MPR guard not rejected");
        require(before==cpu_state(s) && std::equal(memory.begin(),memory.end(),b.bytes->begin()),"block mapping miss had effects");++checks;
    }
    return checks;
}

static unsigned status_stack_matrix(pce::Bus& b) {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U})
    for(unsigned op:{0x73U,0xC3U,0xD3U,0xE3U,0xF3U})for(unsigned value=0;value<256;++value) {
        initialize(b,value);const auto c=find(op,0x2300,0x2400,3);
        pce::Cpu s;s.pc=c.pc;s.mpr=block_mpr;s.p=value;s.sp=value;s.a=value^0xA5;s.x=value^0x69;s.y=value^0x96;s.clock_divisor=speed;
        Expected expected;std::copy_n(b.bytes->begin()+ram,8192,expected.memory.begin());
        expected.a=s.a;expected.x=s.x;expected.y=s.y;expected.sp=s.sp;expected.p=s.p;expected.pc=s.pc;expected.transfer(op);
        require((native?pce::generated_step(b,s,forever):pce::interpret_step(b,s,forever))==pce::Exit::executed,
                "block status/stack matrix did not execute");
        require(s.p==(value&0xDF) && s.sp==value && s.a==expected.a && s.x==expected.x && s.y==expected.y &&
                s.pc==expected.pc && s.cycles==35 && s.ticks==35*speed && s.block_bytes==3 &&
                std::equal(expected.memory.begin(),expected.memory.end(),b.bytes->begin()+ram) && b.generation[0xF8]==expected.changes,
                "block full status/stack-pointer matrix differs from independent expectation");
        ++checks;
    }
    return checks;
}

static unsigned overwritten_opcode(pce::Bus& b) {
    unsigned checks=0;
    // Local source-corroborated contract only: these destructive writes are
    // deliberately excluded from the live Geargrafx block-step comparison.
    for(bool native:{false,true})for(unsigned speed:{3U,12U}) {
        initialize(b);const auto c=find(0xF3,0x2300,0x2400,0);
        (*b.bytes)[ram+0x300]=0xAA;(*b.bytes)[ram+0x301]=0x55;
        pce::Cpu s;s.pc=c.pc;s.mpr=block_mpr;s.p=0xFF;s.a=0x24;s.x=0x68;s.y=0x93;s.clock_divisor=speed;
        Expected expected;std::copy_n(b.bytes->begin()+ram,8192,expected.memory.begin());
        expected.a=s.a;expected.x=s.x;expected.y=s.y;expected.sp=s.sp;expected.p=s.p;expected.pc=s.pc;expected.transfer(0xF3);
        require((native?pce::generated_step(b,s,forever):pce::interpret_step(b,s,forever))==pce::Exit::executed,
                "TAI did not finish after its own opcode was overwritten");
        require((*b.bytes)[ram+(c.pc&8191)]!=0xF3 && s.a==expected.a && s.x==expected.x && s.y==expected.y &&
                s.sp==expected.sp && s.p==expected.p && s.pc==expected.pc && s.cycles==393233 &&
                s.ticks==393233*speed && s.block_bytes==65536 &&
                std::equal(expected.memory.begin(),expected.memory.end(),b.bytes->begin()+ram) && b.generation[0xF8]==expected.changes,
                "latched TAI operation differs from the independent destructive-overwrite expectation");
        ++checks;
    }
    return checks;
}

static unsigned devices(pce::Bus& b) {
    unsigned checks=0;
    // Dedicated fixtures use all F8 mappings. Direct wrapper expectations
    // separately cover the actual FF device bank and its additional waits.
    for(unsigned speed:{3U,12U}) {
        b.vdc=pce::Vdc{};b.cd=pce::CdControl{};b.joypad=pce::Joypad{};
        initialize(b);b.enable_joypad(false,true);b.joypad.set_pressed(0,0xFFF);
        pce::Cpu s;s.mpr=block_mpr;s.mpr[0]=0xFF;s.clock_divisor=speed;
        for(unsigned address=0x800;address<0x1800;++address) {
            const auto reads=b.joypad.reads;const auto ticks=s.ticks;
            require(b.read_block(s,address)==0 && b.joypad.reads==reads && s.ticks==ticks,
                    "block profile did not suppress PSG/timer/controller/IRQ reads");++checks;
        }
        b.enable_vdc();b.vdc.selected=2;b.vdc.reg[0]=0;
        b.write_block(s,2,0x34);b.write_block(s,3,0x12);
        require((*b.vdc.vram)[0]==0x1234 && s.cycles==4 && s.ticks==4*speed,
                "block VDC writes require two wait cycles per byte");++checks;
        b.vdc.reg[1]=0;b.vdc.prefetch();
        require(b.read_block(s,2)==0x34 && b.read_block(s,3)==0x12 && s.cycles==8 && s.ticks==8*speed,
                "block VDC reads require two wait cycles per byte");++checks;
        b.enable_video_timing();const auto start=s.ticks;
        b.clock_cpu(s,14);b.clock_cpu(s,6);b.clock_cpu(s,3);
        require(s.ticks==start+23*speed && b.vdc.raster.master_ticks==s.ticks && s.native_steps==0 && s.interpreter_steps==0,
                "block chunk clocks do not advance devices without extra retirements");++checks;

        b.vdc=pce::Vdc{};b.cd=pce::CdControl{};b.joypad=pce::Joypad{};initialize(b);
        b.enable_video_timing();b.vdc.queued_cpu_accesses=false;b.vdc.selected=2;
        // Retained byte-order/cadence fixture uses the explicit immediate
        // reference path; queued contention is exercised by its own suite.
        auto c=find(0xE3,0x2300,2,4);s=pce::Cpu{};s.mpr=block_mpr;s.mpr[0]=0xFF;s.pc=c.pc;s.clock_divisor=speed;s.p=0xFF;
        for(unsigned i=0;i<4;++i)(*b.bytes)[ram+0x300+i]=static_cast<std::uint8_t>(i%2?0x12+i*0x22:0x34+i*0x22);
        require(pce::interpret_step(b,s,forever)==pce::Exit::executed && (*b.vdc.vram)[0]==0x3434 && (*b.vdc.vram)[1]==0x7878,
                "interpreted TIA did not alternate VDC ports in payload order");
        require(s.cycles==49 && s.ticks==49*speed && b.vdc.raster.master_ticks==s.ticks && s.block_bytes==4,
                "interpreted block did not advance VDC timing with each byte and wait");++checks;

        b.vdc=pce::Vdc{};initialize(b);b.enable_joypad(false,true);
        c=find(0xF3,0x2300,0x2400,4);s=pce::Cpu{};s.mpr=block_mpr;s.mpr[0]=0xFF;s.pc=c.pc;s.clock_divisor=speed;
        (*b.bytes)[ram+(c.pc&8191)+1]=0;(*b.bytes)[ram+(c.pc&8191)+2]=0x10;
        require(pce::interpret_step(b,s,forever)==pce::Exit::executed && b.joypad.reads==0 && s.cycles==41,
                "interpreted TAI polled a controller or changed block base timing");
        for(unsigned i=0;i<4;++i)require((*b.bytes)[ram+0x400+i]==0,"block suppressed I/O read did not yield zero");++checks;

        s=pce::Cpu{};s.ticks=forever-2;const auto before=cpu_state(s);bool fault=false;
        try {b.clock_cpu(s,14);}catch(const pce::Fault&){fault=true;}
        require(fault && cpu_state(s)==before,"block chunk clock overflow was not refused before clock changes");++checks;
    }
    return checks;
}

static unsigned irq_boundary(pce::Bus& b) {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U}) {
        b.vdc=pce::Vdc{};b.cd=pce::CdControl{};b.joypad=pce::Joypad{};initialize(b);
        b.enable_vdc();b.vdc.reg[5]=8;b.vdc.reg[11]=31;b.vdc.reg[13]=239;b.vdc.enable_raster();
        const auto c=find(0x73,0x2300,0x2400,1023);
        pce::Cpu s;s.mpr=block_mpr;s.pc=c.pc;s.clock_divisor=speed;s.p=0;s.a=0x45;s.x=0x67;s.y=0x89;
        require(!b.vdc.irq1 && (native?pce::generated_step(b,s,forever):pce::interpret_step(b,s,forever))==pce::Exit::executed,
                "block refused an IRQ that became pending during the instruction");
        require(b.vdc.irq1 && b.vdc.raster.vblank_events==1 && s.block_bytes==1023 && s.pc==c.pc+7 &&
                s.cycles==17+6*1023 && b.vdc.raster.master_ticks==s.ticks,
                "block did not synchronize VBlank while completing its atomic byte loop");
        const auto before=cpu_state(s);const auto generation=b.generation;
        bool fault=false;
        try {if(native)pce::generated_step(b,s,forever);else pce::interpret_step(b,s,forever);}
        catch(const pce::Fault&){fault=true;}
        require(fault && before==cpu_state(s) && generation==b.generation,
                "new unmasked IRQ was not refused at the following instruction boundary");
        ++checks;
    }
    return checks;
}

int main() {
    try {pce::Bus b;const auto a=independent(b),s=status_stack_matrix(b),o=overwritten_opcode(b),g=boundaries(b),d=devices(b),i=irq_boundary(b);
        std::cout<<a<<" independently expected block instructions, "<<s<<" status/stack-pointer matrix cases, "<<o<<" local destructive-opcode cases, "<<g<<" guard/deadline groups, "<<d<<" block device checks and "<<i<<" deferred IRQ groups passed\n";
        return 0;
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
