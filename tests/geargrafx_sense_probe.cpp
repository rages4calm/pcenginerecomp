// Authored adapter: unchanged separate Gear SCSI/CD register implementations.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "media.h"
#include "memory.h"
#include "cdrom.h"
#include "cdrom_media.h"
#include "cdrom_audio.h"
#include "audio.h"
#include "adpcm.h"
#include "huc6280_psg.h"
#include "scsi_controller.h"
#include "sense_probe_support.hpp"
#include <memory>
bool g_mcp_stdio_mode=true;
template<class T,typename T::type M>struct Access {friend typename T::type member(T){return M;}};
struct Clock{using type=bool(GeargrafxCore::*)(u32);friend type member(Clock);};
struct CdPresent{using type=bool Media::*;friend type member(CdPresent);};
template struct Access<Clock,&GeargrafxCore::ClockHardware<true,false,false>>;
template struct Access<CdPresent,&Media::m_cdrom_hardware_enabled>;
struct Adapter {
    std::unique_ptr<GeargrafxCore> core;const std::vector<std::uint8_t>& rom;const char* cue;
    void reset(unsigned mode){if(mode>1)throw std::runtime_error("Gear baseline media mode");core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
        core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);
        core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);core->GetScsiController()->SetResetValue(0);
        if(!core->LoadHuCardFromBuffer(rom.data(),rom.size(),"authored-sense.pce"))throw std::runtime_error("authored ROM load");
        core->GetMedia()->*member(CdPresent{})=true;core->GetMemory()->Reset();
        if(mode&&!core->GetCDROMMedia()->LoadCueFromFile(cue,false))throw std::runtime_error("authored CUE load");
        core->GetCDROM()->Reset();core->GetScsiController()->Reset();}
    void advance(unsigned n){const auto before=core->GetMasterClockCycles();(core.get()->*member(Clock{}))(n);
        if(before/4096!=core->GetMasterClockCycles()/4096){s16 samples[GG_AUDIO_BUFFER_SIZE];core->GetAudio()->GetPSG()->EndFrame(samples);core->GetAdpcm()->EndFrame(samples);core->GetCDROMAudio()->EndFrame(samples);}}
    unsigned signals()const{return *core->GetScsiController()->GetState()->SIGNALS;}
    bool busy()const{return signals()&0x80;}bool request()const{return signals()&0x40;}bool input()const{return signals()&8;}
    bool control()const{return signals()&0x10;}bool message()const{return signals()&0x20;}
    void select(){core->GetCDROM()->WriteRegister(0x1800,0);}
    void write_data(unsigned v){core->GetCDROM()->WriteRegister(0x1801,v);}void ack(bool v){core->GetCDROM()->WriteRegister(0x1802,v?128:0);}
    unsigned read_data(bool automatic){return core->GetCDROM()->ReadRegister(automatic?0x1808:0x1801);}
    void finish_auto_ack(){advance(21);}
    void warm_reset(){core->GetCDROM()->WriteRegister(0x1804,2);advance(1);core->GetCDROM()->WriteRegister(0x1804,0);advance(1);}
};
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: gear-sense PLAN AUTHORED_ROM AUTHORED_CUE");const auto rom=reset_probe::rom(argv[2]);std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("missing plan");
        Adapter a{nullptr,rom,argv[3]};std::string op;bool first=true;std::cout<<'[';
        while(plan>>op){if(op=="r"){unsigned mode;if(!(plan>>mode))throw std::runtime_error("reset mode");a.reset(mode);}
            else if(!a.core)throw std::runtime_error("operation before reset");
            else if(op=="c"){unsigned automatic;const auto cdb=sense_probe::command(plan,automatic);sense_probe::start(a,cdb);sense_probe::record(first,cdb,automatic,sense_probe::drain(a,automatic));}
            else if(op=="z")a.warm_reset();else throw std::runtime_error("unknown operation");}
        std::cout<<"]\n";return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
