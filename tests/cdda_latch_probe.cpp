// Authored media and timed register driver. No retail bytes or state injection.
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
struct AuthoredMedia final:pce::SectorProvider {
    pce::CdToc directory;
    AuthoredMedia() {
        directory.track_count=2;directory.leadout_lba=16;
        directory.tracks[0]={0,0};directory.tracks[1]={8,4};
    }
    const pce::CdToc& toc() const override { return directory; }
    bool audio_playable(std::uint32_t lba) const override { return lba<8; }
    pce::Sector read(std::uint32_t) override { throw pce::Fault("authored data read not required"); }
    pce::AudioSector read_audio(std::uint32_t lba) override {
        if(lba>=8)throw pce::Fault("data audio read");
        constexpr std::int16_t pattern[]={-32768,32767,-1,1,-12345,23456,0,16384};
        pce::AudioSector out{};
        for(unsigned i=0;i<588;++i) {
            const auto frame=lba*588+i;
            out[i*2]=pattern[(frame*3)%8];out[i*2+1]=pattern[(frame*5+1)%8];
        }
        return out;
    }
};
void audio_command(pce::CdControl& cd,unsigned op,unsigned mode,unsigned lba) {
    cd.scsi.command.fill(0);cd.scsi.command[0]=static_cast<std::uint8_t>(op);
    cd.scsi.command[1]=static_cast<std::uint8_t>(mode);
    cd.scsi.command[3]=static_cast<std::uint8_t>(lba>>16);
    cd.scsi.command[4]=static_cast<std::uint8_t>(lba>>8);
    cd.scsi.command[5]=static_cast<std::uint8_t>(lba);
    cd.audio_command();
}
}
int main(int argc,char** argv) {
    try {
        if(argc!=3 || (std::string(argv[2])!="on" && std::string(argv[2])!="off"))
            throw std::runtime_error("usage: pce-latch PLAN on|off");
        const bool output=std::string(argv[2])=="on";
        std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("cannot open plan");
        std::unique_ptr<pce::Bus> bus;pce::Cpu cpu;std::uint64_t time=0;bool first=true;
        const auto advance=[&](std::uint64_t target) {
            if(!bus || target<time || target-time>150000000)throw std::runtime_error("invalid finite timestamp");
            while(time<target) {
                time+=std::min<std::uint64_t>(target-time,4096);cpu.ticks=time;bus->sync(cpu);
                if(output)bus->pcm.drain();
            }
        };
        std::string op;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                bus=std::make_unique<pce::Bus>();cpu=pce::Cpu{};cpu.mpr[0]=255;
                bus->enable_adpcm();bus->cd.set_sector_provider(std::make_shared<AuthoredMedia>());
                if(output)bus->enable_audio_output();time=0;
            } else if(op=="w") {
                std::uint64_t at;unsigned reg,value;if(!(plan>>at>>reg>>value)||reg>15||value>255)throw std::runtime_error("bad write");
                advance(at);bus->write(cpu,static_cast<std::uint16_t>(0x1800+reg),static_cast<std::uint8_t>(value));
            } else if(op=="a") {
                std::uint64_t at;std::string action;if(!(plan>>at>>action))throw std::runtime_error("bad audio action");advance(at);
                if(action=="play")audio_command(bus->cd,0xd8,1,0);
                else if(action=="data") {bus->cd.scsi.current_lba=8;audio_command(bus->cd,0xd8,1,8);}
                else if(action=="pause")audio_command(bus->cd,0xda,0,0);
                else if(action=="stop")audio_command(bus->cd,0xd9,0,0);
                else if(action=="idle")bus->cd.audio.stop(true);
                else throw std::runtime_error("unknown action");
            } else if(op=="s") {
                std::uint64_t at;if(!(plan>>at))throw std::runtime_error("bad sample");advance(at);
                const auto lo=bus->read(cpu,0x1805),hi=bus->read(cpu,0x1806);
                if(lo!=bus->read(cpu,0x1805)||hi!=bus->read(cpu,0x1806))throw std::runtime_error("unstable reads");
                const auto before=bus->read(cpu,0x1807);
                const auto channel=bus->read(cpu,0x1803)&2;
                const auto after=bus->read(cpu,0x1807);
                if(!first)std::cout<<',';first=false;
                std::cout<<"{\"time\":"<<time<<",\"lo\":"<<unsigned(lo)<<",\"hi\":"<<unsigned(hi)
                    <<",\"channel\":"<<unsigned(channel)<<",\"bram_before\":"<<unsigned(before)<<",\"bram_after\":"<<unsigned(after)
                    <<",\"left\":"<<bus->cd.audio.sample_held[0]<<",\"right\":"<<bus->cd.audio.sample_held[1]<<'}';
            } else throw std::runtime_error("unknown operation");
        }
        if(!plan.eof())throw std::runtime_error("truncated plan");std::cout<<"]\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
