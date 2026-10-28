// Authored observer; pinned original GPL core stays in this separate executable.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "media.h"
#include "memory.h"
#include "cdrom.h"
#include "adpcm.h"
#include "scsi_controller.h"
#include "audio.h"
#include "trace_logger.h"
#include "adpcm_irq_support.hpp"
#include "reset_probe_support.hpp"
#include <filesystem>
#include <fstream>
#include <memory>
#if defined(GG_DISABLE_DISASSEMBLER)
#error Original CPU and device callbacks must be enabled
#endif
bool g_mcp_stdio_mode=true;
namespace {
using namespace adpcm_irq;
struct ClockTag{using type=bool(GeargrafxCore::*)(u32);friend type member(ClockTag);};
template<class Tag,typename Tag::type Member>struct Access{friend typename Tag::type member(Tag){return Member;}};
template struct Access<ClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;
struct Context{
    GeargrafxCore* core;std::uint64_t drained=0;
    std::vector<std::array<std::uint64_t,3>> spans;
    static void clock(void* pointer,u32 ticks){auto& self=*static_cast<Context*>(pointer);const auto before=self.core->GetMasterClockCycles();
        require(self.spans.size()<20000,"Original callback storage bound exceeded");
        (self.core->*member(ClockTag{}))(ticks);const auto after=self.core->GetMasterClockCycles();
        require(after==before+ticks,"Original hardware span differs");self.spans.push_back({before,ticks,after});
        if(after-self.drained>=4096){self.core->GetAudio()->EndFrame(nullptr,nullptr);self.drained=after;}
    }
};
std::string wram(GeargrafxCore& core){return irq_trace::hash(std::span<const std::uint8_t>(core.GetMemory()->GetWorkingRAM(),8192));}
Values observe(GeargrafxCore& core,std::uint64_t origin,unsigned entries,unsigned vector,unsigned rti){
    auto* c=core.GetHuC6280()->GetState();auto* m=core.GetMemory();auto* a=core.GetAdpcm()->GetState();auto* cd=core.GetCDROM()->GetState();
    Values row{c->PC->GetValue(),c->A->GetValue(),c->X->GetValue(),c->Y->GetValue(),c->S->GetValue(),c->P->GetValue(),*c->SPEED?3U:12U,core.GetMasterClockCycles()-origin};
    for(unsigned i=0;i<8;++i)row[8+i]=m->GetMpr(i);
    row[16]=m->GetMprTMA(0);row[17]=entries;row[18]=vector;row[19]=rti;row[20]=*c->IDR;row[21]=*c->IRR;
    row[22]=*core.GetHuC6270_1()->GetState()->SR;row[23]=*cd->ENABLED_IRQS;row[24]=*cd->ACTIVE_IRQS;
    row[25]=m->GetWorkingRAM()[17];row[26]=m->GetWorkingRAM()[18];row[27]=*a->CONTROL;row[28]=*a->ADDRESS;
    row[29]=*a->READ_ADDRESS;row[30]=*a->WRITE_ADDRESS;row[31]=*a->LENGTH;row[32]=*a->HALF_IRQ;
    row[33]=*a->END_IRQ;row[34]=*a->PLAYING;row[35]=core.GetAdpcm()->GetStatusRegisterSnapshot();return row;
}
}
int main(int argc,char** argv){try{
    using namespace adpcm_irq;require(argc==5,"gear-adpcm-irq BIOS CUE CASE NEW_JOURNAL");
    const auto& item=adpcm_irq_case(argv[3]);const auto bios=reset_probe::rom(argv[1]);require(bios==adpcm_irq_rom(item),"Exact authored BIOS required");
    require(!std::filesystem::exists(argv[4]),"Choose new original journal");std::ofstream journal(argv[4]);require(bool(journal),"Cannot create journal");
    GeargrafxCore core;core.Init(nullptr);core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_STANDARD);
    core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);
    core.GetHuC6270_1()->SetSafeDefaults(false);core.GetScsiController()->SetResetValue(0);
    require(core.LoadBiosFromBuffer(bios.data(),int(bios.size()),true)&&core.LoadMedia(argv[2],false)&&core.GetMedia()->IsCDROMHardwareEnabled()
            &&!core.GetMedia()->IsSGX()&&core.GetMemory()->GetCardRAMSize()==0,"Actual Standard CD/no expanded Card RAM required");
    Context context{&core};auto* cpu=core.GetHuC6280();cpu->SetHardwareClock(Context::clock,&context);
    auto* logger=core.GetTraceLogger();require(logger->SetCapacity(8192),"Original trace capacity unavailable");
    logger->SetEnabledFlags(TRACE_FLAG_CPU|TRACE_FLAG_CPU_IRQ|TRACE_FLAG_ADPCM|TRACE_FLAG_CDROM|TRACE_FLAG_VDC);
    logger->SetEventFilter(TRACE_ADPCM,TRACE_ADPCM_FILTER_ALL);logger->SetEventFilter(TRACE_CDROM,TRACE_CDROM_FILTER_ALL);logger->SetEventFilter(TRACE_VDC,TRACE_VDC_FILTER_ALL);
    unsigned entries=0,vector=0,rti=0,blocks=0;std::uint64_t origin=0;
    auto step=[&](bool measured,unsigned ordinal){
        logger->Reset();context.spans.clear();auto* state=cpu->GetState();const auto pc=state->PC->GetValue();
        std::array<unsigned,8> mapping{};for(unsigned i=0;i<8;++i)mapping[i]=core.GetMemory()->GetMpr(i);
        unsigned calls=0;bool complete=false;std::uint64_t returned=0,internal=0;
        std::vector<std::array<std::uint64_t,5>> call_rows;
        do{require(++calls<=65538,"Original continuation bound");const auto first_span=context.spans.size();
            const auto ticks=cpu->RunInstruction(&complete),clocked=cpu->GetClockedMasterCycles();const auto internal_end=context.spans.size();
            require(clocked<=ticks,"Original clock partition differs");returned+=ticks;internal+=clocked;
            if(ticks>clocked)Context::clock(&context,ticks-clocked);
            call_rows.push_back({ticks,clocked,first_span,internal_end,context.spans.size()});
        }while(!complete);
        require(!measured||calls==1,"Measured opcode used multiple original calls");
        unsigned count=0,delivered=0,opcode=0;std::vector<unsigned> bytes;
        for(unsigned i=0;i<logger->GetCount();++i){const auto& e=logger->GetEntry(i);
            if(e.type==TRACE_CPU){++count;opcode=e.cpu.opcodes[0];require(e.cpu.pc==pc&&e.cpu.bank==mapping[pc>>13],"Original fetched context differs");
                for(unsigned n=0;n<e.cpu.size;++n)bytes.push_back(e.cpu.opcodes[n]);}
            else if(e.type==TRACE_CPU_IRQ){++entries;vector=delivered=e.irq.vector;}
        }
        require(count==1&&logger->GetCount()==logger->GetTotalLogged(),"Actual original opcode/trace loss differs");
        if(opcode==0x40)++rti;if(opcode==0x73)++blocks;
        journal<<"{\"phase\":\""<<(measured?"measured":"primer")<<"\",\"ordinal\":"<<ordinal<<",\"calls\":"<<calls<<",\"pc\":"<<pc<<",\"mpr\":[";
        for(unsigned i=0;i<8;++i)journal<<(i?",":"")<<mapping[i];journal<<"],\"bytes\":[";
        for(unsigned i=0;i<bytes.size();++i)journal<<(i?",":"")<<bytes[i];journal<<"],\"returned_ticks\":"<<returned<<",\"internal_ticks\":"<<internal<<",\"call_rows\":[";
        for(unsigned i=0;i<call_rows.size();++i){journal<<(i?",":"")<<'[';for(unsigned n=0;n<5;++n)journal<<(n?",":"")<<call_rows[i][n];journal<<']';}
        journal<<"],\"clocks\":[";
        for(unsigned i=0;i<context.spans.size();++i){if(i)journal<<',';const auto& span=context.spans[i];journal<<'['<<span[0]<<','<<span[1]<<','<<span[2]<<']';}
        journal<<"],\"callbacks\":[";bool first=true;
        for(unsigned i=0;i<logger->GetCount();++i){const auto& e=logger->GetEntry(i);if(e.type==TRACE_CPU)continue;
            if(!first)journal<<',';first=false;journal<<"{\"cycle\":"<<e.cycle<<",\"type\":"<<unsigned(e.type);
            if(e.type==TRACE_CPU_IRQ)journal<<",\"vector\":"<<e.irq.vector<<",\"pc\":"<<e.irq.pc<<",\"mask\":"<<unsigned(e.irq.irq_mask);
            else if(e.type==TRACE_ADPCM)journal<<",\"event\":"<<unsigned(e.adpcm.event)<<",\"length\":"<<e.adpcm.length<<",\"address\":"<<e.adpcm.address<<",\"reg\":"<<unsigned(e.adpcm.reg)<<",\"value\":"<<unsigned(e.adpcm.value)<<",\"state\":"<<unsigned(e.adpcm.state);
            else if(e.type==TRACE_CDROM)journal<<",\"event\":"<<unsigned(e.cdrom.event)<<",\"irq\":"<<unsigned(e.cdrom.irq_type)<<",\"active\":"<<unsigned(e.cdrom.active)<<",\"enabled\":"<<unsigned(e.cdrom.enabled);
            else if(e.type==TRACE_VDC)journal<<",\"event\":"<<unsigned(e.vdc.event)<<",\"value\":"<<e.vdc.value;
            else throw std::runtime_error("Unexpected original callback");journal<<'}';
        }
        journal<<"],\"after\":";row_json(journal,observe(core,origin,entries,vector,rti),wram(core),delivered);journal<<"}\n";require(bool(journal),"Original journal write failed");return delivered;
    };
    for(unsigned i=0;i<item.primer_steps;++i)require(step(false,i+1)==0,"Masked primer delivered IRQ");
    origin=core.GetMasterClockCycles();literal(observe(core,origin,entries,vector,rti),wram(core),item.initial,0);
    std::cout<<"{\"case\":\""<<item.id<<"\",\"tier\":\"gear\",\"origin_ticks\":"<<origin<<",\"initial\":";
    row_json(std::cout,observe(core,origin,entries,vector,rti),wram(core),0);std::cout<<",\"rows\":[";
    for(unsigned i=0;i<item.steps;++i){const auto delivered=step(true,i+1);literal(observe(core,origin,entries,vector,rti),wram(core),item.rows[i],i+1);
        require(delivered==item.rows[i].irq_vector,"Original IRQ delivery vector differs");if(i)std::cout<<',';row_json(std::cout,observe(core,origin,entries,vector,rti),wram(core),delivered);}
    require(blocks==item.block_steps,"Original block instruction count differs");
    std::cout<<"],\"original_instructions\":"<<item.primer_steps+item.steps<<",\"block_steps\":"<<blocks<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

