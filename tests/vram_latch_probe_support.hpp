#pragma once
// Authored fixture dispatch and reporting only; no emulated device operations.
#include "reset_probe_support.hpp"
#include <string>
namespace latch_probe {
inline std::uint16_t pattern(unsigned i) {return static_cast<std::uint16_t>((i*73)^(i>>3)^0xA53C);}
template<class Adapter> void execute(Adapter& a,const char* path) {
    std::ifstream plan(path);if(!plan)throw std::runtime_error("plan missing");
    bool first=true;std::string op;unsigned operations=0;std::cout<<'[';
    while(plan>>op) {
        if(++operations>262144)throw std::runtime_error("plan operation bound");
        unsigned x=0,y=0;
        if(op=="r") {if(!(plan>>x)||x>1)throw std::runtime_error("entry speed");a.reset(x);}
        else if(op=="s")reset_probe::record(first,"device",a.device());
        else if(op=="c")reset_probe::record(first,"cpu",a.cpu());
        else if(op=="m")reset_probe::record(first,"ram",a.ram());
        else if(op=="f") {a.fetch();reset_probe::record(first,"sprites",a.sprites());}
        else if(op=="b")a.vblank();
        else if(op=="q") {if(!(plan>>x)||x>65535)throw std::runtime_error("VRAM address");reset_probe::record(first,"word",{x,a.word(x)});}
        else if(op=="p") {if(!(plan>>x)||x>3)throw std::runtime_error("port");reset_probe::record(first,"byte",{x,a.port(x)});}
        else if(op=="w") {if(!(plan>>x>>y)||x>=20||y>65535)throw std::runtime_error("register");a.reg(x,y);}
        else if(op=="v"||op=="t") {if(!(plan>>x>>y)||x>=(op=="v"?32768U:256U)||y>65535)throw std::runtime_error("memory seed");a.seed(op=="t",x,y);}
        else if(op=="z") {if(!(plan>>x)||x>65535)throw std::runtime_error("uniform seed");for(unsigned i=0;i<32768;++i)a.seed(false,i,x);}
        else if(op=="d") {if(!(plan>>x)||x>4096)throw std::runtime_error("DMA dot bound");a.dots(x);}
        else if(op=="g") {if(!(plan>>x)||x>1000000)throw std::runtime_error("clock bound");a.advance(x);}
        else if(op=="e") {if(!(plan>>x)||x>255)throw std::runtime_error("VCE control");a.control(x);}
        else if(op=="i") {if(!(plan>>x)||x>4096)throw std::runtime_error("retirement bound");a.instructions(x);}
        else throw std::runtime_error("unknown latch fixture operation");
    }
    if(!plan.eof())throw std::runtime_error("truncated plan");std::cout<<"]\n";
}
}
