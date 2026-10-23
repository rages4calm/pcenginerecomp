#include "pce/runtime.hpp"
#include "pce/video.hpp"
#include <iostream>
#include <stdexcept>

namespace {
std::uint64_t checks=0;
void require(bool value) {
    ++checks;
    if(!value) throw std::runtime_error("video expectation failed at "+std::to_string(checks));
}
template<class F> void fault(F&& f) {
    bool caught=false;
    try { f(); } catch(const pce::Fault&) { caught=true; }
    require(caught);
}
void ports() {
    pce::Vce v;
    for(unsigned address=0;address<512;++address) {
        for(unsigned value=0;value<256;++value) {
            v.write(2,static_cast<std::uint8_t>(address));
            v.write(3,static_cast<std::uint8_t>(address>>8));
            v.write(4,static_cast<std::uint8_t>(value));
            require(v.address==address && (v.palette[address]&255)==value);
            v.write(5,static_cast<std::uint8_t>(value));
            require(v.address==(address+1)%512);
            v.write(2,static_cast<std::uint8_t>(address));
            v.write(3,static_cast<std::uint8_t>(address>>8));
            require(v.read(4)==value && v.address==address);
            require(v.read(5)==((value&1) ? 255:254) && v.address==(address+1)%512);
        }
    }
    for(unsigned mirror=0;mirror<128;++mirror) {
        for(unsigned port=0;port<8;++port) {
            pce::Vce a,b;
            a.address=b.address=511;
            a.palette[511]=b.palette[511]=0x159;
            a.write(port,0xAF);b.write(mirror*8+port,0xAF);
            require(a.address==b.address && a.control==b.control && a.palette==b.palette);
            require(a.read(port)==b.read(mirror*8+port) && a.address==b.address);
        }
    }
    for(unsigned port:{0,1,2,3,6,7}) require(v.read(port)==255);
    v.address=256;v.palette[256]=0x100;v.write(4,0xBC);
    require(v.palette[256]==0x1BC && v.address==256);
    v.write(5,0xFE);require(v.palette[256]==0xBC && v.address==257);
}
void snapshots() {
    pce::Vdc vdc;pce::Vce vce;
    vdc.enabled=vce.enabled=true;
    vdc.reg[11]=0;vdc.reg[13]=7;vdc.reg[5]=128;
    // Authored 8x8 tile at pattern one: each plane occupies a different column.
    (*vdc.vram)[0]=0x2001;
    for(unsigned row=0;row<8;++row) {
        (*vdc.vram)[16+row]=0x4080;
        (*vdc.vram)[24+row]=0x1020;
    }
    vce.palette[0]=0x1FF;
    vce.palette[0x21]=0x38;vce.palette[0x22]=0x1C0;
    vce.palette[0x24]=7;vce.palette[0x28]=0;
    const auto image=pce::render_snapshot(vdc,vce);
    require(image.width==8 && image.height==8 && image.rgb.size()==192);
    constexpr unsigned expected[][3]={{255,0,0},{0,255,0},{0,0,255},{0,0,0},
        {255,255,255},{255,255,255},{255,255,255},{255,255,255}};
    for(unsigned y=0;y<8;++y) for(unsigned x=0;x<8;++x)
        for(unsigned c=0;c<3;++c) require(image.rgb[(y*8+x)*3+c]==expected[x][c]);
    vdc.reg[7]=7;const auto scroll=pce::render_snapshot(vdc,vce);
    require(scroll.rgb[0]==255 && scroll.rgb[1]==255 && scroll.rgb[2]==255);
    vdc.reg[7]=0;vdc.reg[5]=0;
    const auto off=pce::render_snapshot(vdc,vce);
    for(auto c:off.rgb) require(c==0);
    // Opaque sprite plane at x0; foreground red, background white.
    std::array<std::uint16_t,256> satb{};
    satb[0]=64;satb[1]=32;satb[2]=8;satb[3]=128;
    (*vdc.vram)[256]=0x8000;vce.palette[257]=0x38;vdc.reg[5]=64;
    const auto sprite=pce::render_snapshot(vdc,vce,satb);
    require(sprite.rgb[0]==255 && sprite.rgb[1]==0 && sprite.rgb[2]==0);
    require(sprite.rgb[3]==255 && sprite.rgb[4]==255 && sprite.rgb[5]==255);
    satb[3]=0x880;const auto flip=pce::render_snapshot(vdc,vce,satb);
    require(flip.rgb[0]==255 && flip.rgb[1]==255 && flip.rgb[2]==255);
    vdc.reg[11]=1;const auto wide=pce::render_snapshot(vdc,vce,satb);
    require(wide.rgb[15*3]==255 && wide.rgb[15*3+1]==0);
    // Two overlapping sprites: a lower index behind BG masks a later foreground sprite.
    vdc.reg[5]=192;satb[3]=0;satb[4]=64;satb[5]=32;satb[6]=8;satb[7]=128|1;
    vce.palette[273]=7;
    const auto priority=pce::render_snapshot(vdc,vce,satb);
    require(priority.rgb[0]==255 && priority.rgb[1]==0 && priority.rgb[2]==0);
    // Snapshot rendering leaves all simulation state untouched.
    require(vdc.reads==0 && vdc.writes==0 && vdc.vram_changes==0 && !vdc.irq1);
    require(vce.reads==0 && vce.writes==0);
    vce.control=128;fault([&]{pce::render_snapshot(vdc,vce);});vce.control=0;
    vdc.reg[9]=3;fault([&]{pce::render_snapshot(vdc,vce);});vdc.reg[9]=0;
    fault([&]{pce::render_snapshot(vdc,vce,std::span(satb).first(255));});
    vdc.enabled=false;fault([&]{pce::render_snapshot(vdc,vce);});
    fault([&]{pce::write_ppm(pce::VideoFrame{},"");});
}
void sprite_layouts() {
    pce::Vdc vdc;pce::Vce vce;vdc.enabled=vce.enabled=true;
    vdc.reg[5]=64;vdc.reg[11]=3;
    // Independently authored 32x64 pixel field, packed into eight 16x16 tiles.
    for(unsigned ty=0;ty<4;++ty) for(unsigned tx=0;tx<2;++tx)
    for(unsigned y=0;y<16;++y) for(unsigned x=0;x<16;++x) {
        const unsigned color=(x+y+tx*3+ty*5)%15+1;
        for(unsigned plane=0;plane<4;++plane)
            if(color&(1<<plane)) (*vdc.vram)[(16+ty*2+tx)*64+plane*16+y]|=1<<(15-x);
    }
    for(unsigned i=0;i<16;++i) vce.palette[256+i]=static_cast<std::uint16_t>(i*31);
    constexpr unsigned heights[]={16,32,64,64};
    for(unsigned wide=0;wide<2;++wide) for(unsigned h=0;h<4;++h)
    for(unsigned flip=0;flip<4;++flip) {
        std::array<std::uint16_t,256> satb{};
        satb[0]=64;satb[1]=32;satb[2]=32;
        satb[3]=static_cast<std::uint16_t>(128|(wide<<8)|(h<<12)|((flip&1)<<11)|((flip&2)<<14));
        const auto width=wide ? 32u:16u,height=heights[h];
        vdc.reg[13]=static_cast<std::uint16_t>(height-1);
        const auto frame=pce::render_snapshot(vdc,vce,satb);
        for(unsigned y=0;y<height;++y) for(unsigned x=0;x<width;++x) {
            const auto sx=(flip&1) ? width-1-x:x;
            const auto sy=(flip&2) ? height-1-y:y;
            const unsigned index=(sx%16+sy%16+(sx/16)*3+(sy/16)*5)%15+1;
            const auto color=index*31;
            const auto offset=(y*32+x)*3;
            require(frame.rgb[offset]==((color>>3)&7)*255/7);
            require(frame.rgb[offset+1]==((color>>6)&7)*255/7);
            require(frame.rgb[offset+2]==(color&7)*255/7);
        }
    }
    // Sixteen visible-in-Y cells consume the line budget even offscreen in X.
    std::array<std::uint16_t,256> satb{};
    for(unsigned i=0;i<17;++i) {
        satb[i*4]=64;satb[i*4+1]=i==16 ? 32:1000;
        satb[i*4+2]=32;satb[i*4+3]=128;
    }
    vdc.reg[13]=0;const auto limited=pce::render_snapshot(vdc,vce,satb);
    for(auto component:limited.rgb) require(component==0);
}
}
int main() {
    try {ports();snapshots();sprite_layouts();std::cout<<"video checks: "<<checks<<"\n";return 0;}
    catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
