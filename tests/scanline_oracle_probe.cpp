// Authored device inputs; expected pixels come only from the external oracle.
#include "pce/runtime.hpp"
#include "pce/scanline.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

int main(int argc,char** argv) {
    if(argc!=3)return 2;
    try {
        unsigned seed,mwr,bxr,byr,cr;
        std::ifstream in(argv[1]);
        if(!(in>>seed>>mwr>>bxr>>byr>>cr)||seed>4||mwr>127||bxr>1023||byr>511||cr>255)return 2;
        std::string tail;if(in>>tail)return 2;
        pce::Bus bus;bus.enable_continuous_video();auto& v=bus.vdc;
        v.reg.fill(0);
        v.reg[5]=cr;v.reg[7]=bxr;v.reg[8]=byr;v.reg[9]=mwr;
        v.reg[10]=0x0202;v.reg[11]=0x041F;v.reg[12]=0x0F02;v.reg[13]=191;v.reg[14]=64;
        v.vram->fill(0);v.satb.fill(0);
        const unsigned columns[]={32,64,128,128};
        const auto width=columns[(mwr>>4)&3],height=(mwr&64)?64u:32u;
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)
            (*v.vram)[y*width+x]=static_cast<std::uint16_t>((0x200+(x*3+y*5+seed)%64)|(((x+y+seed)%16)<<12));
        for(unsigned tile=0;tile<64;++tile)for(unsigned y=0;y<8;++y)for(unsigned x=0;x<8;++x) {
            const auto color=1+(x+y*3+tile+seed)%15,base=(0x200+tile)*16+y;
            for(unsigned plane=0;plane<4;++plane)(*v.vram)[base+(plane>=2?8:0)]|=((color>>plane)&1)<<(7-x+8*(plane%2));
        }
        for(unsigned a=0x4000;a<0x6000;++a)(*v.vram)[a]=static_cast<std::uint16_t>(a*109+seed*997);
        for(unsigned i=0;i<8;++i) {
            v.satb[i*4]=static_cast<std::uint16_t>(64+24+i*19);
            v.satb[i*4+1]=static_cast<std::uint16_t>(32+8+i*29);
            v.satb[i*4+2]=static_cast<std::uint16_t>(0x200+i*8+(seed&1));
            v.satb[i*4+3]=static_cast<std::uint16_t>((i&3)|((i&1)?128:0)|((i&2)?256:0)|((i&4)?0x8800:0));
        }
        auto palette=[&](unsigned phase){for(unsigned i=0;i<512;++i)bus.vce.palette[i]=static_cast<std::uint16_t>((i*29+seed*17+3+phase*183)&511);};
        palette(0);
        const std::uint64_t frame=1365*262;
        std::uint64_t now=0;
        auto advance=[&](std::uint64_t ticks){v.advance(ticks-now,&bus.vce);now=ticks;};
        auto capture=[&](unsigned n){const auto& f=v.video.completed();if(f.width!=256||f.height!=192)throw pce::Fault("Unexpected continuous probe geometry");
            pce::write_ppm(f,(std::filesystem::path(argv[2])/("local-"+std::to_string(n)+".ppm")).string());
            if(n)std::cout<<',';std::cout<<"{\"sequence\":"<<v.video.sequence()<<",\"ticks\":"<<v.video.completed_ticks()<<'}';};
        std::cout<<"{\"frames\":[";
        advance(2*frame+24);capture(0);
        advance(2*frame+96*1365+600);palette(1);
        advance(3*frame+24);capture(1);
        advance(3*frame+80*1365+498);v.reg[7]=(bxr+13)&1023;
        advance(4*frame+24);capture(2);
        advance(4*frame+120*1365+600);
        for(unsigned address=0x2000;address<0x2400;++address)(*v.vram)[address]^=65535;
        advance(5*frame+24);capture(3);
        std::cout<<"]}\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
