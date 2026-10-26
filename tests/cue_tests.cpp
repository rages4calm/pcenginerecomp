#include "pce/sector.hpp"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <string_view>
#include <vector>

namespace {
namespace fs=std::filesystem;
unsigned checks=0;
void require(bool value,const char* message) {++checks;if(!value)throw std::runtime_error(message);}
template<class F> void refuses(F operation) {
    bool refused=false;
    try {operation();}catch(const pce::Fault&) {refused=true;}
    require(refused,"CUE provider accepted an unsupported or changed input");
}
template<class F> void media_error(F operation,pce::SectorReadReason reason,std::uint32_t lba) {
    bool refused=false;
    try {operation();}catch(const pce::SectorReadError& error) {refused=error.reason==reason && error.lba==lba;}
    require(refused,"CUE provider lost typed failure reason or LBA");
}
template<class F> void fatal(F operation) {
    bool refused=false;
    try {operation();}catch(const pce::SectorReadError&) {}catch(const pce::Fault&) {refused=true;}
    require(refused,"CUE source/host/audio failure became recoverable data media error");
}
std::string utf8(const fs::path& path) {
    const auto value=path.generic_u8string();
    return std::string(reinterpret_cast<const char*>(value.data()),value.size());
}
std::string bytes(std::u8string_view value) {return {reinterpret_cast<const char*>(value.data()),value.size()};}
struct Files {
    fs::path dir;
    std::vector<fs::path> owned;
    Files() {
        dir=fs::temp_directory_path()/("pce-cue-tests-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        if(!fs::create_directory(dir))throw std::runtime_error("Cannot create CUE test directory");
    }
    ~Files() {
        std::error_code error;
        for(auto it=owned.rbegin();it!=owned.rend();++it)fs::remove(*it,error);
        fs::remove(dir,error);
    }
    std::string write(const std::string& name,const std::vector<std::uint8_t>& bytes) {
        const auto path=dir/fs::path(std::u8string(reinterpret_cast<const char8_t*>(name.data()),name.size()));
        if(std::find(owned.begin(),owned.end(),path)==owned.end())owned.push_back(path);
        std::ofstream stream(path,std::ios::binary|std::ios::trunc);
        stream.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));
        if(!stream)throw std::runtime_error("Cannot write authored CUE file");
        return utf8(path);
    }
    std::string text(const std::string& name,const std::string& value) {return write(name,{value.begin(),value.end()});}
};
std::vector<std::uint8_t> pattern(unsigned size,unsigned multiplier,unsigned add) {
    std::vector<std::uint8_t> value(size);
    for(unsigned i=0;i<size;++i)value[i]=static_cast<std::uint8_t>(i*multiplier+add);
    return value;
}
std::vector<std::uint8_t> mixed() {
    std::vector<std::uint8_t> value(6*2352);
    for(unsigned f=0;f<6;++f) {
        for(unsigned i=0;i<2352;++i)value[f*2352+i]=static_cast<std::uint8_t>(f*23+i*7);
        value[f*2352]=0;std::fill_n(value.begin()+f*2352+1,10,255);value[f*2352+11]=0;value[f*2352+15]=1;
    }
    return value;
}
const std::string cue=R"(REM authored independent cue provider fixture
FILE "mixed.bin" BINARY
 TRACK 01 MODE1/2352
  INDEX 01 00:00:00
 TRACK 02 AUDIO
  INDEX 00 00:00:02
  INDEX 01 00:00:03
FILE "second.bin" BINARY
 TRACK 03 AUDIO
  PREGAP 00:00:02
  INDEX 01 00:00:00
FILE "third.bin" BINARY
 TRACK 04 AUDIO
  INDEX 00 00:00:00
  INDEX 01 00:00:01
FILE "cooked.bin" BINARY
 TRACK 05 MODE1/2048
  INDEX 01 00:00:00
)";
std::string media(Files& files) {
    files.write("mixed.bin",mixed());
    files.write("second.bin",pattern(4*2352,13,97));
    files.write("third.bin",pattern(3*2352,19,11));
    files.write("cooked.bin",pattern(2*2048,17,43));
    return files.text("authored.cue",cue);
}
void expected() {
    Files files;
    const auto image=media(files);
    const auto provider=pce::open_sector_provider(image);
    const auto& toc=provider->toc();
    require(toc.track_count==5 && toc.leadout_lba==17,"CUE TOC count or leadout mismatch");
    const unsigned starts[]={0,3,8,13,15},types[]={4,0,0,0,4};
    for(unsigned i=0;i<5;++i)require(toc.tracks[i].index1_lba==starts[i] && toc.tracks[i].type==types[i],"CUE literal INDEX 01 geometry mismatch");
    // Expected digest was calculated independently with Python hashlib over
    // the exact authored CUE and deterministic file bytes, not this runtime.
    require(toc.image_sha256=="cd22d55a47b0c27385317381ef5596b0cc03d3ae4d0ce4ac4eefa5cca051dd99","CUE compound SHA256 mismatch");
    require(pce::image_sha256(image)==toc.image_sha256,"CUE identity APIs disagree");
    for(unsigned lba=0;lba<2;++lba) {
        const auto data=provider->read(lba);
        for(unsigned i=0;i<data.size();++i)require(data[i]==std::uint8_t(lba*23+(i+16)*7),"CUE raw MODE1 payload mismatch");
    }
    for(unsigned lba=15;lba<17;++lba) {
        const auto data=provider->read(lba);
        for(unsigned i=0;i<data.size();++i)require(data[i]==std::uint8_t(((lba-15)*2048+i)*17+43),"CUE cooked MODE1 payload mismatch");
    }
    for(unsigned lba=0;lba<19;++lba) {
        const bool playable=(lba>=3 && lba<=5) || (lba>=8 && lba<=14);
        require(provider->audio_playable(lba)==playable,"CUE audio payload/pregap gate mismatch");
    }
    const auto raw=mixed();
    for(unsigned lba=2;lba<6;++lba) {
        const auto samples=provider->read_audio(lba);
        for(unsigned i=0;i<samples.size();++i) {
            const unsigned word=unsigned(raw[lba*2352+i*2])|(unsigned(raw[lba*2352+i*2+1])<<8);
            const int value=word<32768?int(word):int(word)-65536;
            require(samples[i]==value,"CUE little-endian audio sample mismatch");
        }
    }
    const auto gap=provider->read_audio(12);
    require(gap[0]==0x1E0B,"Stored audio pregap lost its actual source bytes");
    for(unsigned lba:{2U,3U,6U,7U,8U,12U,13U,17U})refuses([&]{provider->read(lba);});
    for(unsigned lba:{0U,1U,6U,7U,15U,16U,17U})refuses([&]{provider->read_audio(lba);});
    for(unsigned lba:{3U,8U,13U})media_error([&]{provider->read(lba);},pce::SectorReadReason::wrong_data_track,lba);
    for(unsigned lba:{2U,6U,7U,12U})media_error([&]{provider->read(lba);},pce::SectorReadReason::unrecoverable_data,lba);
    for(unsigned lba:{17U,0xffffffffU})media_error([&]{provider->read(lba);},pce::SectorReadReason::out_of_range,lba);
    for(unsigned lba:{0U,1U,6U,7U,15U,16U,17U})fatal([&]{provider->read_audio(lba);});

    Files relocated;const auto relocated_image=media(relocated);
    require(pce::image_sha256(relocated_image)==toc.image_sha256,"CUE root relocation changed the complete-image identity");
    auto changed=mixed();changed[16]^=1;files.write("mixed.bin",changed);
    // Force observable stamp movement even on coarse timestamp filesystems.
    fs::last_write_time(files.dir/"mixed.bin",fs::last_write_time(files.dir/"mixed.bin")+std::chrono::seconds(2));
    refuses([&]{provider->read(15);});refuses([&]{provider->read_audio(8);});refuses([&]{provider->audio_playable(8);});
    fatal([&]{provider->read(15);});fatal([&]{provider->read(17);});fatal([&]{provider->read_audio(8);});
    require(pce::image_sha256(image)!=toc.image_sha256,"CUE component mutation did not change complete-image identity");
    auto fresh=pce::open_sector_provider(image);
    files.text("authored.cue",cue+"REM exact cue bytes are part of identity\n");
    refuses([&]{fresh->read(0);});refuses([&]{fresh->read_audio(3);});refuses([&]{fresh->audio_playable(3);});
    fatal([&]{fresh->read(0);});fatal([&]{fresh->read(17);});
    require(pce::image_sha256(image)!=fresh->toc().image_sha256,"CUE text mutation did not change complete-image identity");
}
void malformed() {
    Files files;media(files);
    const std::string begin="FILE cooked.bin BINARY\nTRACK 01 MODE1/2048\n";
    const std::string simple=begin+"INDEX 01 00:00:00\n";
    const std::vector<std::string> bad={
        "", "REM only a comment\n", "FILE cooked.bin BINARY\n", "TRACK 01 AUDIO\nINDEX 01 00:00:00\n",
        "FILE missing.bin BINARY\nTRACK 01 AUDIO\nINDEX 01 00:00:00\n",
        "FILE cooked.bin WAVE\nTRACK 01 AUDIO\nINDEX 01 00:00:00\n",
        "FILE cooked.bin BINARY\nTRACK 02 MODE1/2048\nINDEX 01 00:00:00\n",
        "FILE cooked.bin BINARY\nTRACK 01 MODE2/2352\nINDEX 01 00:00:00\n",
        begin,begin+"INDEX 00 00:00:00\n",begin+"INDEX 01 00:00:01\n",
        begin+"INDEX 01 00:00:00\nINDEX 00 00:00:00\n",
        begin+"INDEX 01 00:00:00\nINDEX 01 00:00:00\n",
        begin+"INDEX 02 00:00:00\n",begin+"INDEX 01 0:00:00\n",begin+"INDEX 01 00:60:00\n",
        begin+"INDEX 01 00:00:75\n",begin+"INDEX 01 -1:00:00\n",
        begin+"PREGAP 00:00:01\nINDEX 01 00:00:00\n",
        simple+"PREGAP 00:00:00\n",simple+"POSTGAP 00:00:01\nPOSTGAP 00:00:01\n",simple+"FLAGS PRE\n",simple+"INVENTED 5\n",
        simple+"TRACK 02 AUDIO\nINDEX 01 00:00:01\n",
        simple+"TRACK 02 MODE1/2048\nINDEX 01 00:00:00\n",
        simple+"TRACK 02 MODE1/2048\nINDEX 01 00:00:03\n",
        simple+"TRACK 02 MODE1/2048\nPREGAP 00:00:01\nINDEX 00 00:00:00\nINDEX 01 00:00:01\n",
        simple+"FILE cooked.bin BINARY\nTRACK 02 MODE1/2048\nINDEX 01 00:00:00\n",
        "FILE ../cooked.bin BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n",
        "FILE ./cooked.bin BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n",
        "FILE /cooked.bin BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n",
        "FILE C:\\cooked.bin BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n",
        "FILE \"cooked.bin\"suffix BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n",
        "FILE \"unterminated BINARY\n",simple+std::string("REM \xC0\xAF\n"),simple+std::string("REM \xED\xA0\x80\n"),
        simple+std::string("REM \xF4\x90\x80\x80\n"),simple+std::string("REM \0oops\n",10),
        simple+"TITLE\n",simple+"PERFORMER\n",simple+"SONGWRITER\n",simple+"CATALOG\n",simple+"ISRC\n",
        simple+"REM embedded\rcarriage return\n",simple+"TITLE embedded\rcarriage return\n",
        simple+"REM vertical\vtab\n",simple+"REM form\ffeed\n",simple+"REM delete\x7f\n"
    };
    for(const auto& text:bad) {const auto image=files.text("bad.cue",text);refuses([&]{pce::open_sector_provider(image);});refuses([&]{pce::image_sha256(image);});}
    files.write("empty.bin",{});files.write("partial.bin",{1,2,3});
    for(const auto& name:{"empty.bin","partial.bin"}) {
        const auto image=files.text("bad.cue","FILE "+std::string(name)+" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n");
        refuses([&]{pce::open_sector_provider(image);});
    }
    auto corrupt=mixed();corrupt[15]=2;files.write("mixed.bin",corrupt);
    const auto raw_image=files.text("raw.cue","FILE mixed.bin BINARY\nTRACK 01 MODE1/2352\nINDEX 01 00:00:00\n");
    const auto provider=pce::open_sector_provider(raw_image);refuses([&]{provider->read(0);});
    media_error([&]{provider->read(0);},pce::SectorReadReason::media_data_error,0);
    auto upper=files.text("uppercase.CUE","file cooked.bin binary\r\ntrack 01 mode1/2048\r\nindex 01 00:00:00\r\n");
    require(pce::open_sector_provider(upper)->read(0)[0]==43,"CUE case/CRLF support failed");
    auto bom=files.text("bom.cue",std::string("\xEF\xBB\xBF")+simple);
    require(pce::open_sector_provider(bom)->toc().leadout_lba==2,"CUE UTF8 BOM support failed");
    auto comment=files.text("comment.cue","REM unmatched \" comment is opaque\n"+simple);
    require(pce::open_sector_provider(comment)->read(0)[0]==43,"CUE REM comment tokenization failed");
    std::string self="FILE self.cue BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\nREM ";
    self.append(2048-self.size()-1,'x');self+='\n';
    const auto self_image=files.text("self.cue",self);
    refuses([&]{pce::open_sector_provider(self_image);});
    // Explicit byte-order extrema, including the most negative signed sample.
    auto audio=pattern(2352,1,0);const std::uint8_t extrema[]={0,0,255,127,0,128,255,255};
    std::copy(std::begin(extrema),std::end(extrema),audio.begin());files.write("audio.bin",audio);
    const auto audio_image=files.text("audio.cue","FILE audio.bin BINARY\nTRACK 01 AUDIO\nINDEX 01 00:00:00\n");
    const auto samples=pce::open_sector_provider(audio_image)->read_audio(0);
    require(samples[0]==0 && samples[1]==32767 && samples[2]==-32768 && samples[3]==-1,"CUE signed little-endian extrema failed");
}
void paths() {
    Files files;
    const auto folder=files.dir/"tracks";
    require(fs::create_directory(folder),"Cannot create authored CUE subdirectory");files.owned.push_back(folder);
    const auto filename=utf8(fs::path(u8"tracks/data ü.bin"));
    files.write(filename,pattern(2048,17,43));
    const auto image=files.text("paths.cue",bytes(u8"FILE \"tracks\\data ü.bin\" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n"));
    require(pce::open_sector_provider(image)->read(0)[0]==43,"CUE quoted UTF8 or backslash filename failed");
    const auto original=pce::image_sha256(image);
    files.text("paths.cue",bytes(u8"FILE \"tracks/data ü.bin\" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n"));
    require(pce::image_sha256(image)!=original,"Exact CUE text change was incorrectly canonicalized out of identity");
    // Symlink cases are exercised when the host permits authored symlinks.
    // Windows without Developer Mode may refuse creation; no owner path used.
    Files outside;outside.write("payload.bin",pattern(2048,1,0));
    std::error_code error;
    const auto link=files.dir/"link.bin";
    fs::create_symlink(outside.dir/"payload.bin",link,error);
    if(!error) {
        files.owned.push_back(link);
        const auto escaped=files.text("escape.cue","FILE link.bin BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n");
        refuses([&]{pce::open_sector_provider(escaped);});
        fs::remove(link);fs::create_symlink(folder/fs::path(u8"data ü.bin"),link);
        const auto provider=pce::open_sector_provider(escaped);
        fs::remove(link);fs::create_symlink(outside.dir/"payload.bin",link);
        refuses([&]{provider->read(0);});refuses([&]{provider->audio_playable(0);});refuses([&]{provider->read_audio(0);});
    } else std::cout<<"CUE authored symlink creation unavailable on this host\n";
}
}
int main() {
    try {expected();malformed();paths();std::cout<<"CUE provider checks: "<<checks<<'\n';return 0;}
    catch(const std::exception& error) {std::cerr<<"CUE provider test failed: "<<error.what()<<'\n';return 1;}
}
