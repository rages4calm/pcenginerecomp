// Authored program/gap geometry and synthetic DD response tests. No retail data.
#include "pce/sector.hpp"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
namespace fs=std::filesystem;
unsigned checks=0;
void require(bool condition,const char* message) {++checks;if(!condition)throw std::runtime_error(message);}
template<class F> void fault(F action) {
    bool failed=false;try{action();}catch(const pce::Fault&){failed=true;}
    require(failed,"Expected explicit position-provider refusal");
}
struct Files {
    fs::path dir;
    std::vector<fs::path> files;
    Files() {
        dir=fs::temp_directory_path()/("pce-position-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        if(!fs::create_directory(dir))throw std::runtime_error("Cannot create authored position directory");
    }
    ~Files(){std::error_code error;for(const auto& path:files)fs::remove(path,error);fs::remove(dir,error);}
    std::string write(const std::string& name,const std::vector<std::uint8_t>& bytes) {
        const auto path=dir/name;
        if(std::find(files.begin(),files.end(),path)==files.end())files.push_back(path);
        std::ofstream out(path,std::ios::binary|std::ios::trunc);
        out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
        if(!out)throw std::runtime_error("Cannot write authored position bytes");
        return path.string();
    }
    std::string text(const std::string& name,const std::string& value){return write(name,{value.begin(),value.end()});}
};
void be32(std::vector<std::uint8_t>& out,unsigned at,std::uint32_t value) {
    for(unsigned i=0;i<4;++i)out[at+3-i]=static_cast<std::uint8_t>(value>>(8*i));
}
void be64(std::vector<std::uint8_t>& out,unsigned at,std::uint64_t value) {
    for(unsigned i=0;i<8;++i)out[at+7-i]=static_cast<std::uint8_t>(value>>(8*i));
}
std::vector<std::uint8_t> authored_chd() {
    // The existing authored decoder fixture reads raw test units at4096. This
    // is metadata/provider testing, not a claim of real compressed-CHD parity.
    std::vector<std::uint8_t> out(4096+12*2448);
    std::copy_n("MComprHD",8,out.begin());be32(out,8,124);be32(out,12,5);
    be64(out,32,12*2448);be64(out,48,124);be32(out,56,4*2448);be32(out,60,2448);
    const std::string records[]={
        "TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:4 PREGAP:0 PGTYPE:MODE1 PGSUB:NONE POSTGAP:2",
        "TRACK:2 TYPE:AUDIO SUBTYPE:NONE FRAMES:5 PREGAP:2 PGTYPE:V PGSUB:NONE POSTGAP:0"};
    unsigned at=124;
    for(unsigned i=0;i<2;++i) {
        std::copy_n("CHT2",4,out.begin()+at);const auto size=static_cast<unsigned>(records[i].size()+1);
        be32(out,at+4,size);be64(out,at+8,i==1?0:at+16+size);
        std::copy(records[i].begin(),records[i].end(),out.begin()+at+16);at+=16+size;
    }
    return out;
}
void location(const std::shared_ptr<pce::SectorProvider>& provider,unsigned lba,int index) {
    const auto a=provider->program_track(lba),b=provider->program_track(lba);
    require(a.known && b.known && a.index==b.index,"Program lookup is unknown or unstable");
    require(index<0 ? !a.index : a.index==static_cast<unsigned>(index),"Independent program/gap classification differs");
}
std::array<std::uint8_t,10> query(pce::CdControl& cd,unsigned lba) {
    cd.audio.state=1;cd.scsi.current_lba=lba;cd.scsi.command.fill(0);cd.scsi.command[0]=0xDD;
    const auto head=cd.scsi.current_lba;const auto clock=cd.scsi.master_ticks;
    const auto a=cd.audio.current_lba;const auto sectors=cd.sectors_read;
    cd.audio_command();
    require(cd.scsi.current_lba==head && cd.scsi.master_ticks==clock && cd.audio.current_lba==a && cd.sectors_read==sectors,
            "Position query moved a head, read sector data or advanced clocks");
    require(cd.scsi.response_size==10 && cd.scsi.response_index==0 && cd.scsi.deadline==clock+3000,
            "DD reply length or declared aggregate event delay differs");
    std::array<std::uint8_t,10> result{};std::copy_n(cd.scsi.response.begin(),10,result.begin());return result;
}
pce::CdControl attached(const std::shared_ptr<pce::SectorProvider>& provider) {
    pce::CdControl cd;cd.enabled=cd.scsi.enabled=cd.audio_enabled=true;cd.set_sector_provider(provider);return cd;
}
void compare(pce::CdControl& cd,unsigned lba,std::array<std::uint8_t,10> expected) {
    require(query(cd,lba)==expected,"Independent ten-byte DD response differs");
}
void iso(Files& files) {
    const auto path=files.write("program.iso",std::vector<std::uint8_t>(7*2048));
    const auto provider=pce::open_sector_provider(path);auto cd=attached(provider);
    for(unsigned lba=0;lba<7;++lba)location(provider,lba,0);
    location(provider,7,-1);location(provider,std::numeric_limits<std::uint32_t>::max(),-1);
    compare(cd,0,{1,0x41,1,1,0,0,0,0,2,0});
    compare(cd,6,{1,0x41,1,1,0,0,6,0,2,6});
    compare(cd,7,{1,1,0,1,0,0,0,0,2,7});
    files.write("program.iso",std::vector<std::uint8_t>(8*2048));
    fault([&]{provider->program_track(0);});
}
void cues(Files& files) {
    files.write("data.bin",std::vector<std::uint8_t>(4*2048));
    files.write("audio.bin",std::vector<std::uint8_t>(3*2352));
    files.write("stored.bin",std::vector<std::uint8_t>(5*2352));
    const std::string first="FILE \"data.bin\" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n";
    const std::string endings[]={
        "FILE \"audio.bin\" BINARY\n TRACK 02 AUDIO\n PREGAP 00:00:02\n INDEX 01 00:00:00\n",
        "FILE \"stored.bin\" BINARY\n TRACK 02 AUDIO\n INDEX 00 00:00:00\n INDEX 01 00:00:02\n",
        " POSTGAP 00:00:02\nFILE \"audio.bin\" BINARY\n TRACK 02 AUDIO\n INDEX 01 00:00:00\n",
        " POSTGAP 00:00:02\nFILE \"audio.bin\" BINARY\n TRACK 02 AUDIO\n INDEX 01 00:00:00\n POSTGAP 00:00:02\n"};
    for(unsigned mode=0;mode<4;++mode) {
        const auto provider=pce::open_sector_provider(files.text("geometry"+std::to_string(mode)+".cue",first+endings[mode]));
        require(provider->toc().tracks[1].index1_lba==6 && provider->toc().leadout_lba==(mode==3?11U:9U),"Independent CUE geometry differs");
        for(unsigned lba=0;lba<12;++lba)location(provider,lba,lba<4?0:lba>=6&&lba<9?1:-1);
        auto cd=attached(provider);
        compare(cd,3,{1,0x41,1,1,0,0,3,0,2,3});
        compare(cd,4,{1,1,0,1,0,0,0,0,2,4});
        compare(cd,5,{1,1,0,1,0,0,0,0,2,5});
        compare(cd,6,{1,1,2,1,0,0,0,0,2,6});
        compare(cd,8,{1,1,2,1,0,0,2,0,2,8});
        compare(cd,9,{1,1,0,1,0,0,0,0,2,9});
        // During a real audio seek, DD uses the retained origin rather than
        // the destination. This isolated test sets state; the reference probe
        // separately establishes the idle head through successful READ.
        cd.audio.state=0;cd.audio.seek_deadline=999999;cd.audio.seek_start_lba=4;cd.audio.current_lba=6;
        cd.scsi.command[0]=0xDD;cd.audio_command();
        require(cd.scsi.response[0]==2 && cd.scsi.response[2]==0 && cd.scsi.response[9]==4,"Seeking DD classified its destination instead of origin");
    }
    auto provider=pce::open_sector_provider((files.dir/"geometry0.cue").string());
    files.write("audio.bin",std::vector<std::uint8_t>(4*2352));
    fault([&]{provider->program_track(4);});
}
void chd(Files& files,const char* decoder) {
    const auto provider=pce::open_sector_provider(files.write("authored.chd",authored_chd()),decoder);
    require(provider->toc().tracks[1].index1_lba==8 && provider->toc().leadout_lba==11,"Independent CHD geometry differs");
    for(unsigned lba=0;lba<13;++lba)location(provider,lba,lba<4?0:lba>=8&&lba<11?1:-1);
    auto cd=attached(provider);
    compare(cd,4,{1,1,0,1,0,0,0,0,2,4});
    compare(cd,7,{1,1,0,1,0,0,0,0,2,7});
    compare(cd,8,{1,1,2,1,0,0,0,0,2,8});
    compare(cd,10,{1,1,2,1,0,0,2,0,2,0x10});
}
struct Custom: pce::SectorProvider {
    pce::CdToc table;unsigned reads=0;mutable unsigned inspections=0;
    pce::ProgramTrackLookup answer;
    Custom(){table.track_count=2;table.tracks[0]={0,4};table.tracks[1]={6,0};table.leadout_lba=9;}
    pce::Sector read(std::uint32_t)override{++reads;throw pce::Fault("A position query must not read sectors");}
    const pce::CdToc& toc()const override{return table;}
    pce::ProgramTrackLookup program_track(std::uint32_t)const override{++inspections;return answer;}
};
void fallback() {
    auto provider=std::make_shared<Custom>();auto cd=attached(provider);
    compare(cd,4,{1,0x41,1,1,0,0,4,0,2,4});
    require(provider->reads==0 && provider->inspections==1,"Unknown metadata caused a sector read or repeated lookup");
    provider->answer={true,{}};compare(cd,4,{1,1,0,1,0,0,0,0,2,4});
    for(const auto bad:{pce::ProgramTrackLookup{false,0},pce::ProgramTrackLookup{true,2},pce::ProgramTrackLookup{true,1}}) {
        provider->answer=bad;fault([&]{query(cd,4);});
    }
    provider->answer={true,0};fault([&]{query(cd,6);});
    provider->answer={true,1};fault([&]{query(cd,9);});
    pce::CdControl only;only.enabled=only.scsi.enabled=only.audio_enabled=true;only.set_toc(provider->table);
    compare(only,4,{1,0x41,1,1,0,0,4,0,2,4});
    require(provider->reads==0,"DD fallback accessed payload");
}
}
int main(int argc,char** argv) {
    try {
        if(argc!=2)throw std::runtime_error("Supply the authored sector decoder fixture");
        Files files;iso(files);cues(files);chd(files,argv[1]);fallback();
        std::cout<<checks<<" authored program-range, DD gap/track, fallback, source-guard and pure-inspection checks passed\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
