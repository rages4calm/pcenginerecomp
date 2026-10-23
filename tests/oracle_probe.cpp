// A single-step probe for the optional independently developed emulator.
// Inputs and memory are entirely synthetic. No external CPU code is linked.
#include "pce/runtime.hpp"
#include "fixture.hpp"
#include <iostream>
#include <limits>
#include <fstream>
#include <vector>

static void print_state(const pce::Cpu& s, bool timing=false) {
    std::cout << "{\"pc\":" << s.pc << ",\"a\":" << unsigned(s.a) << ",\"x\":" << unsigned(s.x)
              << ",\"y\":" << unsigned(s.y) << ",\"sp\":" << unsigned(s.sp) << ",\"p\":" << unsigned(s.p)
              << ",\"mpr\":[";
    for(unsigned i=0; i<8; ++i) std::cout << (i ? "," : "") << unsigned(s.mpr[i]);
    std::cout << "]";
    if(timing) std::cout << ",\"clock_divisor\":" << s.clock_divisor << ",\"ticks\":" << s.ticks << ",\"cycles\":" << s.cycles;
    std::cout << "}";
}

static void print_ram(const pce::Bus& bus) {
    constexpr char hex[]="0123456789abcdef";
    for(unsigned i=0; i<8192; ++i) { auto v=(*bus.bytes)[0x1F0000+i]; std::cout << hex[v>>4] << hex[v&15]; }
}

static int mpr_sequence(const char* path, const std::string& tier, bool speed=false) {
    if(tier!="native" && tier!="interpreter") return 2;
    std::ifstream input(path);
    unsigned a,x,y,sp,p,seed,count,divisor=3;
    if(!(input>>a>>x>>y>>sp>>p>>seed) || a>255 || x>255 || y>255 || sp>255 || p>255 || seed>255) return 2;
    if(speed && (!(input>>divisor) || (divisor!=3 && divisor!=12))) return 2;
    if(!(input>>count) || count<1 || count>16) return 2;
    std::vector<std::pair<unsigned,int>> steps;
    for(unsigned i=0;i<count;++i) {
        unsigned pc; int override_a;
        if(!(input>>pc>>override_a) || pc>65535 || override_a < -1 || override_a>255) return 2;
        steps.emplace_back(pc,override_a);
    }
    std::string trailing;
    if(input>>trailing) return 2;
    pce::Cpu s; s.a=a; s.x=x; s.y=y; s.sp=sp; s.p=p; s.clock_divisor=divisor;
    pce::Bus bus; bus.kind[0xF8]=pce::BankKind::ram;
    for(unsigned i=0;i<8192;++i) (*bus.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
    for(auto [pa,value]:program) (*bus.bytes)[pa]=value;
    std::cout << "{\"states\":[";
    for(unsigned i=0;i<count;++i) {
        s.pc=static_cast<std::uint16_t>(steps[i].first);
        if(steps[i].second>=0) s.a=static_cast<std::uint8_t>(steps[i].second);
        auto status=tier=="native" ? pce::step(bus,s,std::numeric_limits<std::uint64_t>::max(),true)
                                   : pce::interpret_step(bus,s,std::numeric_limits<std::uint64_t>::max());
        if(status!=pce::Exit::executed) return 3;
        if(i) std::cout << ',';
        print_state(s,speed);
    }
    std::cout << "],\"ram\":\""; print_ram(bus);
    std::cout << "\",\"mpr_latch\":" << unsigned(s.mpr_latch) << ",\"native_steps\":" << s.native_steps
              << ",\"interpreter_steps\":" << s.interpreter_steps << ",\"guard_misses\":" << s.guard_misses << "}\n";
    return 0;
}

int main(int argc, char** argv) {
    if(argc==4 && (std::string(argv[1])=="--mpr" || std::string(argv[1])=="--speed")) {
        try { return mpr_sequence(argv[2],argv[3],std::string(argv[1])=="--speed"); }
        catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
    }
    if(argc<9 || (argc-9)%2) return 2;
    try {
        pce::Cpu s;
        s.pc=static_cast<std::uint16_t>(std::stoul(argv[1]));
        s.a=static_cast<std::uint8_t>(std::stoul(argv[2]));
        s.x=static_cast<std::uint8_t>(std::stoul(argv[3]));
        s.y=static_cast<std::uint8_t>(std::stoul(argv[4]));
        s.sp=static_cast<std::uint8_t>(std::stoul(argv[5]));
        s.p=static_cast<std::uint8_t>(std::stoul(argv[6]));
        const auto seed=std::stoul(argv[7]);
        pce::Bus bus; bus.kind[0xF8]=pce::BankKind::ram;
        for(auto [pc,op]:cases) if(pc==s.pc && (op==3 || op==19 || op==35)) bus.enable_vdc();
        for(unsigned i=0; i<8192; ++i) (*bus.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
        for(auto [pa,value]:program) (*bus.bytes)[pa]=value;
        for(int i=9; i<argc; i+=2) {
            const auto offset=std::stoul(argv[i]), value=std::stoul(argv[i+1]);
            if(offset>=8192 || value>255) return 2;
            (*bus.bytes)[0x1F0000+offset]=static_cast<std::uint8_t>(value);
        }
        auto status=std::string(argv[8])=="native" ? pce::generated_step(bus,s,std::numeric_limits<std::uint64_t>::max())
                                                 : pce::interpret_step(bus,s,std::numeric_limits<std::uint64_t>::max());
        if(status!=pce::Exit::executed) return 3;
        std::cout << "{\"pc\":" << s.pc << ",\"a\":" << unsigned(s.a) << ",\"x\":" << unsigned(s.x)
                  << ",\"y\":" << unsigned(s.y) << ",\"sp\":" << unsigned(s.sp) << ",\"p\":" << unsigned(s.p)
                  << ",\"mpr\":[";
        for(unsigned i=0; i<8; ++i) std::cout << (i ? "," : "") << unsigned(s.mpr[i]);
        std::cout << "],\"ram\":\"";
        constexpr char hex[]="0123456789abcdef";
        for(unsigned i=0; i<8192; ++i) { auto v=(*bus.bytes)[0x1F0000+i]; std::cout << hex[v>>4] << hex[v&15]; }
        std::cout << "\"}\n";
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}
