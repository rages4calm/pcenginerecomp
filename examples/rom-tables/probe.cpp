// Authored byte-index matrix. Host X presets and resets are not guest work.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <vector>

static void require(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
static std::filesystem::path path(const char* value) {
    return std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(value)));
}
int main(int argc,char** argv) {
 try {
    require(argc==4,"usage: table-probe card native|reference|vector-change|source-change new-capture");
    const std::string mode=argv[2];
    const bool reference=mode=="reference",vector_change=mode=="vector-change",source_change=mode=="source-change";
    require(reference || vector_change || source_change || mode=="native","invalid mode");
    std::ifstream stream(path(argv[1]),std::ios::binary);
    std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(stream)),{});
    require(image.size()==8192,"authored card length");
    if(vector_change)image[0x100]=0x80; // Actual dynamic pointer selects uncovered $E080.
    if(source_change)image[0x41]=0x11; // Target's immediate byte no longer matches.
    pce::CodeCapture capture(path(argv[3]),32);
    const bool negative=vector_change || source_change;
    std::uint64_t native=0,interpreted=0,guards=0;
    constexpr std::array<unsigned,4> targets{0xE040,0x50E0,0xE050,0x40E0};
    for(unsigned x=0;x<(negative?1U:256U);++x) {
        auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
        bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);
        cpu.x=static_cast<std::uint8_t>(x); // Explicit independent matrix precondition.
        for(unsigned i=0;i<(negative?3U:7U);++i) {
            const auto before=capture.before(*bus,cpu);
            require(pce::step(*bus,cpu,10000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)
                    ==pce::Exit::executed,"expected retirement refused");
            capture.after(before,cpu);
        }
        require(cpu.mpr==std::array<std::uint8_t,8>{0,248,0,0,0,0,0,0} && cpu.y==0 && cpu.sp==0 &&
                cpu.x==x && cpu.clock_divisor==12,"literal registers and full mapping");
        if(negative) {
            require(cpu.pc==(vector_change?0xE080:0xE040) && cpu.a==248 && cpu.p==0x84 &&
                    cpu.cycles==14 && cpu.ticks==168 && cpu.native_steps==3 && cpu.interpreter_steps==0,
                    "literal negative boundary");
            const auto generation=bus->generation;
            const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);
            require(pce::step(*bus,cpu,10000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"uncovered/changed target accepted");
            require(cpu.pc==(vector_change?0xE080:0xE040) && cpu.cycles==14 && cpu.ticks==168 &&
                    cpu.native_steps==3 && cpu.interpreter_steps==0 && cpu.guard_misses==1 &&
                    bus->generation==generation && *bus->bytes==*memory,"guard changed guest work or memory");
        } else {
            require(cpu.pc==targets[x%4]+8 && cpu.a==0x10+x%4 && cpu.p==4 &&
                    cpu.cycles==30 && cpu.ticks==360 && cpu.guard_misses==0 &&
                    cpu.native_steps==(reference?0U:7U) && cpu.interpreter_steps==(reference?7U:0U),"literal matrix endpoint");
        }
        for(unsigned i=0;i<8192;++i) {
            const auto value=bus->peek(0x1F0000+i);
            const unsigned expected=negative?0U:i==0?0x10U+x%4:i==1?x:0U;
            require(value && *value==expected,"literal full WRAM mismatch");
        }
        native+=cpu.native_steps;interpreted+=cpu.interpreter_steps;guards+=cpu.guard_misses;
    }
    capture.finish();
    std::cout<<"{\"passed\":true,\"cases\":"<<(negative?1:256)<<",\"native\":"<<native
             <<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
 }catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
