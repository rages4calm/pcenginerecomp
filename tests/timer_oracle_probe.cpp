// Authored timer fixture. Independent emulator executes in a separate process.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "reset_probe_support.hpp"
#include <memory>
#include <string>
#include <filesystem>
static std::vector<std::uint64_t> state(const pce::Bus& b,const pce::Cpu& c) {
    const auto& t=b.irq;return {unsigned(t.timer_enabled),t.timer_reload,t.timer_counter,unsigned(t.timer_pending),t.mask,
        t.timer_enabled?t.timer_deadline-c.ticks:t.timer_frozen_phase};
}
static std::vector<std::uint64_t> cpu(const pce::Cpu& c) {
    std::vector<std::uint64_t> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};
    for(auto m:c.mpr)out.push_back(m);return out;
}
int main(int argc,char** argv) {
    try {
        if(argc!=4&&argc!=6)throw std::runtime_error("usage: timer-probe PLAN LOW_ROM HIGH_ROM [--capture NEW]");
        const auto low=reset_probe::rom(argv[2]),high=reset_probe::rom(argv[3]);std::ifstream plan(argv[1]);
        if(!plan)throw std::runtime_error("plan missing");std::unique_ptr<pce::CodeCapture> capture;
        if(argc==6){if(std::string(argv[4])!="--capture")throw std::runtime_error("capture option");capture=std::make_unique<pce::CodeCapture>(argv[5],65536);}
        std::unique_ptr<pce::Bus> bus;pce::Cpu c;std::string op;bool first=true;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned fast;if(!(plan>>fast)||fast>1)throw std::runtime_error("speed bound");
                bus=std::make_unique<pce::Bus>();bus->configure_hucard(pce::HuCardProfile::base,fast?high:low);
                bus->enable_video();bus->enable_interrupts();bus->enable_psg();bus->enable_joypad(false,true);bus->power_on_cpu(c);
            } else {
                if(!bus)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"timer",state(*bus,c));
                else if(op=="c")reset_probe::record(first,"cpu",cpu(c));
                else if(op=="t") {
                    unsigned ticks;if(!(plan>>ticks)||ticks>1000000)throw std::runtime_error("tick bound");c.ticks+=ticks;bus->sync(c);
                } else if(op=="i") {
                    unsigned count;if(!(plan>>count)||count>4096)throw std::runtime_error("instruction bound");
                    for(unsigned i=0;i<count;++i){pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*bus,c);
#ifdef PCE_TIMER_NATIVE_ONLY
                        if(pce::generated_step(*bus,c,100000000)!=pce::Exit::executed)throw std::runtime_error("native miss; fallback forbidden");
#else
                        if(pce::interpret_step(*bus,c,100000000)!=pce::Exit::executed)throw std::runtime_error("interpreter refused");
#endif
                        if(capture)capture->after(pending,c);reset_probe::record(first,"cpu",cpu(c));}
                } else if(op=="q"||op=="w"||op=="k") {
                    unsigned offset,value=0;if(!(plan>>offset)||offset>8191||(op=="w"&&(!(plan>>value)||value>255)))throw std::runtime_error("bus bound");
                    const auto old=c.mpr[6];c.mpr[6]=op=="k"?0xF8:0xFF;
                    if(op=="w")bus->write(c,0xC000+offset,value);
                    else {auto v=bus->read(c,0xC000+offset);if(op=="q")v&=127;reset_probe::record(first,op=="k"?"ram":"read",{offset,v});}
                    c.mpr[6]=old;
                } else throw std::runtime_error("unknown plan operation");
            }
        }
        std::cout<<"]\n";if(capture)capture->finish();return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
