#include "pce/sector.hpp"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {
namespace fs=std::filesystem;
unsigned checks=0;
void require(bool condition,const char* message) {++checks;if(!condition) throw std::runtime_error(message);}
template<class F> void refuses(F operation,const char* contains="") {
    bool failed=false;
    try {operation();} catch(const pce::Fault& error) {
        failed=std::string(error.what()).find(contains)!=std::string::npos;
    }
    require(failed,"Provider did not refuse expected invalid input");
}
template<class F> void media_error(F operation,pce::SectorReadReason reason,std::uint32_t lba) {
    bool failed=false;
    try {operation();}catch(const pce::SectorReadError& error) {failed=error.reason==reason && error.lba==lba;}
    require(failed,"Provider lost the typed media-read reason or failing LBA");
}
template<class F> void fatal(F operation) {
    bool failed=false;
    try {operation();}catch(const pce::SectorReadError&) {}catch(const pce::Fault&) {failed=true;}
    require(failed,"Provider converted fatal source/configuration failure to recoverable media error");
}
struct Files {
    fs::path dir;
    std::vector<fs::path> owned;
    Files() {
        dir=fs::temp_directory_path()/("pce-sector-tests-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        if(!fs::create_directory(dir)) throw std::runtime_error("Cannot create isolated provider test directory");
    }
    ~Files() {std::error_code error;for(auto& path:owned) fs::remove(path,error);fs::remove(dir,error);}
    std::string write(const std::string& name,const std::vector<std::uint8_t>& bytes) {
        auto path=dir/name;
        if(std::find(owned.begin(),owned.end(),path)==owned.end()) owned.push_back(path);
        std::ofstream output(path,std::ios::binary|std::ios::trunc);
        output.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
        if(!output) throw std::runtime_error("Cannot write authored provider fixture");
        return path.string();
    }
    std::string text(const std::string& name,const std::string& text) {
        return write(name,std::vector<std::uint8_t>(text.begin(),text.end()));
    }
};
void put32(std::vector<std::uint8_t>& bytes,std::size_t at,std::uint32_t value) {
    for(unsigned i=0;i<4;++i) bytes[at+3-i]=static_cast<std::uint8_t>(value>>(8*i));
}
void put64(std::vector<std::uint8_t>& bytes,std::size_t at,std::uint64_t value) {
    for(unsigned i=0;i<8;++i) bytes[at+7-i]=static_cast<std::uint8_t>(value>>(8*i));
}
std::uint8_t pattern(unsigned frame,unsigned offset) {return static_cast<std::uint8_t>(frame*37+offset*11+17);}
std::vector<std::uint8_t> chd() {
    std::vector<std::uint8_t> bytes(4096+20*2448);
    const std::string magic="MComprHD";
    std::copy(magic.begin(),magic.end(),bytes.begin());
    put32(bytes,8,124);put32(bytes,12,5);put64(bytes,32,20*2448);put64(bytes,48,124);
    put32(bytes,56,4*2448);put32(bytes,60,2448);
    const std::string records[]={
        "TRACK:1 TYPE:AUDIO SUBTYPE:NONE FRAMES:5 PREGAP:0 PGTYPE:AUDIO PGSUB:NONE POSTGAP:0",
        "TRACK:2 TYPE:MODE1_RAW SUBTYPE:NONE FRAMES:6 PREGAP:2 PGTYPE:V PGSUB:NONE POSTGAP:0",
        "TRACK:3 TYPE:MODE1 SUBTYPE:NONE FRAMES:3 PREGAP:3 PGTYPE:MODE1 PGSUB:NONE POSTGAP:2"};
    std::size_t at=124;
    for(unsigned i=0;i<3;++i) {
        for(unsigned j=0;j<4;++j) bytes[at+j]=static_cast<std::uint8_t>("CHT2"[j]);
        auto size=records[i].size()+1;
        put32(bytes,at+4,static_cast<std::uint32_t>(size));put64(bytes,at+8,i==2?0:at+16+size);
        std::copy(records[i].begin(),records[i].end(),bytes.begin()+at+16);at+=16+size;
    }
    for(unsigned f=0;f<20;++f) for(unsigned i=0;i<2448;++i) bytes[4096+f*2448+i]=pattern(f,i);
    for(unsigned f=10;f<14;++f) {
        auto raw=bytes.data()+4096+f*2448;
        raw[0]=raw[11]=0;std::fill(raw+1,raw+11,255);raw[15]=1;
    }
    return bytes;
}
void test_hash(Files& files) {
    const std::pair<std::string,std::string> vectors[]={
        {"","e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
        {"abc","ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"},
        {"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq","248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"},
        {std::string(1000000,'a'),"cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"}};
    for(auto& [input,expected]:vectors) require(pce::image_sha256(files.text("hash.bin",input))==expected,"SHA256 known-answer mismatch");
}
void test_iso(Files& files) {
    std::vector<std::uint8_t> bytes(7*2048);
    for(unsigned lba=0;lba<7;++lba) for(unsigned i=0;i<2048;++i) bytes[lba*2048+i]=pattern(lba,i);
    auto path=files.write("disc.ISO",bytes);
    auto provider=pce::open_sector_provider(path);
    require(provider->toc().track_count==1 && provider->toc().tracks[0].index1_lba==0 && provider->toc().tracks[0].type==4
        && provider->toc().leadout_lba==7,"ISO TOC mismatch");
    require(provider->toc().image_sha256==pce::image_sha256(path),"ISO identity mismatch");
    for(unsigned lba:{6U,0U,3U,1U,6U}) {
        auto sector=provider->read(lba);
        for(unsigned i=0;i<2048;++i) require(sector[i]==pattern(lba,i),"ISO user-sector mismatch");
    }
    refuses([&]{provider->read(7);},"outside ISO");refuses([&]{provider->read(0xffffffff);});
    for(unsigned lba:{7U,0xffffffffU})media_error([&]{provider->read(lba);},pce::SectorReadReason::out_of_range,lba);
    fatal([&]{provider->read_audio(0);});
    bytes.push_back(1);files.write("disc.ISO",bytes);
    refuses([&]{provider->read(0);},"changed");
    fatal([&]{provider->read(0);});fatal([&]{provider->read(7);});
    refuses([&]{pce::open_sector_provider(path);},"complete");
    refuses([&]{pce::open_sector_provider(files.write("empty.iso",{}));});
    refuses([&]{pce::open_sector_provider(files.write("wrong.bin",std::vector<std::uint8_t>(2048)));});
    refuses([&]{pce::open_sector_provider((files.dir/"missing.iso").string());});
    path=files.write("same.iso",std::vector<std::uint8_t>(2048));provider=pce::open_sector_provider(path);
    auto old=fs::last_write_time(path);
    fs::last_write_time(path,old+std::chrono::seconds(2));
    refuses([&]{provider->read(0);},"changed");
    fatal([&]{provider->read(0);});
}
void test_chd(Files& files,const std::string& decoder) {
    auto bytes=chd();auto path=files.write("mapping.chd",bytes);
    refuses([&]{pce::open_sector_provider(path);},"explicit libchdr");
    refuses([&]{pce::open_sector_provider(path,(files.dir/"missing.dll").string());},"Cannot load");
    auto provider=pce::open_sector_provider(path,decoder);
    auto& toc=provider->toc();
    require(toc.track_count==3 && toc.leadout_lba==17,"CHD track count/leadout mismatch");
    require(toc.tracks[0].type==0 && toc.tracks[0].index1_lba==0 && toc.tracks[1].type==4 && toc.tracks[1].index1_lba==7
        && toc.tracks[2].index1_lba==14,"CHD pregap INDEX01 mismatch");
    for(unsigned lba:{7U,8U,10U,14U,16U,7U}) {
        unsigned frame=lba<14?lba+3:lba+2,skip=lba<14?16:0;
        auto sector=provider->read(lba);
        for(unsigned i=0;i<2048;++i) require(sector[i]==pattern(frame,i+skip),"CHD mapping/user-sector mismatch");
    }
    for(unsigned lba:{0U,4U}) refuses([&]{provider->read(lba);},"Audio");
    for(unsigned lba:{5U,6U,11U,12U,13U,17U,0xffffffffU}) refuses([&]{provider->read(lba);},"gap or outside");
    for(unsigned lba:{0U,4U})media_error([&]{provider->read(lba);},pce::SectorReadReason::wrong_data_track,lba);
    for(unsigned lba:{5U,6U,11U,12U,13U})media_error([&]{provider->read(lba);},pce::SectorReadReason::unrecoverable_data,lba);
    for(unsigned lba:{17U,0xffffffffU})media_error([&]{provider->read(lba);},pce::SectorReadReason::out_of_range,lba);
    fatal([&]{provider->read_audio(7);});fatal([&]{provider->read_audio(17);});
    auto invalid=bytes;invalid[4096+11*2448+15]=2;
    auto bad=pce::open_sector_provider(files.write("raw.chd",invalid),decoder);
    refuses([&]{bad->read(8);},"raw sector");
    media_error([&]{bad->read(8);},pce::SectorReadReason::media_data_error,8);
    invalid=bytes;invalid[16]=0xEE;bad=pce::open_sector_provider(files.write("decode.chd",invalid),decoder);
    refuses([&]{bad->read(7);},"decode failed");
    fatal([&]{bad->read(7);});
    // Deliberately truncated decoded-hunk double: metadata is still valid.
    invalid=bytes;invalid.resize(4096+2448);bad=pce::open_sector_provider(files.write("short.chd",invalid),decoder);
    refuses([&]{bad->read(7);},"decode failed");
    fatal([&]{bad->read(7);});
    // The authored decoder overwrites its output and returns a failure once.
    // Neither a failed data decode nor a failed audio decode may leave that
    // buffer tagged with the previously cached successful hunk's identity.
    for(bool audio_failure:{false,true}) {
        auto partial=bytes;partial[17]=0xFD;partial[18]=audio_failure?1:4;
        const auto image=files.write(audio_failure?"partial-audio.chd":"partial-data.chd",partial);
        auto fresh=pce::open_sector_provider(image,decoder);
        const auto original=fresh->read(7);
        if(audio_failure)fatal([&]{fresh->read_audio(4);});
        else fatal([&]{fresh->read(16);});
        require(fresh->read(7)==original,"Failed decode exposed overwritten cache as old data hunk");
        const auto samples=fresh->read_audio(0);
        for(unsigned i=0;i<samples.size();++i) {
            const unsigned word=(unsigned(pattern(0,i*2))<<8)|pattern(0,i*2+1);
            const int expected=word<32768?int(word):int(word)-65536;
            require(samples[i]==expected,"Failed decode contaminated subsequent audio samples");
        }
    }
    auto malformed=[&](std::vector<std::uint8_t> data,const char* reason){
        auto file=files.write("invalid.chd",data);refuses([&]{pce::open_sector_provider(file,decoder);},reason);
    };
    invalid=bytes;invalid[12]=1;malformed(invalid,"CHDv5");
    invalid=bytes;invalid[104]=1;malformed(invalid,"Parent");
    invalid=bytes;put32(invalid,56,524289);malformed(invalid,"geometry");
    invalid=bytes;put32(invalid,60,2048);malformed(invalid,"geometry");
    invalid=bytes;put64(invalid,48,125);malformed(invalid,"");
    invalid=bytes;put64(invalid,124+8,124);malformed(invalid,"cyclic");
    invalid=bytes;put32(invalid,124+4,65537);malformed(invalid,"bounds");
    invalid=bytes;put64(invalid,32,24*2448);malformed(invalid,"logical size");
    invalid=bytes;std::copy_n("CHCD",4,invalid.begin()+124);malformed(invalid,"Legacy");
    invalid=bytes;invalid.resize(123);malformed(invalid,"Short");
    auto changed=bytes;changed.push_back(1);files.write("mapping.chd",changed);
    for(unsigned lba:{0U,7U,17U})fatal([&]{provider->read(lba);});
}
} // namespace
int main(int argc,char** argv) {
    try {
        if(argc==5 && std::string(argv[1])=="--probe") {
            auto provider=pce::open_sector_provider(argv[2],argv[3]);
            auto sector=provider->read(static_cast<std::uint32_t>(std::stoul(argv[4])));
            constexpr char digits[]="0123456789abcdef";
            std::cout<<provider->toc().image_sha256<<' '<<provider->toc().leadout_lba<<' '<<provider->toc().track_count<<'\n';
            for(auto value:sector) std::cout<<digits[value>>4]<<digits[value&15];
            std::cout<<'\n';return 0;
        }
        if(argc!=2) throw std::runtime_error("Provider tests require authored decoder ABI-double library path");
        Files files;test_hash(files);test_iso(files);test_chd(files,argv[1]);
        std::cout<<"sector-provider: "<<checks<<" independently expected checks (ISO, SHA256, CHD mapping via authored ABI double)\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
