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
        if(high && (selected==18 || selected==19)) throw Fault("VDC DMA trigger is not implemented");
        if(high && selected==1 && merged>=32768)
            throw Fault("VDC undriven VRAM read requires the rendering bus latch");
        reg[selected]=merged&masks[selected];
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
void Bus::enable_vdc() { vdc=Vdc{}; vdc.enabled=true; kind[255]=BankKind::io; }
void Bus::write_vdc(unsigned port, std::uint8_t value) {
    if(!vdc.enabled) throw Fault("VDC profile is disabled");
    vdc.write(port,value);
}
} // namespace pce
