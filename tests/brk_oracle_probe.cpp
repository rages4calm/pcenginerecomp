// Authored initial CPU/RAM fixtures; actual native or interpreter retirement.
#include "pce/runtime.hpp"
#include "brk_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <string>

int main(int argc,char** argv){try{
    if(argc!=3 || (std::string(argv[2])!="native" && std::string(argv[2])!="interpreter"))
        throw std::runtime_error("usage: brk-probe PLAN native|interpreter");
    const bool native=std::string(argv[2])=="native";
    std::ifstream input(argv[1]);if(!input)throw std::runtime_error("cannot open BRK plan");
    unsigned pc,flags,sp,speed,requests,mask,steps,index=0;bool first=true;std::cout<<'[';
    while(input>>pc>>flags>>sp>>speed>>requests>>mask>>steps){
        if(pc>65535 || flags>255 || sp>255 || (speed!=3 && speed!=12) || requests>7 || mask>7 || steps<1 || steps>2 || ++index>10000)
            throw std::runtime_error("invalid bounded BRK fixture");
        pce::Bus bus;bus.kind[0xF8]=pce::BankKind::ram;bus.enable_interrupts();
        pce::Cpu cpu;cpu.mpr=brk_contexts[0];cpu.pc=pc;cpu.p=flags;cpu.sp=sp;
        cpu.a=0x63;cpu.x=0xA7;cpu.y=0x3B;cpu.clock_divisor=speed;
        for(auto [pa,value]:brk_program)if((pa>>13)==0xF8)(*bus.bytes)[pa]=value;
        for(auto [offset,target]:{std::pair{0x1FF6U,0x2900U},std::pair{0x1FF8U,0x2920U},std::pair{0x1FFAU,0x2940U}}){
            (*bus.bytes)[0x1F0000+offset]=target&255;(*bus.bytes)[0x1F0000+offset+1]=target>>8;}
        bus.irq.external=requests;bus.irq.timer_pending=(requests&4)!=0;bus.irq.mask=mask;
        for(unsigned n=0;n<steps;++n){
            const auto result=native?pce::generated_step(bus,cpu,std::numeric_limits<std::uint64_t>::max()):
                pce::interpret_step(bus,cpu,std::numeric_limits<std::uint64_t>::max());
            if(result!=pce::Exit::executed || cpu.native_steps!=(native?n+1:0) || cpu.interpreter_steps!=(native?0:n+1))
                throw std::runtime_error("BRK fixture did not retire in selected execution tier");
            if(!first)std::cout<<',';first=false;
            std::cout<<"{\"case\":"<<index-1<<",\"step\":"<<n+1<<",\"pc\":"<<cpu.pc<<",\"a\":"<<unsigned(cpu.a)
                <<",\"x\":"<<unsigned(cpu.x)<<",\"y\":"<<unsigned(cpu.y)<<",\"p\":"<<unsigned(cpu.p)
                <<",\"sp\":"<<unsigned(cpu.sp)<<",\"ticks\":"<<cpu.ticks<<",\"mpr\":[";
            for(unsigned j=0;j<8;++j)std::cout<<(j?",":"")<<unsigned(cpu.mpr[j]);
            std::cout<<"],\"stack\":\"";constexpr char hex[]="0123456789abcdef";
            for(unsigned j=0;j<256;++j){const auto v=(*bus.bytes)[0x1F0100+j];std::cout<<hex[v>>4]<<hex[v&15];}
            std::cout<<"\"}";
        }
    }
    if(!input.eof())throw std::runtime_error("truncated BRK plan");std::cout<<"]\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
