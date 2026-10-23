// Authored raw CDDA sample/PSG phase bridge for the independent Gear probe.
#include "pce/cdda_pcm.hpp"
#include <charconv>
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
        if(kind=="cdda") {
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
