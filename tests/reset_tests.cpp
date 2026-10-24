#include "pce/runtime.hpp"
#include <iostream>
#include <tuple>
#include <vector>

namespace {
unsigned checks=0;
void require(bool value,const char* message) {++checks;if(!value) throw pce::Fault(message);}
template<class F> void fault(F action) {
    bool failed=false;try{action();}catch(const pce::Fault&){failed=true;}
    require(failed,"expected setup-only reset fault");
}
std::vector<std::uint8_t> authored_rom() {
    std::vector<std::uint8_t> rom(262144);
    for(unsigned i=0;i<rom.size();++i) rom[i]=static_cast<std::uint8_t>((i>>13)*11+i*37);
    rom[0x1FFE]=0x34;rom[0x1FFF]=0xE0;
    rom[0x34]=0xD4; // CSH: first two cycles remain at reset's low speed.
    return rom;
}
void memory(pce::SystemCardProfile profile,const std::vector<std::uint8_t>& rom) {
    pce::Bus bus;
    bus.configure_system_card(profile,rom,0x5A);
    require(bus.system_card==profile && bus.work_ram_mirrors,"selected machine profile missing");
    pce::Cpu cpu;cpu.mpr[2]=0;
    for(unsigned bank=0;bank<256;++bank) {
        cpu.mpr[2]=static_cast<std::uint8_t>(bank);
        const bool card_ram=profile==pce::SystemCardProfile::super && bank>=0x68 && bank<=0x7F;
        const bool ram=card_ram || (bank>=0x80 && bank<=0x87) || (bank>=0xF8 && bank<=0xFB);
        const bool mapped_rom=bank<0x80 && !card_ram;
        for(unsigned offset=0;offset<8192;++offset) {
            if(mapped_rom) {
                const auto expected=rom[((bank&31)<<13)+offset];
                require(bus.peek((bank<<13)+offset)==expected,"ROM alias source bytes differ");
                require(bus.read(cpu,static_cast<std::uint16_t>(0x4000+offset))==expected,"ROM alias guest read differs");
            } else if(ram) require(bus.peek((bank<<13)+offset)==0x5A,"selected RAM fill differs");
            else require(!bus.peek((bank<<13)+offset),"absent/BRAM/MMIO became native source");
        }
        if(mapped_rom || bus.kind[bank]==pce::BankKind::unmapped) {
            const auto generations=bus.generation;
            const auto before=bus.peek(bank<<13);
            bus.write(cpu,0x4000,0x99);
            require(bus.generation==generations && bus.peek(bank<<13)==before,"ignored write changed memory or generation");
            if(!mapped_rom) require(bus.read(cpu,0x4000)==0xFF,"absent memory failed to return pull-ups");
        }
    }
    require(bus.kind[0x67]==pce::BankKind::rom && bus.kind[0x88]==pce::BankKind::unmapped,
            "System Card boundaries drifted");
    // Loader writes follow canonical storage while dispatch identities retain
    // their mapped physical addresses. Crossing ROM period boundaries works.
    const auto before=bus.generation;
    const std::uint8_t crossing[]{0xBE,0xEF};
    bus.load(0x3FFFF,crossing,2);
    for(unsigned bank=0;bank<0x80;++bank) {
        if(bus.kind[bank]!=pce::BankKind::rom) continue;
        const bool touched=(bank&31)==0 || (bank&31)==31;
        require(bus.generation[bank]==before[bank]+touched,"ROM alias loader generation differs");
        if((bank&31)==0) require(bus.peek(bank<<13)==0xEF,"ROM period start is stale");
        if((bank&31)==31) require(bus.peek((bank<<13)+8191)==0xBE,"ROM period end is stale");
    }
    bus.enable_cd_transport();
    pce::CdToc toc;toc.track_count=1;toc.tracks[0]={0,4};toc.leadout_lba=100;
    bus.cd.set_toc(toc);
    cpu.mpr[2]=0xF7;
    require(bus.read(cpu,0x4000)==0 && bus.read(cpu,0x47FF)==0 && bus.read(cpu,0x4800)==0xFF,
            "blank BRAM was formatted or upper BRAM became storage");
    bus.write(cpu,0x4000,0x76);
    cpu.mpr[2]=0xFF;
    for(unsigned i=0;i<4;++i) {
        constexpr unsigned signature[]{0,0xAA,0x55,3};
        require(bus.read(cpu,static_cast<std::uint16_t>(0x58C0+i))==
                (profile==pce::SystemCardProfile::super ? signature[i]:0xFF),
                "System Card signature differs");
        bus.write(cpu,static_cast<std::uint16_t>(0x58C0+i),0x12);
    }
    fault([&]{bus.write(cpu,0x58C4,0x12);}); // Still an explicitly unimplemented I/O operation.
    bus.enable_video();bus.enable_interrupts();bus.enable_psg();bus.enable_adpcm();
    bus.enable_joypad(false,true);
    bus.joypad.set_pressed(0,1);
    for(unsigned seed=0;seed<256;++seed) {
        pce::Bus seed_bus;
        seed_bus.configure_system_card(profile,rom);
        seed_bus.enable_cd_transport();seed_bus.cd.set_toc(toc);
        seed_bus.enable_video();seed_bus.enable_interrupts();seed_bus.enable_psg();seed_bus.enable_adpcm();
        seed_bus.enable_joypad(false,true);seed_bus.joypad.set_pressed(0,1);
        const std::uint8_t bram=0x76;seed_bus.load(0xF7u<<13,&bram,1);
        auto& bus=seed_bus;
        pce::Cpu cpu;
        const auto generations=bus.generation;
        cpu.ticks=999;cpu.native_steps=9;cpu.interpreter_steps=8;cpu.guard_misses=7;
        cpu.native_block_steps=6;cpu.interpreter_block_steps=5;cpu.block_bytes=4;
        cpu.irq_sampled=7;cpu.irq_vector=0xFFFA;cpu.irq_entries=3;cpu.rti_steps=2;
        bus.irq.mask=7;bus.irq.timer_enabled=true;bus.irq.timer_pending=true;
        bus.irq.timer_reload=99;bus.irq.timer_counter=88;bus.irq.timer_deadline=1234;
        bus.power_on_cpu(cpu,static_cast<std::uint8_t>(seed),static_cast<std::uint8_t>(255-seed));
        require(cpu.pc==0xE034 && cpu.clock_divisor==12,"reset did not fetch actual mapped vector at low speed");
        require(cpu.a==seed && cpu.x==seed && cpu.y==seed && cpu.sp==seed,"explicit register seed lost");
        require(cpu.p==((seed&0xC3)|pce::I),"reset flags differ from independent mask C3/I");
        for(unsigned i=0;i<8;++i) require(cpu.mpr[i]==(i==7 ? 0:255-seed),"reset MPR seed/forced page differs");
        require(cpu.mpr_latch==0 && bus.io_latch==0xFF,"reset latches differ");
        require(cpu.ticks==0 && cpu.cycles==0 && cpu.native_steps==0 && cpu.interpreter_steps==0 &&
                cpu.guard_misses==0 && cpu.native_block_steps==0 && cpu.interpreter_block_steps==0 &&
                cpu.block_bytes==0 && cpu.irq_sampled==0 && cpu.irq_vector==0 && cpu.irq_entries==0 && cpu.rti_steps==0,
                "reset retired an instruction or kept old CPU accounting");
        require(bus.irq.enabled && !bus.irq.timer_enabled && !bus.irq.timer_pending && !bus.irq.mask &&
                !bus.irq.external && !bus.irq.timer_reload && !bus.irq.timer_counter && !bus.irq.timer_deadline,
                "reset did not clear timer/IRQ state");
        require(bus.generation==generations && (*bus.bytes)[0xF7u<<13]==0x76,
                "CPU reset changed RAM provenance or explicit BRAM seed");
        require(bus.cd.toc && bus.cd.toc->leadout_lba==100 && bus.joypad.pads[0].pressed==1 &&
                bus.vdc.read_buffer==0xFFFF,"CPU power-on discarded explicit media/input or reference VDC buffer");
        const auto initial=std::tuple{cpu.pc,cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p,cpu.mpr,bus.io_latch,bus.generation};
        fault([&]{bus.power_on_cpu(cpu,0xA5,0x80);});
        require(initial==std::tuple{cpu.pc,cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p,cpu.mpr,bus.io_latch,bus.generation} &&
                cpu.ticks==0 && bus.system_card_powered,"second zero-clock power-on was not atomic");
    }
    bus.power_on_cpu(cpu,0xFF);
    require(pce::interpret_step(bus,cpu,1000)==pce::Exit::executed && cpu.pc==0xE035 &&
            cpu.clock_divisor==3 && cpu.cycles==3 && cpu.ticks==27 && cpu.interpreter_steps==1,
            "first opcode did not run from vector at reset speed");
    const auto snapshot=std::tuple{cpu.pc,cpu.ticks,cpu.native_steps,cpu.interpreter_steps,bus.io_latch};
    fault([&]{bus.power_on_cpu(cpu);});
    require(snapshot==std::tuple{cpu.pc,cpu.ticks,cpu.native_steps,cpu.interpreter_steps,bus.io_latch},
            "rejected live reset mutated CPU or latches");
}
}
int main() {
    try {
        const auto rom=authored_rom();
        memory(pce::SystemCardProfile::standard,rom);
        memory(pce::SystemCardProfile::super,rom);
        pce::Bus sandbox;pce::Cpu cpu;
        require(cpu.sp==0xFF && cpu.clock_divisor==3 && cpu.mpr[0]==0xFF && sandbox.io_latch==0,
                "legacy sandbox initialization changed");
        fault([&]{sandbox.power_on_cpu(cpu);});
        fault([&]{sandbox.read(cpu,0x4000);});
        sandbox.kind[0x80]=pce::BankKind::rom;
        fault([&]{sandbox.write(cpu,0x4000,0x99);});
        fault([&]{sandbox.configure_system_card(pce::SystemCardProfile::standard,rom);});
        require(sandbox.system_card==pce::SystemCardProfile::none && !sandbox.work_ram_mirrors,
                "rejected occupied setup partially configured machine");
        pce::Bus invalid;
        fault([&]{invalid.configure_system_card(pce::SystemCardProfile::none,rom);});
        fault([&]{invalid.configure_system_card(static_cast<pce::SystemCardProfile>(99),rom);});
        fault([&]{invalid.configure_system_card(pce::SystemCardProfile::super,std::span(rom).first(8192));});
        require(invalid.system_card==pce::SystemCardProfile::none && !invalid.work_ram_mirrors &&
                invalid.kind[0]==pce::BankKind::unmapped && invalid.io_latch==0,"invalid inputs mutated setup");
        const std::uint8_t byte=1;invalid.load(0x1FFFFF,&byte,1);
        fault([&]{invalid.configure_system_card(pce::SystemCardProfile::super,rom);});
        pce::Bus duplicate;duplicate.configure_system_card(pce::SystemCardProfile::super,rom);
        fault([&]{duplicate.configure_system_card(pce::SystemCardProfile::standard,rom);});
        pce::Bus clocked;clocked.configure_system_card(pce::SystemCardProfile::standard,rom);
        const std::array clocks{&clocked.vdc.raster.master_ticks,&clocked.vdc.raster.frames,
            &clocked.irq.master_ticks,&clocked.cd.scsi.master_ticks,&clocked.cd.audio.sample_clock_ticks,
            &clocked.cd.audio.sample_ticks,&clocked.psg.clock_ticks,&clocked.adpcm.master_ticks,&clocked.pcm.master_ticks};
        for(auto* clock:clocks) {
            *clock=1;cpu.pc=0x1234;cpu.ticks=4321;
            fault([&]{clocked.power_on_cpu(cpu);});
            require(cpu.pc==0x1234 && cpu.ticks==4321 && !clocked.system_card_powered,
                    "advanced-device preflight mutated CPU or consumed startup");
            *clock=0;
        }
        clocked.kind[0]=pce::BankKind::ram;
        fault([&]{clocked.power_on_cpu(cpu);});
        require(!clocked.system_card_powered && cpu.pc==0x1234,"bad vector preflight consumed startup");
        clocked.kind[0]=pce::BankKind::rom;
        clocked.power_on_cpu(cpu);
        require(clocked.system_card_powered && cpu.pc==0xE034 && cpu.ticks==0,"valid setup did not recover after rejected preflight");
        std::cout<<"System Card reset: "<<checks<<" expectations passed\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
