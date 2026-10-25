#include "pce/runtime.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
std::uint64_t checks=0;
void require(bool condition) {
    ++checks;
    if(!condition) throw std::runtime_error("DMA expectation failed at "+std::to_string(checks));
}
void reg(pce::Vdc& v,unsigned index,unsigned value) {
    v.write(0,static_cast<std::uint8_t>(index));
    v.write(2,static_cast<std::uint8_t>(value));
    v.write(3,static_cast<std::uint8_t>(value>>8));
}
template<class F> void fault(F&& fn) {
    bool caught=false;try {fn();}catch(const pce::Fault&){caught=true;}require(caught);
}
void dots(pce::Vdc& v,unsigned count) {
    // A 1365-master-clock scanline can end between divider-2/4 dots.
    // Count actual VDC clocks instead of assuming an uninterrupted divider.
    while(count) {
        const auto until_dot=v.raster.divider-v.raster.hclock%v.raster.divider;
        const auto chunk=std::min(until_dot,1365-v.raster.hclock);
        v.advance(chunk);
        if(chunk==until_dot) --count;
    }
}
void transfer_matrix() {
    for(unsigned divider:{2,3,4}) for(unsigned direction=0;direction<4;++direction)
    for(unsigned count:{1,2,3,16,255,256}) for(bool interrupt:{false,true}) {
        pce::Vdc v;v.enabled=v.dma_enabled=true;v.enable_raster();
        v.write_vce_control(divider==4 ? 0:divider==3 ? 1:2);
        const unsigned source=1024,dest=2048;
        for(unsigned a=0;a<32768;++a) (*v.vram)[a]=static_cast<std::uint16_t>(a*73+19);
        const auto saved=*v.vram;
        reg(v,15,((direction&1) ? 4:0)|((direction&2) ? 8:0)|(interrupt ? 2:0));
        reg(v,16,source);reg(v,17,dest);
        v.write(0,18);v.write(2,static_cast<std::uint8_t>(count-1));
        require(v.vram_dma_pending==0);
        v.write(3,static_cast<std::uint8_t>((count-1)>>8));
        require(v.vram_dma_pending==count*4);
        v.advance(divider*4-1);
        require((*v.vram)[dest]==saved[dest] && v.dma_words==0);
        v.advance(1);
        require((*v.vram)[dest]==saved[source] && v.dma_words==1);
        dots(v,(count-1)*4);
        require(v.vram_dma_pending==0 && v.dma_words==count);
        require(v.reg[16]==source+((direction&1) ? -static_cast<int>(count):static_cast<int>(count)));
        require(v.reg[17]==dest+((direction&2) ? -static_cast<int>(count):static_cast<int>(count)));
        require(v.reg[18]==65535);
        require(bool(v.status&16)==interrupt && v.irq1==interrupt);
        for(unsigned i=0;i<count;++i) {
            const auto s=(direction&1) ? source-i:source+i;
            const auto d=(direction&2) ? dest-i:dest+i;
            require((*v.vram)[d]==saved[s]);
        }
        const auto status=v.read(0);require(bool(status&16)==interrupt && !v.irq1 && v.status==0);
    }
}
void ordering_and_boundaries() {
    pce::Vdc v;v.enabled=v.dma_enabled=true;v.enable_raster();
    (*v.vram)[100]=0xBEEF;
    reg(v,16,100);reg(v,17,101);reg(v,18,15);v.advance(16*16);
    for(unsigned a=100;a<=116;++a) require((*v.vram)[a]==0xBEEF);
    require(v.dma_words==16);
    // Writes to SOUR/DESR during a transfer do not replace its latched addresses.
    (*v.vram)[1000]=0xA17;(*v.vram)[1001]=0xB28;
    reg(v,16,1000);reg(v,17,2000);reg(v,18,1);reg(v,16,4000);reg(v,17,5000);
    v.advance(32);require((*v.vram)[2000]==0xA17 && (*v.vram)[2001]==0xB28);
    require(v.reg[16]==1002 && v.reg[17]==2002);
    // Direction bits remain live between words.
    reg(v,15,0);reg(v,16,1000);reg(v,17,3000);reg(v,18,1);v.advance(16);
    reg(v,15,12);v.advance(16);require(v.reg[16]==1000 && v.reg[17]==3000);
    // Destinations in the unconnected half are ignored; the address still wraps.
    (*v.vram)[100]=0x1234;(*v.vram)[101]=0x5678;
    reg(v,15,0);reg(v,16,100);reg(v,17,65535);reg(v,18,1);v.advance(32);
    require((*v.vram)[0]==0x5678 && v.reg[17]==1);
    v.vram_bus_latch=0xB6F2;
    reg(v,16,32768);reg(v,17,0);reg(v,18,0);
    v.advance(16);
    require((*v.vram)[0]==0xB6F2 && v.vram_bus_latch==0xB6F2 &&
            v.reg[16]==32769 && v.reg[17]==1 && v.reg[18]==65535);
    // Functional-only VDC still refuses unsupported asynchronous triggers.
    pce::Vdc functional;functional.enabled=true;
    fault([&]{reg(functional,18,0);});fault([&]{reg(functional,19,0);});
}
void satb() {
    for(bool interrupt:{false,true}) {
        pce::Vdc v;v.enabled=v.dma_enabled=true;
        v.reg[11]=31;v.reg[13]=239;v.enable_raster();
        // These are arbitrary full-word SATB transfer patterns, not drawable
        // sprites. Enter the real frame-latched display-off burst mode before
        // transferring them, so this fixture isolates DMA/IRQ ordering without
        // requesting undriven sprite pattern reads. Do not alter the raw words.
        v.advance(1365*262);require(v.sprite_burst);
        for(unsigned i=0;i<256;++i) (*v.vram)[4096+i]=static_cast<std::uint16_t>(i*29+7);
        reg(v,15,interrupt ? 1:0);reg(v,19,4096);
        require(v.satb_armed && v.satb_pending==0);
        v.vblank_dma();require(!v.satb_armed && v.satb_pending==1024);
        // SATB takes precedence over a pending VRAM transfer.
        reg(v,16,4096);reg(v,17,8192);reg(v,18,0);
        dots(v,1023);require(v.satb_words==255 && v.dma_words==0);
        dots(v,1);require(v.satb_words==256 && v.satb_pending==0 && v.dma_words==0);
        for(unsigned i=0;i<256;++i) require(v.satb[i]==i*29+7);
        require(bool(v.status&8)==interrupt && v.irq1==interrupt);
        dots(v,4);require(v.dma_words==1 && (*v.vram)[8192]==7);
        // Auto-repeat uses the current source at each VBlank.
        reg(v,15,16);v.vblank_dma();dots(v,1024);
        require(v.satb_words==512);
        v.vblank_dma();require(v.satb_pending==1024);
    }
    pce::Vdc v;v.enabled=v.dma_enabled=true;v.enable_raster();
    (*v.vram)[100]=0x123;(*v.vram)[201]=0x456;
    reg(v,19,100);v.vblank_dma();v.advance(16);reg(v,19,200);v.advance(16);
    require(v.satb[0]==0x123 && v.satb[1]==0x456 && v.satb_armed);
}
}
int main() {
    try {transfer_matrix();ordering_and_boundaries();satb();
        std::cout<<"DMA checks: "<<checks<<"\n";return 0;}
    catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;}
}
