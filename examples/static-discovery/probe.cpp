// Authored two-bank known-TAM discovery: real native/reference calls and guards.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include <array>
#include <cstdio>
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
static void write_ram(const std::filesystem::path& output,const std::array<std::uint8_t,8192>& ram) {
#ifdef _WIN32
    auto* stream=_wfopen(output.c_str(),L"wbx");
#else
    auto* stream=std::fopen(output.c_str(),"wbx");
#endif
    require(stream!=nullptr,"RAM output must be new");
    const auto written=std::fwrite(ram.data(),1,ram.size(),stream);
    const auto closed=std::fclose(stream);
    require(written==ram.size() && closed==0,"RAM output write failed");
}

int main(int argc,char** argv) {
 try {
    require(argc==5,"usage: static-probe card native|reference|guard new-capture new-ram");
    const std::string mode=argv[2];
    const bool reference=mode=="reference",guard=mode=="guard";
    require(reference || guard || mode=="native","unknown probe mode");
    std::ifstream input(path(argv[1]),std::ios::binary);
    std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(input)),{});
    require(image.size()==16384,"authored two-bank image size");
    if(guard)image[0x2141]=43; // In-process negative; original source file is unchanged.
    auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
    bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);
    auto capture=std::make_unique<pce::CodeCapture>(path(argv[3]),64);
    auto retire=[&] {
        const auto pending=capture->before(*bus,cpu);
        const auto result=reference ? pce::interpret_step(*bus,cpu,100000)
                                    :pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only);
        require(result==pce::Exit::executed,"instruction did not retire");
        capture->after(pending,cpu);
    };
    for(unsigned index=0;index<100;++index)retire();
    const std::array<std::uint8_t,8> mapping{0,248,0,0,0,0,0,1};
    require(cpu.pc==0xE10F && cpu.a==0 && cpu.x==255 && cpu.y==0 && cpu.sp==255 && cpu.p==6 && cpu.mpr==mapping,
            "literal known-TAM prefix registers/mapping");
    require(cpu.clock_divisor==3 && cpu.cycles==440 && cpu.ticks==1464 && cpu.guard_misses==0 &&
            cpu.native_steps==(reference?0U:100U) && cpu.interpreter_steps==(reference?100U:0U),
            "literal prefix clocks/tiers");
    for(unsigned index=0;index<8192;++index)require(bus->peek(0x1F0000+index)==0,"initial whole WRAM");
    const auto ticks_before=cpu.ticks,cycles_before=cpu.cycles;
    bus->write(cpu,0x2000,1); // Explicit developer assistance, no guest instruction.
    require(cpu.ticks==ticks_before && cpu.cycles==cycles_before &&
            cpu.native_steps+cpu.interpreter_steps==100,"host trigger changed guest work");
    for(unsigned index=0;index<(guard?4U:10U);++index)retire();
    std::array<std::uint8_t,8192> expected{};
    expected[0x1FE]=0x13;expected[0x1FF]=0xE1; // JSR saved return $E113.
    if(guard) {
        require(cpu.pc==0xE140 && cpu.a==1 && cpu.sp==253 && cpu.p==4 && cpu.native_steps==104 &&
                cpu.interpreter_steps==0 && cpu.cycles==458 && cpu.ticks==1518,"literal guard boundary");
        const auto ticks=cpu.ticks,cycles=cpu.cycles,retired=cpu.native_steps;
        require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,
                "changed discovered operand accepted");
        require(cpu.pc==0xE140 && cpu.ticks==ticks && cpu.cycles==cycles && cpu.native_steps==retired &&
                cpu.interpreter_steps==0 && cpu.guard_misses==1,"guard miss changed retired state");
        expected[0]=1;
    } else {
        require(cpu.pc==0xE10F && cpu.a==0 && cpu.x==255 && cpu.y==0 && cpu.sp==255 && cpu.p==6 && cpu.mpr==mapping,
                "literal called routine endpoint");
        require(cpu.cycles==486 && cpu.ticks==1602 && cpu.guard_misses==0 &&
                cpu.native_steps==(reference?0U:110U) && cpu.interpreter_steps==(reference?110U:0U),
                "literal suffix clocks/tiers");
        expected[1]=42;
    }
    std::array<std::uint8_t,8192> actual{};
    for(unsigned index=0;index<actual.size();++index) {
        const auto value=bus->peek(0x1F0000+index);require(value.has_value(),"WRAM peek refused");
        actual[index]=*value;require(actual[index]==expected[index],"literal final whole WRAM");
    }
    capture->finish();write_ram(path(argv[4]),actual);
    std::cout<<"{\"passed\":true,\"mode\":\""<<mode<<"\",\"native\":"<<cpu.native_steps
             <<",\"interpreted\":"<<cpu.interpreter_steps<<",\"guards\":"<<cpu.guard_misses
             <<",\"cycles\":"<<cpu.cycles<<",\"ticks\":"<<cpu.ticks<<",\"wram_bytes_checked\":8192}\n";
 }catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
