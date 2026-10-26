// Authored CUE POSTGAP geometry, payload, refusal and playback-gate fixtures.
#include "pce/sector.hpp"
#include "pce/cdda_pcm.hpp"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
namespace {
namespace fs=std::filesystem;
std::uint64_t checks=0,cases=0;
void require(bool value,const char* why){++checks;if(!value)throw std::runtime_error(why);}
template<class F>void fatal(F fn){bool ok=false;try{fn();}catch(const pce::SectorReadError&){}catch(const pce::Fault&){ok=true;}require(ok,"Expected fatal source/raw-audio refusal");}
template<class F>void data_error(F fn,pce::SectorReadReason reason,unsigned lba){bool ok=false;try{fn();}catch(const pce::SectorReadError& e){ok=e.reason==reason&&e.lba==lba;}require(ok,"Typed gap/range/track error differs");}
std::string utf8(const fs::path& path){const auto s=path.generic_u8string();return {reinterpret_cast<const char*>(s.data()),s.size()};}
struct Files {
    fs::path dir;std::vector<fs::path> owned;
    Files(){dir=fs::temp_directory_path()/("pce-cue-gaps-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));if(!fs::create_directory(dir))throw std::runtime_error("New authored directory required");}
    ~Files(){std::error_code error;for(auto i=owned.rbegin();i!=owned.rend();++i)fs::remove(*i,error);fs::remove(dir,error);}
    std::string write(const std::string& name,const std::vector<std::uint8_t>& bytes){const auto path=dir/name;if(std::find(owned.begin(),owned.end(),path)==owned.end())owned.push_back(path);std::ofstream out(path,std::ios::binary|std::ios::trunc);out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());if(!out)throw std::runtime_error("Authored file write failed");return utf8(path);}
    std::string text(const std::string& name,const std::string& text){return write(name,{text.begin(),text.end()});}
};
unsigned byte(unsigned tag,unsigned frame,unsigned i){return (tag*53+frame*37+i*11+3)&255;}
std::vector<std::uint8_t> raw_file(unsigned tag,const std::vector<bool>& audio){std::vector<std::uint8_t> bytes(audio.size()*2352);for(unsigned f=0;f<audio.size();++f){for(unsigned i=0;i<2352;++i)bytes[f*2352+i]=static_cast<std::uint8_t>(byte(tag,f,i));if(!audio[f]){bytes[f*2352]=bytes[f*2352+11]=0;bytes[f*2352+15]=1;std::fill_n(bytes.begin()+f*2352+1,10,255);}}return bytes;}
int sample(unsigned tag,unsigned frame,unsigned i){const unsigned word=byte(tag,frame,2*i)|(byte(tag,frame,2*i+1)<<8);return word<32768?int(word):int(word)-65536;}
std::string msf(unsigned frames){auto two=[](unsigned n){return std::string(n<10?"0":"")+std::to_string(n);};return two(frames/4500)+":"+two(frames/75%60)+":"+two(frames%75);}
void matrix_case(Files& files,bool split,bool audio1,bool audio2,unsigned pregap_kind,unsigned post1,unsigned post2){
    const unsigned pregap=pregap_kind?2:0,stored=pregap_kind==2?2:0;
    std::vector<bool> first(2,audio1),second(stored+3,audio2);auto both=first;both.insert(both.end(),second.begin(),second.end());
    files.write("one.bin",raw_file(1,split?first:both));if(split)files.write("two.bin",raw_file(2,second));
    const auto mode=[](bool audio){return audio?"AUDIO":"MODE1/2352";};
    std::string text="FILE one.bin BINARY\nTRACK 01 "+std::string(mode(audio1))+"\nINDEX 01 00:00:00\nPOSTGAP "+msf(post1)+"\n";
    if(split)text+="FILE two.bin BINARY\n";
    text+="TRACK 02 "+std::string(mode(audio2))+"\n";
    if(pregap_kind==1)text+="PREGAP 00:00:02\n";
    const unsigned origin=split?0:2;
    if(stored)text+="INDEX 00 "+msf(origin)+"\n";
    text+="INDEX 01 "+msf(origin+stored)+"\nPOSTGAP "+msf(post2)+"\nREM metadata after gap is allowed\nTITLE authored\n";
    auto provider=pce::open_sector_provider(files.text("matrix.cue",text));const auto& toc=provider->toc();
    const unsigned start2=2+post1+pregap,leadout=start2+3+post2;
    require(toc.track_count==2&&toc.tracks[0].index1_lba==0&&toc.tracks[1].index1_lba==start2&&toc.leadout_lba==leadout,"POSTGAP literal disc geometry differs");
    require(toc.tracks[0].type==(audio1?0:4)&&toc.tracks[1].type==(audio2?0:4),"POSTGAP changed track types");
    pce::CddaPcmCache cache;
    for(unsigned lba=0;lba<leadout+2;++lba){
        const bool in_first=lba<2,in_second=lba>=start2&&lba<start2+3;
        const bool in_stored=stored&&lba>=start2-stored&&lba<start2;
        const bool audio=(in_first&&audio1)||((in_second||in_stored)&&audio2);
        const bool playable=(in_first&&audio1)||(in_second&&audio2)||(in_stored&&audio1&&audio2);
        require(provider->audio_playable(lba)==playable,"POSTGAP/pregap playback classification differs");
        unsigned tag=1,frame=lba;if(in_second||in_stored){tag=split?2:1;frame=(split?0:2)+stored+(lba-start2);}
        if((in_first&&!audio1)||(in_second&&!audio2)){
            const auto data=provider->read(lba);for(unsigned i=0;i<data.size();++i)require(data[i]==byte(tag,frame,i+16),"POSTGAP shifted file-backed data bytes");
        }else data_error([&]{(void)provider->read(lba);},lba>=leadout?pce::SectorReadReason::out_of_range:(in_first||in_second)?pce::SectorReadReason::wrong_data_track:pce::SectorReadReason::unrecoverable_data,lba);
        if(audio){const auto samples=provider->read_audio(lba);for(unsigned i=0;i<samples.size();++i)require(samples[i]==sample(tag,frame,i),"POSTGAP shifted raw stored audio bytes");}
        else fatal([&]{(void)provider->read_audio(lba);});
        for(unsigned f:{0U,127U,587U}){const auto actual=cache.sample(provider,lba,f);const std::array<std::int16_t,2> expected{static_cast<std::int16_t>(playable?sample(tag,frame,f*2):0),static_cast<std::int16_t>(playable?sample(tag,frame,f*2+1):0)};require(actual==expected,"POSTGAP playback did not retain program audio / exact gap silence");}
    }
    ++cases;
}
void matrices(){Files files;for(bool split:{false,true})for(bool a:{false,true})for(bool b:{false,true})for(unsigned pg:{0U,1U,2U})for(unsigned first:{0U,1U,2U,3U})for(unsigned last:{0U,1U,2U})matrix_case(files,split,a,b,pg,first,last);}
void boundaries_and_identity(){Files files;std::vector<std::uint8_t> data(4096);for(unsigned f=0;f<2;++f)for(unsigned i=0;i<2048;++i)data[f*2048+i]=static_cast<std::uint8_t>(f*37+i*13+5);files.write("one.bin",data);
    const std::string base="FILE \"one.bin\" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n";
    auto original=pce::open_sector_provider(files.text("plain.cue",base));require(original->toc().image_sha256=="b22fe987fe79052c2b8674a3af6f4ecea1fc60a5fa06d38d949ac692cb9fe617","Existing valid CUE identity changed");
    auto zero=pce::open_sector_provider(files.text("zero.cue",base+"POSTGAP 00:00:00\n"));require(zero->toc().leadout_lba==2&&zero->read(1)==original->read(1),"Explicit zero POSTGAP changed geometry/payload");require(zero->toc().image_sha256!=original->toc().image_sha256,"Exact CUE identity incorrectly canonicalized zero POSTGAP");
    for(const auto boundary:std::vector<unsigned>{75,4500}){files.write("two.bin",{data.begin(),data.begin()+2048});const auto text=base+"POSTGAP "+msf(boundary-2)+"\nFILE two.bin BINARY\nTRACK 02 MODE1/2048\nINDEX 01 00:00:00\nPOSTGAP 00:00:01\n";auto p=pce::open_sector_provider(files.text("boundary.cue",text));require(p->toc().tracks[1].index1_lba==boundary&&p->toc().leadout_lba==boundary+2,"MSF carry across POSTGAP differs");data_error([&]{(void)p->read(boundary-1);},pce::SectorReadReason::unrecoverable_data,boundary-1);require(p->read(boundary)[0]==5,"MSF carry shifted next file source");}
    auto maximum=pce::open_sector_provider(files.text("maximum.cue",base+"POSTGAP 99:57:72\n"));require(maximum->toc().leadout_lba==449849,"Inclusive maximum CUE leadout changed");data_error([&]{(void)maximum->read(449848);},pce::SectorReadReason::unrecoverable_data,449848);data_error([&]{(void)maximum->read(449849);},pce::SectorReadReason::out_of_range,449849);
    for(const std::string gap:{"99:57:73","99:59:74"})fatal([&]{(void)pce::open_sector_provider(files.text("over.cue",base+"POSTGAP "+gap+"\n"));});
}
void malformed(){Files files;files.write("one.bin",std::vector<std::uint8_t>(3*2352));files.write("two.bin",std::vector<std::uint8_t>(2352));const std::string begin="FILE one.bin BINARY\nTRACK 01 AUDIO\n",valid=begin+"INDEX 01 00:00:00\n",post=valid+"POSTGAP 00:00:00\n";
    std::vector<std::string> inputs={"POSTGAP 00:00:00\n","FILE one.bin BINARY\nPOSTGAP 00:00:00\n",begin+"POSTGAP 00:00:01\nINDEX 01 00:00:00\n",begin+"INDEX 00 00:00:00\nPOSTGAP 00:00:00\nINDEX 01 00:00:01\n",valid+"POSTGAP\n",valid+"POSTGAP 00:00:00 extra\n",post+"POSTGAP 00:00:00\n",valid+"POSTGAP 00:00:01\nPOSTGAP 00:00:02\n",post+"INDEX 00 00:00:00\n",post+"INDEX 01 00:00:00\n",post+"INDEX 02 00:00:01\n",post+"PREGAP 00:00:00\n",post+"FILE two.bin BINARY\nPOSTGAP 00:00:00\nTRACK 02 AUDIO\nINDEX 01 00:00:00\n",post+"TRACK 02 AUDIO\nPOSTGAP 00:00:00\nINDEX 01 00:00:01\n"};
    for(const std::string time:{"0:00:00","00:60:00","00:00:75","-1:00:00","100:00:00","00:00:-1","00:AA:01"})inputs.push_back(valid+"POSTGAP "+time+"\n");
    for(const auto& text:inputs)fatal([&]{(void)pce::open_sector_provider(files.text("bad.cue",text));});
}
void mutations(){Files files;files.write("one.bin",raw_file(1,{false,true}));const std::string cue="FILE one.bin BINARY\nTRACK 01 MODE1/2352\nINDEX 01 00:00:00\nPOSTGAP 00:00:02\nTRACK 02 AUDIO\nINDEX 01 00:00:01\nPOSTGAP 00:00:01\n";const auto image=files.text("source.cue",cue);auto p=pce::open_sector_provider(image);require(p->read(0)[0]==byte(1,0,16)&&p->read_audio(3)[0]==sample(1,1,0),"Mutation fixture initial source mismatch");const auto old=p->toc().image_sha256;
    auto changed=raw_file(1,{false,true});changed[2352+100]^=255;const auto prior=fs::last_write_time(files.dir/"one.bin");files.write("one.bin",changed);fs::last_write_time(files.dir/"one.bin",prior+std::chrono::seconds(2));fatal([&]{(void)p->read(0);});fatal([&]{(void)p->read_audio(3);});fatal([&]{(void)p->audio_playable(1);});require(pce::image_sha256(image)!=old,"Component mutation lost compound identity");
    auto fresh=pce::open_sector_provider(image);const auto cue_stamp=fs::last_write_time(files.dir/"source.cue");files.text("source.cue",cue+"REM changed\n");fs::last_write_time(files.dir/"source.cue",cue_stamp+std::chrono::seconds(2));fatal([&]{(void)fresh->read(0);});fatal([&]{(void)fresh->read_audio(3);});fatal([&]{(void)fresh->audio_playable(2);});
}
const char* reason(pce::SectorReadReason r){switch(r){case pce::SectorReadReason::out_of_range:return "out_of_range";case pce::SectorReadReason::wrong_data_track:return "wrong_data_track";case pce::SectorReadReason::unrecoverable_data:return "unrecoverable_data";case pce::SectorReadReason::media_data_error:return "media_data_error";}throw std::runtime_error("Unknown typed data error");}
void samples(const pce::AudioSector& audio){std::cout<<'[';for(unsigned i=0;i<audio.size();++i)std::cout<<(i?",":"")<<audio[i];std::cout<<']';}
void probe(const char* image,const char* plan_path){std::ifstream plan(plan_path);unsigned count=0;if(!(plan>>count)||!count||count>4096)throw std::runtime_error("Bounded plan count required");auto p=pce::open_sector_provider(image);pce::CddaPcmCache cache;for(unsigned i=0;i<count;++i){std::string op;unsigned lba=0;if(!(plan>>op))throw std::runtime_error("Truncated plan");if(op!="t"&&(!(plan>>lba)))throw std::runtime_error("Missing plan LBA");if(op=="t"){const auto& t=p->toc();std::cout<<"{\"kind\":\"toc\",\"leadout\":"<<t.leadout_lba<<",\"tracks\":[";for(unsigned j=0;j<t.track_count;++j)std::cout<<(j?",":"")<<'['<<t.tracks[j].index1_lba<<','<<unsigned(t.tracks[j].type)<<']';std::cout<<"]}\n";}else if(op=="p")std::cout<<"{\"kind\":\"playable\",\"lba\":"<<lba<<",\"value\":"<<(p->audio_playable(lba)?"true":"false")<<"}\n";
        else if(op=="d"){std::cout<<"{\"kind\":\"data\",\"lba\":"<<lba;try{const auto data=p->read(lba);constexpr char digits[]="0123456789abcdef";std::cout<<",\"ok\":true,\"bytes\":\"";for(auto b:data)std::cout<<digits[b>>4]<<digits[b&15];std::cout<<"\"}\n";}catch(const pce::SectorReadError& e){std::cout<<",\"ok\":false,\"error\":\""<<reason(e.reason)<<"\"}\n";}}
        else if(op=="a"){std::cout<<"{\"kind\":\"audio\",\"lba\":"<<lba;try{const auto audio=p->read_audio(lba);std::cout<<",\"ok\":true,\"samples\":";samples(audio);std::cout<<"}\n";}catch(const pce::Fault&){std::cout<<",\"ok\":false,\"error\":\"unavailable_audio\"}\n";}}
        else if(op=="m"){pce::AudioSector audio{};for(unsigned f=0;f<588;++f){const auto value=cache.sample(p,lba,f);audio[f*2]=value[0];audio[f*2+1]=value[1];}std::cout<<"{\"kind\":\"pcm\",\"lba\":"<<lba<<",\"samples\":";samples(audio);std::cout<<"}\n";}else throw std::runtime_error("Unknown plan operation");}std::string extra;if(plan>>extra)throw std::runtime_error("Trailing plan operation");}
}
int main(int argc,char**argv){try{if(argc==4&&std::string(argv[1])=="--probe"){probe(argv[2],argv[3]);return 0;}if(argc!=1)throw std::runtime_error("cue-gap-tests [--probe CUE PLAN]");matrices();boundaries_and_identity();malformed();mutations();std::cout<<"CUE POSTGAP checks "<<checks<<" across "<<cases<<" geometry cases\n";return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
