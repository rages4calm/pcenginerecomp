// Authored adapter to a separately compiled unchanged Geargrafx core.
// Three explicit media configuration fields select expansion hardware after
// authored media loading. No CRC, emulated operation or register is patched.
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
#include "arcade_card_mapper.h"
#include "reset_probe_support.hpp"
#include <memory>
#include <string>

bool g_mcp_stdio_mode=true;
template<class Tag,typename Tag::type Member>struct AuthoredAccess {
    friend typename Tag::type member(Tag){return Member;}
};
struct Clock {using type=bool(GeargrafxCore::*)(u32);friend type member(Clock);};
struct ArcadeMapperTag {using type=Media::HuCardMapper Media::*;friend type member(ArcadeMapperTag);};
struct Cd {using type=bool Media::*;friend type member(Cd);};
struct CardRam {using type=int Media::*;friend type member(CardRam);};
struct TransferStateTag {using type=u32 HuC6280::*;friend type member(TransferStateTag);};
template struct AuthoredAccess<Clock,&GeargrafxCore::ClockHardware<true,false,false>>;
template struct AuthoredAccess<ArcadeMapperTag,&Media::m_mapper>;
template struct AuthoredAccess<Cd,&Media::m_cdrom_hardware_enabled>;
template struct AuthoredAccess<CardRam,&Media::m_card_ram_size>;
template struct AuthoredAccess<TransferStateTag,&HuC6280::m_transfer_state>;
static void clock_cpu(void* context,u32 ticks) {
    auto* core=static_cast<GeargrafxCore*>(context);(core->*member(Clock{}))(ticks);
}
static std::vector<std::uint64_t> cpu_state(GeargrafxCore& core) {
    auto* s=core.GetHuC6280()->GetState();auto* memory=core.GetMemory();
    std::vector<std::uint64_t> out{s->PC->GetValue(),s->A->GetValue(),s->X->GetValue(),s->Y->GetValue(),
        s->S->GetValue(),s->P->GetValue(),*s->SPEED?3U:12U,core.GetMasterClockCycles()};
    for(unsigned i=0;i<8;++i)out.push_back(memory->GetMpr(i));return out;
}
static std::vector<std::uint64_t> arcade_state(GeargrafxCore& core) {
    auto* a=core.GetMemory()->GetArcadeCardMapper()->GetState();std::vector<std::uint64_t> out;
    for(unsigned i=0;i<4;++i)out.insert(out.end(),{a->PORTS[i].base,a->PORTS[i].offset,a->PORTS[i].increment,a->PORTS[i].control});
    out.insert(out.end(),{*a->REGISTER,*a->SHIFT_AMOUNT,*a->ROTATE_AMOUNT});return out;
}
int main(int argc,char** argv) {
    try {
        if(argc!=3)throw std::runtime_error("usage: gear-arcade PLAN AUTHORED_FIRMWARE");
        const auto rom=reset_probe::rom(argv[2]);std::ifstream plan(argv[1]);
        if(!plan)throw std::runtime_error("plan missing");
        std::unique_ptr<GeargrafxCore> core;bool first=true;std::string op;
        std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned fill;if(!(plan>>fill)||fill>255)throw std::runtime_error("reset fill");
                core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
                core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);
                core->GetMedia()->SetCDROMType(GG_CDROM_AUTO);core->GetMedia()->ForceBackupRAM(false);
                core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,fill,fill,fill);
                core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);
                core->GetScsiController()->SetResetValue(0);
                if(!core->LoadHuCardFromBuffer(rom.data(),rom.size(),"authored-arcade.pce"))throw std::runtime_error("load authored firmware");
                auto* media=core->GetMedia();media->*member(ArcadeMapperTag{})=Media::ARCADE_CARD_MAPPER;
                media->*member(Cd{})=true;media->*member(CardRam{})=0x30000;
                core->GetMemory()->Reset();core->GetHuC6280()->Reset();
                if(!media->IsArcadeCard() || !media->IsCDROMHardwareEnabled() || core->GetMemory()->GetCardRAMSize()!=0x30000)
                    throw std::runtime_error("explicit Arcade Duo configuration differs");
                core->GetHuC6280()->SetHardwareClock(clock_cpu,core.get());
            } else {
                if(!core)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"cpu",cpu_state(*core));
                else if(op=="a")reset_probe::record(first,"arcade",arcade_state(*core));
                else if(op=="f") {
                    core->GetMemory()->SetMpr(7,0x40);
                    core->GetHuC6280()->GetState()->PC->SetValue(0xE000);
                }
                else if(op=="i") {
                    unsigned count;if(!(plan>>count)||count>4096)throw std::runtime_error("instruction bound");
                    for(unsigned i=0;i<count;++i){auto* cpu=core->GetHuC6280();unsigned chunks=0;
                        // Gear exposes transfer start/each byte/end as separate
                        // scheduler calls. Group the unchanged calls into one
                        // whole instruction, without modifying transfer state.
                        do {const auto ticks=cpu->RunInstruction();const auto clocked=cpu->GetClockedMasterCycles();
                            if(ticks>clocked)clock_cpu(core.get(),ticks-clocked);
                            if(++chunks>65538)throw std::runtime_error("bounded whole transfer did not finish");
                        }while(cpu->*member(TransferStateTag{}));
                        reset_probe::record(first,"cpu",cpu_state(*core));}
                } else if(op=="k") {
                    unsigned address;if(!(plan>>address)||address>=0x200000)throw std::runtime_error("RAM offset");
                    reset_probe::record(first,"ram",{address,core->GetMemory()->GetArcadeRAM()[address]});
                } else if(op=="q"||op=="w"||op=="p") {
                    unsigned bank,offset,value=0;if(!(plan>>bank>>offset)||bank>255||offset>8191||
                        (op=="w"&&(!(plan>>value)||value>255)))throw std::runtime_error("memory bound");
                    auto* memory=core->GetMemory();const auto old=memory->GetMpr(6);memory->SetMpr(6,bank);
                    if(op=="w")memory->Write(0xC000+offset,value);
                    else if(op=="q")reset_probe::record(first,"memory",{bank,offset,memory->Read(0xC000+offset)});
                    else {u8 byte;if(!memory->TryPeek(0xC000+offset,bank,&byte))throw std::runtime_error("unreadable ordinary source");
                        reset_probe::record(first,"peek",{bank,offset,byte});}
                    memory->SetMpr(6,old);
                } else throw std::runtime_error("unknown operation");
            }
        }
        std::cout<<"]\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
