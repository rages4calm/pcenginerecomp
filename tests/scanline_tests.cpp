#include "pce/runtime.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>

namespace {
std::uint64_t checks=0;
constexpr std::uint64_t frame_ticks=1365*262;
void require(bool value) {
    ++checks;
    if(!value) throw std::runtime_error("scanline expectation failed at "+std::to_string(checks));
}
template<class F> void fault(F&& fn) {
    bool caught=false;try {fn();} catch(const pce::Fault&) {caught=true;}
    require(caught);
}
void configure(pce::Bus& bus, bool output=true, unsigned width=32, unsigned height=8) {
    bus.enable_video();
    auto& v=bus.vdc;
    v.reg[5]=128;v.reg[10]=0x0202;
    // Horizontal and vertical geometry covers one picture per physical frame.
    v.reg[11]=static_cast<std::uint16_t>(((300-width)/8)<<8 | (width/8-1));
    v.reg[12]=0x0F02;v.reg[13]=static_cast<std::uint16_t>(height-1);v.reg[14]=234;
    for(unsigned row=0;row<32;++row) for(unsigned x=0;x<32;++x)
        (*v.vram)[row*32+x]=static_cast<std::uint16_t>(256+(x&1));
    for(unsigned y=0;y<8;++y) {
        (*v.vram)[4096+y]=0x00FF; // Literal plane 0: eight color-1 pixels.
        (*v.vram)[4112+y]=0xFF00; // Literal plane 1: eight color-2 pixels.
    }
    bus.vce.palette[1]=0x38;bus.vce.palette[2]=0x1C0;
    v.enable_raster();
    if(output) v.video.enable(v);
}
void advance(pce::Bus& b,std::uint64_t ticks) {b.vdc.advance(ticks,&b.vce);}
template<class F> void until(pce::Bus& b,F&& predicate) {
    const auto end=b.vdc.raster.master_ticks+frame_ticks*2;
    while(!predicate()) {
        if(b.vdc.raster.master_ticks==end) throw std::runtime_error("scanline phase was not reached");
        advance(b,1);
    }
}
void rgb(const pce::VideoFrame& f,unsigned x,unsigned y,std::array<unsigned,3> value) {
    for(unsigned c=0;c<3;++c) require(f.rgb[(y*f.width+x)*3+c]==value[c]);
}
void basic_and_publication() {
    pce::Bus b;configure(b);
    require(b.vdc.video.sequence()==0 && b.vdc.video.completed().rgb.empty());
    advance(b,frame_ticks);
    const auto& frame=b.vdc.video.completed();
    require(b.vdc.video.sequence()==1 && b.vdc.video.completed_ticks()==frame_ticks);
    require(frame.width==32 && frame.height==8 && frame.rgb.size()==768);
    for(unsigned y=0;y<8;++y) for(unsigned x=0;x<32;++x)
        rgb(frame,x,y,(x/8)&1 ? std::array<unsigned,3>{0,255,0}:std::array<unsigned,3>{255,0,0});
    const auto history=frame.rgb;
    b.vce.palette[1]=7;
    (*b.vdc.vram)[4096]=0;
    advance(b,frame_ticks/2);
    require(b.vdc.video.sequence()==1 && b.vdc.video.completed().rgb==history);
    advance(b,frame_ticks-frame_ticks/2);
    require(b.vdc.video.sequence()==2 && b.vdc.video.completed_ticks()==2*frame_ticks);
    rgb(b.vdc.video.completed(),0,0,{0,0,0});
    rgb(b.vdc.video.completed(),0,1,{0,0,255});
    // Host reads never advance or consume guest frames.
    const auto ticks=b.vdc.raster.master_ticks;
    for(unsigned i=0;i<1000;++i) {
        require(b.vdc.video.sequence()==2);
        require(b.vdc.video.completed().height==8 && b.vdc.raster.master_ticks==ticks);
    }
    b.vdc.enable_raster();
    require(b.vdc.video.enabled && b.vdc.video.sequence()==0 && b.vdc.video.completed().rgb.empty());
    require(b.vdc.raster.master_ticks==0 && b.vdc.video.lines_rendered()==0 && b.vdc.video.pixels_rendered()==0);
    advance(b,frame_ticks);
    require(b.vdc.video.sequence()==1 && b.vdc.video.completed_ticks()==frame_ticks);
}
void history_palette_and_vram() {
    pce::Bus b;configure(b);
    // First line has emitted four pixels when the host writes palette RAM.
    until(b,[&]{return b.vdc.video.pixels_rendered()==4;});
    b.vce.palette[1]=7;
    // VRAM is decoded at HDW entry; changing it now affects the next line,
    // not already latched indices later in this line.
    (*b.vdc.vram)[4096]=0;
    (*b.vdc.vram)[4097]=0;
    until(b,[&]{return b.vdc.video.sequence()==1;});
    const auto& frame=b.vdc.video.completed();
    for(unsigned x=0;x<32;++x) {
        const auto expected=(x/8)&1 ? std::array<unsigned,3>{0,255,0}:
            x<4 ? std::array<unsigned,3>{255,0,0}:std::array<unsigned,3>{0,0,255};
        rgb(frame,x,0,expected);
    }
    rgb(frame,0,1,{0,0,0});
    rgb(frame,16,0,{0,0,255});
    // A snapshot at the end cannot reconstruct the red prefix or blue suffix.
    const auto snapshot=pce::render_snapshot(b.vdc,b.vce);
    require(snapshot.rgb!=frame.rgb);
}
void scroll_latches() {
    pce::Bus b;configure(b);
    until(b,[&]{return b.vdc.video.pixels_rendered()==4;});
    b.vdc.write(0,7);b.vdc.write(2,8); // BXR after this line's latch.
    until(b,[&]{return b.vdc.video.sequence()==1;});
    const auto& frame=b.vdc.video.completed();
    rgb(frame,0,0,{255,0,0});rgb(frame,0,1,{0,255,0});
    // BYR write is remembered as a counter reload plus one on nonzero lines.
    pce::Bus y;configure(y);
    for(unsigned row=0;row<8;++row) (*y.vdc.vram)[4096+row]=row==3 ? 0xFF00:0x00FF;
    until(y,[&]{return y.vdc.video.pixels_rendered()==4;});
    y.vdc.write(0,8);y.vdc.write(2,2);
    until(y,[&]{return y.vdc.video.sequence()==1;});
    rgb(y.vdc.video.completed(),0,0,{255,0,0});
    rgb(y.vdc.video.completed(),0,1,{0,255,0});
    rgb(y.vdc.video.completed(),0,2,{255,0,0});
}
void sprites_and_geometry() {
    pce::Bus b;configure(b);
    b.vdc.reg[5]=192;b.vdc.video.enable(b.vdc);
    b.vdc.satb[0]=64;b.vdc.satb[1]=32;b.vdc.satb[2]=512;b.vdc.satb[3]=128;
    for(unsigned row=0;row<16;++row) (*b.vdc.vram)[16384+row]=0xFFFF;
    b.vce.palette[257]=7;
    until(b,[&]{return b.vdc.video.pixels_rendered()==4;});
    b.vdc.satb[1]=40; // Current decoded line retains the original sprite position.
    until(b,[&]{return b.vdc.video.sequence()==1;});
    const auto& frame=b.vdc.video.completed();
    for(unsigned x=0;x<32;++x) {
        const auto bg=(x/8)&1 ? std::array<unsigned,3>{0,255,0}:std::array<unsigned,3>{255,0,0};
        rgb(frame,x,0,x<16 ? std::array<unsigned,3>{0,0,255}:bg);
        rgb(frame,x,1,x>=8 && x<24 ? std::array<unsigned,3>{0,0,255}:bg);
    }
    pce::Bus geometry;configure(geometry);
    until(geometry,[&]{return geometry.vdc.video.pixels_rendered()==4;});
    geometry.vdc.reg[11]=0x2101; // Width changes on the next horizontal latch.
    geometry.vdc.reg[13]=3;      // Height changes at vertical sync.
    until(geometry,[&]{return geometry.vdc.video.sequence()==1;});
    require(geometry.vdc.video.completed().width==32 && geometry.vdc.video.completed().height==8);
    for(unsigned x=16;x<32;++x) rgb(geometry.vdc.video.completed(),x,1,{0,0,0});
    until(geometry,[&]{return geometry.vdc.video.sequence()==2;});
    require(geometry.vdc.video.completed().width==16 && geometry.vdc.video.completed().height==4);
    // Burst mode is frame-latched. Clearing display bits midframe shows the
    // live backdrop on later lines until burst takes effect next frame.
    pce::Bus burst;configure(burst);burst.vce.palette[0]=0x1FF;
    until(burst,[&]{return burst.vdc.video.pixels_rendered()==4;});
    burst.vdc.reg[5]=0;
    until(burst,[&]{return burst.vdc.video.sequence()==1;});
    rgb(burst.vdc.video.completed(),0,0,{255,0,0});
    rgb(burst.vdc.video.completed(),0,1,{255,255,255});
    until(burst,[&]{return burst.vdc.video.sequence()==2;});
    for(auto byte:burst.vdc.video.completed().rgb) require(byte==0);
}
void partition_and_state() {
    pce::Bus a,b,reference;configure(a);configure(b);configure(reference,false);
    const auto total=frame_ticks*3+12345;
    advance(a,total);advance(reference,total);
    for(std::uint64_t done=0;done<total;) {
        const auto chunk=std::min<std::uint64_t>(total-done,done%37+1);
        advance(b,chunk);done+=chunk;
    }
    require(a.vdc.video.sequence()==3 && b.vdc.video.sequence()==3);
    require(a.vdc.video.completed().rgb==b.vdc.video.completed().rgb);
    require(a.vdc.video.completed_ticks()==b.vdc.video.completed_ticks());
    require(a.vdc.video.lines_rendered()==b.vdc.video.lines_rendered());
    require(a.vdc.video.pixels_rendered()==b.vdc.video.pixels_rendered());
    const auto& x=a.vdc.raster;const auto& y=reference.vdc.raster;
    require(x.master_ticks==y.master_ticks && x.frames==y.frames && x.hclock==y.hclock && x.dot==y.dot);
    require(x.vdc_line==y.vdc_line && x.raster_line==y.raster_line && x.h_state==y.h_state && x.v_state==y.v_state);
    require(x.event==y.event && x.event_remaining==y.event_remaining && x.rcr_events==y.rcr_events && x.vblank_events==y.vblank_events);
    require(a.vdc.reg==reference.vdc.reg && a.vdc.status==reference.vdc.status && a.vdc.irq1==reference.vdc.irq1);
    require(*a.vdc.vram==*reference.vdc.vram && a.vdc.satb==reference.vdc.satb && a.vce.palette==reference.vce.palette);
    // Guest clock changes cadence, never a host clock or presentation call.
    for(unsigned control=0;control<8;++control) {
        pce::Bus c;configure(c);c.vdc.write_vce_control(static_cast<std::uint8_t>(control));
        const auto ticks=1365u*((control&4)?263:262);
        advance(c,ticks-1);require(c.vdc.video.sequence()==0);
        advance(c,1);require(c.vdc.video.sequence()==1 && c.vdc.video.completed_ticks()==ticks);
    }
}
void background_and_monochrome_modes() {
    // Settled current-state and historical renderers agree in every access
    // width mode and both CG selections. Monochrome does not change clocks,
    // VDC color indices, palette RAM or the frame's guest timestamp.
    for(unsigned mode=0;mode<4;++mode) for(unsigned cg=0;cg<2;++cg)
    for(unsigned gray=0;gray<2;++gray) {
        pce::Bus b;configure(b,false);
        b.vdc.reg[9]=static_cast<std::uint16_t>(mode+cg*128);
        for(unsigned row=0;row<8;++row) {
            (*b.vdc.vram)[4096+row]=0x4080;
            (*b.vdc.vram)[4104+row]=0x1020;
            (*b.vdc.vram)[4112+row]=0x1020;
            (*b.vdc.vram)[4120+row]=0x4080;
        }
        for(unsigned color=0;color<16;++color)
            b.vce.palette[color]=static_cast<std::uint16_t>((color*37+51)&511);
        b.vce.write(0,static_cast<std::uint8_t>(gray*128));
        b.vdc.video.enable(b.vdc);
        // MWR belongs to the guest's VSW latch, not enabling framebuffer
        // production. Let the real latch edge settle before comparing modes.
        advance(b,frame_ticks);
        const auto expected=pce::render_snapshot(b.vdc,b.vce);
        const auto palette=b.vce.palette;
        advance(b,frame_ticks);
        require(b.vdc.video.completed().rgb==expected.rgb);
        require(b.vdc.video.completed_ticks()==2*frame_ticks && b.vdc.raster.frames==2);
        require(b.vce.palette==palette && b.vce.control==gray*128);
    }
    // CG selection is part of the existing vertical MWR latch, not a live
    // reinterpretation of a scanline already decoded at HDW entry.
    pce::Bus modes;configure(modes,false);
    modes.vdc.reg[9]=3;
    for(unsigned row=0;row<8;++row) {
        (*modes.vdc.vram)[4096+row]=0x00FF;
        (*modes.vdc.vram)[4104+row]=0xFF00;
        (*modes.vdc.vram)[4112+row]=0x00FF;
        (*modes.vdc.vram)[4120+row]=0xFF00;
    }
    modes.vdc.video.enable(modes.vdc);
    advance(modes,frame_ticks); // Settle initial MWR=3 through guest VSW.
    const auto prior_pixels=modes.vdc.video.pixels_rendered();
    until(modes,[&]{return modes.vdc.video.pixels_rendered()==prior_pixels+4;});
    modes.vdc.write(0,9);modes.vdc.write(2,0x83);
    until(modes,[&]{return modes.vdc.video.sequence()==2;});
    for(unsigned y=0;y<8;++y) for(unsigned x=0;x<32;++x)
        rgb(modes.vdc.video.completed(),x,y,{255,0,0});
    until(modes,[&]{return modes.vdc.video.sequence()==3;});
    for(unsigned y=0;y<8;++y) for(unsigned x=0;x<32;++x)
        rgb(modes.vdc.video.completed(),x,y,{0,255,0});
    // The VCE's monochrome bit is live at each emitted dot. RGB history is
    // retained across enabling it, changing palette RAM and disabling it.
    pce::Bus mono;configure(mono);
    until(mono,[&]{return mono.vdc.video.pixels_rendered()==4;});
    mono.vce.write(0,128);
    until(mono,[&]{return mono.vdc.video.pixels_rendered()==12;});
    mono.vce.palette[2]=7;
    until(mono,[&]{return mono.vdc.video.pixels_rendered()==20;});
    mono.vce.write(0,0);
    until(mono,[&]{return mono.vdc.video.sequence()==1;});
    for(unsigned x=0;x<32;++x) {
        std::array<unsigned,3> expected{};
        if(x<4) expected={255,0,0};
        else if(x<8 || (x>=16 && x<20)) expected={76,76,76};
        else if(x<12) expected={149,149,149};
        else if(x<16) expected={29,29,29};
        else expected=(x/8)&1 ? std::array<unsigned,3>{0,0,255}:std::array<unsigned,3>{255,0,0};
        rgb(mono.vdc.video.completed(),x,0,expected);
    }
    rgb(mono.vdc.video.completed(),0,1,{255,0,0});
    rgb(mono.vdc.video.completed(),8,1,{0,0,255});
    require(mono.vdc.video.completed_ticks()==frame_ticks && mono.vdc.raster.divider==4);
    pce::Bus burst;configure(burst,false);burst.vdc.reg[5]=0;
    burst.vce.write(0,128);burst.vce.palette[0]=511;burst.vdc.video.enable(burst.vdc);
    advance(burst,frame_ticks);
    for(auto byte:burst.vdc.video.completed().rgb) require(byte==0);
}
void bounds_and_profiles() {
    pce::Vdc v;fault([&]{v.video.enable(v);});
    pce::Bus b;configure(b,false);advance(b,1);fault([&]{b.vdc.video.enable(b.vdc);});
    pce::Bus c;configure(c);fault([&]{c.vdc.advance(1);});
    // Maximum native VDC geometry remains bounded to exactly two 1.5 MiB RGB
    // images; clipping safely leaves unavailable physical dots black.
    pce::Bus max;configure(max,false);max.vdc.reg[11]=127;max.vdc.reg[13]=511;
    max.vdc.reg[5]=0;max.vdc.enable_raster();max.vdc.video.enable(max.vdc);
    advance(max,frame_ticks);
    require(max.vdc.video.completed().width==1024 && max.vdc.video.completed().height==512);
    require(max.vdc.video.completed().rgb.size()==1024*512*3);
    require(std::all_of(max.vdc.video.completed().rgb.begin(),max.vdc.video.completed().rgb.end(),[](auto byte){return byte==0;}));
}
}
int main() {
    try {
        basic_and_publication();history_palette_and_vram();scroll_latches();sprites_and_geometry();partition_and_state();background_and_monochrome_modes();bounds_and_profiles();
        std::cout<<"continuous video: "<<checks<<" independent expectations passed\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
