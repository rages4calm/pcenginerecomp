#define Adapter QueueAdapter
#define main prior_queue_main
#include "vdc_queue_oracle_probe.cpp"
#undef main
#undef Adapter
#include "vdc_irq_probe_support.hpp"
struct Adapter:QueueAdapter{
    void reset(unsigned fast,unsigned control){QueueAdapter::reset(fast,control);bus->enable_interrupts();bus->sync(c);}
    void arm(unsigned phase,unsigned mode){
        cpu_entry(0xE300);c.p=mode==1?4:0;
        bus->write(c,0x1402,mode==2?4:0);bus->write(c,0xC00,0);bus->write(c,0xC01,1);
        c.ticks+=3072-phase;bus->sync(c);
        auto reg=[&](unsigned i,unsigned value){write(0,i);write(2,value&255);write(3,value>>8);};
        reg(15,0);reg(16,0);reg(17,0x100);reg(18,15);reg(1,0x100);write(0,2);
    }
    std::vector<std::uint64_t>device()const{
        auto out=QueueAdapter::device();const auto& i=bus->irq;
        for(auto value:{unsigned(i.timer_enabled),unsigned(i.timer_counter),unsigned(i.timer_reload),unsigned(i.timer_enabled?i.timer_deadline-c.ticks:i.timer_frozen_phase),unsigned(bus->irq_requests()),unsigned(i.mask)})out.push_back(value);
        out.push_back(reset_probe::hash(bus->bytes->data()+0x1F0100,256));out.push_back(c.vdc_wait_ticks);return out;
    }
    void instruction(){
#ifdef PCE_QUEUE_NATIVE_ONLY
        if(!guarded){auto snapshot=[&]{return std::tuple{cpu(),device(),ram(),c.irq_sampled,c.irq_entries,c.irq_vector,bus->generation,bus->vdc.reads,bus->vdc.writes};};auto before=snapshot();auto address=pce::Bus::physical(c,c.pc);auto old=(*bus->bytes)[address];(*bus->bytes)[address]^=255;auto result=pce::generated_step(*bus,c,100000000);(*bus->bytes)[address]=old;if(result!=pce::Exit::miss||snapshot()!=before)throw std::runtime_error("source guard mutated timer/queue");++guards;c.mpr[3]^=1;result=pce::generated_step(*bus,c,100000000);c.mpr[3]^=1;if(result!=pce::Exit::miss||snapshot()!=before)throw std::runtime_error("MPR guard mutated timer/queue");++guards;guarded=true;}
#endif
        pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*bus,c);
#ifdef PCE_QUEUE_NATIVE_ONLY
        if(pce::generated_step(*bus,c,100000000)!=pce::Exit::executed)throw std::runtime_error("native miss; fallback forbidden");
#else
        if(pce::interpret_step(*bus,c,100000000)!=pce::Exit::executed)throw std::runtime_error("interpreter refused");
#endif
        if(capture)capture->after(pending,c);
    }
};
int main(int argc,char**argv){try{if(argc!=3&&argc!=5)throw std::runtime_error("irq-probe PLAN ROM [--capture NEW]");auto rom=reset_probe::rom(argv[2]);std::unique_ptr<pce::CodeCapture> capture;if(argc==5){if(std::string(argv[3])!="--capture")throw std::runtime_error("capture option");capture=std::make_unique<pce::CodeCapture>(argv[4],65536);}Adapter a{{nullptr,{},rom,capture.get()}};vdc_irq_probe::execute(a,argv[1]);if(capture)capture->finish();std::cerr<<"PCE_QUEUE_GUARDS="<<a.guards<<'\n';return 0;}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
