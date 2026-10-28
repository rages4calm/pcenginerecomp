// Read-only observer around a separately compiled unchanged original Gear core.
// All compared setup/writes are guest instructions loaded through public APIs.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "memory.h"
#include "media.h"
#include "scsi_controller.h"
#include "trace_logger.h"
#include "vdc_scroll_fixture.hpp"
#include "vdc_scroll_support.hpp"
#include "reset_probe_support.hpp"
#include "irq_trace_support.hpp"
#include <optional>
#include <sstream>

bool g_mcp_stdio_mode=true;
namespace {
template<class Tag,typename Tag::type Pointer>struct Access {friend typename Tag::type member(Tag){return Pointer;}};
#define FIELD(Tag,Type,Name) struct Tag {using type=Type HuC6270::*;friend type member(Tag);};template struct Access<Tag,&HuC6270::Name>;
FIELD(X,u16,m_latched_bxr)
FIELD(Y,s32,m_bg_offset_y)
FIELD(Counter,s32,m_bg_counter_y)
FIELD(Pending,bool,m_bg_scroll_y_update_pending)
FIELD(XClock,s32,m_latch_clock_x)
FIELD(YClock,s32,m_latch_clock_y)
FIELD(LsbClock,s32,m_byr_lsb_write_clock)
FIELD(BxrBefore,bool,m_bxr_written_before_latch)
using Pixels=u16[HUC6270_MAX_BACKGROUND_WIDTH];
FIELD(LinePixels,Pixels,m_line_buffer)
#undef FIELD
struct HardwareClock {using type=bool(GeargrafxCore::*)(u32);friend type member(HardwareClock);};
template struct Access<HardwareClock,&GeargrafxCore::ClockHardware<true,false,false>>;
void clock_cpu(void* opaque,u32 ticks) {
    auto& core=*static_cast<GeargrafxCore*>(opaque);(core.*member(HardwareClock{}))(ticks);
}
scroll_probe::State observe(GeargrafxCore& core) {
    const auto& v=*core.GetHuC6270_1();
    scroll_probe::State out{v.*member(X{}),static_cast<unsigned>(v.*member(Y{})),static_cast<unsigned>(v.*member(Counter{})),v.*member(Pending{}),
        v.*member(XClock{}),v.*member(YClock{}),v.*member(LsbClock{}),v.*member(BxrBefore{})};
    for(unsigned i=0;i<16;++i)out.pixels[i]=(v.*member(LinePixels{}))[i];
    return out;
}
}
int main(int argc,char** argv){try {
    scroll_probe::require(argc==4,"gear-scroll AUTHORED_BIOS AUTHORED_CUE CASE");
    const ScrollCase* selected=nullptr;for(const auto& c:scroll_cases)if(std::string(argv[3])==c.id)selected=&c;
    scroll_probe::require(selected!=nullptr,"Unknown original scroll case");const auto& c=*selected;
    const auto rom=reset_probe::rom(argv[1]);GeargrafxCore core;core.Init(nullptr);
    core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_STANDARD);
    core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);
    core.GetHuC6260()->SetResetValue(0);core.GetHuC6270_1()->SetSafeDefaults(false);
    core.GetHuC6270_1()->SetNoSpriteLimit(false);core.GetScsiController()->SetResetValue(0);
    scroll_probe::require(core.LoadBiosFromBuffer(rom.data(),int(rom.size()),true)&&core.LoadMedia(argv[2],false)&&
        core.GetMedia()->IsCDROMHardwareEnabled() && core.GetMemory()->GetCardRAMSize()==0,
        "Actual authored StandardCD BIOS/media without expanded RAM required");
    auto* cpu=core.GetHuC6280();cpu->SetHardwareClock(clock_cpu,&core);
    auto* logger=core.GetTraceLogger();scroll_probe::require(logger->SetCapacity(4096),"Original bounded trace allocation failed");
    logger->SetEnabledFlags(TRACE_FLAG_CPU|TRACE_FLAG_VDC);logger->SetEventFilter(TRACE_VDC,TRACE_VDC_FILTER_ALL);
    std::ostringstream actions;actions<<'[';unsigned action=0;std::uint64_t calls=0;
    for(unsigned i=0;i<c.gear_steps;++i) {
        logger->Reset();const bool measured=action<c.count && c.gear_actions[action].step==i;
        const auto before=observe(core);const auto entry=core.GetMasterClockCycles();
        if(measured)scroll_probe::require(entry+6==c.gear_actions[action].effect,"Independent original guest port phase differs");
        bool complete=false;unsigned local_calls=0;
        do {
            scroll_probe::require(++local_calls<=65538,"Original block continuation bound exceeded");
            const auto ticks=cpu->RunInstruction(&complete),clocked=cpu->GetClockedMasterCycles();
            scroll_probe::require(clocked<=ticks,"Original clocked accounting exceeds returned ticks");
            if(ticks>clocked)clock_cpu(&core,ticks-clocked);++calls;
        }while(!complete);
        unsigned opcode_count=0,reg_count=0;std::ostringstream writes;writes<<'[';
        for(unsigned n=0;n<logger->GetCount();++n) {
            const auto& event=logger->GetEntry(n);if(event.type==TRACE_CPU)++opcode_count;
            if(measured && event.type==TRACE_VDC && event.vdc.event==TRACE_VDC_REG_WRITE) {
                writes<<(reg_count?",":"")<<"{\"ticks\":"<<event.cycle<<",\"register\":"<<unsigned(event.vdc.reg)
                      <<",\"value\":"<<event.vdc.value<<",\"raw\":"<<unsigned(event.vdc.raw)<<",\"high\":"<<unsigned(event.vdc.msb)<<'}';
                scroll_probe::require(event.cycle==c.gear_actions[action].effect && event.vdc.raw==c.gear_actions[action].value,
                    "Actual original VDC callback differs from authored write time/value");++reg_count;
            }
        }
        writes<<']';scroll_probe::require(opcode_count==1 && logger->GetCount()==logger->GetTotalLogged(),"Original CPU trace count/loss differs");
        if(measured) {
            scroll_probe::require(local_calls==1 && reg_count==(c.gear_actions[action].port?1U:0U),"Original measured port callback count differs");
            const auto after=observe(core);
            actions<<(action?",":"")<<"{\"step\":"<<i<<",\"entry_ticks\":"<<entry<<",\"after_ticks\":"<<core.GetMasterClockCycles()
                   <<",\"effect_ticks\":"<<c.gear_actions[action].effect<<",\"port\":"<<c.gear_actions[action].port
                   <<",\"value\":"<<c.gear_actions[action].value<<",\"before\":";
            scroll_probe::state(actions,before);actions<<",\"after\":";scroll_probe::state(actions,after);actions<<",\"original_writes\":"<<writes.str()<<'}';++action;
        }
    }
    actions<<']';const auto state=observe(core);scroll_probe::require(state==observe(core),"Repeated original observation mutated state");
    scroll_probe::expected(state,c);const auto* s=cpu->GetState();
    scroll_probe::require(core.GetMasterClockCycles()==c.ticks && s->PC->GetValue()==c.gear_end_pc && action==c.count,"Original independent final time/PC differs");
    std::ostringstream guest;guest<<"{\"pc\":"<<s->PC->GetValue()<<",\"ticks\":"<<core.GetMasterClockCycles()
        <<",\"a\":"<<s->A->GetValue()<<",\"x\":"<<s->X->GetValue()<<",\"y\":"<<s->Y->GetValue()
        <<",\"sp\":"<<s->S->GetValue()<<",\"p\":"<<s->P->GetValue()<<",\"mpr\":[";
    for(unsigned i=0;i<8;++i)guest<<(i?",":"")<<unsigned(core.GetMemory()->GetMpr(i));
    guest<<"],\"wram_sha256\":\""<<irq_trace::hash(std::span<const std::uint8_t>(core.GetMemory()->GetWorkingRAM(),8192))<<"\"}";
    std::cout<<"{\"schema\":1,\"case\":\""<<c.id<<"\",\"steps\":"<<c.gear_steps<<",\"original_calls\":"<<calls<<",\"guest\":"<<guest.str()
        <<",\"ticks\":"<<core.GetMasterClockCycles()<<",\"pc\":"<<s->PC->GetValue()<<",\"wram_sha256\":\""
        <<irq_trace::hash(std::span<const std::uint8_t>(core.GetMemory()->GetWorkingRAM(),8192))<<"\",\"scroll\":";
    scroll_probe::state(std::cout,state);std::cout<<",\"actions\":"<<actions.str()<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
