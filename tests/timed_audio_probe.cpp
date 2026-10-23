// Authored timestamped driver through the real runtime bus and audio output.
#include "pce/runtime.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: pce-timed-audio psg|adpcm|mixed PLAN whole|parts|single");
        const std::string mode=argv[1],partition=argv[3];
        if((mode!="psg" && mode!="adpcm" && mode!="mixed") ||
           (partition!="whole" && partition!="parts" && partition!="single"))throw std::runtime_error("invalid mode/partition");
        std::ifstream plan(argv[2]);if(!plan)throw std::runtime_error("cannot open plan");
        std::unique_ptr<pce::Bus> bus; pce::Cpu cpu;std::uint64_t time=0;unsigned phase=0;bool first=true;
        std::vector<std::int16_t> pcm;
        const auto drain=[&] {const auto v=bus->pcm.drain();pcm.insert(pcm.end(),v.begin(),v.end());};
        const auto advance=[&](std::uint64_t target) {
            if(!bus || target<time || target-time>21477273)throw std::runtime_error("invalid finite timestamp");
            constexpr unsigned pieces[]={1,5,17,37,113,487,1021};
            while(time<target) {
                const auto bound=partition=="single" ? 1u:partition=="whole" ? 4093u:pieces[phase++%7];
                time+=std::min<std::uint64_t>(target-time,bound);cpu.ticks=time;bus->sync(cpu);drain();
            }
        };
        std::cout<<'[';std::string op;
        while(plan>>op) {
            if(op=="r") {
                bus=std::make_unique<pce::Bus>();cpu=pce::Cpu{};cpu.mpr[0]=255;
                bus->enable_adpcm();bus->enable_audio_output(pce::AudioProfile::filtered,44100,pce::AudioTiming::gear);
                for(unsigned i=0;i<65536;++i)bus->adpcm.ram[i]=static_cast<std::uint8_t>((i*37+(i>>8)*13+0x57)&255);
                time=0;phase=0;pcm.clear();
            } else if(op=="p" || op=="a") {
                std::uint64_t at;unsigned reg,value;
                if(!(plan>>at>>reg>>value) || value>255 ||
                   (op=="p" ? reg>9:(reg!=8 && reg!=9 && reg!=13 && reg!=14)))throw std::runtime_error("invalid register event");
                advance(at);cpu.ticks=at;
                bus->write(cpu,static_cast<std::uint16_t>((op=="p" ? 0x800:0x1800)+reg),static_cast<std::uint8_t>(value));
            } else if(op=="s") {
                std::uint64_t at;if(!(plan>>at))throw std::runtime_error("missing timestamp");advance(at);drain();
                if(!first)std::cout<<',';first=false;
                std::cout<<"{\"time\":"<<time<<",\"pcm\":[";
                for(unsigned i=0;i<pcm.size();i+=2){if(i)std::cout<<',';std::cout<<'['<<pcm[i]<<','<<pcm[i+1]<<']';}
                const auto& a=bus->adpcm;
                std::cout<<"],\"adpcm\":{\"predictor\":"<<a.decoder_output<<",\"index\":"<<unsigned(a.decoder_index)
                    <<",\"control\":"<<unsigned(a.control)<<",\"rate\":"<<unsigned(a.sample_rate)
                    <<",\"read_address\":"<<a.read_address<<",\"length\":"<<a.length
                    <<",\"playing\":"<<(a.playing?"true":"false")<<",\"pending\":"<<(a.play_pending?"true":"false")
                    <<",\"nibble\":"<<(a.nibble?"true":"false")<<",\"end\":"<<(a.end_irq?"true":"false")
                    <<",\"half\":"<<(a.half_irq?"true":"false")<<",\"phase\":"<<a.sample_phase<<"}}";
                pcm.clear();
            } else throw std::runtime_error("unknown plan operation");
        }
        if(!plan.eof())throw std::runtime_error("truncated plan");std::cout<<"]\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
