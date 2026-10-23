#include "pce/runtime.hpp"

namespace pce {
void Vdc::prefetch() {
    // The undriven half of the VRAM address space depends on the rendering
    // bus latch. Refuse it until that bus exists instead of inventing data.
    if(reg[1]>=32768) throw Fault("VDC undriven VRAM read requires the rendering bus latch");
    read_buffer=(*vram)[reg[1]];
    reg[1]=static_cast<std::uint16_t>(reg[1]+increment());
}
std::uint8_t Vdc::read(unsigned port) {
    std::uint8_t value=0;
    switch(port&3) {
    case 0: value=status&0x3F; status=0; irq1=false; break;
    case 1: break;
    case 2: value=static_cast<std::uint8_t>(read_buffer); break;
    case 3:
        value=static_cast<std::uint8_t>(read_buffer>>8);
        if(selected==2) prefetch();
        break;
    }
    ++reads; return value;
}
void Vdc::write(unsigned port, std::uint8_t value) {
    port&=3;
    if(port==0) selected=value&31;
    else if(port>=2 && selected<20) {
        const bool high=port==3;
        // Each mask describes the implemented register bits of the hardware.
        constexpr std::uint16_t masks[]={65535,65535,65535,0,0,8191,1023,1023,
            511,255,32543,32639,65311,511,255,31,65535,65535,65535,65535};
        const auto merged=static_cast<std::uint16_t>(high ? (reg[selected]&255)|(value<<8):
                                                          (reg[selected]&0xFF00)|value);
        // Refuse unsupported triggers before changing any register or VRAM.
        if(!dma_enabled && high && (selected==18 || selected==19)) throw Fault("VDC DMA trigger is not implemented");
        if(high && selected==1 && merged>=32768)
            throw Fault("VDC undriven VRAM read requires the rendering bus latch");
        reg[selected]=merged&masks[selected];
        if(video.enabled) video.register_write(*this,selected,high);
        if(high && selected==18) {
            vram_dma_pending=4*(unsigned(reg[18])+1); dma_source=reg[16];dma_dest=reg[17];
        }
        if(high && selected==19) satb_armed=true;
        if(high && selected==1) prefetch();
        if(high && selected==2) {
            const auto address=reg[0];
            if(address<32768 && (*vram)[address]!=reg[2]) { (*vram)[address]=reg[2]; ++vram_changes; }
            // The high address bit is unconnected: writes are ignored, not mirrored.
            reg[0]=static_cast<std::uint16_t>(address+increment());
        }
    }
    ++writes;
}
void Vdc::vblank_dma() {
    if(satb_armed || (reg[15]&16)) {satb_armed=false;satb_pending=1024;}
}
void Vdc::dma_tick() {
    if(satb_pending) {
        --satb_pending;
        if(!(satb_pending&3)) {
            const auto index=255-(satb_pending>>2);
            const auto source=static_cast<std::uint16_t>(reg[19]+index);
            if(source>=32768) throw Fault("SATB DMA undriven VRAM source requires the rendering bus latch");
            satb[index]=(*vram)[source];++satb_words;
            if(!satb_pending && (reg[15]&1)) {status|=8;irq1=true;}
        }
    } else if(vram_dma_pending) {
        --vram_dma_pending;
        if(!(vram_dma_pending&3)) {
            if(dma_dest<32768) {
                if(dma_source>=32768) throw Fault("VRAM DMA undriven source requires the rendering bus latch");
                const auto value=(*vram)[dma_source];
                if((*vram)[dma_dest]!=value) {(*vram)[dma_dest]=value;++vram_changes;}
            }
            dma_source=static_cast<std::uint16_t>(dma_source+((reg[15]&4)?-1:1));
            dma_dest=static_cast<std::uint16_t>(dma_dest+((reg[15]&8)?-1:1));
            reg[16]=dma_source;reg[17]=dma_dest;reg[18]=static_cast<std::uint16_t>((vram_dma_pending>>2)-1);
            ++dma_words;
            if(!vram_dma_pending && (reg[15]&2)) {status|=16;irq1=true;}
        }
    }
}
void Bus::enable_vdc() { vdc=Vdc{}; vdc.enabled=true; kind[255]=BankKind::io; }
void Bus::write_vdc(unsigned port, std::uint8_t value) {
    if(!vdc.enabled) throw Fault("VDC profile is disabled");
    vdc.write(port,value);
}
} // namespace pce
