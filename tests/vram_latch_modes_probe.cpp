// Authored two-bit fetch observations; no third-party implementation linked.
#include "pce/runtime.hpp"
#include "pce/video.hpp"
#include <array>
#include <fstream>
#include <iostream>
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    try {
        std::ofstream out(argv[1],std::ios::binary);if(!out)return 2;
        pce::Vdc vdc;vdc.enabled=true;
        std::array<std::uint16_t,8> pixels{};
        for(unsigned high=0;high<2;++high) for(unsigned cg=0;cg<2;++cg)
            for(unsigned word=0;word<65536;++word) {
                (*vdc.vram)[0]=static_cast<std::uint16_t>(high?0x7800:0x7200);
                (*vdc.vram)[0x2000]=static_cast<std::uint16_t>(word);
                (*vdc.vram)[0x2008]=static_cast<std::uint16_t>(word^65535);
                vdc.vram_bus_latch=static_cast<std::uint16_t>(word^0xA55A);
                pce::render_guest_scanline_indices(vdc,0,0,0,128,
                    static_cast<std::uint16_t>(3|(cg<<7)),pixels);
                for(auto pixel:pixels)out.put(static_cast<char>(pixel));
                out.put(static_cast<char>(vdc.vram_bus_latch));
                out.put(static_cast<char>(vdc.vram_bus_latch>>8));
            }
        if(!out)return 2;
        std::cout<<"{\"cases\":262144,\"pixels\":2097152,\"latches\":262144}\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}
}
