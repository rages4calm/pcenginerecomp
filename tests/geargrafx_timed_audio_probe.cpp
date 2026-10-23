// Authored public-API driver; external GPL sources are compiled separately.
#include "geargrafx_core.h"
#include "audio.h"
#include "adpcm.h"
#include "huc6280_psg.h"
#include "cdrom_audio.h"
#include <algorithm>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
bool g_mcp_stdio_mode=true;
namespace {
template<class T>T field(const std::string& bytes,unsigned offset) {
    T value{};std::memcpy(&value,bytes.data()+offset,sizeof(value));return value;
}
void samples(const std::vector<s16>& values) {
    std::cout<<'[';for(unsigned i=0;i<values.size();i+=2) {
        if(i)std::cout<<',';std::cout<<'['<<values[i]<<','<<values[i+1]<<']';
    }std::cout<<']';
}
}
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: gear-timed-audio psg|adpcm|mixed PLAN whole|parts|single");
        const std::string mode=argv[1],partition=argv[3];
        if((mode!="psg" && mode!="adpcm" && mode!="mixed") ||
           (partition!="whole" && partition!="parts" && partition!="single"))throw std::runtime_error("invalid mode/partition");
        std::ifstream plan(argv[2]);if(!plan)throw std::runtime_error("cannot open plan");
        std::unique_ptr<GeargrafxCore> core;u64 time=0;unsigned phase=0;bool first=true;
        std::vector<s16> psg_pcm,adpcm_pcm;
        const auto drain=[&] {
            s16 p[GG_AUDIO_BUFFER_SIZE],a[GG_AUDIO_BUFFER_SIZE];
            const auto pn=core->GetAudio()->GetPSG()->EndFrame(p),an=core->GetAdpcm()->EndFrame(a);
            core->GetCDROMAudio()->EndFrame(nullptr);
            if(pn!=an || pn<0 || pn>GG_AUDIO_BUFFER_SIZE || (pn&1))throw std::runtime_error("source lengths disagree");
            psg_pcm.insert(psg_pcm.end(),p,p+pn);adpcm_pcm.insert(adpcm_pcm.end(),a,a+an);
        };
        const auto advance=[&](u64 target) {
            if(!core || target<time || target-time>21477273)throw std::runtime_error("invalid finite timestamp");
            constexpr unsigned pieces[]={1,5,17,37,113,487,1021};
            while(time<target) {
                const auto bound=partition=="single" ? 1u:partition=="whole" ? 4093u:pieces[phase++%7];
                const auto step=static_cast<u32>(std::min<u64>(target-time,bound));
                core->GetAudio()->Clock(step);time+=step;drain();
            }
        };
        std::cout<<'[';std::string op;
        while(plan>>op) {
            if(op=="r") {
                core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
                core->GetAudio()->Reset(true);core->GetAdpcm()->Reset();
                core->GetAudio()->GetPSG()->EnableHuC6280A(true);
                for(unsigned i=0;i<65536;++i)core->GetAdpcm()->GetRAM()[i]=static_cast<u8>((i*37+(i>>8)*13+0x57)&255);
                time=0;phase=0;psg_pcm.clear();adpcm_pcm.clear();
            } else if(op=="p" || op=="a") {
                u64 at;unsigned reg,value;
                if(!(plan>>at>>reg>>value) || value>255 ||
                   (op=="p" ? reg>9:(reg!=8 && reg!=9 && reg!=13 && reg!=14)))throw std::runtime_error("invalid register event");
                advance(at);
                if(op=="p")core->GetAudio()->WritePSG(reg,static_cast<u8>(value));
                else core->GetAdpcm()->Write(reg,static_cast<u8>(value));
            } else if(op=="s") {
                u64 at;if(!(plan>>at))throw std::runtime_error("missing timestamp");advance(at);drain();
                if(!first)std::cout<<',';first=false;
                std::vector<s16> mixed(psg_pcm.size());
                for(unsigned i=0;i<mixed.size();++i)mixed[i]=static_cast<s16>(((mode!="adpcm" ? int(psg_pcm[i]):0)+(mode!="psg" ? int(adpcm_pcm[i]):0))/3);
                std::cout<<"{\"time\":"<<time<<",\"pcm\":";samples(mixed);
                std::cout<<",\"psg\":";samples(psg_pcm);std::cout<<",\"adpcm_pcm\":";samples(adpcm_pcm);
                std::ostringstream saved(std::ios::binary);core->GetAdpcm()->SaveState(saved);const auto bytes=saved.str();
                if(bytes.size()!=65599)throw std::runtime_error("pinned ADPCM state layout changed");
                const auto tail=bytes.substr(65536);
                std::cout<<",\"adpcm\":{\"predictor\":"<<field<s16>(tail,36)<<",\"index\":"<<unsigned(field<u8>(tail,38))
                    <<",\"control\":"<<unsigned(field<u8>(tail,21))<<",\"rate\":"<<unsigned(field<u8>(tail,16))
                    <<",\"read_address\":"<<field<u16>(tail,10)<<",\"length\":"<<field<u32>(tail,32)
                    <<",\"playing\":"<<(field<u8>(tail,29)?"true":"false")<<",\"pending\":"<<(field<u8>(tail,30)?"true":"false")
                    <<",\"nibble\":"<<(field<u8>(tail,31)?"true":"false")<<",\"end\":"<<(field<u8>(tail,27)?"true":"false")
                    <<",\"half\":"<<(field<u8>(tail,28)?"true":"false")<<",\"phase\":"<<field<s32>(tail,39)<<"}}";
                psg_pcm.clear();adpcm_pcm.clear();
            } else throw std::runtime_error("unknown plan operation");
        }
        if(!plan.eof())throw std::runtime_error("truncated plan");std::cout<<"]\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
