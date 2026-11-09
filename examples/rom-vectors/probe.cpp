// Authored ROM-vector discovery. Dynamic pointer reads remain in translated code.
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
    require(argc==4,"usage: vector-probe card native|reference|vector-change|source-change new-capture");
    const std::string mode=argv[2];
    const bool reference=mode=="reference",vector_change=mode=="vector-change",source_change=mode=="source-change";
    require(reference || vector_change || source_change || mode=="native","invalid mode");
    std::ifstream stream(path(argv[1]),std::ios::binary);
    std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(stream)),{});
    require(image.size()==8192,"authored card length");
    if(vector_change)image[0x1FF]=0x60; // Original file unchanged; actual pointer now selects uncovered $E160.
    if(source_change)image[0x121]=0x2B; // Original target's translated immediate guard must refuse.
    auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
    bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);
    auto capture=std::make_unique<pce::CodeCapture>(path(argv[3]),32);
    const bool negative=vector_change || source_change;
    for(unsigned i=0;i<(negative?4U:9U);++i) {
        const auto before=capture->before(*bus,cpu);
        require(pce::step(*bus,cpu,10000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)
                ==pce::Exit::executed,"expected retirement refused");
        capture->after(before,cpu);
    }
    require(cpu.mpr==std::array<std::uint8_t,8>{0,248,0,0,0,0,0,0} && cpu.y==0 && cpu.sp==0 &&
            cpu.x==2 && cpu.p==4 && cpu.clock_divisor==12,"literal registers and full mapping");
    if(negative) {
        require(cpu.pc==(vector_change?0xE160:0xE120) && cpu.a==248 && cpu.cycles==16 && cpu.ticks==192 &&
                cpu.native_steps==4 && cpu.interpreter_steps==0 && cpu.guard_misses==0,"literal negative boundary");
        require(pce::step(*bus,cpu,10000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,
                "uncovered vector target or changed target source accepted");
        require(cpu.pc==(vector_change?0xE160:0xE120) && cpu.cycles==16 && cpu.ticks==192 &&
                cpu.native_steps==4 && cpu.interpreter_steps==0 && cpu.guard_misses==1,"miss changed retirement/clocks");
    } else {
        require(cpu.pc==0xE143 && cpu.a==42 && cpu.cycles==39 && cpu.ticks==468 && cpu.guard_misses==0 &&
                cpu.native_steps==(reference?0U:9U) && cpu.interpreter_steps==(reference?9U:0U),"literal endpoint");
    }
    for(unsigned i=0;i<8192;++i) {
        const auto value=bus->peek(0x1F0000+i);
        const unsigned expected=negative?0U:i==0?42U:i==1?2U:0U;
        require(value && *value==expected,"literal full WRAM mismatch");
    }
    capture->finish();
    std::cout<<"{\"passed\":true,\"mode\":\""<<mode<<"\",\"pc\":"<<cpu.pc
             <<",\"native\":"<<cpu.native_steps<<",\"interpreted\":"<<cpu.interpreter_steps
             <<",\"guards\":"<<cpu.guard_misses<<",\"cycles\":"<<cpu.cycles
             <<",\"ticks\":"<<cpu.ticks<<",\"wram_bytes_checked\":8192}\n";
 }catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
