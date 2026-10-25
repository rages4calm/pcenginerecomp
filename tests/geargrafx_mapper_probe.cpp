// Authored adapter for a separate unchanged GPL Geargrafx core. Configuration,
// loading and observations use public APIs; the compile-time shim below calls
// its original scheduler. No emulator implementation is copied into the toolkit.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "huc6280_psg.h"
#include "audio.h"
#include "input.h"
#include "media.h"
#include "memory.h"
#include "scsi_controller.h"
#include "reset_probe_support.hpp"
#include <algorithm>
#include <memory>
#include <string>

bool g_mcp_stdio_mode=true;
struct HuCardClockTag {using type=bool(GeargrafxCore::*)(u32);friend type hucard_clock(HuCardClockTag);};
template<class Tag,typename Tag::type Member>struct HuCardClockAccess {
    friend typename Tag::type hucard_clock(Tag){return Member;}
};
template struct HuCardClockAccess<HuCardClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;
static void clock_cpu(void* context,u32 ticks) {
    auto* core=static_cast<GeargrafxCore*>(context);(core->*hucard_clock(HuCardClockTag{}))(ticks);
}
static std::vector<u8> read_rom(const char* path) {
    std::ifstream file(path,std::ios::binary);if(!file)throw std::runtime_error("cannot open authored decoded HuCard");
    std::vector<u8> rom((std::istreambuf_iterator<char>(file)),{});
    if(rom.empty() || rom.size()%8192 || rom.size()>0x280000)throw std::runtime_error("authored mapper ROM size");
    return rom;
}
static u8 io_latch(GeargrafxCore& core) {
    auto* memory=core.GetMemory();const auto old=memory->GetMpr(6);memory->SetMpr(6,255);
    const auto value=memory->Read(0xC800);memory->SetMpr(6,old);return value;
}
static std::vector<std::uint64_t> cpu_state(GeargrafxCore& core) {
    auto* s=core.GetHuC6280()->GetState();auto* memory=core.GetMemory();
    std::vector<std::uint64_t> out{s->PC->GetValue(),s->A->GetValue(),s->X->GetValue(),s->Y->GetValue(),
        s->S->GetValue(),s->P->GetValue(),*s->SPEED?3U:12U,core.GetMasterClockCycles()};
    for(unsigned i=0;i<8;++i)out.push_back(memory->GetMpr(i));
    out.insert(out.end(),{memory->GetMprTMA(0),io_latch(core),unsigned(*s->TIMER),*s->TIMER_RELOAD,*s->TIMER_COUNTER,*s->IDR,*s->IRR});
    return out;
}
static std::vector<std::uint64_t> devices(GeargrafxCore& core) {
    auto* chip=core.GetHuC6270_1();auto* v=chip->GetState();auto* vce=core.GetHuC6260()->GetState();
    auto* p=core.GetAudio()->GetPSG()->GetState();
    std::vector<std::uint64_t> out{*v->AR,*v->SR,*v->READ_BUFFER};for(unsigned i=0;i<20;++i)out.push_back(v->R[i]);
    out.insert(out.end(),{*vce->CR,*vce->CTA,reset_probe::hash(core.GetHuC6260()->GetColorTable(),512),core.GetInput()->ReadK(),
        *p->CHANNEL_SELECT,*p->MAIN_AMPLITUDE,*p->LFO_FREQUENCY,*p->LFO_CONTROL});
    for(unsigned i=0;i<6;++i){const auto& c=p->CHANNELS[i];out.insert(out.end(),{
        c.frequency,c.control,unsigned((c.vol_left<<4)|c.vol_right),c.wave_index,c.noise_control,unsigned(c.dda)&255U,c.noise_seed,
        reset_probe::hash(c.wave_data,32)});}
    out.insert(out.end(),{reset_probe::hash(core.GetMemory()->GetWorkingRAM(),8192),
        reset_probe::hash(chip->GetVRAM(),32768),reset_probe::hash(chip->GetSAT(),256)});
    return out;
}
struct CardRamTag {using type=int Media::*;friend type card_ram_member(CardRamTag);};
template<class Tag,typename Tag::type Member>struct CardRamAccess {
    friend typename Tag::type card_ram_member(Tag){return Member;}
};
template struct CardRamAccess<CardRamTag,&Media::m_card_ram_size>;
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: gear-hucard PLAN AUTHORED_DECODED_ROM sf2|populous");
        const std::string profile=argv[3];
        if(profile!="sf2" && profile!="populous")throw std::runtime_error("explicit mapper profile required");
        const auto rom=read_rom(argv[2]);
        if(rom.size()!=(profile=="sf2"?0x280000u:0x80000u))throw std::runtime_error("explicit mapper ROM size");std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("cannot open plan");
        std::unique_ptr<GeargrafxCore> core;bool first=true;std::string op;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned region,registers,mpr,ram;
                if(!(plan>>region>>registers>>mpr>>ram) || region>1 || registers>255 || mpr>255 || ram>255)throw std::runtime_error("invalid authored reset");
                core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
                core->GetMedia()->SetConsoleType(region?GG_CONSOLE_TG16:GG_CONSOLE_PCE);
                core->GetMedia()->SetCDROMType(GG_CDROM_AUTO);core->GetMedia()->ForceBackupRAM(false);
                core->GetHuC6280()->SetResetValue(registers);core->GetMemory()->SetResetValues(mpr,ram,ram,0);
                core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);core->GetScsiController()->SetResetValue(0);
                if(!core->LoadHuCardFromBuffer(rom.data(),static_cast<int>(rom.size()),"authored.pce"))throw std::runtime_error("cannot load authored HuCard");
                // Explicit configuration-only RAM selection after loading. Do not call
                // Core::Reset here: its media re-detection would replace this setting.
                if(profile=="populous") {
                    core->GetMedia()->*card_ram_member(CardRamTag{})=0x8000;
                    core->GetMemory()->Reset();core->GetHuC6280()->Reset();
                }
                if(core->GetMedia()->IsCDROMHardwareEnabled() || core->GetMedia()->IsSGX() || core->GetMemory()->GetCardRAMSize()!=(profile=="populous"?0x8000:0) || core->GetMemory()->IsBackupRamEnabled())
                    throw std::runtime_error("authored mapper fixture unexpectedly selected hardware");
                core->GetHuC6280()->SetHardwareClock(clock_cpu,core.get());
            } else {
                if(!core)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"cpu",cpu_state(*core));
                else if(op=="d")reset_probe::record(first,"devices",devices(*core));
                else if(op=="i") {
                    unsigned count;if(!(plan>>count) || count>4096)throw std::runtime_error("instruction count");
                    for(unsigned i=0;i<count;++i){auto* cpu=core->GetHuC6280();const auto ticks=cpu->RunInstruction();
                        const auto clocked=cpu->GetClockedMasterCycles();if(ticks>clocked)clock_cpu(core.get(),ticks-clocked);
                        reset_probe::record(first,"cpu",cpu_state(*core));}
                } else if(op=="q" || op=="p" || op=="w") {
                    unsigned bank,offset,value=0;
                    if(!(plan>>bank>>offset) || bank>255 || offset>8191 || (op=="w" && (!(plan>>value) || value>255)))throw std::runtime_error("finite memory transaction");
                    auto* memory=core->GetMemory();const auto old=memory->GetMpr(6);memory->SetMpr(6,bank);
                    if(op=="w")memory->Write(static_cast<u16>(0xC000+offset),static_cast<u8>(value));
                    else if(op=="q")reset_probe::record(first,"memory",{bank,offset,memory->Read(static_cast<u16>(0xC000+offset))});
                    else {u8 byte=0;if(!memory->TryPeek(static_cast<u16>(0xC000+offset),static_cast<u8>(bank),&byte))throw std::runtime_error("unreadable source peek");reset_probe::record(first,"peek",{bank,offset,byte});}
                    memory->SetMpr(6,old);
                } else throw std::runtime_error("unknown authored operation");
            }
        }
        std::cout<<"]\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
