#include "pce/adpcm.hpp"
#include "pce/runtime.hpp"
#include <algorithm>
#include <limits>

namespace pce {
namespace {
std::uint64_t after(std::uint64_t ticks,std::uint64_t delay) {
    if(ticks>std::numeric_limits<std::uint64_t>::max()-delay)throw Fault("ADPCM clock overflow");
    return ticks+delay;
}
unsigned slot_delay(std::uint64_t ticks,bool read) {
    const auto phase=static_cast<unsigned>(ticks%36);
    if(read)return phase<27?27-phase:phase<35?1:28;
    return phase<9?9-phase:phase<26?1:45-phase;
}
bool data_ready(const CdControl* cd) {
    return cd && cd->scsi.enabled && cd->scsi.response_size &&
           cd->scsi.response_index<cd->scsi.response_size;
}
bool requested(const CdControl* cd) {
    return cd && cd->scsi.enabled && (cd->scsi.signals&0x5A)==0x48;
}
// MSM5205 quantizer widths, derived here from floor(16*(11/10)^index).
// This is mathematical device data, not a copied emulator lookup table.
constexpr auto decoder_widths() {
    std::array<unsigned,49> widths{};
    long double value=16;
    for(auto& width:widths){width=static_cast<unsigned>(value);value=value*11/10;}
    return widths;
}
constexpr auto widths=decoder_widths();
}
std::uint64_t Adpcm::sample_period() const {
    // Rounded 16.16 master ticks, using Gear's default 32100 Hz chip clock.
    return (21477273ULL*65536*(16-(sample_rate&15))+16050)/32100;
}
void Adpcm::update_irq(CdControl* cd) {
    if(cd)cd->interrupt_active=static_cast<std::uint8_t>((cd->interrupt_active&~12)|(half_irq?4:0)|(end_irq?8:0));
}
void Adpcm::flags() {
    if(control&16){length=address;end_irq=false;}
    if(control&128){
        read_deadline=write_deadline=0;read_address=write_address=address=0;length=0;
        nibble=false;play_pending=false;end_irq=half_irq=false;playing=(control&32)!=0;
        decoder_output=2048;decoder_index=0;
    }else if(!(control&32) || ((control&64) && !length))playing=play_pending=false;
}
std::uint8_t Adpcm::read(unsigned port) {
    ++reads;
    switch(port){
    case 9:return 0; // Undriven ADPCM address-high read in selected reference.
    case 10:read_deadline=after(master_ticks,slot_delay(master_ticks,true));return read_latch;
    case 11:return dma;
    case 12:return static_cast<std::uint8_t>((playing?8:0)|(end_irq?1:0)|(read_deadline?128:0)|(write_deadline?4:0));
    case 13:return control;
    case 14:return sample_rate;
    default:throw Fault("unsupported ADPCM read port");
    }
}
void Adpcm::write(unsigned port,std::uint8_t value,CdControl* source) {
    switch(port){
    case 8:address=static_cast<std::uint16_t>((address&0xFF00)|value);break;
    case 9:address=static_cast<std::uint16_t>((address&255)|(unsigned(value)<<8));break;
    case 10:write_deadline=after(master_ticks,slot_delay(master_ticks,false));write_latch=value;break;
    case 11:
        if((value&3) && !source)throw Fault("ADPCM DMA requires a clocked CD transport source");
        dma=data_ready(source)?value:static_cast<std::uint8_t>(value&~1);break;
    case 12:break; // Read-only busy/status register.
    case 13:
        if((value&2) && !(control&2))write_address=static_cast<std::uint16_t>(address-((value&1)?0:1));
        if((value&8) && !(control&8))read_address=static_cast<std::uint16_t>(address-((value&4)?0:1));
        if((value&32) && !playing)play_pending=true;
        control=value;break;
    case 14:sample_rate=value;break;
    default:throw Fault("unsupported ADPCM write port");
    }
    ++writes;flags();update_irq(source);
}
void Adpcm::consume_sample() {
    if(!playing && !play_pending)return;
    if(!(control&32) || ((control&64) && !length)){playing=play_pending=false;return;}
    if(play_pending){play_pending=false;playing=true;decoder_output=2048;decoder_index=0;}
    nibble=!nibble;
    last_nibble=static_cast<std::uint8_t>(nibble?ram[read_address]>>4:ram[read_address]&15);
    const auto magnitude=last_nibble&7;
    const auto width=widths[decoder_index];
    const auto delta=static_cast<int>(width/8+(magnitude&1?width/4:0)+
                                      (magnitude&2?width/2:0)+(magnitude&4?width:0));
    // OKI's datasheet explicitly distinguishes the MSM5205's wraparound from
    // the MSM5218's overflow protection. Use unsigned modulo, including when
    // the signed adjustment would be negative; do not clamp the accumulator.
    decoder_output=static_cast<std::uint16_t>((static_cast<unsigned>(decoder_output)+
                    static_cast<unsigned>(last_nibble&8 ? -delta:delta))&4095);
    const int adjustment=magnitude<4 ? -1:2+2*static_cast<int>(magnitude-4);
    decoder_index=static_cast<std::uint8_t>(std::clamp(static_cast<int>(decoder_index)+adjustment,0,48));
    if(!nibble){++read_address;length=(length-1)&0x1FFFF;half_irq=length<=0x8000;if(!length)end_irq=true;}
    ++samples;
}
void Adpcm::advance_to(std::uint64_t ticks,CdControl* cd) {
    if(!enabled){if(cd)cd->advance_to(ticks);return;}
    if(ticks<master_ticks)throw Fault("CPU/ADPCM clock regression");
    if(cd && cd->scsi.enabled && cd->scsi.master_ticks>master_ticks)throw Fault("CD advanced ahead of ADPCM event clock");
    // Independent absolute event timestamps make partitioning host calls safe.
    // The one-byte DMA latch and 64 KiB RAM bound storage regardless of time.
    unsigned event_budget=0;
    for(;;){
        if(cd)cd->advance_to(master_ticks);
        flags();update_irq(cd);
        if((dma&3) && !dma_deadline && requested(cd))dma_deadline=after(master_ticks,36);
        if(master_ticks==ticks)break;
        if(++event_budget>1000000)throw Fault("ADPCM event budget exceeded for one clock advance");
        auto next=ticks;
        for(auto when:{read_deadline,write_deadline,(dma&3)?dma_deadline:0})if(when && when<next)next=when;
        if(cd && (dma&3)){
            for(auto when:{cd->scsi.event?cd->scsi.deadline:0,cd->scsi.auto_ack_deadline,cd->scsi.load_deadline,cd->audio_enabled?cd->audio.deadline:0})
                if(when>master_ticks && when<next)next=when;
        }
        const bool clock_samples=!(control&128) && (playing || play_pending);
        if(clock_samples){
            const auto period=sample_period();
            const auto remain=sample_phase>=period?1:(period-sample_phase+65535)/65536;
            if(remain<next-master_ticks)next=master_ticks+remain;
            const auto delta=next-master_ticks;
            if(delta>std::numeric_limits<std::uint64_t>::max()/65536)throw Fault("ADPCM playback clock overflow");
            sample_phase+=delta*65536;
        }
        if(!(dma&3) && dma_deadline)dma_deadline=after(dma_deadline,next-master_ticks);
        master_ticks=next;if(cd)cd->advance_to(next);
        if(clock_samples && sample_phase>=sample_period()){
            sample_phase-=sample_period();consume_sample();
        }
        if(read_deadline && read_deadline<=next){
            read_deadline=0;read_latch=ram[read_address++];
            if(!(control&16)){
                if(length){--length;half_irq=length<0x8000;}else{half_irq=false;end_irq=true;}
            }
        }
        if(write_deadline && write_deadline<=next){
            write_deadline=0;ram[write_address++]=write_latch;
            half_irq=length<0x8000;if(!length)end_irq=true;
            if(!(control&16))length=(length+1)&0x1FFFF;
        }
        if((dma&3) && dma_deadline && dma_deadline<=next){
            dma_deadline=0;
            if(write_deadline)dma_deadline=after(next,1);
            else if(cd){
                write_deadline=after(next,slot_delay(next,false));
                write_latch=cd->transport_read(8);++dma_bytes;
                if(!data_ready(cd))dma&=static_cast<std::uint8_t>(~1);
            }else throw Fault("ADPCM DMA source detached during transfer");
        }
    }
}
} // namespace pce
