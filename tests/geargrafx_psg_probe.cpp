// Authored API-only wrapper for an independently built Geargrafx PSG oracle.
// Compile separately against the user's unmodified Geargrafx sources. This
// file contains no synthesizer implementation and is not linked to pce-runtime.
#include "huc6280_psg.h"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

bool g_mcp_stdio_mode=true;
int main(int argc,char** argv) {
    try {
        if(argc!=2) throw std::runtime_error("usage: gear-psg-probe PLAN");
        std::ifstream plan(argv[1]);
        if(!plan) throw std::runtime_error("cannot read PSG plan");
        HuC6280PSG p;p.Init();
        std::string operation;unsigned a=0,b=0,samples=0;bool first=true;
        std::cout<<'[';
        while(plan>>operation) {
            if(operation=="r" && (plan>>a) && a<=1) {
                p.Reset();p.EnableHuC6280A(a!=0);samples=0;
            } else if(operation=="w" && (plan>>a>>b) && a<=15 && b<=255) {
                p.Write(static_cast<u16>(a),static_cast<u8>(b));
            } else if(operation=="s" && (plan>>a) && a<=10000000) {
                p.Clock(a);p.Sample();
                auto* channels=p.GetState()->CHANNELS;
                int left=0,right=0;
                for(unsigned i=0;i<6;++i) {left+=channels[i].left_sample;right+=channels[i].right_sample;}
                if(!first) std::cout<<',';first=false;
                std::cout<<'['<<std::clamp(left/2,-32768,32767)<<','<<std::clamp(right/2,-32768,32767)<<",[";
                for(unsigned i=0;i<6;++i) {if(i) std::cout<<',';std::cout<<unsigned(channels[i].wave_index);}
                std::cout<<"],["<<channels[4].noise_seed<<','<<channels[5].noise_seed<<"]]";
                // Drain before the external implementation's finite frame
                // buffer fills. Its filtered output is deliberately unused.
                if(++samples==512) {s16 buffer[GG_AUDIO_BUFFER_SIZE];p.EndFrame(buffer);samples=0;}
            } else throw std::runtime_error("invalid PSG plan operation");
        }
        if(!plan.eof()) throw std::runtime_error("incomplete PSG plan");
        std::cout<<"]\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
