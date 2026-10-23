// Authored adapter for a separate Geargrafx reference executable. It never
// links the toolkit runtime; GPL reference code stays out of toolkit binaries.
#include "geargrafx_core.h"
#include "cdrom.h"
#include "cdrom_audio.h"
#include "cdrom_media.h"
#include "audio.h"
#include "adpcm.h"
#include "huc6280_psg.h"
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

bool g_mcp_stdio_mode=true;
// Public CPU clocks are quantized. This authored member-pointer bridge calls
// the ORIGINAL private scheduler, including its real master clock, at exact
// one-tick boundaries. It does not read/write private data or replace code.
struct CoreClockTag {
    using type=bool (GeargrafxCore::*)(u32);
    friend type clock_member(CoreClockTag);
};
template<class Tag, typename Tag::type Member> struct ClockAccess {
    friend typename Tag::type clock_member(Tag) { return Member; }
};
template struct ClockAccess<CoreClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;

int main(int argc,char** argv) {
    try {
        if(argc!=3)throw std::runtime_error("usage: gear-latch PLAN AUTHORED_CUE");
        std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("cannot open plan");
        std::unique_ptr<GeargrafxCore> core;u64 time=0;bool first=true;
        const auto drain=[&] {
            s16 samples[GG_AUDIO_BUFFER_SIZE];
            core->GetAudio()->GetPSG()->EndFrame(samples);
            core->GetAdpcm()->EndFrame(samples);
            core->GetCDROMAudio()->EndFrame(samples);
        };
        const auto advance=[&](u64 target) {
            if(!core || target<time || target-time>150000000)throw std::runtime_error("invalid finite timestamp");
            while(time<target) {
                (core.get()->*clock_member(CoreClockTag{}))(1);++time;
                if(time%4096==0)drain();
            }
            if(core->GetMasterClockCycles()!=time)throw std::runtime_error("core clock mismatch");
        };
        std::string op;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
                if(!core->GetCDROMMedia()->LoadCueFromFile(argv[2],false))throw std::runtime_error("cannot load authored cue");
                core->GetCDROM()->Reset();core->GetAudio()->Reset(true);time=0;
                if(core->GetMasterClockCycles()!=0)throw std::runtime_error("initial clock mismatch");
            } else if(op=="w") {
                u64 at;unsigned reg,value;if(!(plan>>at>>reg>>value)||reg>15||value>255)throw std::runtime_error("bad write");
                advance(at);core->GetCDROM()->WriteRegister(static_cast<u16>(0x1800+reg),static_cast<u8>(value));
            } else if(op=="a") {
                u64 at;std::string action;if(!(plan>>at>>action))throw std::runtime_error("bad audio action");advance(at);
                if(action=="play")core->GetCDROMAudio()->StartAudio(0,false);
                else if(action=="data") {
                    // Authored drive begins on the selected data track. This
                    // selects the same 150 ms seek profile as the toolkit.
                    core->GetCDROMMedia()->SetCurrentSector(8);
                    core->GetCDROMAudio()->StartAudio(8,false);
                }
                else if(action=="pause")core->GetCDROMAudio()->PauseAudio();
                else if(action=="stop")core->GetCDROMAudio()->StopAudio();
                else if(action=="idle")core->GetCDROMAudio()->SetIdle();
                else if(action=="reset")core->GetCDROM()->Reset();
                else throw std::runtime_error("unknown action");
            } else if(op=="s") {
                u64 at;if(!(plan>>at))throw std::runtime_error("bad sample");advance(at);
                const auto lo=core->GetCDROM()->ReadRegister(0x1805),hi=core->GetCDROM()->ReadRegister(0x1806);
                if(lo!=core->GetCDROM()->ReadRegister(0x1805)||hi!=core->GetCDROM()->ReadRegister(0x1806))throw std::runtime_error("unstable reads");
                const auto before=core->GetCDROM()->ReadRegister(0x1807);
                const auto channel=core->GetCDROM()->ReadRegister(0x1803)&2;
                const auto after=core->GetCDROM()->ReadRegister(0x1807);
                if(!first)std::cout<<',';first=false;
                std::cout<<"{\"time\":"<<time<<",\"lo\":"<<unsigned(lo)<<",\"hi\":"<<unsigned(hi)
                    <<",\"channel\":"<<unsigned(channel)<<",\"bram_before\":"<<unsigned(before)<<",\"bram_after\":"<<unsigned(after)
                    <<",\"left\":"<<core->GetCDROMAudio()->GetLeftSample()<<",\"right\":"<<core->GetCDROMAudio()->GetRightSample()<<'}';
            } else throw std::runtime_error("unknown operation");
        }
        if(!plan.eof())throw std::runtime_error("truncated plan");std::cout<<"]\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
