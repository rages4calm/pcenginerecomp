// Authored ABI double, NOT a CHD decoder. Tests provider mapping independently
// of compression: test files store decoded hunks directly after byte 4096.
#include <cstdint>
#include <fstream>
#include <string>
#ifdef _WIN32
#define EXPORTED extern "C" __declspec(dllexport)
#else
#define EXPORTED extern "C" __attribute__((visibility("default")))
#endif
struct FixtureDecoder {
    std::ifstream input;
    unsigned hunk=0,partial_hunk=0;
    bool refuse=false,partial_once=false,failed=false;
};
EXPORTED int chd_open(const char* path,int mode,void* parent,void** out) {
    if(!out || mode!=1 || parent) return 1;
    *out=nullptr;
    auto decoder=new FixtureDecoder;
    decoder->input.open(path,std::ios::binary);
    unsigned char header[124]{};
    decoder->input.read(reinterpret_cast<char*>(header),124);
    if(!decoder->input) {delete decoder;return 1;}
    decoder->hunk=(unsigned(header[56])<<24)|(unsigned(header[57])<<16)|(unsigned(header[58])<<8)|header[59];
    decoder->refuse=header[16]==0xEE;
    decoder->partial_once=header[17]==0xFD;decoder->partial_hunk=header[18];
    *out=decoder;return 0;
}
EXPORTED int chd_read(void* handle,std::uint32_t number,void* out) {
    auto decoder=static_cast<FixtureDecoder*>(handle);
    if(!decoder || !out || decoder->refuse) return 1;
    if(decoder->partial_once && !decoder->failed && number==decoder->partial_hunk) {
        std::fill_n(static_cast<unsigned char*>(out),decoder->hunk,0xA5);
        decoder->failed=true;return 1;
    }
    decoder->input.clear();
    decoder->input.seekg(4096ULL+std::uint64_t(number)*decoder->hunk);
    decoder->input.read(static_cast<char*>(out),decoder->hunk);
    return decoder->input?0:1;
}
EXPORTED void chd_close(void* handle) {delete static_cast<FixtureDecoder*>(handle);}
