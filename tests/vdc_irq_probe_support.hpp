#pragma once
#include "vdc_queue_probe_support.hpp"
namespace vdc_irq_probe {
template<class Adapter>void execute(Adapter& a,const char* path){
    std::ifstream input(path);if(!input)throw std::runtime_error("IRQ plan open");
    bool first=true;std::cout<<'[';char op;
    while(input>>op){unsigned x=0,y=0;
        if(op=='r'){input>>x>>y;a.reset(x,y);}
        else if(op=='z'){input>>x>>y;a.arm(x,y);reset_probe::record(first,"device",a.device());}
        else if(op=='i'){input>>x;while(x--){a.instruction();reset_probe::record(first,"cpu",a.cpu());reset_probe::record(first,"device",a.device());}}
        else if(op=='m')reset_probe::record(first,"ram",a.ram());
        else throw std::runtime_error("unknown VDC IRQ operation");
        if(!input)throw std::runtime_error("truncated VDC IRQ operation");
    }
    std::cout<<"]\n";
}
}
