// Authored CUE provider observations and actual translated CD READ operations.
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "scsi_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {
void hex(std::span<const std::uint8_t> bytes) {
    constexpr char digits[]="0123456789abcdef";
    for(auto b:bytes)std::cout<<digits[b>>4]<<digits[b&15];
}
unsigned site(unsigned op,unsigned address=0) {
    for(auto c:scsi_cases)if(c.op==op && c.address==address)return c.pc;
    throw pce::Fault("authored operation missing from emitted SCSI fixture");
}
void inspect(const char* image,const char* plan_path) {
    auto provider=pce::open_sector_provider(image);
    std::ifstream plan(plan_path);unsigned count=0;
    if(!(plan>>count) || count>1024)throw pce::Fault("bad bounded CUE plan");
    const auto& toc=provider->toc();
    std::cout<<"{\"leadout\":"<<toc.leadout_lba<<",\"tracks\":[";
    for(unsigned i=0;i<toc.track_count;++i) {
        if(i)std::cout<<',';
        std::cout<<'['<<toc.tracks[i].index1_lba<<','<<unsigned(toc.tracks[i].type)<<']';
    }
    std::cout<<"],\"observations\":[";
    for(unsigned i=0;i<count;++i) {
        char op;std::uint32_t lba;
        if(!(plan>>op>>lba))throw pce::Fault("truncated CUE plan");
        if(i)std::cout<<',';
        std::cout<<"{\"op\":\""<<op<<"\",\"lba\":"<<lba;
        if(op=='p')std::cout<<",\"playable\":"<<(provider->audio_playable(lba)?"true":"false");
        else if(op=='d') {const auto bytes=provider->read(lba);std::cout<<",\"bytes\":\"";hex(bytes);std::cout<<'"';}
        else if(op=='a') {
            const auto samples=provider->read_audio(lba);std::cout<<",\"samples\":[";
            for(unsigned j=0;j<samples.size();++j){if(j)std::cout<<',';std::cout<<samples[j];}std::cout<<']';
        } else throw pce::Fault("unknown CUE plan operation");
        std::cout<<'}';
    }
    std::string extra;if(plan>>extra)throw pce::Fault("trailing CUE plan data");
    std::cout<<"],\"image_sha256\":\""<<toc.image_sha256<<"\"}\n";
}
void stream(const char* image,const std::string& tier,std::uint32_t lba,unsigned count) {
    if((tier!="native" && tier!="interpreter") || !count || count>8)throw pce::Fault("bad bounded stream selection");
    auto provider=pce::open_sector_provider(image);pce::Bus bus;pce::Cpu cpu;
    cpu.mpr=scsi_mpr;bus.kind[0xF8]=pce::BankKind::ram;bus.enable_cd_transport();
    for(const auto& [address,value]:scsi_program)(*bus.bytes)[address]=value;
    bus.cd.set_sector_provider(provider);const bool native=tier=="native";
    const auto execute=[&](unsigned op,unsigned address=0,int value=-1) {
        cpu.pc=static_cast<std::uint16_t>(site(op,address));if(value>=0)cpu.a=static_cast<std::uint8_t>(value);
        auto result=native?pce::generated_step(bus,cpu,UINT64_MAX):pce::interpret_step(bus,cpu,UINT64_MAX);
        if(result!=pce::Exit::executed)throw pce::Fault("CUE translated MMIO operation refused");
    };
    const auto advance=[&](std::uint64_t ticks){cpu.ticks+=ticks;bus.sync(cpu);};
    const auto ack=[&]{execute(0x8D,0x1802,0xE0);execute(0x8D,0x1802,0x60);};
    execute(0x8D,0x1800,0);advance(75000);
    unsigned cdb[]={8,(lba>>16)&31,(lba>>8)&255,lba&255,count,0};
    for(unsigned i=0;i<6;++i){execute(0x8D,0x1801,cdb[i]);ack();if(i<5)advance(3000);}
    std::cout<<"{\"sectors\":[";
    for(unsigned n=0;n<count;++n) {
        const auto due=bus.cd.scsi.load_deadline;
        if(due<cpu.ticks)throw pce::Fault("CUE stream load deadline in past");advance(due-cpu.ticks);
        pce::Sector bytes{};
        for(unsigned i=0;i<bytes.size();++i) {
            execute(0xAD,0x1800);if(cpu.a!=0xC8)throw pce::Fault("CUE stream REQ missing");
            execute(0xAD,0x1801);bytes[i]=cpu.a;ack();
        }
        if(n)std::cout<<',';std::cout<<'"';hex(bytes);std::cout<<'"';
    }
    advance(3000);execute(0xAD,0x1800);const auto status_port=cpu.a;
    execute(0xAD,0x1801);const auto status=cpu.a;ack();advance(1500);
    execute(0xAD,0x1800);const auto message_port=cpu.a;ack();advance(1500);
    execute(0xAD,0x1800);const auto final_port=cpu.a;
    std::cout<<"],\"status_port\":"<<unsigned(status_port)<<",\"status\":"<<unsigned(status)
             <<",\"message_port\":"<<unsigned(message_port)<<",\"final_port\":"<<unsigned(final_port)
             <<",\"native_steps\":"<<cpu.native_steps<<",\"interpreter_steps\":"<<cpu.interpreter_steps
             <<",\"guard_misses\":"<<cpu.guard_misses<<",\"sectors_read\":"<<bus.cd.sectors_read
             <<",\"read_errors\":"<<bus.cd.read_errors<<",\"data_bytes_acked\":"<<bus.cd.data_bytes_acked<<"}\n";
}
}
int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--inspect")inspect(argv[2],argv[3]);
        else if(argc==6 && std::string(argv[1])=="--stream")stream(argv[2],argv[3],std::stoul(argv[4]),std::stoul(argv[5]));
        else throw pce::Fault("usage: cue-probe --inspect IMAGE PLAN | --stream IMAGE native|interpreter LBA COUNT");
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
