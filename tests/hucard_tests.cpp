#include "pce/cartridge.hpp"
#include "pce/runtime.hpp"

#include <algorithm>
#include <iostream>
#include <limits>
#include <vector>

namespace {
unsigned checks=0;
void require(bool value,const char* reason) {++checks;if(!value)throw pce::Fault(reason);}
template<class F> void fault(F action) {
    bool failed=false;try{action();}catch(const pce::Fault&){failed=true;}
    require(failed,"expected explicit HuCard refusal");
}
std::vector<unsigned> expected_map(unsigned count) {
    // Assemble independently selected board segments instead of using the
    // production bank formula. The 512 KiB layout is a compatibility choice.
    std::vector<unsigned> result;
    const auto add=[&](unsigned begin,unsigned end,unsigned repeat) {
        while(repeat--)for(unsigned i=begin;i<end;++i)result.push_back(i);
    };
    if(count==48) {add(0,32,2);add(32,48,4);}
    else if(count==64) {add(0,64,1);add(32,64,2);}
    else if(count==96) {add(0,64,1);add(64,96,2);}
    else {
        unsigned current=0;
        while(result.size()<128) {result.push_back(current);if(++current==count)current=0;}
    }
    require(result.size()==128,"authored map must describe every ROM window");
    return result;
}
std::uint8_t pattern(unsigned bank,unsigned offset) {
    return static_cast<std::uint8_t>(bank*53+offset*17+(offset>>8));
}
std::vector<std::uint8_t> rom(unsigned banks) {
    std::vector<std::uint8_t> image(banks*8192);
    for(unsigned bank=0;bank<banks;++bank)for(unsigned offset=0;offset<8192;++offset)
        image[bank*8192+offset]=pattern(bank,offset);
    image[0x1FFE]=0x34;image[0x1FFF]=0xE0;
    image[0x34]=0xA9;image[0x35]=0x56; // LDA #$56 at the actual reset entry.
    return image;
}
void decoder() {
    const auto input=rom(1);
    for(auto header:{pce::HuCardHeader::none,pce::HuCardHeader::copier512})
        for(auto encoding:{pce::HuCardEncoding::linear,pce::HuCardEncoding::bit_reversed}) {
            std::vector<std::uint8_t> source(header==pce::HuCardHeader::copier512?512:0,0xA6);
            source.insert(source.end(),input.begin(),input.end());
            const auto before=source;
            const auto decoded=pce::decode_hucard(source,header,encoding);
            require(decoded.header_bytes==source.size()-input.size(),"declared header extent differs");
            require(decoded.bit_reversed==(encoding==pce::HuCardEncoding::bit_reversed),"declared encoding flag differs");
            require(decoded.rom.size()==input.size() && source==before,"decode changed input or padded bytes");
            constexpr unsigned nibble[]={0,8,4,12,2,10,6,14,1,9,5,13,3,11,7,15};
            for(unsigned i=0;i<input.size();++i) {
                const auto value=input[i];
                const auto expected=encoding==pce::HuCardEncoding::linear?value:(nibble[value&15]*16+nibble[value>>4]);
                require(decoded.rom[i]==expected,"decoded byte differs from independent nibble reversal");
            }
        }
    for(std::size_t size:{std::size_t{0},std::size_t{1},std::size_t{511},std::size_t{512},
                         std::size_t{8191},std::size_t{8193},std::size_t{0x100001}}) {
        const std::vector<std::uint8_t> bad(size);
        fault([&]{static_cast<void>(pce::decode_hucard(bad,pce::HuCardHeader::none,pce::HuCardEncoding::linear));});
    }
    const std::vector<std::uint8_t> missing_header(511);
    fault([&]{static_cast<void>(pce::decode_hucard(missing_header,pce::HuCardHeader::copier512,pce::HuCardEncoding::linear));});
    fault([&]{static_cast<void>(pce::decode_hucard(input,static_cast<pce::HuCardHeader>(77),pce::HuCardEncoding::linear));});
    fault([&]{static_cast<void>(pce::decode_hucard(input,pce::HuCardHeader::none,static_cast<pce::HuCardEncoding>(77)));});
}
void mappings() {
    pce::Bus bus;
    for(unsigned count=1;count<=128;++count) {
        const auto image=rom(count);
        const auto expected=expected_map(count);
        const auto actual=pce::hucard_bank_map(image.size());
        bus=pce::Bus{};bus.configure_hucard(image,0x5A);
        require(bus.hucard && !bus.hucard_powered && bus.hucard_rom_bytes==image.size(),"HuCard profile not configured");
        require(bus.system_card==pce::SystemCardProfile::none && !bus.system_card_powered,"HuCard impersonated System Card");
        require(!bus.cd.enabled && !bus.cd.scsi.enabled && !bus.adpcm.enabled,"HuCard enabled phantom CD hardware");
        pce::Cpu cpu;cpu.mpr[2]=0;
        for(unsigned bank=0;bank<128;++bank) {
            require(actual[bank]==expected[bank] && bus.hucard_banks[bank]==expected[bank],"ROM bank layout differs");
            cpu.mpr[2]=static_cast<std::uint8_t>(bank);
            for(unsigned offset:{0u,1u,0x34u,0x1FFEu,0x1FFFu}) {
                const auto wanted=image[expected[bank]*8192+offset];
                const auto physical=(bank<<13)+offset;
                require(bus.peek(physical)==wanted,"pure mapped source peek differs");
                require(bus.read(cpu,static_cast<std::uint16_t>(0x4000+offset))==wanted,"mapped ROM guest read differs");
                require(pce::Bus::physical(cpu,static_cast<std::uint16_t>(0x4000+offset))==physical,
                        "mapped source identity was canonicalized");
                require(bus.backing_address(physical)==expected[bank]*8192+offset,"storage backing differs");
            }
            const auto before=bus.generation;
            bus.write(cpu,0x4000,0xCC);
            require(bus.generation==before && bus.peek(bank<<13)==image[expected[bank]*8192],"ignored ROM write mutated state");
        }
        require((*bus.bytes)[image.size()-1]==image.back(),"decoded initial backing was aliased during setup");
        for(unsigned bank=128;bank<256;++bank) {
            const bool ram=bank>=0xF8 && bank<=0xFB;
            require(bus.kind[bank]==(ram?pce::BankKind::ram:bank==255?pce::BankKind::io:pce::BankKind::unmapped),
                    "base HuCard mapped unsupported RAM/device bank");
            if(bank==255)continue;
            cpu.mpr[2]=static_cast<std::uint8_t>(bank);
            if(ram)require(bus.read(cpu,0x4000)==0x5A,"WRAM seed or alias differs");
            else {
                require(!bus.peek(bank<<13) && bus.read(cpu,0x4000)==255,"absent memory became readable native source/data");
                const auto before=bus.generation;bus.write(cpu,0x4000,0x91);
                require(bus.generation==before,"absent-memory write changed a generation");
            }
        }
    }
}
void aliases() {
    for(unsigned count:{1u,3u,32u,48u,64u,96u,128u}) {
        const auto image=rom(count);
        const auto mapping=expected_map(count);
        pce::Bus bus;bus.configure_hucard(image);
        const auto before=bus.generation;
        // Loader patch crosses a bank boundary; every physical alias whose
        // storage changed receives one generation, not one per patched byte.
        constexpr std::uint8_t patch[]{0xBE,0xEF};
        bus.load(0x7FFFF,patch,2);
        const auto first=mapping[63],second=mapping[64];
        for(unsigned bank=0;bank<128;++bank) {
            const bool changed=mapping[bank]==first || mapping[bank]==second;
            require(bus.generation[bank]==before[bank]+(changed?1:0),"loader ROM generation aliases differ");
            if(mapping[bank]==first)require(bus.peek((bank<<13)+8191)==0xBE,"first cross-bank patch not mirrored");
            if(mapping[bank]==second)require(bus.peek(bank<<13)==0xEF,"second cross-bank patch not mirrored");
        }
        pce::Cpu cpu;cpu.mpr[2]=0xF9;
        const auto generations=bus.generation;bus.write(cpu,0x4123,0x77);
        for(unsigned bank=0xF8;bank<=0xFB;++bank)
            require(bus.peek((bank<<13)+0x123)==0x77 && bus.generation[bank]==generations[bank]+1,"WRAM write alias generation differs");
        const std::uint8_t value=0x99;bus.load(0x1F6123,&value,1);
        for(unsigned bank=0xF8;bank<=0xFB;++bank)require(bus.peek((bank<<13)+0x123)==0x99,"WRAM loader alias differs");
    }
}
void initial_and_devices() {
    const auto image=rom(48);
    pce::Bus bus;bus.configure_hucard(image);bus.enable_video();bus.enable_interrupts();bus.enable_psg();
    bus.enable_joypad(false,false);
    pce::Cpu cpu;cpu.pc=0x1234;cpu.ticks=99;
    bus.power_on_cpu(cpu);
    require(cpu.pc==0xE034 && cpu.a==0 && cpu.x==0 && cpu.y==0 && cpu.sp==0 && cpu.p==4,
            "reset vector/register policy differs");
    require(cpu.mpr==std::array<std::uint8_t,8>{} && cpu.clock_divisor==12 && !cpu.ticks && !cpu.cycles,
            "reset mapping/speed/clock policy differs");
    require(bus.hucard_powered && !bus.system_card_powered && bus.io_latch==255 && bus.vdc.read_buffer==65535,
            "reset profile/initial device state differs");
    require(pce::interpret_step(bus,cpu,std::numeric_limits<std::uint64_t>::max())==pce::Exit::executed &&
            cpu.a==0x56 && cpu.interpreter_steps==1 && cpu.ticks==24,"actual ROM reset instruction failed");
    const auto pc=cpu.pc;
    const auto ticks=cpu.ticks;
    fault([&]{bus.power_on_cpu(cpu);});
    require(cpu.pc==pc && cpu.ticks==ticks,"second power-on changed CPU state");
    cpu.mpr[0]=255;bus.io_latch=0x52;
    for(unsigned offset=0x1800;offset<8192;++offset) {
        require(bus.read(cpu,static_cast<std::uint16_t>(offset))==255,"absent CD/unused I/O pull-ups differ");
        bus.write(cpu,static_cast<std::uint16_t>(offset),0xA7);
        require(bus.io_latch==0x52 && !bus.cd.enabled && !bus.adpcm.enabled,"absent I/O changed latch/device profile");
    }
    require(bus.read(cpu,0x1000)==0xB0,"USA no-CD joypad identification differs");
    bus.enable_joypad(true,false);require(bus.read(cpu,0x1000)==0xF0,"Japan no-CD joypad identification differs");
    require(!bus.cd.enabled && !bus.adpcm.enabled,"input identification enabled CD hardware");
    for(unsigned fill:{0u,0x5Au,0xFFu}) {
        pce::Bus seeded;seeded.configure_hucard(image);seeded.enable_interrupts();
        seeded.irq.mask=7;seeded.irq.timer_pending=true;seeded.irq.external=7;
        pce::Cpu state;state.native_steps=17;state.irq_entries=19;
        seeded.power_on_cpu(state,static_cast<std::uint8_t>(fill),static_cast<std::uint8_t>(255-fill));
        require(state.a==fill && state.x==fill && state.y==fill && state.sp==fill &&
                state.p==((fill&0xC7)|4),"explicit register-seed policy differs");
        for(unsigned mpr=0;mpr<8;++mpr)
            require(state.mpr[mpr]==(mpr==7?0:255-fill),"explicit MPR seed/reset-vector mapping differs");
        require(!state.native_steps && !state.interpreter_steps && !state.irq_entries &&
                seeded.irq.enabled && !seeded.irq.mask && !seeded.irq.external && !seeded.irq.timer_pending,
                "power-on inherited prior CPU/IRQ state");
    }
}
void refusals() {
    const auto image=rom(1);
    for(unsigned dirty=0;dirty<8;++dirty) {
        pce::Bus bus;
        switch(dirty) {
        case 0:bus.kind[0]=pce::BankKind::rom;break;
        case 1:(*bus.bytes)[0x8000]=1;break;
        case 2:bus.generation[254]=1;break;
        case 3:bus.io_latch=1;break;
        case 4:bus.enable_psg();break;
        case 5:bus.enable_interrupts();break;
        case 6:bus.hucard_banks[1]=1;break;
        default:bus.hucard_rom_bytes=8192;break;
        }
        const auto kinds=bus.kind;
        const auto generations=bus.generation;
        fault([&]{bus.configure_hucard(image);});
        require(!bus.hucard && bus.kind==kinds && bus.generation==generations,"invalid setup partially configured bus");
    }
    pce::Bus invalid;const std::uint8_t byte=0;
    fault([&]{invalid.configure_hucard(std::span(&byte,1));});
    require(!invalid.hucard && invalid.kind[0]==pce::BankKind::unmapped,"bad ROM size partially configured bus");
    pce::Bus card;card.configure_hucard(image);
    fault([&]{card.configure_hucard(image);});
    fault([&]{card.enable_cd_control();});
    fault([&]{card.enable_cd_transport();});
    fault([&]{card.enable_adpcm();});
    require(!card.cd.enabled && !card.cd.scsi.enabled && !card.adpcm.enabled,"unsupported CD attachment changed HuCard hardware");
    pce::Bus dirty_clock;dirty_clock.irq.master_ticks=1;
    fault([&]{dirty_clock.configure_hucard(image);});
    require(!dirty_clock.hucard && dirty_clock.kind[0]==pce::BankKind::unmapped,
            "preexisting inactive device clock partially configured HuCard");
    const std::vector<std::uint8_t> system_rom(262144);
    fault([&]{card.configure_system_card(pce::SystemCardProfile::standard,system_rom);});
    pce::Bus system;system.configure_system_card(pce::SystemCardProfile::standard,system_rom);
    fault([&]{system.configure_hucard(image);});
    pce::Bus clocked;clocked.configure_hucard(image);clocked.enable_interrupts();clocked.irq.master_ticks=1;
    pce::Cpu cpu;cpu.pc=0x1234;cpu.ticks=27;
    fault([&]{clocked.power_on_cpu(cpu);});
    require(!clocked.hucard_powered && cpu.pc==0x1234 && cpu.ticks==27,"clock preflight was not atomic");
    pce::Bus vector;vector.configure_hucard(image);vector.kind[0]=pce::BankKind::ram;
    fault([&]{vector.power_on_cpu(cpu);});
    require(!vector.hucard_powered && cpu.pc==0x1234,"bad vector consumed one-shot reset");
    pce::Bus sandbox;cpu.mpr[0]=255;sandbox.kind[255]=pce::BankKind::io;
    fault([&]{static_cast<void>(sandbox.read(cpu,0x1800));});
    fault([&]{sandbox.write(cpu,0x1800,0);});
    cpu.mpr[0]=0;
    fault([&]{static_cast<void>(sandbox.read(cpu,0));});
    fault([&]{sandbox.write(cpu,0,0);});
}
} // namespace
int main() {
    try {decoder();mappings();aliases();initial_and_devices();refusals();
        std::cout<<"HuCard profile: "<<checks<<" authored expectations passed\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
