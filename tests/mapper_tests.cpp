// Authored boards and literal expectations, no cartridge/game excerpts.
#include "pce/runtime.hpp"
#include "pce/cartridge.hpp"
#include "mapper_fixture.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <tuple>

namespace {
std::uint64_t checks=0;
constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
void require(bool okay,const char* message) {++checks;if(!okay)throw pce::Fault(message);}
template<class F>void refuses(F action) {
    bool failed=false;try{action();}catch(const pce::Fault&){failed=true;}
    require(failed,"mapper operation should refuse explicitly");
}
auto state(const pce::Cpu& s) {return std::tuple{s.pc,s.a,s.x,s.y,s.sp,s.p,s.mpr,s.cycles,s.ticks,
    s.native_steps,s.interpreter_steps,s.native_block_steps,s.interpreter_block_steps,s.block_bytes};}
std::vector<std::uint8_t> image(pce::HuCardProfile profile) {
    const unsigned size=profile==pce::HuCardProfile::sf2 ? 0x280000:0x80000;
    std::vector<std::uint8_t> result(size);
    for(unsigned i=0;i<size;++i)result[i]=static_cast<std::uint8_t>((i/8192)*37+(i%8192)*13+(i>>21)*101);
    result[0x1FFE]=0;result[0x1FFF]=0xE1;
    if(profile==pce::HuCardProfile::sf2)
        for(unsigned block=0;block<4;++block) {
            result[0x80000+block*0x80000]=0xA9;
            result[0x80001+block*0x80000]=static_cast<std::uint8_t>(0x20+block);
            const auto pc=0x80100+block*0x80000;
            result[pc]=0x8D;result[pc+1]=0xF2;result[pc+2]=0x1F;
            result[pc+3]=0xA9;result[pc+4]=static_cast<std::uint8_t>(0x40+block);
        }
    return result;
}
pce::Cpu cpu() {pce::Cpu result;result.mpr=mapper_mpr;result.pc=0xE100;return result;}
void selector(pce::Bus& bus,pce::Cpu& s,unsigned latch) {s.mpr[0]=0;bus.write(s,static_cast<std::uint16_t>(0x1FF0+latch),0xA5);}
void sizes_and_setup() {
    for(auto profile:{pce::HuCardProfile::sf2,pce::HuCardProfile::populous}) {
        const auto rom=image(profile);
        const auto decoded=pce::decode_hucard(rom,pce::HuCardHeader::none,pce::HuCardEncoding::linear,profile);
        require(decoded.rom==rom,"enhanced decoder changed declared linear bytes");
        std::vector<std::uint8_t> headered(512,0xA6);headered.insert(headered.end(),rom.begin(),rom.end());
        require(pce::decode_hucard(headered,pce::HuCardHeader::copier512,pce::HuCardEncoding::linear,profile).rom==rom,
                "enhanced decoder failed explicit copier header");
        auto bus_owner=std::make_unique<pce::Bus>();auto& bus=*bus_owner;bus.configure_hucard(profile,rom,0x5A);
        require(bus.hucard_profile==profile && bus.hucard && bus.hucard_mapper_latch==0,"enhanced board reset differs");
        require(bus.hucard_rom_bytes==rom.size() && !bus.cd.enabled && !bus.adpcm.enabled,"enhanced profile enabled CD");
        require(bus.peek(0x200000)==std::nullopt && bus.bytes->size()==0x200000,"SF2 widened physical guest address space");
        pce::Cpu s;bus.power_on_cpu(s);
        require(s.pc==0xE100 && s.mpr==std::array<std::uint8_t,8>{},"mapper reset did not use fixed bank00 vector");
        refuses([&]{bus.configure_hucard(profile,rom);});
        refuses([&]{bus.enable_cd_control();});
        refuses([&]{bus.enable_adpcm();});
        for(auto bad_size:{0u,8192u,0x7FFFFu,0x80001u,0x100000u,0x27FFFFu,0x280001u}) {
            auto invalid_owner=std::make_unique<pce::Bus>();auto& invalid=*invalid_owner;
            const std::vector<std::uint8_t> bad(bad_size);
            refuses([&]{invalid.configure_hucard(profile,bad);});
            require(!invalid.hucard && invalid.hucard_profile==pce::HuCardProfile::none &&
                    invalid.hucard_mapper_rom.empty() && invalid.generation==std::array<std::uint64_t,256>{},
                    "invalid board size partly configured bus");
        }
        for(unsigned dirty=0;dirty<3;++dirty) {
            auto invalid_owner=std::make_unique<pce::Bus>();auto& invalid=*invalid_owner;
            if(dirty==0)invalid.hucard_profile=pce::HuCardProfile::sf2;
            if(dirty==1)invalid.hucard_mapper_latch=1;
            if(dirty==2)invalid.hucard_mapper_rom.push_back(0xCC);
            refuses([&]{invalid.configure_hucard(profile,rom);});
            require(!invalid.hucard && invalid.generation[0]==0,"dirty mapper setup mutated mapped bus");
            const std::vector<std::uint8_t> firmware(262144);
            refuses([&]{invalid.configure_system_card(pce::SystemCardProfile::super,firmware);});
        }
    }
    refuses([]{pce::validate_hucard_size(0x80000,pce::HuCardProfile::none);});
    refuses([]{pce::validate_hucard_size(0x80000,static_cast<pce::HuCardProfile>(88));});
    auto ordinary_owner=std::make_unique<pce::Bus>();auto& ordinary=*ordinary_owner;
    ordinary.configure_hucard(image(pce::HuCardProfile::populous));
    require(ordinary.hucard_profile==pce::HuCardProfile::base && ordinary.kind[0x40]==pce::BankKind::rom,
            "size guessed an enhanced board");
    refuses([&]{ordinary.select_hucard_bank(0);});
    auto preselected_owner=std::make_unique<pce::Bus>();auto& preselected=*preselected_owner;
    preselected.configure_hucard(pce::HuCardProfile::sf2,image(pce::HuCardProfile::sf2));
    auto before_cpu=cpu();before_cpu.a=0xA6;
    preselected.select_hucard_bank(4); // Same effective window, nonzero raw latch.
    const auto before=state(before_cpu);const auto generations=preselected.generation;
    refuses([&]{preselected.power_on_cpu(before_cpu);});
    require(state(before_cpu)==before && preselected.hucard_mapper_latch==4 &&
            preselected.generation==generations && !preselected.hucard_powered,
            "preselected mapper boot partly reset CPU or mapper state");
    preselected.select_hucard_bank(0);preselected.power_on_cpu(before_cpu);
    require(preselected.hucard_powered && before_cpu.pc==0xE100,"explicitly restored initial mapper could not boot");
}
void sf2_windows() {
    const auto rom=image(pce::HuCardProfile::sf2);
    auto bus_owner=std::make_unique<pce::Bus>();auto& bus=*bus_owner;bus.configure_hucard(pce::HuCardProfile::sf2,rom);
    auto s=cpu();
    for(unsigned latch=0;latch<16;++latch) {
        const auto before=bus.generation;
        const auto previous=bus.hucard_mapper_latch;
        selector(bus,s,latch);
        require(bus.hucard_mapper_latch==latch,"SF2 did not retain four-bit address latch");
        for(unsigned bank=0;bank<256;++bank) {
            const bool changed=(previous%4!=latch%4 && bank>=64 && bank<128);
            require(bus.generation[bank]==before[bank]+unsigned(changed),"SF2 source-generation window differs");
        }
        // Data never participates in latch selection, including every byte value.
        const auto selected=bus.generation;
        for(unsigned value=0;value<256;++value) {
            bus.write(s,static_cast<std::uint16_t>(0x1FF0+latch),static_cast<std::uint8_t>(value));
            require(bus.hucard_mapper_latch==latch && bus.generation==selected,"SF2 selected by data or refreshed same window");
        }
        for(unsigned bank=0;bank<128;++bank) {
            const unsigned file_bank=bank<64 ? bank:bank+(latch%4)*64;
            s.mpr[2]=static_cast<std::uint8_t>(bank);
            for(unsigned offset:{0u,1u,127u,4095u,8191u}) {
                const auto expected=rom[file_bank*8192+offset];
                require(bus.peek(bank*8192+offset)==expected,"SF2 pure source peek selected wrong file window");
                require(bus.read(s,static_cast<std::uint16_t>(0x4000+offset))==expected,"SF2 guest read selected wrong window");
            }
        }
    }
    s.mpr[0]=0;
    for(unsigned offset=0;offset<0x1FF0;++offset) {
        const auto latch=bus.hucard_mapper_latch;
        const auto before=bus.generation;
        bus.write(s,static_cast<std::uint16_t>(offset),static_cast<std::uint8_t>(offset));
        require(bus.hucard_mapper_latch==latch && bus.generation==before,"SF2 decoded outside its sixteen addresses");
    }
    for(unsigned bank=1;bank<128;++bank) {
        s.mpr[0]=static_cast<std::uint8_t>(bank);
        const auto before=bus.generation;const auto latch=bus.hucard_mapper_latch;
        bus.write(s,0x1FF0,0);
        require(bus.hucard_mapper_latch==latch && bus.generation==before,"SF2 latch decoded outside physical bank00");
    }
    // Selection follows the translated physical bank, at every logical page.
    // These are cartridge writes, not I/O-latch accesses or wait-state ports.
    const auto clocks=std::pair{s.cycles,s.ticks};const auto io=bus.io_latch;
    for(unsigned page=0;page<8;++page) {
        s.mpr[page]=0;
        bus.write(s,static_cast<std::uint16_t>(page*8192+0x1FF0+page),0xFF);
        require(bus.hucard_mapper_latch==page,"SF2 mapper ignored full logical-to-physical translation");
    }
    require(std::pair{s.cycles,s.ticks}==clocks && bus.io_latch==io,"mapper write charged I/O waits or changed bus latch");
    selector(bus,s,1);
    const std::uint8_t patch=0xD3;bus.load(0x80031,&patch,1);
    selector(bus,s,2);selector(bus,s,5);
    require(bus.peek(0x80031)==patch && bus.hucard_mapper_rom[0x100031]==patch,"loader patch lost when SF2 window returned");
    const auto before=bus.generation;const std::vector<std::uint8_t> bytes(bus.bytes->begin(),bus.bytes->end());
    const auto old_latch=bus.hucard_mapper_latch;
    bus.generation[0x60]=forever;
    refuses([&]{selector(bus,s,2);});
    require(bus.hucard_mapper_latch==old_latch && std::equal(bus.bytes->begin(),bus.bytes->end(),bytes.begin()),
            "mapper generation overflow changed window or latch");
    for(unsigned bank=0;bank<256;++bank)if(bank!=0x60)
        require(bus.generation[bank]==before[bank],"mapper generation overflow partly advanced generations");
}
void populous_ram() {
    const auto rom=image(pce::HuCardProfile::populous);
    auto bus_owner=std::make_unique<pce::Bus>();auto& bus=*bus_owner;bus.configure_hucard(pce::HuCardProfile::populous,rom,0x5A);
    auto s=cpu();
    for(unsigned bank=0x40;bank<=0x5F;++bank) {
        s.mpr[2]=static_cast<std::uint8_t>(bank);
        require(bus.kind[bank]==pce::BankKind::ram,"Populous cartridge RAM window missing");
        for(unsigned offset:{0u,1u,4095u,8191u}) {
            require(bus.peek(bank*8192+offset)==0x5A,"Populous RAM deterministic initial fill differs");
            require(bus.backing_address(bank*8192+offset)==0x80000+(bank%4)*8192+offset,
                    "Populous RAM is not four pages repeated eight times");
        }
    }
    for(unsigned bank=0x40;bank<=0x5F;++bank)for(unsigned value=0;value<256;++value) {
        s.mpr[2]=static_cast<std::uint8_t>(bank);
        const auto before=bus.generation;
        const auto old=*bus.peek(bank*8192+123);
        bus.write(s,0x407B,static_cast<std::uint8_t>(value));
        for(unsigned alias=0;alias<256;++alias) {
            const bool shared=alias>=0x40 && alias<=0x5F && alias%4==bank%4;
            require(bus.generation[alias]==before[alias]+unsigned(shared && old!=value),"Populous guest-write alias generations differ");
            if(shared)require(bus.peek(alias*8192+123)==value,"Populous guest-write alias did not share storage");
        }
        require(bus.read_block(s,0x407B)==value,"block read bypassed cartridge RAM alias");
    }
    const auto before=bus.generation;
    const std::uint8_t boundary[]{0xCD,0xEF};bus.load(0x87FFF,boundary,2);
    for(unsigned bank=0;bank<256;++bank) {
        const bool touched=bank>=0x40 && bank<=0x5F && (bank%4==0 || bank%4==3);
        require(bus.generation[bank]==before[bank]+unsigned(touched),"Populous loader boundary generation differs");
    }
    for(unsigned alias=0;alias<8;++alias) {
        require(bus.peek((0x43+alias*4)*8192+8191)==0xCD,"Populous loader last-page alias differs");
        require(bus.peek((0x40+alias*4)*8192)==0xEF,"Populous loader wrap alias differs");
    }
    for(unsigned bank=0x60;bank<0x80;++bank)
        require(bus.peek(bank*8192+123)==rom[(bank-0x40)*8192+123],"Populous RAM destroyed upper ROM backing");
    s.mpr[2]=0x5E;bus.write_block(s,0x4000,0xB7);
    require(bus.peek(0x84000)==0xB7,"block write bypassed Populous alias");
}
pce::Exit step(pce::Bus& b,pce::Cpu& s,bool native,std::uint64_t deadline=forever) {
    return native?pce::generated_step(b,s,deadline):pce::interpret_step(b,s,deadline);
}
void execution() {
    for(bool native:{false,true})for(unsigned divisor:{3u,12u}) {
        auto b_owner=std::make_unique<pce::Bus>();auto& b=*b_owner;
        b.configure_hucard(pce::HuCardProfile::sf2,image(pce::HuCardProfile::sf2));
        auto s=cpu();s.clock_divisor=divisor;
        // A store can replace the same ROM window from which it is running.
        // Its already decoded operation retires once; the next instruction is
        // guarded against the newly selected bytes at the same PC/MPR context.
        s.pc=0x4100;
        require(step(b,s,native)==pce::Exit::executed && b.hucard_mapper_latch==2 && s.pc==0x4103,
                "self-window mapper store did not retire once at its decoded length");
        require(step(b,s,native)==pce::Exit::executed && s.a==0x42,
                "next native instruction retained the previous overlay bytes");
        for(unsigned latch=0;latch<16;++latch) {
            const std::uint8_t operation[]{0x8D,static_cast<std::uint8_t>(0xF0+latch),0x1F};
            b.load(0x100,operation,3);s.pc=0xE100;s.a=static_cast<std::uint8_t>(255-latch);
            const auto cycles=s.cycles;
            require(step(b,s,native)==pce::Exit::executed,"translated mapper store did not execute");
            require(b.hucard_mapper_latch==latch && s.cycles==cycles+5 && s.pc==0xE103,"mapper store cycles/PC/latch differ");
            s.pc=0x4000;
            require(step(b,s,native)==pce::Exit::executed && s.a==0x20+latch%4,"translated overlay code not selected");
        }
        const std::uint8_t block[]{0x73,0,0x20,0xF0,0x1F,16,0};b.load(0x200,block,7);
        s.pc=0xE200;
        for(unsigned i=0;i<16;++i)(*b.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*7);
        require(step(b,s,native)==pce::Exit::executed && b.hucard_mapper_latch==15,"block transfer bypassed SF2 latch decode");
        require(s.block_bytes==16 && (native?s.native_block_steps:s.interpreter_block_steps)==1,"mapper block retirement differs");
        s.pc=0x4000;
        const auto old=state(s);const auto generations=b.generation;
        require(step(b,s,native,0)==pce::Exit::budget && state(s)==old && b.generation==generations,"deadline changed mapper or CPU");
        if(native) {
            (*b.bytes)[0x80001]=0x99;
            const auto before=state(s);const auto latch=b.hucard_mapper_latch;
            require(step(b,s,true)==pce::Exit::miss && state(s)==before && b.hucard_mapper_latch==latch && b.generation==generations,
                    "unknown overlay bytes mutated state before native miss");
            (*b.bytes)[0x80001]=0x23;s.mpr[6]^=1;
            const auto wrong_mapping=state(s);
            require(step(b,s,true)==pce::Exit::miss && state(s)==wrong_mapping,"unknown MPR context executed mapper source");
        }
        auto ram_owner=std::make_unique<pce::Bus>();auto& ram=*ram_owner;
        ram.configure_hucard(pce::HuCardProfile::populous,image(pce::HuCardProfile::populous));
        auto r=cpu();r.clock_divisor=divisor;
        const std::uint8_t ram_block[]{0x73,0,0x20,0,0x40,16,0};ram.load(0x200,ram_block,7);
        for(unsigned i=0;i<16;++i)(*ram.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(0xA0+i);
        r.pc=0xE200;
        require(step(ram,r,native)==pce::Exit::executed,"translated Populous block copy did not execute");
        for(unsigned i=0;i<16;++i)for(unsigned alias=0;alias<8;++alias)
            require(ram.peek((0x40+alias*4)*8192+i)==0xA0+i,"translated block payload did not reach all cartridge aliases");
        const std::uint8_t code[]{0xA9,0x71};ram.load(0x80000,code,2);r.pc=0x4000;
        require(step(ram,r,native)==pce::Exit::executed && r.a==0x71,"cartridge RAM code did not execute");
        if(native) {
            r.pc=0x4000;r.mpr[3]=0x44;ram.write(r,0x6001,0x99);r.mpr[3]=0x41;
            const auto before=state(r);const auto generations=ram.generation;
            require(step(ram,r,true)==pce::Exit::miss && state(r)==before && ram.generation==generations,
                    "Populous RAM alias write did not invalidate exact native guard");
        }
    }
}
}
int main() {
    try {sizes_and_setup();sf2_windows();populous_ram();execution();
        std::cout<<"Enhanced HuCard mapper: "<<checks<<" authored expectations passed\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
