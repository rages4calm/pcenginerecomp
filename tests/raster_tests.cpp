#include "pce/runtime.hpp"
#include "fixture.hpp"
#include "raster_expectations.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

static void require(bool condition,const char* message) {
    if(!condition) throw std::runtime_error(message);
}
static void print_state(const pce::Vdc& v) {
    const auto& r=v.raster;
    std::cout<<"{\"hclock\":"<<r.hclock<<",\"line\":"<<r.line<<",\"dot\":"<<r.dot
        <<",\"vdc_line\":"<<r.vdc_line<<",\"h_state\":"<<unsigned(r.h_state)
        <<",\"v_state\":"<<unsigned(r.v_state)<<",\"status\":"<<unsigned(v.status)
        <<",\"irq1\":"<<(v.irq1?"true":"false")<<'}';
}
static int clock_probe(const char* path) {
    std::ifstream in(path);
    std::array<std::uint16_t,20> registers{};
    for(auto& value:registers) {unsigned input;if(!(in>>input) || input>65535)return 2;value=input;}
    unsigned count;if(!(in>>count) || count<1 || count>4096)return 2;
    std::vector<std::uint64_t> times;
    std::uint64_t previous=0;
    for(unsigned i=0;i<count;++i) {
        std::uint64_t input;
        if(!(in>>input) || input<previous || input>4ULL*1365*263)return 2;
        times.push_back(input);previous=input;
    }
    std::string trailing;if(in>>trailing)return 2;
    pce::Vdc v;v.enabled=true;v.reg[11]=31;v.reg[13]=239;v.enable_raster();
    v.reg=registers;
    std::cout<<"{\"states\":[";
    previous=0;
    for(unsigned i=0;i<count;++i) {
        v.advance(times[i]-previous);previous=times[i];
        if(i)std::cout<<',';print_state(v);
    }
    const auto vb=v.raster.vblank_events,rc=v.raster.rcr_events;
    const auto acknowledged=v.read(0);v.advance(18);
    require(v.raster.vblank_events==vb && v.raster.rcr_events==rc,
            "clock probe acknowledgement crosses an enabled event; choose a stable interior phase");
    std::cout<<"],\"ack\":{\"value\":"<<unsigned(acknowledged)<<",\"state\":";
    print_state(v);std::cout<<"}}\n";return 0;
}
static std::uint16_t site(unsigned op) {
    for(auto [pc,code]:cases)if(code==op)return pc;
    throw std::runtime_error("Missing authored opcode fixture");
}
static unsigned cadence_expectations() {
    unsigned count=0;
    constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
    for(bool native:{false,true})for(unsigned divisor:{3U,12U}) {
        pce::Bus b;b.kind[0xF8]=b.kind[0x80]=b.kind[0x81]=pce::BankKind::ram;b.enable_video_timing();
        for(auto [pa,value]:program)(*b.bytes)[pa]=value;
        pce::Cpu s;s.clock_divisor=divisor;
        for(unsigned i=0;i<60000;++i) {
            s.pc=site(0xEA);
            const auto result=native?pce::generated_step(b,s,forever):pce::interpret_step(b,s,forever);
            require(result==pce::Exit::executed,"timed NOP fixture failed");
            require(s.ticks==std::uint64_t(i+1)*2*divisor,"NOP master-clock accumulation");
            require(b.vdc.raster.master_ticks==s.ticks,"CPU retirement did not synchronize video");
            require(b.vdc.raster.hclock==s.ticks%1365 && b.vdc.raster.line==(s.ticks/1365)%262,
                    "CPU cadence does not follow literal VCE line/frame periods");
            ++count;
        }
        require(s.native_steps==(native?60000U:0U) && s.interpreter_steps==(native?0U:60000U),
                "timed NOP routing did not use selected execution tier");
        const auto ticks=s.ticks,master=b.vdc.raster.master_ticks;
        s.pc=site(0xEA);
        require((native?pce::generated_step(b,s,ticks):pce::interpret_step(b,s,ticks))==pce::Exit::budget,
                "retirement deadline was not honored");
        require(s.ticks==ticks && b.vdc.raster.master_ticks==master,"deadline advanced video");
        // Invalidated translated bytes may not advance either CPU or devices.
        const auto pa=pce::Bus::physical(s,s.pc);(*b.bytes)[pa]^=1;
        require(pce::generated_step(b,s,forever)==pce::Exit::miss,"mutated source did not miss");
        require(s.ticks==ticks && b.vdc.raster.master_ticks==master,"source guard advanced video");
        (*b.bytes)[pa]^=1;
    }
    // A decoded status read uses the same VDC and acknowledgement through all
    // physical aliases. Direct Bus access deliberately adds a wait cycle;
    // these checks do not claim the exact sub-instruction sampling phase.
    pce::Bus b;b.enable_video_timing();pce::Cpu s;s.mpr[0]=0xFF;s.mpr[5]=0xFF;
    for(auto address:{0x0000,0x03FC,0xA000,0xA3FC}) {
        b.vdc.status=0x24;b.vdc.irq1=true;
        require(b.read(s,address)==0x24 && b.vdc.status==0 && !b.vdc.irq1,"timed status alias/acknowledgement");
        ++count;
    }
    for(bool native:{false,true}) {
        // A pending unmasked IRQ must stop at the boundary until delivery is
        // implemented; it must not silently let the next instruction retire.
        pce::Bus interrupted;
        interrupted.kind[0xF8]=interrupted.kind[0x80]=interrupted.kind[0x81]=pce::BankKind::ram;
        interrupted.enable_video_timing();
        for(auto [pa,value]:program)(*interrupted.bytes)[pa]=value;
        pce::Cpu cpu;cpu.pc=site(0xEA);cpu.p=0;
        interrupted.vdc.status=32;interrupted.vdc.irq1=true;
        bool failed=false;
        try { if(native)pce::generated_step(interrupted,cpu,forever);else pce::interpret_step(interrupted,cpu,forever); }
        catch(const pce::Fault&){failed=true;}
        require(failed && cpu.pc==site(0xEA) && cpu.ticks==0 && cpu.cycles==0 &&
                cpu.native_steps==0 && cpu.interpreter_steps==0 && interrupted.vdc.irq1,
                "unmasked pending IRQ1 did not refuse before instruction retirement");
        ++count;
        for(unsigned old:{3U,12U})for(unsigned next:{3U,12U}) {
            pce::Bus speed;
            speed.kind[0xF8]=speed.kind[0x80]=speed.kind[0x81]=pce::BankKind::ram;
            speed.enable_video_timing();for(auto [pa,value]:program)(*speed.bytes)[pa]=value;
            pce::Cpu clock;clock.clock_divisor=old;clock.pc=site(next==3?0xD4:0x54);
            const auto exit=native?pce::generated_step(speed,clock,forever):pce::interpret_step(speed,clock,forever);
            const unsigned expected=old==3?(next==3?9:18):(next==3?27:36);
            require(exit==pce::Exit::executed && clock.ticks==expected && clock.cycles==3 &&
                    clock.clock_divisor==next && speed.vdc.raster.master_ticks==expected,
                    "speed transition did not synchronize two entry-speed plus one selected-speed cycles");
            ++count;
        }
    }
    pce::Bus regressed;regressed.enable_video_timing();regressed.vdc.advance(10);
    bool refused=false;try{regressed.sync(pce::Cpu{});}catch(const pce::Fault&){refused=true;}
    require(refused && regressed.vdc.raster.master_ticks==10,"clock regression was accepted or mutated video");
    ++count;
    return count;
}
int main(int argc,char** argv) {
    try {
        if(argc==3 && std::string(argv[1])=="--clock")return clock_probe(argv[2]);
        if(argc!=1)return 2;
        const auto independent=raster_expected::run();
        const auto cadence=cadence_expectations();
        std::cout<<independent<<" independent raster expectations; "<<cadence
                 <<" native/interpreter cadence and alias checks; deadlines/guards passed\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
