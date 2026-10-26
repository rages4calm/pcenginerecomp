// Authored observer for separately compiled ORIGINAL Gear media code.
// Input CUEs deliberately translate inter-track POSTGAP into the next virtual
// PREGAP. This is not a claim that original Gear parses CUE POSTGAP.
#include "cdrom_cuebin_image.h"
#include <array>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
bool g_mcp_stdio_mode=true;
int main(int argc,char**argv) {
    try {
        if(argc!=3)throw std::runtime_error("gear-cue-gap TRANSFORMED_AUTHORED_CUE PLAN");
        auto image=std::make_unique<CdRomCueBinImage>();image->Init();
        if(!image->LoadFromFile(argv[1],false))throw std::runtime_error("Original transformed CUE refused");
        const auto original=*image->GetTOC();
        std::ifstream plan(argv[2]);unsigned count;
        if(!(plan>>count) || count>4096)throw std::runtime_error("Invalid bounded media plan");
        for(unsigned n=0;n<count;++n) {
            char op;if(!(plan>>op))throw std::runtime_error("Truncated media plan");
            if(op=='t') {
                const auto& toc=*image->GetTOC();
                if(toc.sector_count!=original.sector_count || toc.tracks.size()!=original.tracks.size())
                    throw std::runtime_error("Original TOC observation changed geometry");
                std::cout<<"{\"kind\":\"toc\",\"leadout\":"<<toc.sector_count<<",\"tracks\":[";
                for(unsigned i=0;i<toc.tracks.size();++i) {
                    if(toc.tracks[i].start_lba!=original.tracks[i].start_lba || toc.tracks[i].type!=original.tracks[i].type)
                        throw std::runtime_error("Original TOC observation changed tracks");
                    std::cout<<(i?",":"")<<'['<<toc.tracks[i].start_lba<<','<<(toc.tracks[i].type==GG_CDROM_AUDIO_TRACK?0:4)<<']';
                }
                std::cout<<"]}\n";
            } else {
                unsigned lba;if(!(plan>>lba) || lba>449849)throw std::runtime_error("Bounded LBA required");
                if(op=='p')std::cout<<"{\"kind\":\"playable\",\"lba\":"<<lba<<",\"value\":"<<(image->IsPlayableAudioSector(lba)?"true":"false")<<"}\n";
                else if(op=='a') {
                    std::array<s16,1176> samples{};const bool ok=image->ReadSamples(lba,0,samples.data(),samples.size());
                    std::cout<<"{\"kind\":\"audio\",\"lba\":"<<lba<<",\"ok\":"<<(ok?"true":"false");
                    if(ok) {std::cout<<",\"samples\":[";for(unsigned i=0;i<samples.size();++i)std::cout<<(i?",":"")<<samples[i];std::cout<<']';}
                    else std::cout<<",\"error\":\"unavailable_audio\"";
                    std::cout<<"}\n";
                } else if(op=='d') {
                    std::array<u8,2048> data{};if(!image->ReadSector(lba,data.data()))throw std::runtime_error("Original declared program data refused");
                    constexpr char digits[]="0123456789abcdef";
                    std::cout<<"{\"kind\":\"data\",\"lba\":"<<lba<<",\"ok\":true,\"bytes\":\"";
                    for(auto value:data)std::cout<<digits[value>>4]<<digits[value&15];std::cout<<"\"}\n";
                } else throw std::runtime_error("Unsupported original media operation");
            }
        }
        std::string extra;if(plan>>extra)throw std::runtime_error("Trailing media plan token");return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
