// Authored presentation-filter probe; no external reference code is linked.
#include "pce/audio.hpp"
#include "pce/audio_dsp.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc,char** argv) {
    try {
        if(argc!=3)throw std::runtime_error("usage: pce-filter-probe psg|adpcm PLAN");
        const bool adpcm_mode=std::string(argv[1])=="adpcm";
        if(!adpcm_mode && std::string(argv[1])!="psg")throw std::runtime_error("unknown filter source");
        std::ifstream input(argv[2]);if(!input)throw std::runtime_error("cannot open filter plan");
        pce::Psg p;p.enabled=true;p.synthesis_enabled=true;
        pce::PsgPresentationFilter psg;pce::AdpcmPresentationFilter adpcm;
        std::uint64_t ticks=0;bool first=true;std::string op;int a=0,b=0;
        std::cout<<'[';
        const auto emit=[&](pce::StereoSample value) {
            if(!first)std::cout<<',';first=false;std::cout<<'['<<value[0]<<','<<value[1]<<']';
        };
        while(input>>op) {
            if(op=="r" && input>>a && a>=0 && a<=1) {
                p=pce::Psg{};p.enabled=true;p.synthesis_enabled=true;p.centered_dac=a!=0;
                ticks=0;psg.reset();adpcm.reset();
            } else if(!adpcm_mode && op=="w" && input>>a>>b && a>=0 && a<=15 && b>=0 && b<=255) {
                p.write(static_cast<unsigned>(a),static_cast<std::uint8_t>(b));
            } else if(!adpcm_mode && op=="s" && input>>a && a>0 && a<=10000000) {
                ticks+=static_cast<unsigned>(a)*6ULL;p.advance_to(ticks);emit(psg.process(p.sample_sum()));
            } else if(!adpcm_mode && op=="x" && input>>a>>b && a>=-196608 && a<=196602 && b>=-196608 && b<=196602) {
                emit(psg.process({a,b}));
            } else if(adpcm_mode && op=="a" && input>>a>>b && a>=0 && a<=4095 && b>=0 && b<=1) {
                const auto value=adpcm.process(static_cast<std::uint16_t>(a),static_cast<float>(b));emit({value,value});
            } else if(adpcm_mode && op=="v" && input>>a && a>=0 && a<=15) {
                // Decoder rate is deliberately outside this presentation API.
            } else throw std::runtime_error("invalid authored filter plan");
        }
        if(!input.eof())throw std::runtime_error("truncated filter plan");
        std::cout<<"]\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
