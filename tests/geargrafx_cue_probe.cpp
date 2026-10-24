// Authored public-API adapter for a separately compiled GPL Geargrafx oracle.
// This file does not include or link the toolkit runtime.
#include "cdrom_cuebin_image.h"
#include <array>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
bool g_mcp_stdio_mode=true;
namespace {
void hex(const u8* bytes,unsigned count) {
    constexpr char digits[]="0123456789abcdef";
    for(unsigned i=0;i<count;++i)std::cout<<digits[bytes[i]>>4]<<digits[bytes[i]&15];
}
}
int main(int argc,char** argv) {
    try {
        if(argc!=3)throw std::runtime_error("usage: gear-cue IMAGE PLAN");
        auto image=std::make_unique<CdRomCueBinImage>();image->Init();
        if(!image->LoadFromFile(argv[1],false))throw std::runtime_error("Gear refused authored CUE");
        std::ifstream plan(argv[2]);unsigned count=0;
        if(!(plan>>count)||count>1024)throw std::runtime_error("bad bounded CUE plan");
        const auto& toc=*image->GetTOC();
        std::cout<<"{\"leadout\":"<<toc.sector_count<<",\"tracks\":[";
        for(unsigned i=0;i<toc.tracks.size();++i) {
            if(i)std::cout<<',';const auto& track=toc.tracks[i];
            std::cout<<'['<<track.start_lba<<','<<(track.type==GG_CDROM_AUDIO_TRACK?0:4)<<']';
        }
        std::cout<<"],\"observations\":[";
        for(unsigned i=0;i<count;++i) {
            char op;u32 lba;if(!(plan>>op>>lba))throw std::runtime_error("truncated CUE plan");
            if(i)std::cout<<',';std::cout<<"{\"op\":\""<<op<<"\",\"lba\":"<<lba;
            if(op=='p')std::cout<<",\"playable\":"<<(image->IsPlayableAudioSector(lba)?"true":"false");
            else if(op=='d') {
                std::array<u8,2048> bytes{};if(!image->ReadSector(lba,bytes.data()))throw std::runtime_error("Gear data read refused");
                std::cout<<",\"bytes\":\"";hex(bytes.data(),bytes.size());std::cout<<'"';
            } else if(op=='a') {
                std::array<s16,1176> samples{};
                if(!image->ReadSamples(lba,0,samples.data(),1176))throw std::runtime_error("Gear audio read refused");
                std::cout<<",\"samples\":[";
                for(unsigned j=0;j<samples.size();++j){if(j)std::cout<<',';std::cout<<samples[j];}std::cout<<']';
            } else throw std::runtime_error("unknown CUE plan operation");
            std::cout<<'}';
        }
        std::string extra;if(plan>>extra)throw std::runtime_error("trailing CUE plan data");
        std::cout<<"]}\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
