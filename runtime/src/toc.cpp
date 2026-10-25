#include "pce/runtime.hpp"
#include <charconv>
#include <fstream>
#include <filesystem>
#include <sstream>

namespace pce {
CdToc read_toc(const std::string& path) {
    std::ifstream stream(std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(path.c_str()))),std::ios::binary|std::ios::ate);
    if(!stream) throw Fault("cannot open TOC descriptor");
    const auto length=stream.tellg();
    if(length<=0 || length>8192) throw Fault("TOC descriptor exceeds the 8 KiB limit or is empty");
    std::string text(static_cast<std::size_t>(length),'\0');
    stream.seekg(0); stream.read(text.data(),length);
    if(!stream) throw Fault("short TOC descriptor read");
    if(text.find_first_not_of("\t\r\n abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789")!=std::string::npos)
        throw Fault("invalid character in TOC descriptor");
    std::istringstream input(text);
    auto token=[&]() { std::string word; if(!(input>>word)) throw Fault("truncated TOC descriptor"); return word; };
    auto keyword=[&](const char* expected) { if(token()!=expected) throw Fault("unexpected TOC descriptor field"); };
    auto decimal=[&]() {
        const auto word=token(); std::uint32_t value=0;
        const auto parsed=std::from_chars(word.data(),word.data()+word.size(),value);
        if(parsed.ec!=std::errc{} || parsed.ptr!=word.data()+word.size()) throw Fault("invalid TOC decimal value");
        return value;
    };
    keyword("PCE_TOC"); keyword("1"); keyword("image_sha256");
    CdToc result; result.image_sha256=token();
    if(result.image_sha256.size()!=64) throw Fault("TOC descriptor requires a source SHA256");
    keyword("leadout_lba"); result.leadout_lba=decimal();
    std::string word;
    while(input>>word) {
        if(word!="track" || result.track_count>=result.tracks.size()) throw Fault("invalid or excessive TOC tracks");
        if(decimal()!=result.track_count+1) throw Fault("TOC tracks must be numbered consecutively from one");
        const auto lba=decimal(), type=decimal();
        if(type!=0 && type!=4) throw Fault("unsupported TOC track type");
        result.tracks[result.track_count++]={lba,static_cast<std::uint8_t>(type)};
    }
    result.validate(); return result;
}
} // namespace pce
