// Authored CPU/stack IRQ observations. External lines mirror reference sources.
#include "pce/runtime.hpp"
#include "irq_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <string>

int main(int argc,char** argv) {
    if(argc!=3 || (std::string(argv[2])!="native" && std::string(argv[2])!="interpreter")) return 2;
    try {
        unsigned seed,a,x,y,sp,p,divisor,mask,pulled,entry,count;
        std::ifstream in(argv[1]);
        if(!(in>>seed>>a>>x>>y>>sp>>p>>divisor>>mask>>pulled>>entry>>count)
           || seed>255 || a>255 || x>255 || y>255 || sp>255 || p>255
           || (divisor!=3 && divisor!=12) || mask>7 || pulled>255
           || (entry!=0x2800 && entry!=0x2810 && entry!=0x2820 && entry!=0x2830 && entry!=0x2840)
           || count!=3) return 2;
        std::string trailing; if(in>>trailing) return 2;
        pce::Bus bus; bus.kind[0xF8]=pce::BankKind::ram;bus.enable_interrupts();
        bus.irq.external=7;bus.irq.mask=mask;
        for(unsigned i=0;i<8192;++i) (*bus.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
        for(auto [address,value]:irq_program) (*bus.bytes)[address]=value;
        auto write=[&](unsigned offset,unsigned value){(*bus.bytes)[0x1F0000+offset]=static_cast<std::uint8_t>(value);};
        for(auto [offset,target]:{std::pair{0x1FF6u,0x2900u},std::pair{0x1FF8u,0x2970u},std::pair{0x1FFAu,0x2980u}}) {
            write(offset,target);write(offset+1,target>>8);
        }
        write(0x100+((sp+1)&255),pulled);write(0x100+((sp+2)&255),0);write(0x100+((sp+3)&255),0x28);
        pce::Cpu s;s.pc=entry;s.mpr=irq_mpr;s.a=a;s.x=x;s.y=y;s.sp=sp;s.p=p;s.clock_divisor=divisor;
        std::cout << "{\"states\":[";
        for(unsigned n=0;n<count;++n) {
            auto status=std::string(argv[2])=="native" ? pce::generated_step(bus,s,std::numeric_limits<std::uint64_t>::max())
                :pce::interpret_step(bus,s,std::numeric_limits<std::uint64_t>::max());
            if(status!=pce::Exit::executed) return 3;
            std::cout << (n?",":"") << "{\"pc\":"<<s.pc<<",\"a\":"<<unsigned(s.a)<<",\"x\":"<<unsigned(s.x)
                <<",\"y\":"<<unsigned(s.y)<<",\"sp\":"<<unsigned(s.sp)<<",\"p\":"<<unsigned(s.p)<<",\"mpr\":[";
            for(unsigned i=0;i<8;++i)std::cout<<(i?",":"")<<unsigned(s.mpr[i]);
            std::cout << "]}";
        }
        std::cout << "],\"ram\":\"";
        constexpr char hex[]="0123456789abcdef";
        for(unsigned i=0;i<8192;++i){auto v=(*bus.bytes)[0x1F0000+i];std::cout<<hex[v>>4]<<hex[v&15];}
        std::cout << "\",\"native_steps\":"<<s.native_steps<<",\"interpreter_steps\":"<<s.interpreter_steps
            <<",\"cycles\":"<<s.cycles<<",\"ticks\":"<<s.ticks<<",\"irq_entries\":"<<s.irq_entries<<"}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}
}
