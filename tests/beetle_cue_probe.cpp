// Authored media observer linked to separately compiled, unchanged original
// Beetle/Mednafen implementations. No toolkit media/device implementation.
#include <libretro.h>
#include <mednafen/mednafen.h>
#include <mednafen/cdrom/CDAccess.h>
#include <array>
#include <cstdarg>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
std::string directory;
void log_message(enum retro_log_level,const char* format,...) {
    va_list values;va_start(values,format);std::vfprintf(stderr,format,values);va_end(values);
}
bool environment(unsigned command,void* data) {
    if(command==RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY || command==RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY) {
        *static_cast<const char**>(data)=directory.c_str();return true;
    }
    if(command==RETRO_ENVIRONMENT_GET_LOG_INTERFACE) {
        static_cast<retro_log_callback*>(data)->log=log_message;return true;
    }
    return false;
}
void hex(const std::uint8_t* data,unsigned size) {
    constexpr char digits[]="0123456789abcdef";
    for(unsigned n=0;n<size;++n)std::cout<<digits[data[n]>>4]<<digits[data[n]&15];
}
void samples(const std::uint8_t* raw) {
    for(unsigned n=0;n<1176;++n) {
        const unsigned value=unsigned(raw[2*n])|(unsigned(raw[2*n+1])<<8);
        std::cout<<(n?",":"")<<(value<32768?int(value):int(value)-65536);
    }
}
}
int main(int argc,char**argv) {
    try {
        if(argc!=3)throw std::runtime_error("beetle-cue AUTHORED_CUE PLAN");
        directory=std::filesystem::absolute(argv[1]).parent_path().string();
        retro_set_environment(environment);retro_init();
        auto image=std::unique_ptr<CDAccess>(CDAccess_Open(argv[1],false));
        if(!image)throw std::runtime_error("Original media open failed");
        TOC toc;if(!image->Read_TOC(&toc) || toc.first_track!=1 || toc.last_track<1 || toc.last_track>99)
            throw std::runtime_error("Original bounded TOC unavailable");
        std::ifstream plan(argv[2]);unsigned count;
        if(!(plan>>count) || count>4096)throw std::runtime_error("Invalid bounded media plan");
        for(unsigned n=0;n<count;++n) {
            char op;if(!(plan>>op))throw std::runtime_error("Truncated media plan");
            if(op=='t') {
                TOC second;if(!image->Read_TOC(&second))throw std::runtime_error("Repeated TOC unavailable");
                if(second.first_track!=toc.first_track || second.last_track!=toc.last_track ||
                   second.tracks[100].lba!=toc.tracks[100].lba)throw std::runtime_error("TOC observation changed geometry");
                std::cout<<"{\"kind\":\"toc\",\"leadout\":"<<toc.tracks[100].lba<<",\"tracks\":[";
                for(unsigned t=1;t<=toc.last_track;++t) {
                    if(second.tracks[t].lba!=toc.tracks[t].lba || second.tracks[t].control!=toc.tracks[t].control)
                        throw std::runtime_error("TOC observation changed track");
                    std::cout<<(t>1?",":"")<<'['<<toc.tracks[t].lba<<','<<(toc.tracks[t].control&4)<<']';
                }
                std::cout<<"]}\n";
            } else {
                unsigned lba;if(!(plan>>lba) || lba>=toc.tracks[100].lba || (op!='d' && op!='a' && op!='m'))
                    throw std::runtime_error("Unsupported or out-of-range original raw request");
                std::array<std::uint8_t,2448> bytes{};
                if(!image->Read_Raw_Sector(bytes.data(),static_cast<std::int32_t>(lba)))
                    throw std::runtime_error("Original raw sector refused");
                if(op=='d') {
                    std::cout<<"{\"kind\":\"data\",\"lba\":"<<lba<<",\"ok\":true,\"bytes\":\"";
                    hex(bytes.data()+16,2048);std::cout<<"\"}\n";
                } else {
                    std::cout<<"{\"kind\":\""<<(op=='a'?"audio":"pcm")<<"\",\"lba\":"<<lba;
                    if(op=='a')std::cout<<",\"ok\":true";
                    std::cout<<",\"samples\":[";samples(bytes.data());std::cout<<"]}\n";
                }
            }
        }
        std::string extra;if(plan>>extra)throw std::runtime_error("Trailing media plan token");
        image.reset();retro_deinit();return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
