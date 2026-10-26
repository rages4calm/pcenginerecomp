// Authored observer around the separately compiled complete original Gear core.
// Actual TRACE_CPU_IRQ records identify delivery; PC/SP changes are not used as
// a substitute. Original CPU/device implementation bodies remain unchanged.
#define main previous_authored_mapper_main
#include "geargrafx_mapper_probe.cpp"
#undef main
#include "irq_boundary_fixture.hpp"
#include "irq_trace_support.hpp"
#include "trace_logger.h"
#include <cstdio>
#include <filesystem>
#include <optional>
#include <sstream>
#if defined(GG_DISABLE_DISASSEMBLER)
#error Original TRACE_CPU_IRQ must remain enabled for this reference observer
#endif
namespace {
void require_irq(bool ok,const std::string& why){if(!ok)throw std::runtime_error(why);}
irq_trace::State observe_irq(GeargrafxCore& core){
    auto* cpu=core.GetHuC6280()->GetState();auto* memory=core.GetMemory();irq_trace::State state;
    state.pc=cpu->PC->GetValue();state.a=cpu->A->GetValue();state.x=cpu->X->GetValue();state.y=cpu->Y->GetValue();state.sp=cpu->S->GetValue();state.p=cpu->P->GetValue();
    for(unsigned page=0;page<8;++page)state.mpr[page]=memory->GetMpr(page);
    state.mpr_latch=memory->GetMprTMA(0);state.clock_divisor=*cpu->SPEED?3:12;state.ticks=core.GetMasterClockCycles();
    state.wram_sha256=irq_trace::hash(std::span<const std::uint8_t>(memory->GetWorkingRAM(),8192));return state;
}
std::array<std::uint64_t,26> irq_values(GeargrafxCore& core,std::uint64_t origin,std::uint64_t entries,unsigned vector,unsigned rti){
    const auto state=observe_irq(core);auto* cpu=core.GetHuC6280()->GetState();
    std::array<std::uint64_t,26> values{state.pc,state.a,state.x,state.y,state.sp,state.p,state.clock_divisor,state.ticks-origin};
    for(unsigned page=0;page<8;++page)values[8+page]=state.mpr[page];values[16]=*state.mpr_latch;
    values[17]=entries;values[18]=vector;values[19]=rti;values[20]=(*cpu->IRR&4)!=0;values[21]=*cpu->IDR;values[22]=*cpu->TIMER;
    for(unsigned i=0;i<3;++i)values[23+i]=core.GetMemory()->GetWorkingRAM()[0x10+i];return values;
}
void gear_literal(GeargrafxCore& core,std::uint64_t origin,const IrqLiteral& expected,unsigned ordinal,
                  std::uint64_t entries,unsigned vector,unsigned rti){
    const auto first=observe_irq(core),second=observe_irq(core);require_irq(first==second,"Repeated original IRQ inspection changed state");
    const auto actual=irq_values(core,origin,entries,vector,rti);
    if(actual!=expected.values){std::cerr<<"ACTUAL";for(auto value:actual)std::cerr<<' '<<value;
        std::cerr<<"\nEXPECTED";for(auto value:expected.values)std::cerr<<' '<<value;std::cerr<<'\n';
        throw std::runtime_error("Original Gear IRQ literal differs at ordinal "+std::to_string(ordinal));}
    require_irq(first.wram_sha256==expected.wram_sha256,"Original full WRAM/stack literal differs at ordinal "+std::to_string(ordinal));
}
void dump_irq(const std::filesystem::path& path,const std::uint8_t* bytes){
#ifdef _WIN32
    auto* file=_wfopen(path.c_str(),L"wbx");
#else
    auto* file=std::fopen(path.c_str(),"wbx");
#endif
    require_irq(file!=nullptr,"Choose a new private original WRAM dump");const auto size=std::fwrite(bytes,1,8192,file);const auto closed=std::fclose(file);
    require_irq(size==8192&&closed==0,"Original WRAM dump failed");
}
}
int main(int argc,char** argv){try{
    require_irq(argc==5,"gear-irq-boundary ROM CASE NEW_WRAM NEW_IRQ_JOURNAL");
    const auto& item=irq_case(argv[2]);const auto rom=read_rom(argv[1]);require_irq(rom==irq_rom(item),"Exact authored original IRQ ROM required");
    const auto journal_path=std::filesystem::path(argv[4]);
#ifdef _WIN32
    auto* opened=_wfopen(journal_path.c_str(),L"wbx");
#else
    auto* opened=std::fopen(journal_path.c_str(),"wbx");
#endif
    require_irq(opened!=nullptr,"Choose a new original IRQ journal");
    std::unique_ptr<std::FILE,decltype(&std::fclose)> journal_file(opened,&std::fclose);
    GeargrafxCore core;core.Init(nullptr);core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_AUTO);core.GetMedia()->ForceBackupRAM(false);
    core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);core.GetHuC6270_1()->SetSafeDefaults(false);core.GetScsiController()->SetResetValue(0);
    require_irq(core.LoadHuCardFromBuffer(rom.data(),static_cast<int>(rom.size()),"authored-irq-boundary.pce"),"Original IRQ ROM load failed");
    auto* cpu=core.GetHuC6280();cpu->SetHardwareClock(clock_cpu,&core);auto* logger=core.GetTraceLogger();
    require_irq(logger->SetCapacity(64),"Original IRQ logger capacity unavailable");logger->SetEnabledFlags(TRACE_FLAG_CPU|TRACE_FLAG_CPU_IRQ);
    unsigned entries=0,last_vector=0,rti=0;
    auto step=[&](const char* phase,unsigned ordinal){
        logger->Reset();const auto entry=observe_irq(core);unsigned calls=0;bool complete=false;std::ostringstream journal;
        do {if(++calls>65538)throw std::runtime_error("Original instruction continuation bound exceeded");
            const auto ticks=cpu->RunInstruction(&complete),clocked=cpu->GetClockedMasterCycles();if(ticks>clocked)clock_cpu(&core,ticks-clocked);
        }while(!complete);
        unsigned cpu_records=0,irq_records=0,opcode=0;std::optional<std::uint16_t> delivered;
        journal<<"{\"phase\":\""<<phase<<"\",\"ordinal\":"<<ordinal<<",\"original_calls\":"<<calls<<",\"entry\":";
        reference_trace::write_state(journal,entry);journal<<",\"original_trace\":[";
        for(unsigned i=0;i<logger->GetCount();++i){const auto& event=logger->GetEntry(i);journal<<(i?",":"");
            if(event.type==TRACE_CPU){++cpu_records;opcode=event.cpu.opcodes[0];
                require_irq(event.cpu.pc==entry.pc&&event.cpu.bank==entry.mpr[entry.pc>>13],"Original fetched CPU source differs");
                journal<<"{\"type\":\"cpu\",\"pc\":"<<event.cpu.pc<<",\"bank\":"<<unsigned(event.cpu.bank)<<",\"bytes\":[";
                for(unsigned b=0;b<event.cpu.size;++b)journal<<(b?",":"")<<unsigned(event.cpu.opcodes[b]);journal<<"]}";
            }else if(event.type==TRACE_CPU_IRQ){++irq_records;++entries;last_vector=event.irq.vector;delivered=event.irq.vector;
                require_irq(event.irq.vector==0xFFF6||event.irq.vector==0xFFF8||event.irq.vector==0xFFFA,"Original IRQ callback vector invalid");
                journal<<"{\"type\":\"TRACE_CPU_IRQ\",\"cycle\":"<<event.cycle<<",\"pc\":"<<event.irq.pc<<",\"vector\":"<<event.irq.vector<<'}';
            }else throw std::runtime_error("Unexpected original trace type");
        }
        require_irq(cpu_records==1&&irq_records<=1&&logger->GetCount()==logger->GetTotalLogged(),"Original CPU/IRQ trace loss or event count differs");
        if(opcode==0x40)++rti;
        const auto after=observe_irq(core);journal<<"],\"state\":";reference_trace::write_state(journal,after);journal<<"}\n";
        const auto raw=journal.str();require_irq(std::fwrite(raw.data(),1,raw.size(),journal_file.get())==raw.size()&&std::fflush(journal_file.get())==0,
            "Original IRQ journal write failed");
        return delivered;
    };
    for(unsigned i=0;i<item.primer_steps;++i)require_irq(!step("primer",i+1),"Masked software primer unexpectedly delivered an IRQ");
    const auto initial=observe_irq(core);const auto origin=initial.ticks;gear_literal(core,origin,item.initial,0,entries,last_vector,rti);
    irq_trace::write_initial(std::cout,initial);
    for(unsigned ordinal=1;ordinal<=item.steps;++ordinal){const auto entry=observe_irq(core);const auto delivered=step("measured",ordinal);
        gear_literal(core,origin,item.gear_rows[ordinal-1],ordinal,entries,last_vector,rti);
        require_irq((delivered?*delivered:0)==item.gear_rows[ordinal-1].irq_vector&&unsigned(delivered.has_value())==item.gear_rows[ordinal-1].irq_count,
                    "Actual original IRQ callback delivery differs");
        const auto after=observe_irq(core);irq_trace::write_event(std::cout,ordinal,"opcode",entry,after,delivered);
        irq_trace::write_instruction(std::cout,ordinal,ordinal,ordinal,entry,after,delivered);
    }
    require_irq(observe_irq(core).pc==item.end_pc,"Original IRQ sentinel differs");
    irq_trace::write_final(std::cout,item.steps,item.steps,observe_irq(core));dump_irq(std::filesystem::path(argv[3]),core.GetMemory()->GetWorkingRAM());return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
