// Authored observations exercise direct capture emission; never retail code.
#include "pce/runtime.hpp"
#include "capture_fixture.hpp"
#include <iostream>
#include <limits>
#include <string>

static void state(const pce::Cpu& s) {
    std::cout << "{\"pc\":" << s.pc << ",\"a\":" << unsigned(s.a) << ",\"x\":" << unsigned(s.x)
              << ",\"y\":" << unsigned(s.y) << ",\"sp\":" << unsigned(s.sp) << ",\"p\":" << unsigned(s.p) << ",\"mpr\":[";
    for(unsigned i=0;i<8;++i) std::cout << (i?",":"") << unsigned(s.mpr[i]);
    std::cout << "],\"ticks\":" << s.ticks << ",\"cycles\":" << s.cycles << "}";
}

int main(int argc, char** argv) {
    if(argc!=3) return 2;
    try {
        const auto index=std::stoul(argv[1]); const std::string tier=argv[2];
        if(index>=std::size(capture_plans) || (tier!="native" && tier!="interpreter" && tier!="guards")) return 2;
        const auto& p=capture_plans[index];
        pce::Bus bus; bus.kind[0xF8]=pce::BankKind::ram;
        for(unsigned bank=0;bank<8;++bank) bus.kind[bank]=pce::BankKind::rom;
        for(unsigned i=0;i<capture_rom.size();++i) (*bus.bytes)[i]=capture_rom[i];
        for(unsigned i=0;i<8192;++i) (*bus.bytes)[0x1F0000+i]=p.ram[i];
        pce::Cpu s;s.pc=p.pc;s.a=p.a;s.x=p.x;s.y=p.y;s.sp=p.sp;s.p=p.p;s.mpr=p.mpr;s.clock_divisor=p.divisor;s.mpr_latch=p.latch;
        if(tier=="guards") {
            // Pure misses cannot mutate registers, counters, ticks, latch, RAM,
            // source generations or any other CPU/bus storage.
            unsigned checks=0;
            auto miss=[&]() {
                const auto before=s;const auto bytes=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus.bytes);const auto generations=bus.generation;
                const auto result=pce::generated_step(bus,s,std::numeric_limits<std::uint64_t>::max());
                if(result!=pce::Exit::miss || s.pc!=before.pc || s.a!=before.a || s.x!=before.x || s.y!=before.y || s.sp!=before.sp || s.p!=before.p || s.mpr!=before.mpr || s.mpr_latch!=before.mpr_latch || s.ticks!=before.ticks || s.cycles!=before.cycles || s.clock_divisor!=before.clock_divisor || s.native_steps || s.interpreter_steps || s.guard_misses || *bus.bytes!=*bytes || bus.generation!=generations) throw std::runtime_error("guard mutated state or accepted unknown source");
                ++checks;
            };
            for(unsigned i=0;i<3;++i) {
                const auto logical=static_cast<std::uint16_t>(s.pc+i);
                const auto address=(unsigned(s.mpr[logical>>13])<<13)|(logical&8191);
                const auto old=(*bus.bytes)[address];(*bus.bytes)[address]=0x02;
                // Only actual instruction bytes invalidate. LDA/ADC/TAM/TMA
                // have two; one-byte stack instructions have one.
                if(i<(p.pc==0x2800 && (p.ram[0x800]==0x48 || p.ram[0x800]==0x40)?1u:2u)) miss();
                (*bus.bytes)[address]=old;
            }
            s.pc=0x2500;miss();s.pc=p.pc;s.mpr[6]^=0x80;miss();
            std::cout << "{\"guard_checks\":" << checks << "}\n";return 0;
        }
        std::cout << "{\"states\":[";
        for(unsigned step=0;step<2;++step) {
            if(step) {s.pc=0x2600;std::cout << ',';}
            const auto result=tier=="native"?pce::generated_step(bus,s,std::numeric_limits<std::uint64_t>::max()):pce::interpret_step(bus,s,std::numeric_limits<std::uint64_t>::max());
            if(result!=pce::Exit::executed) return 3;
            state(s);
        }
        std::cout << "],\"ram\":\"";constexpr char hex[]="0123456789abcdef";
        for(unsigned i=0;i<8192;++i) {const auto v=(*bus.bytes)[0x1F0000+i];std::cout<<hex[v>>4]<<hex[v&15];}
        std::cout << "\",\"mpr_latch\":" << unsigned(s.mpr_latch) << ",\"native_steps\":" << s.native_steps << ",\"interpreter_steps\":" << s.interpreter_steps << "}\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 2;}
}
