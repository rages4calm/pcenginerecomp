// Authored settled functional device expectations; no CPU-tier/timing claim.
#include "pce/runtime.hpp"
#include "pce/video.hpp"
#include <fstream>
#include <iostream>
#include <string>

int main(int argc,char** argv) {
    if(argc!=2)return 2;
    try {
        unsigned mode,seed,dcr,source,destination,length;
        std::ifstream in(argv[1]);
        if(!(in>>mode>>seed>>dcr>>source>>destination>>length) || mode>2 || seed>255 || dcr>31 || source>65535 || destination>65535 || length>1024 || !length)return 2;
        std::string tail;if(in>>tail)return 2;
        pce::Vdc vdc;vdc.enabled=true;vdc.dma_enabled=true;
        pce::Vce vce;vce.enabled=true;
        for(unsigned i=0;i<32768;++i)(*vdc.vram)[i]=static_cast<std::uint16_t>(i*73+seed*257);
        auto reg=[&](unsigned index,unsigned value){vdc.write(0,index);vdc.write(2,value);vdc.write(3,value>>8);};
        if(mode==0) {
            reg(15,dcr);reg(16,source);reg(17,destination);reg(18,length-1);
            while(vdc.vram_dma_pending)vdc.dma_tick();
        } else if(mode==1) {
            reg(15,dcr);reg(19,source);vdc.vblank_dma();
            while(vdc.satb_pending)vdc.dma_tick();
        } else {
            vce.write(2,253);vce.write(3,1);
            for(unsigned i=0;i<512;++i){vce.write(4,(i*37+seed*17)&255);vce.write(5,(i*11+seed)&255);}
            vce.write(2,253);vce.write(3,1);
        }
        constexpr char hex[]="0123456789abcdef";
        auto output=[&](unsigned value){std::cout<<hex[(value>>4)&15]<<hex[value&15];};
        std::cout<<"{\"vram\":\"";
        for(auto value:*vdc.vram){output(value);output(value>>8);}
        std::cout<<"\",\"sat\":\"";
        for(auto value:vdc.satb){output(value);output(value>>8);}
        std::cout<<"\",\"palette\":\"";
        for(auto value:vce.palette){output(value);output(value>>8);}
        std::cout<<"\",\"readback\":\"";
        if(mode==2)for(unsigned i=0;i<512;++i){output(vce.read(4));output(vce.read(5));}
        std::cout<<"\",\"address\":"<<vce.address<<",\"status\":"<<unsigned(vdc.status)
            <<",\"irq1\":"<<(vdc.irq1?"true":"false")<<",\"dma_registers\":["
            <<vdc.reg[16]<<','<<vdc.reg[17]<<','<<vdc.reg[18]<<"]}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}
}
