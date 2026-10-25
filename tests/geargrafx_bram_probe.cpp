// Authored observation adapter; Gear CPU, memory, BRAM and register bodies are unchanged.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "media.h"
#include "memory.h"
#include "cdrom.h"
#include "scsi_controller.h"
#include "bram_probe_support.hpp"
#include <memory>
bool g_mcp_stdio_mode=true;
template<class T,typename T::type M>struct Access {friend typename T::type member(T){return M;}};
struct Clock{using type=bool(GeargrafxCore::*)(u32);friend type member(Clock);};
struct CdPresent{using type=bool Media::*;friend type member(CdPresent);};
template struct Access<Clock,&GeargrafxCore::ClockHardware<true,false,false>>;
template struct Access<CdPresent,&Media::m_cdrom_hardware_enabled>;
static void clock_cpu(void* context,u32 ticks) {auto* core=static_cast<GeargrafxCore*>(context);(core->*member(Clock{}))(ticks);}
struct Adapter {
    std::unique_ptr<GeargrafxCore> core;const std::vector<std::uint8_t>& rom;unsigned fast=0;
    void reset(unsigned selected) {
        fast=selected;core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
        core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);
        core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);core->GetScsiController()->SetResetValue(0);
        if(!core->LoadHuCardFromBuffer(rom.data(),rom.size(),"authored-bram.pce"))throw std::runtime_error("authored ROM load");
        core->GetMedia()->*member(CdPresent{})=true;core->GetMemory()->EnableBackupRam(true);
        core->GetMemory()->Reset();core->GetCDROM()->Reset();core->GetScsiController()->Reset();
        const auto initial=bram_probe::seed();std::string raw(initial.begin(),initial.end());std::istringstream stream(raw);
        if(!core->GetMemory()->LoadRam(stream,2048))throw std::runtime_error("deterministic authored seed rejected");
        *core->GetHuC6280()->GetState()->SPEED=fast?1:0;
        core->GetHuC6280()->SetHardwareClock(clock_cpu,core.get());
    }
    void instructions(unsigned count) {
        if(!core)throw std::runtime_error("instructions before reset");
        for(unsigned i=0;i<count;++i){auto* c=core->GetHuC6280();const auto ticks=c->RunInstruction(),done=c->GetClockedMasterCycles();if(ticks>done)clock_cpu(core.get(),ticks-done);}
    }
    std::vector<std::uint64_t> cpu()const {if(!core)throw std::runtime_error("state before reset");auto* s=core->GetHuC6280()->GetState();
        std::vector<std::uint64_t> out{s->PC->GetValue(),s->A->GetValue(),s->X->GetValue(),s->Y->GetValue(),s->S->GetValue(),s->P->GetValue(),*s->SPEED?3U:12U,core->GetMasterClockCycles()};
        for(unsigned i=0;i<8;++i)out.push_back(core->GetMemory()->GetMpr(i));return out;}
    std::vector<std::uint64_t> bram()const{return bram_probe::values(core->GetMemory()->GetBackupRAM(),2048);}
    std::vector<std::uint64_t> ram()const{return bram_probe::values(core->GetMemory()->GetWorkingRAM(),16);}
    unsigned gate()const{return *core->GetCDROM()->GetState()->BRAM_ENABLED;}
    void save(const std::filesystem::path& path) {std::ofstream file(path,std::ios::binary);if(!file)throw std::runtime_error("raw export open");core->GetMemory()->SaveRam(file);file.close();if(!file)throw std::runtime_error("raw export failed");}
    void restore(const std::filesystem::path& path) {
        reset(fast);const auto before=cpu();const auto locked=gate();std::ifstream file(path,std::ios::binary);
        if(!file||!core->GetMemory()->LoadRam(file,2048)||before!=cpu()||locked!=gate())throw std::runtime_error("raw restore failed or mutated CPU/gate");
        // Original Gear LoadRam must reject each invalid size/short read atomically.
        const auto bytes=bram();
        for(unsigned size:{2047U,2049U}) {std::istringstream invalid(std::string(size,'x'));if(core->GetMemory()->LoadRam(invalid,size)||bytes!=bram()||before!=cpu()||locked!=gate())throw std::runtime_error("invalid Gear RAM size changed guest");}
        std::istringstream short_file(std::string(2047,'x'));if(core->GetMemory()->LoadRam(short_file,2048)||bytes!=bram()||before!=cpu()||locked!=gate())throw std::runtime_error("short Gear RAM read changed guest");
    }
};
int main(int argc,char** argv) {try {if(argc!=4)throw std::runtime_error("usage: gear-bram PLAN AUTHORED_ROM NEW_EXPORT_PREFIX");const auto rom=reset_probe::rom(argv[2]);Adapter adapter{nullptr,rom};bram_probe::execute(adapter,argv[1],argv[3]);return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
