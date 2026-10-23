#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <span>
#include <stdexcept>
#include <string>

namespace pce {
// Explicit, bounded diagnostic capture. Never appends to or replaces a file.
class WaveWriter {
    std::FILE* file_=nullptr;
    std::uint32_t limit_,written_=0,rate_;
    bool truncated_=false;
    void word(std::uint32_t value,unsigned bytes) {
        for(unsigned i=0;i<bytes;++i)if(std::fputc((value>>(i*8))&255,file_)==EOF)throw std::runtime_error("WAV write failed");
    }
    void header() {
        if(std::fseek(file_,0,SEEK_SET))throw std::runtime_error("WAV header seek failed");
        if(std::fwrite("RIFF",1,4,file_)!=4)throw std::runtime_error("WAV header write failed");
        word(36+written_*4,4);
        if(std::fwrite("WAVEfmt ",1,8,file_)!=8)throw std::runtime_error("WAV header write failed");
        word(16,4);word(1,2);word(2,2);word(rate_,4);word(rate_*4,4);word(4,2);word(16,2);
        if(std::fwrite("data",1,4,file_)!=4)throw std::runtime_error("WAV header write failed");
        word(written_*4,4);
    }
public:
    WaveWriter(const std::string& path,std::uint32_t max_frames,unsigned rate=44100):limit_(max_frames),rate_(rate) {
        if((rate!=44100 && rate!=48000) || !max_frames || max_frames>rate*120)
            throw std::runtime_error("WAV capture requires 44100 or 48000 Hz and 1..120 seconds of frames");
        const auto p=std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(path.c_str())));
#ifdef _WIN32
        file_=_wfopen(p.c_str(),L"wbx");
#else
        file_=std::fopen(p.c_str(),"wbx");
#endif
        if(!file_)throw std::runtime_error("Cannot create new WAV capture");
        try{header();}catch(...){std::fclose(file_);file_=nullptr;throw;}
    }
    WaveWriter(const WaveWriter&)=delete;
    WaveWriter& operator=(const WaveWriter&)=delete;
    ~WaveWriter(){if(file_)std::fclose(file_);}
    void write(std::span<const std::int16_t> samples) {
        if(!file_ || samples.size()%2)throw std::runtime_error("Invalid WAV stereo write");
        const auto frames=samples.size()/2;
        const auto count=std::min<std::size_t>(frames,limit_-written_);
        for(std::size_t i=0;i<count*2;++i)word(static_cast<std::uint16_t>(samples[i]),2);
        written_+=static_cast<std::uint32_t>(count);if(count<frames)truncated_=true;
    }
    void finish() {
        if(!file_)return;
        header();const auto failed=std::fclose(file_);file_=nullptr;
        if(failed)throw std::runtime_error("WAV finalization failed");
    }
    std::uint32_t frames() const{return written_;}
    bool truncated() const{return truncated_;}
};
} // namespace pce
