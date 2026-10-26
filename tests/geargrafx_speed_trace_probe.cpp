// Authored wrapper. Original pinned Gear CPU and scheduler stay separate.
#define main previous_mapper_probe_main
#include "geargrafx_mapper_probe.cpp"
#undef main
#include "speed_trace_fixture.hpp"
#include "reference_trace_support.hpp"
struct SpeedTimerPhase {using type=s32 HuC6280::*;friend type speed_member(SpeedTimerPhase);};
template<class Tag,typename Tag::type Member>struct SpeedAccess {friend typename Tag::type speed_member(Tag){return Member;}};
template struct SpeedAccess<SpeedTimerPhase,&HuC6280::m_timer_cycles>;
struct SpeedTransfer {using type=u32 HuC6280::*;friend type speed_member(SpeedTransfer);};
template struct SpeedAccess<SpeedTransfer,&HuC6280::m_transfer_state>;
static reference_trace::State speed_observe(GeargrafxCore& core){
    auto* s=core.GetHuC6280()->GetState();auto* m=core.GetMemory();reference_trace::State out;
    out.pc=s->PC->GetValue();out.a=s->A->GetValue();out.x=s->X->GetValue();out.y=s->Y->GetValue();out.sp=s->S->GetValue();out.p=s->P->GetValue();
    for(unsigned p=0;p<8;++p)out.mpr[p]=m->GetMpr(p);out.mpr_latch=m->GetMprTMA(0);
    out.clock_divisor=*s->SPEED?3:12;out.ticks=core.GetMasterClockCycles();
    out.wram_sha256=reference_trace::hash(std::span<const std::uint8_t>(m->GetWorkingRAM(),8192));return out;
}
int main(int argc,char**argv){try{
    if(argc!=2)throw std::runtime_error("gear-speed AUTHORED_ROM");const auto rom=read_rom(argv[1]);if(rom.size()!=262144)throw std::runtime_error("256KiB authored firmware required");
    GeargrafxCore core;core.Init(nullptr);core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_AUTO);core.GetMedia()->ForceBackupRAM(false);
    core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);core.GetHuC6270_1()->SetSafeDefaults(false);core.GetScsiController()->SetResetValue(0);
    if(!core.LoadHuCardFromBuffer(rom.data(),static_cast<int>(rom.size()),"authored-speed.pce"))throw std::runtime_error("Authored firmware load failed");
    auto* cpu=core.GetHuC6280();cpu->SetHardwareClock(clock_cpu,&core);
    auto step=[&]{do{const auto ticks=cpu->RunInstruction(),clocked=cpu->GetClockedMasterCycles();if(ticks>clocked)clock_cpu(&core,ticks-clocked);}while(cpu->*speed_member(SpeedTransfer{}));};
    for(unsigned i=0;i<speed_primer_steps;++i)step();const auto initial=speed_observe(core);if(initial.pc!=speed_marker || initial.clock_divisor!=12)throw std::runtime_error("Software primer differs");
    reference_trace::write_initial(std::cout,initial);
    for(unsigned i=0;i<speed_trace_steps;++i){const auto entry=speed_observe(core);step();const auto state=speed_observe(core);auto* s=cpu->GetState();
        std::vector<std::uint64_t> row{state.pc,state.a,state.x,state.y,state.sp,state.p,state.clock_divisor,state.ticks-initial.ticks};for(auto m:state.mpr)row.push_back(m);
        row.insert(row.end(),{*state.mpr_latch,unsigned(*s->TIMER),unsigned(*s->TIMER_RELOAD),unsigned(*s->TIMER_COUNTER),unsigned((*s->IRR&4)!=0),unsigned(*s->IDR),unsigned(cpu->*speed_member(SpeedTimerPhase{}))});
        for(unsigned b=0;b<4;++b)row.push_back(core.GetMemory()->GetWorkingRAM()[0xF0+b]);
        if(row!=std::vector<std::uint64_t>(speed_expected_gear[i].begin(),speed_expected_gear[i].end())){std::cerr<<"ACTUAL";for(auto v:row)std::cerr<<' '<<v;std::cerr<<"\nEXPECTED";for(auto v:speed_expected_gear[i])std::cerr<<' '<<v;std::cerr<<'\n';throw std::runtime_error("Independent Gear literal differs at ordinal "+std::to_string(i+1));}
        reference_trace::write_instruction(std::cout,i+1,entry,state);
        std::cerr<<"SPEED_DEVICE "<<i+1;for(auto v:row)std::cerr<<' '<<v;std::cerr<<'\n';
    }
    reference_trace::write_final(std::cout,speed_trace_steps);return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
