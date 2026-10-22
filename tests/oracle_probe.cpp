// A single-step probe for the optional independently developed emulator.
// Inputs and memory are entirely synthetic. No external CPU code is linked.
#include "pce/runtime.hpp"
#include "fixture.hpp"
#include <iostream>
#include <limits>

int main(int argc, char** argv) {
    if(argc!=9 && argc!=11) return 2;
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
        for(unsigned i=0; i<8192; ++i) (*bus.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
        for(auto [pa,value]:program) (*bus.bytes)[pa]=value;
        if(argc==11) {
            const auto offset=std::stoul(argv[9]), value=std::stoul(argv[10]);
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
