#include "pce/runtime.hpp"
#include "mirror_fixture.hpp"
#include <iostream>
#include <tuple>

namespace {
unsigned checks=0;
void require(bool value,const char* message) {++checks;if(!value) throw pce::Fault(message);}
template<class F> void fault(F f) {bool failed=false;try{f();}catch(const pce::Fault&){failed=true;}require(failed,"expected mirror setup fault");}
void fixture(pce::Bus& bus) {
    bus.enable_work_ram_mirrors();
    for(const auto& [address,byte]:mirror_program) bus.load(address,&byte,1);
}
}
int main() {
    try {
        pce::Bus bus; pce::Cpu cpu;
        require(!bus.peek(0x1F2000),"sandbox aliases unexpectedly enabled");
        bus.enable_work_ram_mirrors();
        for(unsigned source=0xF8;source<=0xFB;++source) {
            cpu.mpr[2]=static_cast<std::uint8_t>(source);
            for(unsigned offset=0;offset<8192;++offset) {
                const auto value=static_cast<std::uint8_t>(offset*37+source);
                const auto before=bus.generation;
                const bool changed=*bus.peek(0x1F0000+offset)!=value;
                bus.write(cpu,static_cast<std::uint16_t>(0x4000+offset),value);
                for(unsigned alias=0xF8;alias<=0xFB;++alias) {
                    cpu.mpr[3]=static_cast<std::uint8_t>(alias);
                    require(bus.read(cpu,static_cast<std::uint16_t>(0x6000+offset))==value,"guest WRAM alias is independent");
                    require(bus.peek((alias<<13)+offset)==value,"source peek missed alias write");
                    require(bus.generation[alias]==before[alias]+changed,"alias generation was not coherent");
                }
                require(bus.generation[0xF7]==before[0xF7] && bus.generation[0xFC]==before[0xFC],"mirror touched neighboring bank");
            }
        }
        const std::uint8_t wrapped[]{0x12,0x34,0x56};
        bus.load(0x1F3FFF,wrapped,3);
        require(bus.peek(0x1F1FFF)==0x12 && bus.peek(0x1F0000)==0x34 && bus.peek(0x1F6001)==0x56,"loader did not wrap alias boundary");
        const auto before=bus.generation;
        bus.load(0x1F0000,nullptr,0);
        require(bus.generation==before,"empty loader changed generations");
        bus.enable_work_ram_mirrors();
        require(bus.generation==before,"idempotent profile setup changed generations");
        pce::Bus occupied;
        occupied.kind[0xFA]=pce::BankKind::ram;
        fault([&]{occupied.enable_work_ram_mirrors();});
        require(!occupied.work_ram_mirrors && occupied.kind[0xF8]==pce::BankKind::unmapped,"failed setup partially configured banks");
        pce::Bus loaded;
        loaded.load(0x1F2000,wrapped,3);
        fault([&]{loaded.enable_work_ram_mirrors();});
        for(bool native:{false,true}) {
            pce::Bus target;fixture(target);pce::Cpu s;s.mpr=mirror_mpr;s.pc=0x4800;
            const auto step=[&]{return native ? pce::generated_step(target,s,100000):pce::interpret_step(target,s,100000);};
            require(step()==pce::Exit::executed && s.a==0x42,"alias source did not execute");
            s.pc=0x4810;require(step()==pce::Exit::executed && target.peek(0x1F6000)==0x42,"alias store failed");
            s.pc=0x4820;s.a=0;require(step()==pce::Exit::executed && s.a==0x42,"alias load failed");
            s.pc=0x4830;require(step()==pce::Exit::executed && target.peek(0x1F2000)==0x43,"alias RMW failed");
            s.pc=0x4840;require(step()==pce::Exit::executed && target.peek(0x1F0001)==0x43 && target.peek(0x1F0002)==0x43,"overlapping aliased block copy failed");
        }
        pce::Bus guarded;fixture(guarded);pce::Cpu s;s.mpr=mirror_mpr;s.pc=0x4800;
        s.mpr[3]=0xFB;
        guarded.write(s,0x6801,0x77); // Same operand through a different physical alias.
        s.mpr=mirror_mpr;
        const auto saved=std::tuple{s.pc,s.a,s.p,s.ticks,s.native_steps,guarded.generation};
        require(pce::generated_step(guarded,s,1000)==pce::Exit::miss,"native guard accepted changed aliased operand");
        require(saved==std::tuple{s.pc,s.a,s.p,s.ticks,s.native_steps,guarded.generation},"source miss mutated guest");
        require(pce::interpret_step(guarded,s,1000)==pce::Exit::executed && s.a==0x77,"fallback fetched stale physical alias");
        std::cout<<"WRAM mirrors: "<<checks<<" expectations passed\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
