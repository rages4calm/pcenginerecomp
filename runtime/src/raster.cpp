#include "pce/runtime.hpp"
#include <algorithm>
#include <limits>

namespace pce {
void Vdc::latch_horizontal() {
    raster.horizontal={unsigned((reg[10]>>8)&127)+1,unsigned(reg[11]&127)+1,
        unsigned((reg[11]>>8)&127)+1,unsigned(reg[10]&31)+1};
    for(auto& length:raster.horizontal) length*=8;
}
void Vdc::latch_vertical() {
    raster.vertical={unsigned(reg[12]>>8)+2,unsigned(reg[13]&511)+1,
        unsigned(reg[14]&255),unsigned(reg[12]&31)+1};
}
void Vdc::enable_raster() {
    raster=RasterTiming{}; raster.enabled=true;
    latch_horizontal(); latch_vertical(); raster.v_remaining=static_cast<int>(raster.vertical[0]);
}
void Vdc::write_vce_control(std::uint8_t value) {
    if(!raster.enabled) throw Fault("VCE timing profile is disabled");
    const auto lines=(value&4) ? 263U:262U;
    // Reducing the frame count behind a live line counter requires separately
    // qualified wrap behavior. Reject it before changing the clock selection.
    if(raster.line>=lines) throw Fault("VCE frame-length change behind the current line is unsupported");
    raster.control=value; raster.total_lines=lines;
    raster.divider=(value&3)==0 ? 4:(value&3)==1 ? 3:2;
}
void Vdc::schedule_line_events() {
    auto& r=raster;
    latch_horizontal();
    r.event=0; r.event_remaining=0;
    const auto display_start=static_cast<int>(r.dot)+r.h_remaining+static_cast<int>(r.horizontal[0]);
    if((display_start-24)*static_cast<int>(r.divider)>=1365) return;
    const bool active=r.v_state==1;
    r.event=active ? 1:3;
    r.event_remaining=display_start-(active ? 36:26)-static_cast<int>(r.dot);
    if(r.event_remaining<=0) { r.event_remaining=0; raster_event(); }
}
void Vdc::compare_line() {
    auto& r=raster;
    ++r.raster_line; r.compare_pending=false;
    --r.v_remaining;
    while(r.v_remaining<=0) {
        r.v_state=(r.v_state+1)&3;
        r.v_remaining=static_cast<int>(r.vertical[r.v_state]);
        if(r.v_state==1) { r.raster_line=0; r.blank_consumed=false; }
        if(r.v_state==3) latch_vertical();
    }
    if((reg[5]&4) && static_cast<int>(r.raster_line)==static_cast<int>(reg[6])-64) {
        status|=4; irq1=true; ++r.rcr_events;
    }
}
void Vdc::raster_event() {
    auto& r=raster;
    const auto event=r.event; r.event=0; r.event_remaining=0;
    if(event==1) { r.event=2; r.event_remaining=2; }
    if(event==2) { r.event=3; r.event_remaining=6; }
    if(event==3 && r.v_state!=1 && !r.blank_consumed) {
        // Consume the source event even with CR disabled: enabling it later
        // cannot manufacture an interrupt for an event that already passed.
        r.blank_consumed=true;
        if(reg[15]&16) throw Fault("VDC automatic SATB DMA is not implemented");
        if(reg[5]&8) { status|=32; irq1=true; ++r.vblank_events; }
    }
    if(event==4) compare_line();
}
void Vdc::horizontal_edge() {
    auto& r=raster;
    r.h_state=(r.h_state+1)&3;
    r.h_remaining=static_cast<int>(r.horizontal[r.h_state]);
    if(r.h_state==1) {
        r.compare_pending=true; r.event=4;
        r.event_remaining=static_cast<int>(r.horizontal[1])-14;
        if(r.event_remaining<=0) { r.event_remaining=0; raster_event(); }
    }
    if(r.h_state==3) schedule_line_events();
}
void Vdc::dot_tick() {
    auto& r=raster;
    ++r.dot;
    if(--r.h_remaining==0) horizontal_edge();
    // New horizontal events participate in this same dot, as on the VDC.
    if(r.event_remaining>0 && --r.event_remaining==0) raster_event();
}
void Vdc::line_tick() {
    auto& r=raster;
    r.hclock=0; r.dot=0;
    ++r.vdc_line;
    if(r.compare_pending) compare_line();
    if(r.vdc_line==r.total_lines) r.vdc_line=0;
    r.h_state=3; r.h_remaining=r.divider==3 ? 32:24;
    schedule_line_events();
    if(r.line==r.total_lines-4) {
        r.vsync=false; latch_vertical();
        r.v_state=3; r.v_remaining=static_cast<int>(r.vertical[3]);
    } else if(r.line==r.total_lines-1) r.vsync=true;
    if(++r.line==r.total_lines) { r.line=0; ++r.frames; }
    r.hsync=true;
}
void Vdc::advance(std::uint64_t delta) {
    if(!raster.enabled) return;
    auto& r=raster;
    if(delta>std::numeric_limits<std::uint64_t>::max()-r.master_ticks) throw Fault("video clock overflow");
    while(delta) {
        const unsigned to_dot=r.divider-r.hclock%r.divider;
        const auto chunk=std::min<std::uint64_t>({delta,to_dot,1365-r.hclock});
        r.hclock+=static_cast<unsigned>(chunk); r.master_ticks+=chunk; delta-=chunk;
        if(chunk==to_dot) dot_tick();
        if(r.hclock==1365) line_tick();
        else if(r.hclock==1128) r.hsync=false;
    }
}
void Bus::enable_video_timing() {
    enable_vdc();
    // Deterministic reference-emulator reset geometry, not a reconstructed IPL
    // state or a hardware power-on guarantee. Functional-only VDC stays zeroed.
    vdc.reg[11]=31; vdc.reg[13]=239;
    vdc.enable_raster();
}
void Bus::sync(const Cpu& cpu) {
    if(!vdc.raster.enabled) return;
    if(cpu.ticks<vdc.raster.master_ticks) throw Fault("CPU/video clock regression");
    vdc.advance(cpu.ticks-vdc.raster.master_ticks);
}
void Bus::begin_instruction(const Cpu& cpu) {
    sync(cpu);
    if(vdc.raster.enabled && vdc.irq1 && !(cpu.p&I)) throw Fault("unmasked IRQ1 delivery is not implemented");
}
void Bus::retire(Cpu& cpu,unsigned cycles,bool native) { cpu.retire(cycles,native); sync(cpu); }
void Bus::retire_speed(Cpu& cpu,unsigned divisor,bool native) { cpu.retire_speed(divisor,native); sync(cpu); }
} // namespace pce
