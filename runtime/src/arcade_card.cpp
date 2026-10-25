#include "pce/arcade_card.hpp"
#include "pce/runtime.hpp"
#include <algorithm>
#include <bit>
#include <limits>

namespace pce {
namespace {
void checked_port(unsigned port) {
    if(port>=4) throw Fault("Arcade Card port must be in 0..3");
}
void checked_register(std::uint16_t address) {
    if(address<0x1A00 || address>=0x1C00)
        throw Fault("Arcade Card hardware address must be in $1A00..$1BFF");
}
std::uint32_t offset_term(const ArcadePort& port) {
    // Control bit 3 selects the negative 64 KiB offset range unconditionally;
    // it does not sign-extend from offset bit 15.
    return std::uint32_t(port.offset)+((port.control&8) ? 0xFF0000u:0u);
}
}

ArcadeCard::ArcadeCard(std::uint8_t fill)
    :ram(std::make_unique<std::array<std::uint8_t,0x200000>>()) {
    ram->fill(fill);
}
std::uint32_t ArcadeCard::effective_address(unsigned port) const {
    checked_port(port);
    const auto& p=ports[port];
    return (p.base+((p.control&2) ? offset_term(p):0u))&0x1FFFFF;
}
void ArcadeCard::advance(unsigned port) {
    auto& p=ports[port];
    if(!(p.control&1)) return;
    if(p.control&16) p.base=(p.base+p.increment)&0xFFFFFF;
    else p.offset=static_cast<std::uint16_t>(p.offset+p.increment);
}
void ArcadeCard::add_offset(unsigned port) {
    auto& p=ports[port];
    p.base=(p.base+offset_term(p))&0xFFFFFF;
}
std::uint8_t ArcadeCard::read_data(unsigned port) {
    const auto address=effective_address(port);
    ++reads;
    advance(port);
    return (*ram)[address];
}
void ArcadeCard::write_data(unsigned port,std::uint8_t value) {
    const auto address=effective_address(port);
    ++writes;
    advance(port);
    (*ram)[address]=value;
}
std::uint8_t ArcadeCard::read_register(std::uint16_t address) {
    checked_register(address);
    if(address>=0x1B00) {++reads;return 0xFF;}
    if(address<0x1A80) {
        const auto port=(address>>4)&3, index=address&15;
        if(index<2) return read_data(port);
        ++reads;
        const auto& p=ports[port];
        if(index>=2 && index<=4) return static_cast<std::uint8_t>(p.base>>((index-2)*8));
        if(index==5 || index==6) return static_cast<std::uint8_t>(p.offset>>((index-5)*8));
        if(index==7 || index==8) return static_cast<std::uint8_t>(p.increment>>((index-7)*8));
        if(index==9) return p.control;
        return index==10 ? 0:0xFF;
    }
    ++reads;
    if(address<0x1AE0) return 0xFF;
    const auto index=address&31;
    if(index<4) return static_cast<std::uint8_t>(shift_register>>(index*8));
    if(index==4) return shift_amount;
    if(index==5) return rotate_amount;
    if(index==28 || index==29) return 0;
    if(index==30) return 0x10;
    if(index==31) return 0x51;
    return 0xFF;
}
void ArcadeCard::write_register(std::uint16_t address,std::uint8_t value) {
    checked_register(address);
    if(address>=0x1B00) {++writes;return;}
    if(address<0x1A80) {
        const auto port=(address>>4)&3, index=address&15;
        if(index<2) {write_data(port,value);return;}
        ++writes;
        auto& p=ports[port];
        if(index>=2 && index<=4) {
            const auto shift=(index-2)*8;
            p.base=(p.base&~(0xFFu<<shift))|(std::uint32_t(value)<<shift);
        } else if(index==5 || index==6) {
            const auto shift=(index-5)*8;
            p.offset=static_cast<std::uint16_t>((p.offset&~(0xFFu<<shift))|(unsigned(value)<<shift));
            if(((p.control>>5)&3)==index-4) add_offset(port);
        } else if(index==7 || index==8) {
            const auto shift=(index-7)*8;
            p.increment=static_cast<std::uint16_t>((p.increment&~(0xFFu<<shift))|(unsigned(value)<<shift));
        } else if(index==9) p.control=value&127;
        else if(index==10 && ((p.control>>5)&3)==3) add_offset(port);
        return;
    }
    ++writes;
    if(address<0x1AE0) return;
    const auto index=address&31;
    if(index<4) {
        const auto shift=index*8;
        shift_register=(shift_register&~(0xFFu<<shift))|(std::uint32_t(value)<<shift);
    } else if(index==4 || index==5) {
        const auto amount=static_cast<std::uint8_t>(value&15);
        const int distance=amount<8 ? int(amount):int(amount)-16;
        if(index==4) {
            shift_amount=amount;
            if(distance>=0) shift_register<<=distance;
            else shift_register>>=-distance;
        } else {
            rotate_amount=amount;
            shift_register=std::rotl(shift_register,distance);
        }
    }
}

void Bus::configure_arcade_card_duo(std::uint8_t fill) {
    if(system_card!=SystemCardProfile::super || system_card_powered ||
       hucard || hucard_powered || arcade_card)
        throw Fault("Arcade Card Duo requires an unpowered Super System Card bus");
    if(vdc.raster.master_ticks || vdc.raster.frames || irq.master_ticks ||
       cd.scsi.master_ticks || cd.audio.sample_clock_ticks || cd.audio.sample_ticks ||
       psg.clock_ticks || adpcm.master_ticks || pcm.master_ticks)
        throw Fault("Arcade Card Duo setup requires devices at their initial clock phase");
    for(unsigned bank=0x40;bank<=0x43;++bank) {
        if(kind[bank]!=BankKind::rom) throw Fault("Arcade Card Duo requires unoccupied ROM windows $40..$43");
        if(generation[bank]==std::numeric_limits<std::uint64_t>::max())
            throw Fault("Arcade Card window generation overflow");
    }
    auto card=std::make_unique<ArcadeCard>(fill);
    arcade_card=std::move(card);
    for(unsigned bank=0x40;bank<=0x43;++bank) {kind[bank]=BankKind::io;++generation[bank];}
}
} // namespace pce
