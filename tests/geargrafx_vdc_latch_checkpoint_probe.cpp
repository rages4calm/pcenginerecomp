// Direct-device authored fixture around separately linked unchanged GPL Gear.
// Setup mutates only authored initial VRAM/registers; observed phases/latches
// arise from the original positive hardware clocks, never injected state.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "memory.h"
#include "media.h"
#include "scsi_controller.h"
#include "trace_logger.h"
#include "vdc_latch_checkpoint_support.hpp"
#include <iostream>
#include <memory>

bool g_mcp_stdio_mode=true;
namespace {
namespace model=vdc_latch_checkpoint;
template<class Tag,typename Tag::type Pointer>struct Access {friend typename Tag::type member(Tag){return Pointer;}};
#define FIELD(Tag,Type,Name) struct Tag{using type=Type HuC6270::*;friend type member(Tag);};template struct Access<Tag,&HuC6270::Name>;
FIELD(Cr,u16,m_latched_cr)
FIELD(Mwr,u16,m_latched_mwr)
FIELD(Burst,bool,m_burst_mode)
FIELD(ReadPending,bool,m_pending_memory_read)
FIELD(WritePending,bool,m_pending_memory_write)
FIELD(Delay,s32,m_transfer_delay)
FIELD(Carry,u32,m_cpu_vram_cycles)
FIELD(BgStart,s32,m_load_bg_start_clock)
FIELD(BgEnd,s32,m_load_bg_end_clock)
FIELD(Hsync,s32,m_hsync_start_clock)
using Pixels=u16[HUC6270_MAX_BACKGROUND_WIDTH];
FIELD(Indices,Pixels,m_line_buffer)
#undef FIELD
struct Clock{using type=bool(GeargrafxCore::*)(u32);friend type member(Clock);};
template struct Access<Clock,&GeargrafxCore::ClockHardware<false,false,false>>;
void advance(GeargrafxCore& core,std::uint64_t ticks){
    const auto before=core.GetMasterClockCycles();model::require(ticks>=before&&ticks-before<=2000000,"finite positive original device clocks required");
    (core.*member(Clock{}))(static_cast<u32>(ticks-before));model::require(core.GetMasterClockCycles()==ticks,"original scheduler elapsed clock differs");
}
void reg(HuC6270& v,unsigned index,unsigned value){v.WriteRegister(0,u8(index));v.WriteRegister(2,u8(value));v.WriteRegister(3,u8(value>>8));}
std::unique_ptr<GeargrafxCore> configured(const model::Case& c){
    auto core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
    core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core->GetMedia()->SetCDROMType(GG_CDROM_AUTO);core->GetMedia()->ForceBackupRAM(false);
    core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);core->GetHuC6260()->SetResetValue(0);
    core->GetHuC6270_1()->SetSafeDefaults(false);core->GetHuC6270_1()->SetNoSpriteLimit(false);core->GetScsiController()->SetResetValue(0);
    const auto rom=model::rom();model::require(core->LoadHuCardFromBuffer(rom.data(),int(rom.size()),"authored-latches.pce"),"authored HuCard load failed");
    model::require(!core->GetMedia()->IsCDROMHardwareEnabled()&&!core->GetMedia()->IsSGX()&&core->GetMemory()->GetCardRAMSize()==0,"unexpected original board profile");
    auto& v=*core->GetHuC6270_1();model::seed_vram(v.GetVRAM());core->GetHuC6260()->GetColorTable()[1]=0x38;
    reg(v,5,model::old_cr(c.edge));reg(v,9,0);reg(v,10,0x0202);reg(v,11,0x7F1D);reg(v,12,0x0F02);reg(v,13,239);reg(v,14,2);reg(v,0,0x1800);reg(v,1,0x18FF);
    return core;
}
void ports(GeargrafxCore& core,const model::Case& c){
    auto& v=*core.GetHuC6270_1();v.WriteRegister(0,2);
    if(c.queue&2){v.WriteRegister(2,0xCD);v.WriteRegister(3,0xAB);}
    if(c.queue&1)(void)v.ReadRegister(3);
    reg(v,model::write_reg(c.edge),model::write_value(c.edge));
}
model::State observe(GeargrafxCore& core){
    const auto& v=*core.GetHuC6270_1();const auto* r=core.GetHuC6270_1()->GetState();const auto* vce=core.GetHuC6260()->GetState();
    model::State out{core.GetMasterClockCycles(),std::uint64_t(*vce->HPOS),std::uint64_t(*vce->VPOS),std::uint64_t(*r->VPOS),
        std::uint64_t(*r->H_STATE),std::uint64_t(*r->V_STATE),r->R[5],r->R[9],v.*member(Cr{}),v.*member(Mwr{}),v.*member(Burst{}),
        v.*member(ReadPending{}),v.*member(WritePending{}),std::uint64_t(v.*member(Delay{})),v.*member(Carry{}),r->R[1],r->R[0],*r->READ_BUFFER,
        core.GetHuC6270_1()->GetVRAM()[0x1800],std::uint64_t(v.*member(BgStart{})),std::uint64_t(v.*member(BgEnd{})),std::uint64_t(v.*member(Hsync{}))};
    for(unsigned i=0;i<16;++i)out[22+i]=(v.*member(Indices{}))[i];return out;
}
}
int main(int argc,char** argv){try{
    model::require(argc==2,"original-gear-latch CASE");const auto c=model::selected(argv[1]);auto core=configured(c);
    advance(*core,c.write_ticks);ports(*core,c);
    std::cout<<"{\"case\":\""<<c.id<<"\",\"scope\":\"host-configured original device clocks; no opcode retirements\",\"native\":0,\"interpreted\":0,\"rows\":[";
    for(unsigned i=0;i<model::offsets.size();++i){advance(*core,c.write_ticks+model::offsets[i]);const auto row=observe(*core);
        model::require(row==observe(*core),"original repeated observer changed state");model::expected(c,row,true);
        std::cout<<(i?",":"");model::state_json(std::cout,row);}
    std::cout<<"]}\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
