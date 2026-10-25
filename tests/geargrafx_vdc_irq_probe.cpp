// New authored fixture; the original Gear bodies remain in the private checkout.
#define Adapter QueueAdapter
#define main prior_queue_main
#include "geargrafx_vdc_queue_probe.cpp"
#undef main
#undef Adapter
#include "vdc_irq_probe_support.hpp"
struct TimerPhase{using type=s32 HuC6280::*;friend type member(TimerPhase);};template struct Access<TimerPhase,&HuC6280::m_timer_cycles>;
struct ExtraTicks{using type=u32 HuC6280::*;friend type member(ExtraTicks);};template struct Access<ExtraTicks,&HuC6280::m_extra_master_cycles>;
struct Adapter:QueueAdapter{
    std::uint64_t waits=0,underflow=0;unsigned underflow_extra=0,underflow_dma=0;bool reported=false;
    void reset(unsigned fast,unsigned control){QueueAdapter::reset(fast,control);waits=underflow=0;underflow_extra=underflow_dma=0;reported=false;}
    static void hardware_clock(void* context,u32 ticks){auto* a=static_cast<Adapter*>(context);auto* c=a->core->GetHuC6280();const bool before=(*c->GetState()->IRR&4)!=0;const auto dma=a->v().*member(VramPending{});clock_cpu(a->core.get(),ticks);if(!before&&(*c->GetState()->IRR&4)&&!a->underflow){a->underflow=a->core->GetMasterClockCycles();a->underflow_extra=c->*member(ExtraTicks{});a->underflow_dma=dma;}}
    void arm(unsigned phase,unsigned mode){
        cpu_entry(0xE300);auto* c=core->GetHuC6280();c->GetState()->P->SetValue(mode==1?4:0);
        c->WriteInterruptRegister(0x1402,mode==2?4:0);c->WriteTimerRegister(0xC00,0);c->WriteTimerRegister(0xC01,1);
        advance(3072-phase);
        auto reg=[&](unsigned i,unsigned value){write(0,i);write(2,value&255);write(3,value>>8);};
        reg(15,0);reg(16,0);reg(17,0x100);reg(18,15);reg(1,0x100);write(0,2);
        c->SetHardwareClock(hardware_clock,this);
    }
    std::vector<std::uint64_t>device()const{
        auto out=QueueAdapter::device();auto* c=core->GetHuC6280();auto* s=c->GetState();
        for(auto value:{unsigned(*s->TIMER),unsigned(*s->TIMER_COUNTER),unsigned(*s->TIMER_RELOAD),unsigned(c->*member(TimerPhase{})),unsigned(*s->IRR),unsigned(*s->IDR)})out.push_back(value);
        out.push_back(reset_probe::hash(core->GetMemory()->GetWorkingRAM()+256,256));out.push_back(waits);return out;
    }
    void instruction(){QueueAdapter::instruction();waits+=core->GetHuC6280()->*member(ExtraTicks{});if(underflow&&!reported){std::cerr<<"UNDERFLOW "<<underflow<<' '<<underflow_extra<<' '<<underflow_dma<<'\n';reported=true;}}
};
int main(int argc,char**argv){try{if(argc!=3)throw std::runtime_error("gear-irq PLAN ROM");auto rom=reset_probe::rom(argv[2]);Adapter a{{nullptr,rom}};vdc_irq_probe::execute(a,argv[1]);return 0;}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
