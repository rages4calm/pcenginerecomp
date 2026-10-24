#include "pce/cartridge.hpp"
#include "pce/runtime.hpp"

#include <algorithm>

namespace pce {
std::array<std::uint8_t,128> hucard_bank_map(std::size_t decoded_size) {
    if(!decoded_size || decoded_size>0x100000 || decoded_size%8192)
        throw Fault("Base HuCard requires 8 KiB-aligned ROM data from 8 KiB through 1 MiB");
    const auto banks=static_cast<unsigned>(decoded_size/8192);
    std::array<std::uint8_t,128> result{};
    for(unsigned bank=0;bank<result.size();++bank) {
        unsigned backing=bank%banks;
        if(banks==48) backing=bank<0x40 ? bank&31:0x20+(bank&15);
        else if(banks==64) backing=bank<0x40 ? bank&63:0x20+(bank&31);
        else if(banks==96) backing=bank<0x40 ? bank&63:0x40+(bank&31);
        result[bank]=static_cast<std::uint8_t>(backing);
    }
    return result;
}
HuCardImage decode_hucard(std::span<const std::uint8_t> input,HuCardHeader header,HuCardEncoding encoding) {
    if(header!=HuCardHeader::none && header!=HuCardHeader::copier512)
        throw Fault("Unknown HuCard header interpretation");
    if(encoding!=HuCardEncoding::linear && encoding!=HuCardEncoding::bit_reversed)
        throw Fault("Unknown HuCard byte encoding");
    const unsigned skipped=header==HuCardHeader::copier512 ? 512:0;
    if(input.size()<skipped)throw Fault("HuCard input is shorter than its declared copier header");
    const auto bytes=input.subspan(skipped);
    static_cast<void>(hucard_bank_map(bytes.size()));
    HuCardImage result;
    result.header_bytes=skipped;result.bit_reversed=encoding==HuCardEncoding::bit_reversed;
    result.rom.assign(bytes.begin(),bytes.end());
    if(result.bit_reversed)for(auto& value:result.rom) {
        unsigned reversed=0;
        for(unsigned bit=0;bit<8;++bit)reversed|=((unsigned(value)>>bit)&1)<<(7-bit);
        value=static_cast<std::uint8_t>(reversed);
    }
    return result;
}
void Bus::configure_hucard(std::span<const std::uint8_t> rom,std::uint8_t ram_fill) {
    const auto mapping=hucard_bank_map(rom.size());
    if(hucard || hucard_powered || hucard_rom_bytes ||
       std::any_of(hucard_banks.begin(),hucard_banks.end(),[](auto b){return b!=0;}) ||
       system_card!=SystemCardProfile::none || system_card_powered || work_ram_mirrors ||
       cd.enabled || vdc.enabled || vce.enabled || psg.enabled || adpcm.enabled ||
       pcm.enabled || joypad.enabled || irq.enabled || io_latch ||
       vdc.raster.master_ticks || vdc.raster.frames || irq.master_ticks ||
       cd.scsi.master_ticks || cd.audio.sample_clock_ticks || cd.audio.sample_ticks ||
       psg.clock_ticks || adpcm.master_ticks || pcm.master_ticks ||
       std::any_of(kind.begin(),kind.end(),[](auto k){return k!=BankKind::unmapped;}) ||
       std::any_of(generation.begin(),generation.end(),[](auto g){return g!=0;}) ||
       std::any_of(bytes->begin(),bytes->end(),[](auto b){return b!=0;}))
        throw Fault("HuCard setup requires a pristine bus");
    hucard=true;hucard_banks=mapping;hucard_rom_bytes=static_cast<std::uint32_t>(rom.size());
    for(unsigned bank=0;bank<0x80;++bank) {kind[bank]=BankKind::rom;generation[bank]=1;}
    // This is file-backed canonical ROM storage, not a guest physical load:
    // special cartridge mirrors can alias a lower physical bank elsewhere.
    std::copy(rom.begin(),rom.end(),bytes->begin());
    enable_work_ram_mirrors();
    std::fill_n(bytes->begin()+0x1F0000,8192,ram_fill);
    for(unsigned bank=0xF8;bank<=0xFB;++bank)generation[bank]=1;
    kind[0xFF]=BankKind::io;io_latch=0xFF;
}
} // namespace pce
