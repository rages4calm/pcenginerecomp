#include "pce/runtime.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
std::uint64_t checks=0;
void require(bool condition,const char* what) {
    ++checks;if(!condition) throw std::runtime_error(what);
}
void reg(pce::Vdc& v,unsigned index,unsigned value) {
    v.write(0,static_cast<std::uint8_t>(index));
    v.write(2,static_cast<std::uint8_t>(value));
    v.write(3,static_cast<std::uint8_t>(value>>8));
}
void storage_and_ports() {
    pce::Vdc v;
    require(v.vram_bus_latch==0 && v.peek_vram(0xFFFF)==0,"cold undriven bus is deterministic zero");
    for(unsigned i=0;i<32768;++i) (*v.vram)[i]=static_cast<std::uint16_t>((i*149)^0xA5C3);
    for(unsigned i=0;i<32768;++i) {
        const auto previous=v.vram_bus_latch;
        const auto expected=static_cast<std::uint16_t>((i*149)^0xA5C3);
        require(v.peek_vram(static_cast<std::uint16_t>(i))==expected && v.vram_bus_latch==previous,
                "connected inspection is pure");
        require(v.read_vram(static_cast<std::uint16_t>(i))==expected && v.vram_bus_latch==expected,
                "connected guest read drives full word");
        require(v.read_vram(static_cast<std::uint16_t>(i+32768))==expected && v.vram_bus_latch==expected,
                "undriven high half retains full word without mirroring");
    }
    constexpr unsigned increments[]={1,32,64,128};
    for(unsigned mode=0;mode<4;++mode)for(unsigned start:{0x7FFFU,0x8000U,0xFFFFU}) {
        v.reg[5]=static_cast<std::uint16_t>(mode<<11);v.vram_bus_latch=0xC15E;
        const auto writes=v.writes;
        reg(v,1,start);
        const auto word=start<32768 ? static_cast<std::uint16_t>((start*149)^0xA5C3):std::uint16_t(0xC15E);
        require(v.read_buffer==word && v.vram_bus_latch==word && v.writes==writes+3,
                "MARR high write prefetch drives or retains latch");
        require(v.reg[1]==static_cast<std::uint16_t>(start+increments[mode]),"prefetch increments and wraps MARR");
        v.write(0,2);
        require(v.read(2)==(word&255),"low VDC port reads read-buffer low byte");
        const auto next=v.reg[1];
        require(v.read(3)==(word>>8),"high VDC port returns old buffer before next prefetch");
        const auto after=next<32768 ? (*v.vram)[next]:word;
        require(v.read_buffer==after && v.vram_bus_latch==after,"high port settles subsequent bus read");
        require(v.reg[1]==static_cast<std::uint16_t>(next+increments[mode]),"high-port address wrap");
    }
    v.reg[5]=0;v.vram_bus_latch=0xB29D;const auto old=(*v.vram)[0];
    reg(v,0,0x8000);reg(v,2,0x3456);
    require(v.vram_bus_latch==0xB29D && (*v.vram)[0]==old && v.reg[0]==0x8001,
            "undriven write ignores data without driving bus or mirroring storage");
    reg(v,0,15);reg(v,2,0x5678);
    require((*v.vram)[15]==0x5678 && v.vram_bus_latch==0xB29D,"connected write does not drive read bus");
    v.read(0);v.read(1);
    require(v.vram_bus_latch==0xB29D,"status and unused reads do not drive VRAM bus");
}
void transfers() {
    for(unsigned direction=0;direction<4;++direction)
    for(unsigned source:{0U,0x7FFFU,0x8000U,0xFFFFU})
    for(unsigned dest:{0U,0x7FFFU,0x8000U,0xFFFFU}) {
        pce::Vdc v;v.enabled=v.dma_enabled=true;
        for(unsigned i=0;i<32768;++i) (*v.vram)[i]=static_cast<std::uint16_t>(i^0xED91);
        auto expected=*v.vram;std::uint16_t latch=0x739A,src=source,dst=dest;
        v.vram_bus_latch=latch;reg(v,15,2|((direction&1)?4:0)|((direction&2)?8:0));
        reg(v,16,source);reg(v,17,dest);reg(v,18,3);
        for(unsigned index=0;index<4;++index) {
            if(dst<32768) {if(src<32768)latch=expected[src];expected[dst]=latch;}
            src=static_cast<std::uint16_t>(src+((direction&1)?-1:1));
            dst=static_cast<std::uint16_t>(dst+((direction&2)?-1:1));
            for(unsigned dot=0;dot<4;++dot)v.dma_tick();
            require(v.vram_bus_latch==latch,"DMA source reads only for driven destinations");
            require(v.reg[16]==src && v.reg[17]==dst,"DMA address direction/wrap");
            require(v.reg[18]==static_cast<std::uint16_t>(2-index),"DMA length progression");
        }
        require(*v.vram==expected && v.dma_words==4 && v.vram_dma_pending==0,"whole DMA storage exact");
        require(v.irq1 && (v.status&16),"DMA completion IRQ retained");
    }
    for(unsigned source:{0x7F80U,0x8000U,0xFFFFU}) {
        pce::Vdc v;v.enabled=v.dma_enabled=true;v.vram_bus_latch=0x81E3;
        for(unsigned i=0;i<32768;++i)(*v.vram)[i]=static_cast<std::uint16_t>(i*31+0xA17);
        reg(v,15,1);reg(v,19,source);v.vblank_dma();std::uint16_t held=0x81E3;
        for(unsigned i=0;i<256;++i) {
            const auto address=static_cast<std::uint16_t>(source+i);
            if(address<32768)held=static_cast<std::uint16_t>(address*31+0xA17);
            for(unsigned dot=0;dot<4;++dot)v.dma_tick();
            require(v.satb[i]==held && v.vram_bus_latch==held,"SATB preserves driven/held words across address boundary");
        }
        require(v.satb_words==256 && v.satb_pending==0 && v.irq1 && (v.status&8),"SATB completion unchanged");
    }
}
void rendering_and_inspection() {
    pce::Vdc v;v.enabled=true;std::array<std::uint16_t,24> line{};
    for(unsigned i=0;i<4;++i) {(*v.vram)[i]=static_cast<std::uint16_t>(i+16);(*v.vram)[(i+16)*16+8]=static_cast<std::uint16_t>(0x1111*(i+1));}
    pce::render_guest_scanline_indices(v,0,3,0,128,0,line);
    require(v.vram_bus_latch==0x4444,"four-bit background settles final tile's upper plane word");
    const auto before=v.vram_bus_latch;
    pce::render_scanline_indices(v,0,3,0,128,0,line);
    require(v.vram_bus_latch==before,"pure line inspector does not drive VRAM");
    for(unsigned cg=0;cg<2;++cg) {
        (*v.vram)[0]=0x7200;(*v.vram)[0x2000]=0x8A31;(*v.vram)[0x2008]=0x53C7;
        pce::render_guest_scanline_indices(v,0,0,0,128,static_cast<std::uint16_t>(3|(cg<<7)),std::span(line).first(8));
        require(v.vram_bus_latch==(cg?0x53C7:0x8A31),"two-bit background drives only selected CG word");
        (*v.vram)[0]=0x7800;
        pce::render_guest_scanline_indices(v,0,0,0,128,static_cast<std::uint16_t>(3|(cg<<7)),std::span(line).first(8));
        require(v.vram_bus_latch==0x7800,"two-bit tile bit11 selects undriven pattern, retaining actual BAT read");
    }
    pce::Vce palette;palette.enabled=true;v.reg[5]=64;v.reg[11]=1;v.reg[13]=0;
    v.satb[0]=64;v.satb[1]=32;v.satb[2]=1024;v.satb[3]=128;
    palette.palette[271]=0x38;v.vram_bus_latch=0x8000;
    const auto registers=v.reg;const auto reads=v.reads,writes=v.writes;
    const auto picture=pce::render_snapshot(v,palette,v.satb);
    require(picture.rgb[0]==255 && picture.rgb[1]==0 && picture.rgb[2]==0,"snapshot high sprite words observe held value");
    require(v.vram_bus_latch==0x8000 && v.reg==registers && v.reads==reads && v.writes==writes,
            "snapshot never mutates retained bus, registers or port counters");

    pce::Vdc sprite;sprite.enabled=true;sprite.reg[5]=64;sprite.reg[11]=1;sprite.reg[13]=239;
    sprite.satb[0]=64;sprite.satb[1]=32;sprite.satb[2]=512;sprite.satb[3]=128;
    (*sprite.vram)[0x4000]=0x8000;sprite.enable_raster();
    for(unsigned ticks=0;ticks<100000 && !sprite.sprite_count;++ticks)sprite.advance(1);
    require(sprite.sprite_count==1 && sprite.sprite_rows[0].planes[0]==0x8000,"actual raster evaluator captures sprite data");
    (*sprite.vram)[0x4000]=0;sprite.satb[1]=1000;sprite.satb[3]=4;
    pce::render_guest_scanline_indices(sprite,0,0,0,64,0,std::span(line).first(16));
    require(line[0]==257,"continuous rendering uses captured sprite words, position, palette and priority after RAM/SAT writes");
    palette.palette[257]=0x38;
    const auto inspected=pce::render_snapshot(sprite,palette,sprite.satb);
    require(inspected.rgb[0]==0,"pure snapshot separately reflects current edited sprite state");
}
void output_independence() {
    pce::Bus silent,shown;
    for(auto* b:{&silent,&shown}) {
        b->enable_video();b->vdc.reg[5]=128;std::fill(b->vdc.vram->begin(),b->vdc.vram->end(),0x1357);
        b->vdc.enable_raster();
    }
    shown.vdc.video.enable(shown.vdc);
    constexpr unsigned intervals[]={1,1127,4,1365*13,1365*7+3,1365*250};
    for(auto ticks:intervals) {
        silent.vdc.advance(ticks,&silent.vce);shown.vdc.advance(ticks,&shown.vce);
        require(silent.vdc.vram_bus_latch==shown.vdc.vram_bus_latch,"guest background bus independent of framebuffer production");
        require(silent.vdc.raster.master_ticks==shown.vdc.raster.master_ticks && silent.vdc.reg==shown.vdc.reg,
                "presentation does not change guest time or registers");
    }
    require(silent.vdc.vram_bus_latch==0x1357,"presentation-off actual background fetch drives bus");
    require(silent.vdc.video.sequence()==0 && shown.vdc.video.sequence()>0,"frame publication remains opt-in");
}
}
int main() try {
    storage_and_ports();transfers();rendering_and_inspection();output_independence();
    std::cout<<checks<<" authored VRAM retained-bus, DMA, rendering-cache and pure-inspection checks passed\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
