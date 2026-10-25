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
    fault([&]{pce::render_snapshot(vdc,vce,std::span(satb).first(255));});
    vdc.enabled=false;fault([&]{pce::render_snapshot(vdc,vce);});
    fault([&]{pce::write_ppm(pce::VideoFrame{},"");});
}
void background_modes() {
    pce::Vdc vdc;pce::Vce vce;vdc.enabled=vce.enabled=true;
    vdc.reg[5]=128;vdc.reg[11]=0;vdc.reg[13]=0;
    (*vdc.vram)[0]=0xF400;
    std::array<std::uint16_t,8> line{};
    // Enumerate every authored eight-pixel two-bit row, then pack its two
    // planes. Expected pixels are the original base-four digits, independent
    // of the renderer's bit extraction. The unused CG word is its complement.
    for(unsigned packed=0;packed<65536;++packed) {
        std::array<unsigned,8> expected{};
        std::uint16_t word=0;
        for(unsigned x=0;x<8;++x) {
            expected[x]=(packed>>(x*2))&3;
            if(expected[x]&1) word|=1u<<(7-x);
            if(expected[x]&2) word|=1u<<(15-x);
        }
        for(unsigned cg=0;cg<2;++cg) {
            (*vdc.vram)[0x4000+cg*8]=word;
            (*vdc.vram)[0x4000+(1-cg)*8]=static_cast<std::uint16_t>(~word);
            pce::render_scanline_indices(vdc,0,0,0,128,static_cast<std::uint16_t>(3+cg*128),line);
            for(unsigned x=0;x<8;++x)
                require(line[x]==(expected[x] ? 0xF0+expected[x]:0));
        }
    }
    // All BAT palettes retain their four-bit stride, rather than shrinking to
    // four colors. Color zero always selects the global backdrop.
    constexpr unsigned colors[]={0,1,2,3,0,3,2,1};
    constexpr std::uint16_t word=0x3655;
    for(unsigned palette=0;palette<16;++palette) for(unsigned cg=0;cg<2;++cg) {
        (*vdc.vram)[0]=static_cast<std::uint16_t>((palette<<12)|0x400);
        (*vdc.vram)[0x4000+cg*8]=word;
        (*vdc.vram)[0x4000+(1-cg)*8]=0xFFFF;
        vdc.reg[9]=static_cast<std::uint16_t>(3+cg*128);
        for(unsigned i=0;i<512;++i) vce.palette[i]=static_cast<std::uint16_t>(i);
        pce::render_scanline_indices(vdc,0,0,0,128,vdc.reg[9],line);
        const auto frame=pce::render_snapshot(vdc,vce);
        for(unsigned x=0;x<8;++x) {
            const auto index=colors[x] ? palette*16+colors[x]:0;
            require(line[x]==index);
            require(frame.rgb[x*3]==((index>>3)&7)*255/7);
            require(frame.rgb[x*3+1]==((index>>6)&7)*255/7);
            require(frame.rgb[x*3+2]==(index&7)*255/7);
        }
    }
    // Access modes 0/1/2 keep all four planes and ignore the CG selector.
    (*vdc.vram)[0]=0x2400;(*vdc.vram)[0x4000]=0x4080;(*vdc.vram)[0x4008]=0x1020;
    constexpr unsigned four[]={0x21,0x22,0x24,0x28,0,0,0,0};
    for(unsigned mode=0;mode<3;++mode) for(unsigned cg=0;cg<2;++cg) {
        pce::render_scanline_indices(vdc,0,0,0,128,static_cast<std::uint16_t>(mode+cg*128),line);
        for(unsigned x=0;x<8;++x) require(line[x]==four[x]);
    }
    // Both map dimensions and fine scroll wrap independently in two-bit mode.
    constexpr unsigned widths[]={32,64,128,128};
    for(unsigned shape=0;shape<8;++shape) {
        const auto width=widths[shape&3],height=(shape&4) ? 64u:32u;
        for(unsigned y=0;y<height;++y) for(unsigned x=0;x<width;++x)
            (*vdc.vram)[y*width+x]=static_cast<std::uint16_t>(0x400+((x+y*3)&15));
        for(unsigned tile=0;tile<16;++tile) for(unsigned y=0;y<8;++y) {
            // Every pixel of each row has an independently selected color.
            const auto color=(tile+y)%4;
            (*vdc.vram)[0x4000+tile*16+y]=static_cast<std::uint16_t>((color&1 ? 0xFF:0)|(color&2 ? 0xFF00:0));
            (*vdc.vram)[0x4008+tile*16+y]=static_cast<std::uint16_t>((color&2 ? 0xFF:0)|(color&1 ? 0xFF00:0));
        }
        for(unsigned sx:{0u,7u,width*8-1,width*8+7})
        for(unsigned sy:{0u,7u,height*8-1,height*8+7}) for(unsigned cg=0;cg<2;++cg) {
            pce::render_scanline_indices(vdc,0,sx,sy,128,static_cast<std::uint16_t>(shape*16+3+cg*128),line);
            for(unsigned x=0;x<8;++x) {
                const auto px=(sx+x)%(width*8),py=sy%(height*8);
                auto color=(((px/8+(py/8)*3)&15)+(py&7))%4;
                if(cg) color=((color&1)<<1)|(color>>1);
                require(line[x]==color);
            }
        }
    }
    // A behind-background sprite appears only through color zero. Sprite
    // access-width selection remains separate from background access width.
    vdc.vram->fill(0);vdc.satb.fill(0);
    (*vdc.vram)[0]=0xF400;vdc.satb[0]=64;vdc.satb[1]=32;vdc.satb[2]=0x280;
    (*vdc.vram)[0x5000]=0xFFFF;
    for(unsigned cg=0;cg<2;++cg) for(unsigned color=0;color<4;++color)
    for(unsigned front=0;front<2;++front) {
        (*vdc.vram)[0x4000+cg*8]=static_cast<std::uint16_t>((color&1 ? 0xFF:0)|(color&2 ? 0xFF00:0));
        vdc.satb[3]=static_cast<std::uint16_t>(front*128);
        pce::render_scanline_indices(vdc,0,0,0,192,static_cast<std::uint16_t>(3+cg*128),line);
        for(auto pixel:line) require(pixel==(front || !color ? 257u:0xF0+color));
    }
}
void digital_monochrome() {
    pce::Vdc vdc;pce::Vce vce;vdc.enabled=vce.enabled=true;
    vdc.reg[5]=128;vdc.reg[11]=0;vdc.reg[13]=0;
    // Integer luminance supplies independent expectations for this finite
    // palette. Mesen's specified double truncation lands one lower at the
    // single boundary value 365; retain that digital-profile distinction.
    for(unsigned color=0;color<512;++color) {
        const auto red=((color>>3)&7)*255/7,green=((color>>6)&7)*255/7,blue=(color&7)*255/7;
        const auto gray=(299*red+587*green+114*blue)/1000-(color==365 ? 1:0);
        for(unsigned control:{0u,127u,128u,255u}) {
            vce.control=static_cast<std::uint8_t>(control);vce.palette[0]=static_cast<std::uint16_t>(color);
            const auto frame=pce::render_snapshot(vdc,vce);
            const std::array<unsigned,3> expected=control&128 ? std::array<unsigned,3>{gray,gray,gray}:
                std::array<unsigned,3>{red,green,blue};
            for(unsigned x=0;x<8;++x) for(unsigned c=0;c<3;++c) require(frame.rgb[x*3+c]==expected[c]);
            const auto rgb=pce::vce_rgb(static_cast<std::uint16_t>(color|0xFE00),static_cast<std::uint8_t>(control));
            for(unsigned c=0;c<3;++c) require(rgb[c]==expected[c]);
        }
    }
    // Display-off burst black bypasses the palette and monochrome conversion.
    vdc.reg[5]=0;vce.control=128;vce.palette[0]=511;
    for(auto byte:pce::render_snapshot(vdc,vce).rgb) require(byte==0);
    require(vdc.reads==0 && vdc.writes==0 && vdc.vram_changes==0 && !vdc.irq1);
    require(vce.reads==0 && vce.writes==0);
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
    try {ports();snapshots();background_modes();digital_monochrome();sprite_layouts();std::cout<<"video checks: "<<checks<<"\n";return 0;}
    catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
