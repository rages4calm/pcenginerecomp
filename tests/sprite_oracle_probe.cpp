#include "pce/runtime.hpp"
#include <fstream>
#include <iostream>
#include <string>

// Authored memory seeds and device-port accesses only: no status, interrupt,
// sprite-cache, or scheduler state is injected by this adapter.
int main(int argc,char** argv) try {
    if(argc<2 || argc>3 || (argc==3 && std::string(argv[2])!="--video")) return 2;
    std::ifstream input(argv[1]);
    if(!input) return 2;
    const bool output=argc==3;
    pce::Vdc v;pce::Vce palette;palette.enabled=true;
    const auto reset=[&] {
        v=pce::Vdc{};v.enabled=true;v.reg[11]=31;v.reg[13]=239;v.enable_raster();
        palette=pce::Vce{};palette.enabled=true;
        if(output) v.video.enable(v);
    };
    reset();
    const auto advance=[&](std::uint64_t time) {
        if(time<v.raster.master_ticks || time>4ULL*1365*263)
            throw std::runtime_error("invalid sprite plan timestamp");
        v.advance(time-v.raster.master_ticks,&palette);
    };
    bool comma=false;
    std::cout<<'[';
    std::string op;
    while(input>>op) {
        if(op=="r") {reset();continue;}
        std::uint64_t time;
        unsigned address,value;
        if(op=="v" || op=="t") {
            if(!(input>>address>>value) || value>65535) return 2;
            if(op=="v") {if(address>=32768)return 2;(*v.vram)[address]=value;}
            else {if(address>=256)return 2;v.satb[address]=value;}
        } else if(op=="w") {
            if(!(input>>time>>address>>value) || address>=20 || value>65535)return 2;
            advance(time);v.write(0,address);v.write(2,value&255);v.write(3,value>>8);
        } else if(op=="c") {
            if(!(input>>time>>value) || value>255)return 2;
            advance(time);v.write_vce_control(value);palette.write(0,value);
        } else if(op=="s" || op=="d") {
            if(!(input>>time))return 2;
            advance(time);
            const auto status=v.status&63;const bool irq=v.irq1;
            if(op=="d") v.read(0);
            if(comma)std::cout<<',';comma=true;
            std::cout<<"{\"time\":"<<time<<",\"status\":"<<unsigned(status)
                <<",\"irq\":"<<(irq?"true":"false")<<",\"after_status\":"<<unsigned(v.status&63)
                <<",\"after_irq\":"<<(v.irq1?"true":"false")<<'}';
        } else return 2;
    }
    std::cout<<"]\n";
    return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
