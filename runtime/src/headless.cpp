#include "pce/runtime.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <vector>

static std::uint64_t number(const char* text) {
    std::size_t end=0;
    auto value=std::stoull(text,&end,0);
    if(text[0]=='-' || text[end]!='\0') throw pce::Fault("invalid nonnegative number");
    return value;
}
int main(int argc, char** argv) {
    // Baseline developer sandbox: one contiguous payload, no settings/saves,
    // no GUI, and no implicit BIOS or hardware implementation.
    if(argc!=8 && argc!=10) {
        std::cerr << "usage: pce-headless IMAGE PHYSICAL_LOAD PC MPR_CSV MAX_STEPS MAX_TICKS native|hybrid [--bios RAW_256K_SYSTEM_CARD]\n";
        return 2;
    }
    try {
        if(argc==10 && std::string(argv[8])!="--bios") throw pce::Fault("unknown optional argument; expected --bios");
        const auto load=number(argv[2]), pc=number(argv[3]), max_steps=number(argv[5]), deadline=number(argv[6]);
        if(load>=0x200000 || pc>0xFFFF || !max_steps || max_steps>10000000) throw pce::Fault("load/PC/step limit out of range");
        const std::string tier=argv[7];
        if(tier!="native" && tier!="hybrid") throw pce::Fault("tier must be native or hybrid");
        pce::Cpu s;
        s.pc=static_cast<std::uint16_t>(pc);
        std::stringstream mprs(argv[4]); std::string item; unsigned index=0;
        while(std::getline(mprs,item,',')) {
            auto value=number(item.c_str());
            if(index>=8 || value>255) throw pce::Fault("MPR must have eight bytes");
            s.mpr[index++]=static_cast<std::uint8_t>(value);
        }
        if(index!=8) throw pce::Fault("MPR must have eight bytes");
        std::ifstream stream(argv[1],std::ios::binary|std::ios::ate);
        if(!stream) throw pce::Fault("cannot open input");
        const auto length=stream.tellg();
        if(length<=0 || static_cast<std::uint64_t>(length)>0x200000-load) throw pce::Fault("input exceeds physical address space");
        std::vector<std::uint8_t> payload(static_cast<std::size_t>(length));
        stream.seekg(0); stream.read(reinterpret_cast<char*>(payload.data()),length);
        if(!stream) throw pce::Fault("short input read");
        pce::Bus bus;
        if(argc==10) {
            std::ifstream firmware(argv[9],std::ios::binary|std::ios::ate);
            if(!firmware) throw pce::Fault("cannot open System Card ROM");
            if(firmware.tellg()!=262144) throw pce::Fault("System Card ROM must be a raw 256 KiB image");
            std::vector<std::uint8_t> rom(262144);
            firmware.seekg(0); firmware.read(reinterpret_cast<char*>(rom.data()),static_cast<std::streamsize>(rom.size()));
            if(!firmware) throw pce::Fault("short System Card ROM read");
            for(unsigned bank=0; bank<32; ++bank) bus.kind[bank]=pce::BankKind::rom;
            bus.load(0,rom.data(),rom.size());
        }
        for(unsigned bank=0x80; bank<=0x87; ++bank) bus.kind[bank]=pce::BankKind::ram;
        bus.kind[0xF8]=pce::BankKind::ram; bus.kind[0xFF]=pce::BankKind::io;
        for(std::size_t bank=load>>13; bank<=(load+payload.size()-1)>>13; ++bank) {
            if(bus.kind[bank]!=pce::BankKind::ram) throw pce::Fault("payload must reside in standard CD RAM or work RAM");
        }
        bus.load(static_cast<std::uint32_t>(load),payload.data(),payload.size());
        auto status=pce::Exit::executed;
        std::string diagnostic;
        try {
            for(std::uint64_t i=0; i<max_steps; ++i) {
                status=pce::step(bus,s,deadline,tier=="hybrid");
                if(status!=pce::Exit::executed) break;
            }
        } catch(const pce::Fault& error) { diagnostic=error.what(); }
        std::cout << "{\"scope\":\"headless CPU sandbox, not game boot\",\"stop\":\""
                  << (diagnostic.empty() ? (status==pce::Exit::executed ? "step_limit" : pce::exit_name(status)) : "bus_fault")
                  << "\",\"pc\":" << s.pc << ",\"a\":" << unsigned(s.a) << ",\"x\":" << unsigned(s.x)
                  << ",\"y\":" << unsigned(s.y) << ",\"sp\":" << unsigned(s.sp) << ",\"p\":" << unsigned(s.p)
                  << ",\"ticks\":" << s.ticks << ",\"cycles\":" << s.cycles
                  << ",\"native_steps\":" << s.native_steps << ",\"interpreter_steps\":" << s.interpreter_steps
                  << ",\"guard_misses\":" << s.guard_misses << "}\n";
        if(!diagnostic.empty()) std::cerr << diagnostic << '\n';
        return diagnostic.empty() && (status==pce::Exit::executed || status==pce::Exit::budget) ? 0 : 3;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}
