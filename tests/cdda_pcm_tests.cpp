// Authored literal PCM/geometry fixtures. Decoder ABI double is not libchdr.
#include "pce/cdda_pcm.hpp"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

namespace {
namespace fs=std::filesystem;
unsigned checks=0;
void require(bool value,const char* why) {++checks;if(!value) throw std::runtime_error(why);}
template<class F> void refuses(F operation) {
    bool refused=false;try {operation();} catch(const pce::Fault&) {refused=true;}
    require(refused,"invalid audio operation was accepted");
}
void put32(std::vector<std::uint8_t>& b,unsigned at,unsigned value) {
    for(unsigned i=0;i<4;++i) b[at+3-i]=static_cast<std::uint8_t>(value>>(8*i));
}
void put64(std::vector<std::uint8_t>& b,unsigned at,std::uint64_t value) {
    for(unsigned i=0;i<8;++i) b[at+7-i]=static_cast<std::uint8_t>(value>>(8*i));
}
constexpr std::int16_t literals[]={-32768,-1,0,1,0x1234,32767,-0x1234};
std::int16_t expected(unsigned frame,unsigned sample) {return literals[(frame+sample)%std::size(literals)];}
std::vector<std::uint8_t> fixture() {
    std::vector<std::uint8_t> b(4096+24*2448,0x5a);
    std::fill_n(b.begin(),124,0);std::copy_n("MComprHD",8,b.begin());
    put32(b,8,124);put32(b,12,5);put64(b,32,24*2448);put64(b,48,124);
    put32(b,56,4*2448);put32(b,60,2448);
    const std::string metadata[]={
        "TRACK:1 TYPE:AUDIO SUBTYPE:NONE FRAMES:5 PREGAP:0 PGTYPE:AUDIO PGSUB:NONE POSTGAP:0",
        "TRACK:2 TYPE:AUDIO SUBTYPE:NONE FRAMES:5 PREGAP:2 PGTYPE:VAUDIO PGSUB:NONE POSTGAP:0",
        "TRACK:3 TYPE:MODE1 SUBTYPE:NONE FRAMES:3 PREGAP:2 PGTYPE:MODE1 PGSUB:NONE POSTGAP:2",
        "TRACK:4 TYPE:AUDIO SUBTYPE:NONE FRAMES:2 PREGAP:1 PGTYPE:AUDIO PGSUB:NONE POSTGAP:0"};
    unsigned at=124;
    for(unsigned i=0;i<std::size(metadata);++i) {
        std::copy_n("CHT2",4,b.begin()+at);
        const auto size=static_cast<unsigned>(metadata[i].size()+1);
        put32(b,at+4,size);put64(b,at+8,i+1==std::size(metadata)?0:at+16+size);
        std::copy(metadata[i].begin(),metadata[i].end(),b.begin()+at+16);
        b[at+16+size-1]=0;at+=16+size;
    }
    for(unsigned frame=0;frame<24;++frame) for(unsigned sample=0;sample<1176;++sample) {
        const auto value=static_cast<std::uint16_t>(expected(frame,sample));
        b[4096+frame*2448+sample*2]=static_cast<std::uint8_t>(value>>8);
        b[4096+frame*2448+sample*2+1]=static_cast<std::uint8_t>(value);
    }
    return b;
}
struct Files {
    fs::path dir=fs::temp_directory_path()/("pce-cdda-tests-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::vector<fs::path> owned;
    Files() {if(!fs::create_directory(dir)) throw std::runtime_error("cannot create audio fixture directory");}
    ~Files() {std::error_code error;for(const auto& p:owned) fs::remove(p,error);fs::remove(dir,error);}
    std::string write(const char* name,const std::vector<std::uint8_t>& bytes) {
        const auto p=dir/name;owned.push_back(p);std::ofstream out(p,std::ios::binary);
        out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
        if(!out) throw std::runtime_error("cannot write audio fixture");return p.string();
    }
};
struct AudioDouble final:pce::SectorProvider {
    pce::CdToc table;
    unsigned reads=0;
    int offset=0;
    pce::Sector read(std::uint32_t) override {throw pce::Fault("not data");}
    const pce::CdToc& toc() const override {return table;}
    bool audio_playable(std::uint32_t lba) const override {return lba!=50;}
    pce::AudioSector read_audio(std::uint32_t lba) override {
        ++reads;if(lba==99) throw pce::Fault("authored missing sector");
        pce::AudioSector result{};
        for(unsigned i=0;i<result.size();++i) result[i]=static_cast<std::int16_t>(int(lba*100+i)+offset);
        return result;
    }
};
struct DataDouble final:pce::SectorProvider {
    pce::CdToc table;
    pce::Sector read(std::uint32_t) override {return {};}
    const pce::CdToc& toc() const override {return table;}
};
void test_cache() {
    auto a=std::make_shared<AudioDouble>();auto b=std::make_shared<AudioDouble>();b->offset=2000;
    pce::CddaPcmCache cache;
    for(unsigned i:{0U,1U,587U,10U})
        require(cache.sample(a,2,i)==std::array<std::int16_t,2>{std::int16_t(200+2*i),std::int16_t(201+2*i)},"cache sample/frame/channel mismatch");
    require(a->reads==1,"same sector reread for each PCM frame");
    require(cache.sample(a,3,0)[0]==300 && a->reads==2,"sector change retained stale cache");
    require(cache.sample(b,3,0)[0]==2300 && b->reads==1,"provider change retained stale cache");
    refuses([&]{cache.sample(b,99,0);});
    require(cache.sample(b,3,0)[0]==2300,"failed lookup corrupted previous cache");
    cache.reset();require(cache.sample(b,3,0)[0]==2300 && b->reads==3,"reset did not invalidate sector");
    refuses([&]{cache.sample(b,3,588);});refuses([&]{cache.sample({},3,0);});
    auto old=std::weak_ptr<pce::SectorProvider>(b);b.reset();require(old.expired(),"cache unexpectedly retained provider lifetime");
    refuses([&]{std::make_shared<DataDouble>()->read_audio(0);});
    require(cache.sample(a,50,123)==std::array<std::int16_t,2>{0,0},"nonplayable sector did not produce reference silence");
    refuses([&]{cache.sample(std::make_shared<DataDouble>(),0,0);});
}
void test_provider(Files& files,const std::string& decoder) {
    auto bytes=fixture();const auto path=files.write("audio.chd",bytes);
    const auto hash=pce::image_sha256(path);
    auto provider=pce::open_sector_provider(path,decoder);
    require(provider->toc().track_count==4 && provider->toc().leadout_lba==20,"audio TOC geometry mismatch");
    const std::pair<unsigned,unsigned> mappings[]={{0,0},{3,3},{4,4},{5,8},{6,9},{7,10},{9,12},{18,20},{19,21},{0,0}};
    for(const auto [lba,frame]:mappings) {
        const auto sector=provider->read_audio(lba);
        require(provider->audio_playable(lba),"authored audio sector was not classified playable");
        for(unsigned i=0;i<sector.size();++i) require(sector[i]==expected(frame,i),"audio mapping/endian/channel sample mismatch");
        refuses([&]{provider->read(lba);});
    }
    for(unsigned lba:{10U,11U,12U,14U,15U,16U,17U,20U,0xffffffffU}) {
        require(!provider->audio_playable(lba),"data/gap/outside sector was classified playable");
        refuses([&]{provider->read_audio(lba);});
    }
    require(provider->read(12).size()==2048,"audio support broke MODE1 access");
    require(pce::image_sha256(path)==hash,"provider modified its source image");
    // Stored audio pregap after a data track is readable raw content, but the
    // reference playback gate deliberately emits silence at that transition.
    auto mixed=bytes;
    const std::string audio_type="TYPE:AUDIO";
    const auto first=std::search(mixed.begin(),mixed.end(),audio_type.begin(),audio_type.end());
    require(first!=mixed.end(),"missing authored audio metadata");
    std::copy_n("MODE1",5,first+5);
    auto data_first=pce::open_sector_provider(files.write("data-first.chd",mixed),decoder);
    require(!data_first->audio_playable(0),"data track classified audio");
    for(unsigned lba:{5U,6U}) {
        require(!data_first->audio_playable(lba),"audio pregap after data was classified playable");
        require(data_first->read_audio(lba)[0]==expected(lba+3,0),"stored pregap raw sample mismatch");
        pce::CddaPcmCache cache;
        require(cache.sample(data_first,lba,0)==std::array<std::int16_t,2>{0,0},"data-to-audio pregap was not silent");
    }
    require(data_first->audio_playable(7),"main audio after data pregap was muted");
    const auto prior=fs::last_write_time(path);fs::last_write_time(path,prior+std::chrono::seconds(2));
    refuses([&]{provider->read_audio(0);});
    auto invalid=bytes;invalid[16]=0xee;
    auto bad=pce::open_sector_provider(files.write("decode.chd",invalid),decoder);
    refuses([&]{bad->read_audio(0);});
    auto iso=pce::open_sector_provider(files.write("data.iso",std::vector<std::uint8_t>(2048)));
    require(!iso->audio_playable(0),"ISO sector was classified audio");
    refuses([&]{iso->read_audio(0);});
}
}
int main(int argc,char** argv) {
    try {
        if(argc!=2) throw std::runtime_error("audio tests require decoder ABI-double path");
        Files files;test_cache();test_provider(files,argv[1]);
        std::cout << "CDDA PCM: " << checks << " independent literal/cache/geometry checks passed\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
