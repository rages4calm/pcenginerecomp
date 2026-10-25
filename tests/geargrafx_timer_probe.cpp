// Authored observation adapter. Gear CPU/timer/memory/scheduler run unchanged.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "media.h"
#include "memory.h"
#include "reset_probe_support.hpp"
#include <memory>
#include <string>
bool g_mcp_stdio_mode=true;
template<class Tag,typename Tag::type Member>struct Access {friend typename Tag::type member(Tag){return Member;}};
struct Clock {using type=bool(GeargrafxCore::*)(u32);friend type member(Clock);};
struct Phase {using type=s32 HuC6280::*;friend type member(Phase);};
template struct Access<Clock,&GeargrafxCore::ClockHardware<false,false,false>>;
template struct Access<Phase,&HuC6280::m_timer_cycles>;
static void clock_cpu(void* context,u32 ticks) {auto* core=static_cast<GeargrafxCore*>(context);(core->*member(Clock{}))(ticks);}
static std::vector<std::uint64_t> state(GeargrafxCore& core) {
    auto* c=core.GetHuC6280();auto* s=c->GetState();
    return {unsigned(*s->TIMER),*s->TIMER_RELOAD,*s->TIMER_COUNTER,
        unsigned((*s->IRR&4)!=0),*s->IDR,static_cast<std::uint64_t>(c->*member(Phase{}))};
}
static std::vector<std::uint64_t> cpu(GeargrafxCore& core) {
    auto* s=core.GetHuC6280()->GetState();std::vector<std::uint64_t> out{
        s->PC->GetValue(),s->A->GetValue(),s->X->GetValue(),s->Y->GetValue(),s->S->GetValue(),s->P->GetValue(),
        *s->SPEED?3U:12U,core.GetMasterClockCycles()};
    for(unsigned i=0;i<8;++i)out.push_back(core.GetMemory()->GetMpr(i));return out;
}
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: gear-timer PLAN LOW_ROM HIGH_ROM");
        const auto low=reset_probe::rom(argv[2]),high=reset_probe::rom(argv[3]);std::ifstream plan(argv[1]);
        if(!plan)throw std::runtime_error("plan missing");std::unique_ptr<GeargrafxCore> core;std::string op;bool first=true;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned fast;if(!(plan>>fast)||fast>1)throw std::runtime_error("speed bound");
                core=std::make_unique<GeargrafxCore>();core->Init(nullptr);core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);
                core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);
                core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);
                const auto& rom=fast?high:low;
                if(!core->LoadHuCardFromBuffer(rom.data(),rom.size(),"authored-timer.pce"))throw std::runtime_error("authored ROM load");
                core->GetHuC6280()->SetHardwareClock(clock_cpu,core.get());
            } else {
                if(!core)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"timer",state(*core));
                else if(op=="c")reset_probe::record(first,"cpu",cpu(*core));
                else if(op=="t") {
                    unsigned ticks;if(!(plan>>ticks)||ticks>1000000)throw std::runtime_error("tick bound");
                    // The original scheduler calls ClockTimer once per chunk.
                    // Explicit <=3-tick chunks also cover long authored waits.
                    while(ticks){const auto n=ticks>3?3:ticks;clock_cpu(core.get(),n);ticks-=n;}
                } else if(op=="i") {
                    unsigned count;if(!(plan>>count)||count>4096)throw std::runtime_error("instruction bound");
                    for(unsigned i=0;i<count;++i){auto* c=core->GetHuC6280();const auto ticks=c->RunInstruction();const auto done=c->GetClockedMasterCycles();
                        if(ticks>done)clock_cpu(core.get(),ticks-done);reset_probe::record(first,"cpu",cpu(*core));}
                } else if(op=="q"||op=="w"||op=="k") {
                    unsigned offset,value=0;if(!(plan>>offset)||offset>8191||(op=="w"&&(!(plan>>value)||value>255)))throw std::runtime_error("bus bound");
                    auto* m=core->GetMemory();const auto old=m->GetMpr(6);m->SetMpr(6,op=="k"?0xF8:0xFF);
                    if(op=="w")m->Write(0xC000+offset,value);
                    else {auto v=m->Read(0xC000+offset);if(op=="q")v&=127;reset_probe::record(first,op=="k"?"ram":"read",{offset,v});}
                    m->SetMpr(6,old);
                } else throw std::runtime_error("unknown plan operation");
            }
        }
        std::cout<<"]\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
