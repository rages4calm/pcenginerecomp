// Authored raw CDDA sample/PSG phase bridge for the independent Gear probe.
#include "pce/cdda_pcm.hpp"
#include <charconv>
#include <fstream>
#include <iostream>
#include <string_view>

namespace {
unsigned number(const char* text,unsigned maximum) {
    unsigned value=0;const std::string_view s=text;
    const auto r=std::from_chars(s.data(),s.data()+s.size(),value);
    if(r.ec!=std::errc{} || r.ptr!=s.data()+s.size() || value>maximum) throw pce::Fault("invalid PCM probe argument");
    return value;
}
struct AuthoredAudio final:pce::SectorProvider {
    pce::CdToc table;
    pce::Sector read(std::uint32_t) override {throw pce::Fault("PCM fixture is not a data reader");}
    const pce::CdToc& toc() const override {return table;}
    bool audio_playable(std::uint32_t lba) const override {return (lba>=10 && lba<60) || (lba>=70 && lba<90);}
    pce::AudioSector read_audio(std::uint32_t lba) override {
        if(!audio_playable(lba)) throw pce::Fault("non-audio fixture address");
        constexpr std::int16_t values[]={-32768,-1,0,1,4660,32767,-4660};
        pce::AudioSector result{};
        for(unsigned i=0;i<result.size();++i) result[i]=values[(lba+i)%7];
        return result;
    }
};
}
int main(int argc,char** argv) {
    try {
        if(argc!=4) throw pce::Fault("usage: pcm-probe cdda LBA FRAME | psg-phase FREQUENCY TICKS");
        const std::string_view kind=argv[1];
        if(kind=="psg-plan") {
            std::ifstream plan(argv[2]);if(!plan) throw pce::Fault("cannot read PSG plan");
            pce::Psg p;std::string operation;unsigned a=0,b=0;bool first=true;
            std::cout<<'[';
            while(plan>>operation) {
                if(operation=="r" && (plan>>a) && a<=1) {
                    p=pce::Psg{};p.enabled=p.synthesis_enabled=true;p.centered_dac=a!=0;
                } else if(operation=="w" && (plan>>a>>b) && a<=15 && b<=255) p.write(a,static_cast<std::uint8_t>(b));
                else if(operation=="s" && (plan>>a) && a<=10000000) {
                    p.advance_to(p.clock_ticks+static_cast<std::uint64_t>(a)*6);
                    const auto pcm=p.sample_pcm();if(!first) std::cout<<',';first=false;
                    std::cout<<'['<<pcm[0]<<','<<pcm[1]<<",[";
                    for(unsigned i=0;i<6;++i) {if(i) std::cout<<',';std::cout<<unsigned(p.channels[i].wave_index);}
                    std::cout<<"],["<<p.channels[4].noise_lfsr<<','<<p.channels[5].noise_lfsr<<"]]";
                } else throw pce::Fault("invalid PSG plan operation");
            }
            if(!plan.eof()) throw pce::Fault("incomplete PSG plan");
            std::cout<<"]\n";
        } else if(kind=="cdda") {
            const auto source=std::make_shared<AuthoredAudio>();pce::CddaPcmCache cache;
            const auto pcm=cache.sample(source,number(argv[2],89),number(argv[3],587));
            std::cout<<"{\"left\":"<<pcm[0]<<",\"right\":"<<pcm[1]<<"}\n";
        } else if(kind=="psg-phase") {
            pce::Psg p;p.enabled=p.synthesis_enabled=true;
            const auto frequency=number(argv[2],4095),ticks=number(argv[3],10000000);
            p.write(0,0);p.write(2,static_cast<std::uint8_t>(frequency));p.write(3,static_cast<std::uint8_t>(frequency>>8));
            p.write(4,0xdf);p.write(6,31);p.write(4,0x9f);p.advance_to(ticks);
            std::cout<<"{\"wave_index\":"<<unsigned(p.channels[0].wave_index)<<"}\n";
        } else throw pce::Fault("unknown PCM probe mode");
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
