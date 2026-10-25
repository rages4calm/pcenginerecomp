#include "pce/runtime.hpp"

namespace pce {
std::uint16_t Vdc::peek_vram(std::uint16_t address) const {
    return address<32768 ? (*vram)[address]:vram_bus_latch;
}
std::uint16_t Vdc::read_vram(std::uint16_t address) {
    if(address<32768) vram_bus_latch=(*vram)[address];
    return vram_bus_latch;
}
void Vdc::prefetch() {
    read_buffer=read_vram(reg[1]);
    reg[1]=static_cast<std::uint16_t>(reg[1]+increment());
}
bool Vdc::vram_wait_required(unsigned port,bool write_access) const {
    if(!queues_vram() || (port&3)<2) return false;
    return write_access ? selected<=2 && has_pending_vram():pending_vram_read;
}
void Vdc::update_vram_busy() {
    status=static_cast<std::uint8_t>((status&~0x40)|(has_pending_vram()?0x40:0));
}
void Vdc::queue_vram_read() {
    if(!queues_vram()) {prefetch();return;}
    constexpr int delay[]={24,24,15,15};
    pending_vram_read=true;vram_transfer_delay=delay[raster.control&3];
    update_vram_busy();
}
void Vdc::queue_vram_write() {
    if(!queues_vram()) {complete_vram_write();return;}
    constexpr int delay[]={21,18,12,12};
    pending_vram_write=true;vram_transfer_delay=delay[raster.control&3];
    update_vram_busy();
}
void Vdc::complete_vram_read() {
    prefetch();pending_vram_read=false;update_vram_busy();
}
void Vdc::complete_vram_write() {
    const auto address=reg[0];
    if(address<32768 && (*vram)[address]!=reg[2]) {(*vram)[address]=reg[2];++vram_changes;}
    reg[0]=static_cast<std::uint16_t>(address+increment());
    pending_vram_write=false;update_vram_busy();
}
bool Vdc::cpu_vram_slot_available(unsigned elapsed_master_ticks) const {
    if(satb_pending || vram_dma_pending) return false;
    const auto& r=raster;
    const auto clock=static_cast<int>(r.hclock),divider=static_cast<int>(r.divider);
    const bool fetching=!sprite_burst && clock>=load_bg_start_clock && clock<load_bg_end_clock &&
        r.vdc_line>=14 && r.vdc_line<256;
    const bool sprites=(sprite_control&64)!=0;
    bool blocked=false;
    if(r.v_state!=1 || sprite_burst || ((!sprites || !sprite_count) && !fetching)) {
        blocked=((clock/divider)&1)!=0;
    } else if(fetching) {
        const auto dot=(clock-load_bg_start_clock)/divider-1;
        bool allowed=false;
        if(dot>=0) {
            switch(sprite_mode&3) {
            case 0: allowed=(dot&1)==0;break;
            case 1:case 2: allowed=(dot&7)==2 || (dot&7)==3;break;
            default: break;
            }
        }
        blocked=!allowed;
    } else if(sprites) {
        const auto elapsed=clock>load_bg_end_clock ? clock-load_bg_end_clock:
            1365-load_bg_end_clock+clock;
        constexpr unsigned cost[]={4,4,8,16};
        blocked=static_cast<unsigned>(elapsed/divider)<sprite_count*cost[(sprite_mode>>2)&3] ||
            ((clock/divider)&1)!=0;
    }
    if(blocked)return false;
    if(r.h_state==3) {
        const auto future=static_cast<unsigned>((r.hclock+elapsed_master_ticks)%1365);
        const auto since=(future+1365-hsync_start_clock)%1365;
        if(since<8*r.divider)return false;
    }
    return true;
}
void Vdc::process_cpu_vram_accesses(unsigned master_ticks) {
    if(!queues_vram() || !has_pending_vram()) {vram_cpu_cycles=0;return;}
    auto available=std::uint64_t(master_ticks)+vram_cpu_cycles;
    while(has_pending_vram() && available>=3) {
        available-=3;
        if(vram_transfer_delay>0) {
            vram_transfer_delay-=3;
            if(vram_transfer_delay>0) continue;
        }
        vram_transfer_delay=0;
        if(!cpu_vram_slot_available())continue;
        if(pending_vram_read)complete_vram_read();else complete_vram_write();
    }
    vram_cpu_cycles=has_pending_vram() ? static_cast<unsigned>(available):0;
}
std::uint8_t Vdc::read(unsigned port) {
    if(vram_wait_required(port,false))throw Fault("VDC data read requires queued VRAM clock progress");
    std::uint8_t value=0;
    switch(port&3) {
    case 0: value=static_cast<std::uint8_t>((status&0x3F)|(has_pending_vram()?0x40:0)); status=0; irq1=false;update_vram_busy();break;
    case 1: break;
    case 2: value=static_cast<std::uint8_t>(read_buffer); break;
    case 3:
        value=static_cast<std::uint8_t>(read_buffer>>8);
        if(selected==2) queue_vram_read();
        break;
    }
    ++reads; return value;
}
void Vdc::write(unsigned port, std::uint8_t value) {
    if(vram_wait_required(port,true))throw Fault("VDC data write requires queued VRAM clock progress");
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
        reg[selected]=merged&masks[selected];
        video.register_write(*this,selected,high);
        if(high && selected==18) {
            vram_dma_pending=4*(unsigned(reg[18])+1); dma_source=reg[16];dma_dest=reg[17];
        }
        if(high && selected==19) satb_armed=true;
        if(high && selected==1) queue_vram_read();
        if(high && selected==2) queue_vram_write();
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
            satb[index]=read_vram(source);++satb_words;
            if(!satb_pending && (reg[15]&1)) {status|=8;irq1=true;}
        }
    } else if(vram_dma_pending) {
        --vram_dma_pending;
        if(!(vram_dma_pending&3)) {
            if(dma_dest<32768) {
                const auto value=read_vram(dma_source);
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
