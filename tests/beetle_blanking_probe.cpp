// Authored full-core frontend for palette-distinguishing synthetic HuCards.
// The GPL core is compiled separately and is never linked into pce-runtime.
#include <libretro.h>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::string directory;
unsigned frames=0;
bool accepted_format=false;
std::vector<std::uint16_t> rows;
unsigned width=0,height=0;
void message(enum retro_log_level,const char* format,...) {
    va_list args;va_start(args,format);std::vfprintf(stderr,format,args);va_end(args);
}
bool environment(unsigned command,void* data) {
    switch(command) {
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        *static_cast<const char**>(data)=directory.c_str();return true;
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
        static_cast<retro_log_callback*>(data)->log=message;return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
        accepted_format=*static_cast<retro_pixel_format*>(data)==RETRO_PIXEL_FORMAT_RGB565;
        return accepted_format;
    case RETRO_ENVIRONMENT_GET_CAN_DUPE:*static_cast<bool*>(data)=true;return true;
    default:return false;
    }
}
void video(const void* data,unsigned w,unsigned h,std::size_t pitch) {
    if(!data)return;
    if(!accepted_format || !w || !h || w>1024 || h>512 || pitch<w*2)
        throw std::runtime_error("Unexpected original core framebuffer");
    width=w;height=h;rows.resize(h);
    for(unsigned y=0;y<h;++y) {
        const auto* row=reinterpret_cast<const std::uint16_t*>(static_cast<const std::uint8_t*>(data)+y*pitch);
        rows[y]=row[w/2];
    }
    ++frames;
}
void audio(std::int16_t,std::int16_t){}
std::size_t samples(const std::int16_t*,std::size_t n){return n;}
void poll(){}
std::int16_t input(unsigned,unsigned,unsigned,unsigned){return 0;}
}
int main(int argc,char**argv) {
    try {
        if(argc!=2)throw std::runtime_error("beetle-blanking AUTHORED_ROM");
        const auto rom=std::filesystem::absolute(argv[1]);
        if(!std::filesystem::is_regular_file(rom)||std::filesystem::file_size(rom)!=262144)
            throw std::runtime_error("Authored 256 KiB ROM required");
        directory=rom.parent_path().string();
        retro_set_environment(environment);retro_set_video_refresh(video);
        retro_set_audio_sample(audio);retro_set_audio_sample_batch(samples);
        retro_set_input_poll(poll);retro_set_input_state(input);retro_init();
        const auto name=rom.string();const retro_game_info game{name.c_str(),nullptr,0,nullptr};
        if(!retro_load_game(&game))throw std::runtime_error("Original full core load failed");
        for(unsigned n=0;n<30;++n)retro_run();
        if(frames<20||rows.empty())throw std::runtime_error("No settled original frames");
        const auto* ram=static_cast<const std::uint8_t*>(retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM));
        if(!ram||retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM)<0x42)
            throw std::runtime_error("Original system RAM markers unavailable");
        std::cout<<"{\"schema\":1,\"format\":\"authored-blanking-frame-1\",\"frames\":"<<frames
            <<",\"pixel_format\":\"RGB565\",\"width\":"<<width<<",\"height\":"<<height<<",\"center_rows\":[";
        for(unsigned n=0;n<rows.size();++n)std::cout<<(n?",":"")<<rows[n];
        std::cout<<"],\"markers\":{\"disabled\":"<<unsigned(ram[0x40])
            <<",\"reenabled\":"<<unsigned(ram[0x41])<<"}}\n";
        retro_unload_game();retro_deinit();return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
