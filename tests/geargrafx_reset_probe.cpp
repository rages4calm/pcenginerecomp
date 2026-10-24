// Authored adapter for a separate unchanged GPL Geargrafx process.
// Only documented public configuration, loading and state observation are used.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "huc6280_psg.h"
#include "audio.h"
#include "input.h"
#include "media.h"
#include "memory.h"
#include "cdrom.h"
#include "cdrom_audio.h"
#include "scsi_controller.h"
#include "adpcm.h"
#include "reset_probe_support.hpp"
#include <algorithm>
#include <memory>
#include <string>

bool g_mcp_stdio_mode=true;
// Invoke the unchanged core scheduler at the exact cycles requested by its CPU,
// just as RunToVBlank does; no private state is injected or replaced.
struct ResetClockTag {using type=bool(GeargrafxCore::*)(u32);friend type reset_clock(ResetClockTag);};
template<class Tag,typename Tag::type Member>struct ResetClockAccess {
    friend typename Tag::type reset_clock(Tag){return Member;}
};
template struct ResetClockAccess<ResetClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;
static void clock_cpu(void* context,u32 ticks) {
    auto* core=static_cast<GeargrafxCore*>(context);(core->*reset_clock(ResetClockTag{}))(ticks);
}
static std::vector<std::uint64_t> cpu_state(GeargrafxCore& core) {
    auto* s=core.GetHuC6280()->GetState();auto* memory=core.GetMemory();
    std::vector<std::uint64_t> out{ s->PC->GetValue(),s->A->GetValue(),s->X->GetValue(),s->Y->GetValue(),
        s->S->GetValue(),s->P->GetValue(),*s->SPEED?3U:12U,core.GetMasterClockCycles()};
    for(unsigned i=0;i<8;++i)out.push_back(memory->GetMpr(i));
    out.push_back(memory->GetMprTMA(0));
    const auto old=memory->GetMpr(6);memory->SetMpr(6,255);out.push_back(memory->Read(0xC800));memory->SetMpr(6,old);
    out.insert(out.end(),{unsigned(*s->TIMER),*s->TIMER_RELOAD,*s->TIMER_COUNTER,*s->IDR,*s->IRR});
    return out;
}
static std::vector<std::uint64_t> devices(GeargrafxCore& core) {
    auto* vdc=core.GetHuC6270_1();auto* v=vdc->GetState();auto* vce=core.GetHuC6260()->GetState();
    auto* cd=core.GetCDROM()->GetState();auto* scsi=core.GetScsiController()->GetState();
    auto* adpcm=core.GetAdpcm()->GetState();auto* psg=core.GetAudio()->GetPSG()->GetState();
    auto* audio=core.GetCDROMAudio()->GetState();auto* memory=core.GetMemory();
    std::vector<std::uint64_t> out{*v->AR,*v->SR,*v->READ_BUFFER};
    for(unsigned i=0;i<20;++i)out.push_back(v->R[i]);
    out.insert(out.end(),{*vce->CR,*vce->CTA,reset_probe::hash(core.GetHuC6260()->GetColorTable(),512),core.GetInput()->ReadK(),
        *cd->RESET,unsigned(*cd->BRAM_ENABLED),*cd->ACTIVE_IRQS,*cd->ENABLED_IRQS,*cd->FADER,*scsi->DB,*scsi->SIGNALS,
        unsigned(*scsi->PHASE),unsigned(*audio->CURRENT_STATE),*audio->START_LBA,*audio->STOP_LBA,*audio->CURRENT_LBA,*audio->CURRENT_SAMPLE,
        *adpcm->CONTROL,*adpcm->DMA,*adpcm->SAMPLE_RATE,*adpcm->ADDRESS,*adpcm->READ_ADDRESS,*adpcm->WRITE_ADDRESS,*adpcm->LENGTH,
        unsigned(*adpcm->PLAYING),unsigned(*adpcm->END_IRQ),unsigned(*adpcm->HALF_IRQ),*psg->CHANNEL_SELECT,*psg->MAIN_AMPLITUDE,*psg->LFO_FREQUENCY,*psg->LFO_CONTROL});
    for(unsigned i=0;i<6;++i){const auto& c=psg->CHANNELS[i];out.insert(out.end(),{
        c.frequency,c.control,unsigned((c.vol_left<<4)|c.vol_right),c.wave_index,c.noise_control,unsigned(c.dda)&255U,c.noise_seed,
        reset_probe::hash(c.wave_data,32)});}
    out.insert(out.end(),{reset_probe::hash(memory->GetWorkingRAM(),8192),reset_probe::hash(memory->GetCDROMRAM(),65536),
        reset_probe::hash(memory->GetCardRAM(),memory->GetCardRAMSize()),reset_probe::hash(memory->GetBackupRAM(),2048),
        reset_probe::hash(vdc->GetVRAM(),32768),reset_probe::hash(vdc->GetSAT(),256),reset_probe::hash(core.GetAdpcm()->GetRAM(),65536)});
    return out;
}
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: gear-reset PLAN AUTHORED_ROM AUTHORED_CUE");
        std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("cannot open plan");
        const auto base=reset_probe::rom(argv[2]);std::unique_ptr<GeargrafxCore> core;bool first=true;std::string op;
        std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned profile,region,vector,registers,mpr,ram;
                if(!(plan>>profile>>region>>vector>>registers>>mpr>>ram))throw std::runtime_error("truncated reset");
                reset_probe::valid(profile,region,vector,registers,mpr,ram);
                auto rom=base;rom[8190]=vector&255;rom[8191]=vector>>8;
                core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
                core->GetMedia()->SetConsoleType(region?GG_CONSOLE_TG16:GG_CONSOLE_PCE);
                core->GetMedia()->SetCDROMType(profile?GG_CDROM_SUPER_CDROM:GG_CDROM_STANDARD);
                core->GetHuC6280()->SetResetValue(registers);core->GetMemory()->SetResetValues(mpr,ram,ram,0);
                core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);
                core->GetScsiController()->SetResetValue(0);
                if(!core->LoadBiosFromBuffer(rom.data(),int(rom.size()),true) || !core->LoadMedia(argv[3],false))
                    throw std::runtime_error("cannot load authored reset media");
                // Explicit authored BRAM image. Gear's automatic formatting is
                // not treated as hardware reset behavior or shared policy.
                std::fill_n(core->GetMemory()->GetBackupRAM(),2048,0x5A);
                core->GetHuC6280()->SetHardwareClock(clock_cpu,core.get());
            } else {
                if(!core)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"cpu",cpu_state(*core));
                else if(op=="d")reset_probe::record(first,"devices",devices(*core));
                else if(op=="i") {
                    unsigned count;if(!(plan>>count) || count>4096)throw std::runtime_error("invalid instruction count");
                    for(unsigned i=0;i<count;++i){auto* cpu=core->GetHuC6280();const auto cycles=cpu->RunInstruction();
                        const auto clocked=cpu->GetClockedMasterCycles();if(cycles>clocked)clock_cpu(core.get(),cycles-clocked);
                        reset_probe::record(first,"cpu",cpu_state(*core));}
                } else if(op=="q" || op=="p" || op=="w") {
                    unsigned bank,offset,value=0;if(!(plan>>bank>>offset) || bank>254 || offset>8191 || (op=="w" && (!(plan>>value) || value>255)))
                        throw std::runtime_error("invalid finite memory transaction");
                    auto* memory=core->GetMemory();const auto old=memory->GetMpr(6);memory->SetMpr(6,bank);
                    if(op=="w")memory->Write(0xC000+offset,value);
                    else if(op=="q")reset_probe::record(first,"memory",{bank,offset,memory->Read(0xC000+offset)});
                    else {u8 byte=0;if(!memory->TryPeek(0xC000+offset,bank,&byte))throw std::runtime_error("unreadable source peek");reset_probe::record(first,"peek",{bank,offset,byte});}
                    memory->SetMpr(6,old);
                } else if(op=="c") {
                    unsigned port,value;if(!(plan>>port>>value) || port>1023 || value>255)throw std::runtime_error("invalid CD write");
                    core->GetCDROM()->WriteRegister(0x1800+port,value);
                } else if(op=="a") {
                    unsigned port;if(!(plan>>port) || port>1023)throw std::runtime_error("invalid CD read");
                    reset_probe::record(first,"port",{port,core->GetCDROM()->ReadRegister(0x1800+port)});
                } else throw std::runtime_error("unknown reset operation");
            }
        }
        std::cout<<"]\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
