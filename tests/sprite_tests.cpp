#include "pce/runtime.hpp"
#include "pce/video.hpp"
#include <iostream>
#include <stdexcept>

namespace {
unsigned checks=0;
void require(bool value,const char* message) {
    ++checks;if(!value)throw std::runtime_error(message);
}
void reg(pce::Vdc& v,unsigned index,unsigned value) {
    v.write(0,index);v.write(2,value&255);v.write(3,value>>8);
}
void setup(pce::Vdc& v,unsigned control=67,unsigned mode=0) {
    v.enabled=true;v.reg[10]=0x0202;v.reg[11]=31;v.reg[12]=0x0c02;v.reg[13]=239;
    v.reg[5]=control;v.reg[9]=mode;v.enable_raster();
    for(unsigned row=0;row<16;++row) {
        (*v.vram)[0x4000+row]=65535;(*v.vram)[0x4040+row]=65535;
    }
}
void sprite(pce::Vdc& v,unsigned index,unsigned x=32,unsigned flags=128,unsigned pattern=512) {
    v.satb[index*4]=80; // Authored top16, visible after the reset border.
    v.satb[index*4+1]=x;v.satb[index*4+2]=pattern;v.satb[index*4+3]=flags;
}
void budget() {
    struct Case {unsigned narrow,wide;bool overflow;};
    for(const auto c:{Case{16,0,false},Case{17,0,true},Case{0,8,false},Case{0,9,true},Case{15,1,true}})
        for(const unsigned control:{2U,66U,130U,194U}) {
            pce::Vdc v;setup(v,control);
            for(unsigned i=0;i<c.narrow;++i)sprite(v,i,1023,128);
            for(unsigned i=0;i<c.wide;++i)sprite(v,c.narrow+i,1023,384);
            // Initial burst is clear even for CR display-off. After its frame
            // boundary, display-off suppresses further fetches.
            v.advance(100000);
            require(bool(v.status&2)==c.overflow,"sprite cell budget/offscreen admission");
            require(v.irq1==c.overflow,"overflow IRQ line");
            require(v.read(0)==(c.overflow?2:0),"overflow status acknowledgement");
            require(v.status==0 && !v.irq1,"acknowledgement clears latch and IRQ");
        }
    pce::Vdc v;setup(v,64);for(unsigned i=0;i<17;++i)sprite(v,i);
    v.advance(100000);require(v.status==0 && !v.irq1,"masked overflow is consumed");
    reg(v,5,66);v.advance(1000);require(v.status==0,"late enable cannot revive consumed overflow");
}
void collision() {
    for(unsigned scenario=0;scenario<8;++scenario) {
        pce::Vdc v;setup(v,scenario==5?129:67);
        const unsigned first=scenario==1?1:0;
        sprite(v,first,scenario==3?1023:32,scenario==4?0:128);
        sprite(v,first+1,scenario==3?1023:32);
        if(scenario==2) v.satb[2]=0; // Sprite0 transparent authored pattern.
        if(scenario==6) v.satb[5]=48; // Touching edges do not overlap.
        if(scenario==7) reg(v,5,66); // Collision mask off.
        v.advance(100000);
        const bool expected=scenario==0 || scenario==4;
        require(bool(v.status&1)==expected,"sprite0 opaque/viewport/enable collision gate");
    }
    pce::Vdc v;setup(v);sprite(v,0);sprite(v,1);
    for(unsigned t=0;t<100000 && !(v.status&1);++t)v.advance(1);
    require(v.status==1 && v.irq1,"collision occurs on visible line");
    const auto tick=v.raster.master_ticks;
    require(v.read(0)==1,"collision status read");
    v.advance(1);require(v.status==0 && !v.irq1,"no per-pixel IRQ reassert after HDW acknowledgement");
    v.advance(1365);require(v.status==1 && v.raster.master_ticks==tick+1366,"next line produces fresh collision");
}
void deferred_events() {
    pce::Vdc v;setup(v,64);for(unsigned i=0;i<17;++i)sprite(v,i);
    for(unsigned t=0;t<100000 && !v.sprite_overflow;++t)v.advance(1);
    require(v.sprite_overflow && v.sprite_count==16,"overflow is pending after row fetch");
    require(v.status==0 && !v.irq1,"row fetch does not immediately assert overflow IRQ");
    reg(v,5,66); // Admission samples the live mask at the deferred HDS event.
    for(unsigned t=0;t<1365 && !(v.status&2);++t)v.advance(1);
    require(v.status==2 && v.irq1 && !v.sprite_overflow,"deferred overflow samples current IRQ enable");
    const auto tick=v.raster.master_ticks;v.read(0);
    v.advance(1);require(v.status==0 && v.raster.master_ticks==tick+1,"overflow acknowledgment stays clear inside line");
    pce::Vdc masked;setup(masked,64);for(unsigned i=0;i<17;++i)sprite(masked,i);
    for(unsigned t=0;t<100000 && !masked.sprite_overflow;++t)masked.advance(1);
    for(unsigned t=0;t<1365 && masked.sprite_overflow;++t)masked.advance(1);
    require(!masked.sprite_overflow && masked.status==0,"masked event still consumes pending overflow");
    reg(masked,5,66);masked.advance(1);require(masked.status==0,"enabling after HDS cannot recreate prior event");
}
void cache_and_output() {
    for(bool output:{false,true}) {
        pce::Vdc v;setup(v);sprite(v,0);sprite(v,1);pce::Vce palette;palette.enabled=true;
        if(output)v.video.enable(v);
        // Wait for the first admitted row. Its opaque pattern survives later
        // SAT/VRAM changes until the next fetch, even with no host framebuffer.
        for(unsigned t=0;t<100000 && v.sprite_count!=2;++t)v.advance(1,&palette);
        require(v.sprite_count==2,"raster event fetches authored sprite row");
        for(unsigned row=0;row<16;++row)(*v.vram)[0x4000+row]=0;
        v.satb[0]=0;v.satb[4]=0;
        for(unsigned t=0;t<1365 && !(v.status&1);++t)v.advance(1,&palette);
        require(v.status&1,"collision uses prefetched row rather than live SAT/VRAM");
        const auto prior=v.status;const auto irq=v.irq1;
        (void)pce::render_snapshot(v,palette,v.satb);
        require(v.status==prior && v.irq1==irq,"snapshot is a pure presentation operation");
    }
}
void burst_and_reset() {
    pce::Vdc v;setup(v,0);for(unsigned i=0;i<17;++i)sprite(v,i);
    v.advance(1365*262);v.read(0);reg(v,5,2);
    v.advance(100000);require(v.status==0 && v.sprite_burst,"frame-latched burst suppresses fetch");
    reg(v,5,66);v.advance(2ULL*1365*262-v.raster.master_ticks);v.read(0);v.advance(100000);
    require(v.status&2,"next frame releases burst and sprite evaluation");
    v.enable_raster();require(v.sprite_count==0 && !v.sprite_overflow && !v.sprite_burst,"timing reset clears cached evaluation");
}
void row_addressing() {
    // These checks use authored asymmetric row/plane words, independently of
    // the renderer. They guard admission, height masks, flips, and 2bpp source.
    for(unsigned height_code=0;height_code<4;++height_code)
        for(bool flip_y:{false,true})for(bool wide:{false,true})for(bool flip_x:{false,true}) {
            pce::Vdc v;setup(v,64);
            const unsigned heights[]={16,32,64,64};
            const unsigned row=flip_y?heights[height_code]-1:0;
            const unsigned base=0x4000+(row/16)*128+(row&15);
            (*v.vram)[base]=0x0011;(*v.vram)[base+16]=0x0022;
            (*v.vram)[base+32]=0x0044;(*v.vram)[base+48]=0x0088;
            (*v.vram)[base+64]=0x0101;
            sprite(v,0,32,(height_code<<12)|(flip_y?32768:0)|(wide?256:0)|(flip_x?2048:0),513);
            for(unsigned t=0;t<100000 && !v.sprite_count;++t)v.advance(1);
            require(v.sprite_count==(wide?2U:1U),"wide sprite cell count");
            require(v.sprite_rows[0].planes[0]==(wide&&flip_x?0x0101:0x0011),"height mask, Y flip and wide X flip row address");
            require(v.sprite_rows[0].flip==flip_x && v.sprite_rows[0].index==0,"cached pixel orientation/source index");
        }
    for(bool odd_pattern:{false,true}) {
        pce::Vdc v;setup(v,64,4);
        v.advance(1365*262); // VSW latches MWR, not a mid-line live mode.
        sprite(v,0,32,128,512+unsigned(odd_pattern));
        for(unsigned t=0;t<100000 && !v.sprite_count;++t)v.advance(1);
        require(v.sprite_mode==4 && v.sprite_count==1,"frame mode latch");
        require(v.sprite_rows[0].planes[0]==(odd_pattern?0:65535),"2bpp SAT pattern bit selects half pattern");
        require(v.sprite_rows[0].planes[2]==0 && v.sprite_rows[0].planes[3]==0,"2bpp suppresses high planes");
    }
}
}
int main() try {
    budget();collision();deferred_events();cache_and_output();burst_and_reset();row_addressing();
    std::cout<<"sprite checks passed: "<<checks<<'\n';return 0;
} catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
