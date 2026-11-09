// Independently authored endpoint and source-guard qualification. No retail data.
#include "pce/runtime.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

namespace {
void require(bool value, const char* message) {
    if(!value) throw std::runtime_error(message);
}
}

int main(int argc,char** argv) {
    try {
        require(argc==3,"usage: native-workflow-probe authored-card normal|guard");
        const std::string mode=argv[2];
        require(mode=="normal" || mode=="guard","unknown probe mode");
        std::ifstream input(argv[1],std::ios::binary);
        std::vector<std::uint8_t> card((std::istreambuf_iterator<char>(input)),{});
        require(card.size()==262144,"authored card size");
        pce::Bus bus; pce::Cpu cpu;
        bus.configure_system_card(pce::SystemCardProfile::standard,card);
        bus.power_on_cpu(cpu);
        const unsigned count=mode=="normal" ? 200:11;
        for(unsigned i=0;i<count;++i)
            require(pce::step(bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::executed,
                    "native instruction did not retire");
        require(cpu.interpreter_steps==0 && cpu.guard_misses==0,"unexpected interpreter/guard activity");
        if(mode=="guard") {
            require(cpu.pc==0x2200 && cpu.native_steps==11,"guard setup endpoint");
            require(bus.peek(0x1F0201)==0x11,"first source operand");
            bus.write(cpu,0x2201,0x7F); // Host-assisted negative: never a promoted source identity.
            const auto ticks=cpu.ticks,cycles=cpu.cycles,native=cpu.native_steps;
            require(pce::step(bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,
                    "uncaptured source variant was accepted");
            require(cpu.pc==0x2200 && cpu.ticks==ticks && cpu.cycles==cycles &&
                    cpu.native_steps==native && cpu.interpreter_steps==0 && cpu.guard_misses==1,
                    "guard refusal changed retired state");
            std::cout<<"{\"passed\":true,\"mode\":\"guard\",\"native_steps\":11,"
                         "\"interpreter_steps\":0,\"guard_misses\":1,\"retired_after_mutation\":0}\n";
            return 0;
        }
        // 27-opcode/159-cycle prefix, then 87 INX and 86 BRA: 677 cycles.
        // 21 slow cycles, CSH's 2 slow+1 fast cycles: 677*3+207=2238 ticks.
        require(cpu.pc==0xE035 && cpu.a==64 && cpu.x==87 && cpu.y==0 && cpu.sp==255 && cpu.p==4,
                "literal CPU endpoint");
        require(cpu.cycles==677 && cpu.ticks==2238 && cpu.native_steps==200 &&
                cpu.native_block_steps==1 && cpu.block_bytes==6,"literal clock/block endpoint");
        require(cpu.mpr==std::array<std::uint8_t,8>{255,248,0,0,0,0,0,64},"full MPR endpoint");
        std::array<std::uint8_t,8192> expected{};
        expected[0x30]=0x2A;expected[0x31]=0x11;expected[0x32]=0x2A;
        expected[0x1FD]=0xFF;expected[0x1FE]=0x27;expected[0x1FF]=0xE0;
        const std::array<std::uint8_t,6> source{0xA9,0x2A,0x8D,0x30,0x20,0x60};
        for(unsigned i=0;i<source.size();++i)expected[0x200+i]=source[i];
        for(unsigned i=0;i<expected.size();++i)
            require(bus.peek(0x1F0000+i)==expected[i],"literal full canonical WRAM differs");
        std::cout<<"{\"passed\":true,\"mode\":\"normal\",\"native_steps\":200,"
                     "\"interpreter_steps\":0,\"guard_misses\":0,\"ram_bytes_checked\":8192,"
                     "\"cycles\":677,\"ticks\":2238}\n";
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
