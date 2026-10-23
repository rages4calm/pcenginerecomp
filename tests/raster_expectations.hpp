#pragma once

#include "pce/runtime.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>

// Authored device expectations. The edge times below are literal consequences
// of the documented reset phase, not a second copy of the runtime state machine.
namespace raster_expected {
inline void check(bool condition,const char* message) {
    if(!condition) throw std::runtime_error(message);
}
inline void word(pce::Vdc& v,unsigned reg,unsigned value) {
    v.write(0,static_cast<std::uint8_t>(reg));
    v.write(2,static_cast<std::uint8_t>(value));
    v.write(3,static_cast<std::uint8_t>(value>>8));
}
inline pce::Vdc start(unsigned control=12,unsigned compare=65) {
    pce::Vdc v;v.enabled=true;
    // Match Geargrafx's zero-HSR, 256-dot/240-line reset geometry explicitly.
    // Functional VDC initialization itself deliberately retains zero registers.
    v.reg[11]=31;v.reg[13]=239;v.reg[5]=static_cast<std::uint16_t>(control);
    v.reg[6]=static_cast<std::uint16_t>(compare);v.enable_raster();
    return v;
}
inline unsigned bus_controls() {
    unsigned count=0;
    pce::Bus b;
    constexpr unsigned dividers[]={4,3,2,2};
    for(unsigned value=0;value<8;++value)for(unsigned page=0;page<8;++page)
    for(unsigned mirror:{0x400U,0x408U,0x7F8U})for(unsigned cpu_divisor:{3U,12U}) {
        b.enable_video_timing();
        pce::Cpu s;s.mpr.fill(0xF8);s.mpr[page]=0xFF;
        s.clock_divisor=cpu_divisor;s.cycles=17;s.ticks=24;
        s.pc=0xABCD;s.a=0x39;s.x=0xA5;s.y=0x5A;s.sp=0x81;s.p=0xD4;
        const auto generations=b.generation;
        const auto address=static_cast<std::uint16_t>((page<<13)|mirror);
        b.write(s,address,static_cast<std::uint8_t>(value));
        check(s.cycles==18 && s.ticks==24+cpu_divisor,
              "mapped VCE control fixed wait cycle or CPU-speed scaling");
        check(b.vdc.raster.control==value && b.vdc.raster.divider==dividers[value&3]
              && b.vdc.raster.total_lines==((value&4)?263U:262U),
              "mapped VCE control MPR page/mirror decode");
        b.sync(s);
        check(b.vdc.raster.master_ticks==s.ticks && b.vdc.raster.hclock==s.ticks
              && b.vdc.raster.line==0,"VCE write wait was not synchronized into video");
        check(s.pc==0xABCD && s.a==0x39 && s.x==0xA5 && s.y==0x5A && s.sp==0x81 && s.p==0xD4
              && s.native_steps==0 && s.interpreter_steps==0 && s.guard_misses==0,
              "direct VCE control write changed unrelated CPU state");
        check(b.generation==generations,"VCE control dirtied executable memory generation");
        ++count;
    }
    for(unsigned page=0;page<8;++page)for(unsigned mirror:{0x400U,0x408U,0x7F8U})
    for(unsigned cpu_divisor:{3U,12U}) {
        b.enable_video_timing();
        pce::Cpu s;s.mpr.fill(0xF8);s.mpr[page]=0xFF;
        s.clock_divisor=cpu_divisor;s.cycles=17;s.ticks=24;b.sync(s);
        const auto generations=b.generation;
        for(unsigned port=1;port<8;++port) {
            bool refused=false;
            const auto address=static_cast<std::uint16_t>((page<<13)|mirror|port);
            try {b.write(s,address,7);}catch(const pce::Fault&){refused=true;}
            check(refused && s.cycles==17 && s.ticks==24 && b.vdc.raster.control==0
                  && b.vdc.raster.master_ticks==24 && b.generation==generations,
                  "unsupported VCE port write accepted or mutated state");
            ++count;
        }
        const auto address=static_cast<std::uint16_t>((page<<13)|mirror);
        bool refused=false;
        try {b.read(s,address);}catch(const pce::Fault&){refused=true;}
        check(refused && s.cycles==17 && s.ticks==24 && b.vdc.raster.control==0,
              "unsupported VCE control read accepted or charged a wait");
        ++count;
        b.enable_vdc(); // The transfer-only profile does not enable VCE timing.
        refused=false;
        try {b.write(s,address,7);}catch(const pce::Fault&){refused=true;}
        check(refused && !b.vdc.raster.enabled && s.cycles==17 && s.ticks==24
              && b.generation==generations,"untimed profile accepted VCE control write");
        ++count;
    }
    return count;
}
inline unsigned run() {
    unsigned count=0;
    // With divider four the initial one-dot HDS ends at tick four. The first
    // comparison is dot 242 (968 ticks), and the initial blank event is dot
    // 265 (1060 ticks). Only enabled event sources latch status/IRQ1.
    for(unsigned control:{0U,4U,8U,12U,0x1FFFU})
    for(unsigned compare:{0U,64U,65U,66U,1023U})
    for(unsigned tick:{0U,967U,968U,1059U,1060U}) {
        auto v=start(control,compare);v.advance(tick);
        const unsigned want=((tick>=968 && compare==65 && (control&4))?4:0)
                            |((tick>=1060 && (control&8))?32:0);
        check(v.status==want && v.irq1==(want!=0),"raster literal startup event/gate edge");
        check(v.raster.master_ticks==tick && v.raster.hclock==tick && v.raster.line==0,
              "raster literal startup master/line phase");
        check(v.raster.raster_line==(tick>=968?1:0),"raster startup comparison counter");
        ++count;
    }
    // RCR resets to zero on entry to VDW. The short reset HSW/HDS/HDE values
    // allow another HDW before line end: its pending comparison completes on
    // the external line edge. This deliberately tests two vertical clocks per
    // physical line instead of assuming fixed geometry.
    struct Edge {unsigned tick,line,counter,state;};
    constexpr Edge edges[]={
        {1364,0,1,0},{1365,1,0,1},{2456,1,0,1},{2457,1,1,1},
        {2730,2,2,1},{3821,2,2,1},{3822,2,3,1},
        {5186,3,4,1},{5187,3,5,1},{6551,4,6,1},{6552,4,7,1}};
    for(auto edge:edges) {
        auto v=start(4,64);v.advance(edge.tick);
        check(v.raster.line==edge.line && v.raster.hclock==edge.tick%1365,
              "raster literal scanline/pixel remainder edge");
        check(v.raster.raster_line==edge.counter && unsigned(v.raster.v_state)==edge.state,
              "raster literal VDS/VDW counter edge");
        check(v.status==(edge.tick>=1365?4:0) && v.irq1==(edge.tick>=1365),
              "RCR 64 must match zero on VDW entry");
        ++count;
    }
    for(unsigned chunk:{1U,2U,3U,4U,5U,17U,97U,341U,1365U,6552U}) {
        auto v=start();unsigned left=6552;
        while(left) {const auto n=std::min(chunk,left);v.advance(n);left-=n;}
        check(v.raster.master_ticks==6552 && v.raster.line==4 && v.raster.hclock==1092,
              "partitioned raster advance lost master phase");
        check(v.raster.raster_line==7 && unsigned(v.raster.v_state)==1 && v.status==36 && v.irq1,
              "partitioned raster advance changed events");
        ++count;
    }
    {
        auto v=start();v.advance(968);
        check(v.status==4 && v.irq1,"RCR edge did not latch");
        word(v,5,0); // Disable after assertion: pending IRQ is not acknowledged.
        check(v.status==4 && v.irq1,"CR disable erased pending raster IRQ");
        v.selected=5;v.read_buffer=0xABCD;
        check(v.read(1)==0 && v.read(2)==0xCD && v.read(3)==0xAB && v.status==4 && v.irq1,
              "data/unused port acknowledged raster status");
        check(v.read(0)==4 && v.status==0 && !v.irq1 && v.read(0)==0,
              "status read did not return then acknowledge raster IRQ");
        v.advance(92); // The disabled blank event is consumed.
        word(v,5,8);v.advance(1);
        check(v.status==0 && !v.irq1,"late CR enable replayed consumed VBlank");
        ++count;
    }
    {
        auto v=start(0);v.advance(967);word(v,5,4);v.advance(1);
        check(v.status==4 && v.irq1,"RCR enable immediately before event ignored");
        check(v.read(0)==4,"RCR status acknowledgement value");
        word(v,5,0);v.advance(91);word(v,5,8);v.advance(1);
        check(v.status==32 && v.irq1,"VBlank enable immediately before event ignored");
        check(v.read(0)==32 && v.status==0 && !v.irq1,"VBlank IRQ acknowledge");
        v.advance(1);check(v.status==0 && !v.irq1,"acknowledged VBlank relatched without event");
        ++count;
    }
    {
        auto v=start(4,64);v.advance(968); // Comparison did not match.
        word(v,6,65);v.advance(92);
        check(v.status==0 && !v.irq1,"RCR register write replayed prior comparison");
        word(v,6,64);v.advance(305);
        check(v.status==4 && v.irq1,"live RCR comparison was not sampled at VDW entry");
        ++count;
    }
    {
        auto v=start(0);word(v,12,0xFF1F);word(v,13,0);word(v,14,255);
        v.advance(5187);
        check(unsigned(v.raster.v_state)==1 && v.raster.raster_line==5,
              "vertical geometry writes changed already latched VDS/VDW timing");
        ++count;
    }
    for(unsigned control=0;control<8;++control) {
        auto v=start(0);v.write_vce_control(static_cast<std::uint8_t>(control));
        constexpr unsigned dividers[]={4,3,2,2};
        const auto lines=control&4?263U:262U;
        check(v.raster.divider==dividers[control&3] && v.raster.total_lines==lines,
              "VCE control divider/262-263-line selection");
        const std::uint64_t frame=1365ULL*lines;
        v.advance(frame-1);
        check(v.raster.master_ticks==frame-1 && v.raster.line==lines-1 && v.raster.hclock==1364,
              "VCE frame last master clock");
        v.advance(1);
        check(v.raster.master_ticks==frame && v.raster.line==0 && v.raster.hclock==0,
              "VCE programmed frame length/wrap");
        check(v.status==0 && !v.irq1,"disabled event sources asserted during frame advance");
        ++count;
    }
    {
        pce::Vdc v;v.advance(8192);
        check(v.raster.master_ticks==0,"disabled raster clock advanced");
        bool refused=false;
        try {v.write_vce_control(4);}catch(const pce::Fault&){refused=true;}
        check(refused && !v.raster.enabled && v.raster.control==0,
              "disabled VCE control did not refuse before mutation");
        ++count;
    }
    {
        auto v=start(0);v.advance(1);
        bool refused=false;
        try {v.advance(std::numeric_limits<std::uint64_t>::max());}catch(const pce::Fault&){refused=true;}
        check(refused && v.raster.master_ticks==1 && v.raster.hclock==1,
              "raster master-clock overflow did not refuse before advance");
        ++count;
    }
    {
        auto v=start(0);v.write_vce_control(4);v.advance(262ULL*1365);
        check(v.raster.line==262,"263-line profile did not reach final line");
        bool refused=false;
        try {v.write_vce_control(1);}catch(const pce::Fault&){refused=true;}
        check(refused && v.raster.control==4 && v.raster.total_lines==263 && v.raster.divider==4,
              "unsupported frame shortening did not refuse before mutation");
        ++count;
    }
    return count+bus_controls();
}
} // namespace raster_expected
