// Authored CPU dispatch microbenchmark. No retail inputs, device timing,
// rendering, wall-clock pacing or campaign performance claim.
#include "pce/runtime.hpp"
#include "capture_fixture.hpp"
#include <charconv>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string_view>

namespace {
void fold(std::uint64_t& hash, std::uint64_t value) {
    // Defined modulo-2^64 word digest, identical across architectures. This
    // is a workload checksum, not a cryptographic or standard byte FNV hash.
    hash ^= value;
    hash *= 1099511628211ULL;
}
}

int main(int argc, char** argv) {
    try {
        unsigned iterations=100000;
        if(argc>2) throw std::runtime_error("usage: pce-dispatch-benchmark [iterations:1..10000000]");
        if(argc==2) {
            const std::string_view text=argv[1];
            const auto parsed=std::from_chars(text.data(),text.data()+text.size(),iterations);
            if(parsed.ec!=std::errc{} || parsed.ptr!=text.data()+text.size() || !iterations || iterations>10000000)
                throw std::runtime_error("iterations must be in 1..10000000");
        }
        std::uint64_t hash=14695981039346656037ULL, native=0, interpreted=0, ticks=0, cycles=0;
        double seconds=0;
        for(const auto& p:capture_plans) {
            pce::Bus bus; bus.kind[0xF8]=pce::BankKind::ram;
            for(unsigned bank=0;bank<8;++bank) bus.kind[bank]=pce::BankKind::rom;
            for(unsigned i=0;i<capture_rom.size();++i) (*bus.bytes)[i]=capture_rom[i];
            for(unsigned i=0;i<8192;++i) (*bus.bytes)[0x1F0000+i]=p.ram[i];
            const auto started=std::chrono::steady_clock::now();
            for(unsigned iteration=0;iteration<iterations;++iteration) {
                pce::Cpu s;
                s.pc=p.pc;s.a=p.a;s.x=p.x;s.y=p.y;s.sp=p.sp;s.p=p.p;
                s.mpr=p.mpr;s.clock_divisor=p.divisor;s.mpr_latch=p.latch;
                constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
                if(pce::step(bus,s,forever,false)!=pce::Exit::executed)
                    throw std::runtime_error("authored instruction was not executed natively");
                s.pc=0x2600;
                if(pce::step(bus,s,forever,false)!=pce::Exit::executed || s.native_steps!=2 || s.interpreter_steps)
                    throw std::runtime_error("authored TMA was not executed natively");
                native+=s.native_steps;interpreted+=s.interpreter_steps;ticks+=s.ticks;cycles+=s.cycles;
                fold(hash,s.a|(std::uint64_t(s.x)<<8)|(std::uint64_t(s.y)<<16)|
                          (std::uint64_t(s.sp)<<24)|(std::uint64_t(s.p)<<32)|
                          (std::uint64_t(s.pc)<<40));
                fold(hash,s.mpr_latch|(std::uint64_t(s.clock_divisor)<<8));
                std::uint64_t mapping=0;
                for(unsigned i=0;i<8;++i) mapping|=std::uint64_t(s.mpr[i])<<(i*8);
                fold(hash,mapping);fold(hash,s.ticks);fold(hash,s.cycles);
            }
            seconds+=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
            for(unsigned i=0;i<8192;++i) fold(hash,(*bus.bytes)[0x1F0000+i]);
            for(const auto generation:bus.generation) fold(hash,generation);
        }
        std::cout << "{\"semantic\":{\"workload\":\"authored-capture-dispatch-v1\",\"plans\":"
                  << std::size(capture_plans) << ",\"iterations_per_plan\":" << iterations
                  << ",\"native_steps\":" << native << ",\"interpreted_steps\":" << interpreted
                  << ",\"master_ticks\":" << ticks << ",\"cpu_cycles\":" << cycles
                  << ",\"authored_state_ram_digest64\":\"" << std::hex << std::setw(16) << std::setfill('0') << hash
                  << "\"},\"simulation_seconds\":" << std::dec << std::setprecision(12) << seconds << "}\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr << error.what() << '\n';return 2;
    }
}
