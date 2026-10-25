// Authored, finite device fixture. Expected values are supplied by the separate
// reference adapter; no external implementation is linked into this program.
#include "pce/runtime.hpp"
#include "pce/video.hpp"
#include <array>
#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
    if(argc!=2) return 2;
    try {
        std::ofstream out(argv[1],std::ios::binary);
        if(!out) return 2;
        pce::Vdc vdc; pce::Vce vce;
        vdc.enabled=vce.enabled=true;
        vdc.reg[5]=128;vdc.reg[11]=0;vdc.reg[13]=0;
        (*vdc.vram)[0]=0x0200;
        (*vdc.vram)[0x2000]=0x0080;
        // All 512 nine-bit colors, with an explicitly supplied standard RGB
        // palette and grayscale control. The other seven pixels are irrelevant.
        vce.control=128;
        for(unsigned color=0;color<512;++color) {
            vce.palette[1]=static_cast<std::uint16_t>(color);
            const auto frame=pce::render_snapshot(vdc,vce);
            out.write(reinterpret_cast<const char*>(frame.rgb.data()),3);
        }
        // Exhaust every possible selected pattern word and both CG halves.
        // The unselected word is its complement, making incorrect selection
        // observable. Palette seven checks zero-color transparency separately.
        (*vdc.vram)[0]=0x7200;
        std::array<std::uint16_t,8> pixels{};
        for(unsigned cg=0;cg<2;++cg) for(unsigned word=0;word<65536;++word) {
            (*vdc.vram)[0x2000]=static_cast<std::uint16_t>(word);
            (*vdc.vram)[0x2008]=static_cast<std::uint16_t>(word^65535);
            pce::render_scanline_indices(vdc,0,0,0,128,static_cast<std::uint16_t>(3|(cg<<7)),pixels);
            for(auto pixel:pixels) out.put(static_cast<char>(pixel));
        }
        if(!out) return 2;
        std::cout<<"{\"palette_colors\":512,\"selected_words\":131072,\"pattern_pixels\":1048576}\n";
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 2; }
}
