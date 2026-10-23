// Authored one-instruction inputs for the independent block-transfer oracle.
#include "pce/runtime.hpp"
#include "block_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <string>

int main(int argc, char** argv) {
    if(argc!=3 || (std::string(argv[2])!="native" && std::string(argv[2])!="interpreter")) return 2;
    try {
        std::ifstream input(argv[1]);
        unsigned index,seed,a,x,y,sp,p,divisor,patches;
        if(!(input>>index>>seed>>a>>x>>y>>sp>>p>>divisor>>patches) || index>=block_cases.size()
           || seed>255 || a>255 || x>255 || y>255 || sp>255 || p>255
           || (divisor!=3 && divisor!=12) || patches>32) return 2;
        pce::Bus bus; bus.kind[0xF8]=pce::BankKind::ram;
        for(unsigned i=0;i<8192;++i) (*bus.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
        for(auto [address,value]:block_program) (*bus.bytes)[address]=value;
        for(unsigned i=0;i<patches;++i) {
            unsigned offset,value;
            if(!(input>>offset>>value) || offset>=8192 || value>255) return 2;
            (*bus.bytes)[0x1F0000+offset]=static_cast<std::uint8_t>(value);
        }
        std::string trailing; if(input>>trailing) return 2;
        pce::Cpu s; s.pc=block_cases[index].pc; s.mpr=block_mpr;
        s.a=a; s.x=x; s.y=y; s.sp=sp; s.p=p; s.clock_divisor=divisor;
        auto status=std::string(argv[2])=="native"
            ? pce::generated_step(bus,s,std::numeric_limits<std::uint64_t>::max())
            : pce::interpret_step(bus,s,std::numeric_limits<std::uint64_t>::max());
        if(status!=pce::Exit::executed) return 3;
        std::cout << "{\"cpu\":{\"pc\":" << s.pc << ",\"a\":" << unsigned(s.a)
            << ",\"x\":" << unsigned(s.x) << ",\"y\":" << unsigned(s.y)
            << ",\"sp\":" << unsigned(s.sp) << ",\"p\":" << unsigned(s.p) << ",\"mpr\":[";
        for(unsigned i=0;i<8;++i) std::cout << (i?",":"") << unsigned(s.mpr[i]);
        std::cout << "],\"clock_divisor\":" << s.clock_divisor << ",\"cycles\":" << s.cycles
            << ",\"ticks\":" << s.ticks << "},\"ram\":\"";
        constexpr char hex[]="0123456789abcdef";
        for(unsigned i=0;i<8192;++i) {auto value=(*bus.bytes)[0x1F0000+i]; std::cout << hex[value>>4] << hex[value&15];}
        std::cout << "\",\"native_steps\":" << s.native_steps << ",\"interpreter_steps\":" << s.interpreter_steps << "}\n";
        return 0;
    } catch(const std::exception& error) {std::cerr << error.what() << '\n'; return 2;}
}
