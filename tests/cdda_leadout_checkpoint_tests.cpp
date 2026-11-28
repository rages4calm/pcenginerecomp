// Authored device/PCM/checkpoint states; zero guest instruction retirements.
#include "pce/checkpoint.hpp"
#include "pce/checkpoint_archive.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
unsigned checks=0;
constexpr std::uint64_t hz=21477273;
void require(bool value,const char* why){++checks;if(!value)throw std::runtime_error(why);}
class Media final:public pce::SectorProvider {
public:
    pce::CdToc geometry;
    unsigned reads=0;
    Media(){geometry.track_count=3;geometry.leadout_lba=6;
        geometry.tracks[0]={0,4};geometry.tracks[1]={2,0};geometry.tracks[2]={4,0};}
    const pce::CdToc& toc()const override{return geometry;}
    pce::Sector read(std::uint32_t)override{throw pce::Fault("unexpected data READ");}
    bool audio_playable(std::uint32_t lba)const override{return lba>=2&&lba<6;}
    pce::AudioSector read_audio(std::uint32_t lba)override {
        require(lba<6,"read beyond authored leadout");++reads;pce::AudioSector result{};
        for(unsigned i=0;i<588;++i){result[2*i]=static_cast<std::int16_t>(lba*1000+i+1);
            result[2*i+1]=static_cast<std::int16_t>(-int(lba*1000+i+1));}
        return result;
    }
};
struct Machine{pce::Bus bus;pce::Cpu cpu;};
std::shared_ptr<Media> setup(Machine& m,pce::AudioTiming timing,unsigned output){
    m.bus.enable_cd_transport();m.bus.cd.audio_enabled=true;
    auto media=std::make_shared<Media>();m.bus.cd.set_sector_provider(media);
    m.bus.enable_audio_output(output==0?pce::AudioProfile::raw:pce::AudioProfile::filtered,
        output==2?48000:44100,timing);return media;
}
void clock(Machine& m,std::uint64_t ticks){m.cpu.ticks=ticks;m.bus.sync(m.cpu);}
void command(Machine& m,unsigned opcode,unsigned mode,unsigned track){
    auto& cd=m.bus.cd;cd.scsi.command.fill(0);cd.scsi.command[0]=static_cast<std::uint8_t>(opcode);
    cd.scsi.command[1]=static_cast<std::uint8_t>(mode);cd.scsi.command[2]=static_cast<std::uint8_t>(track);
    cd.scsi.command[9]=0x80;cd.scsi.phase=3;cd.scsi.signals=0xD0;cd.scsi.event=0;cd.scsi.deadline=0;
    cd.scsi.response_size=cd.scsi.response_index=0;cd.scsi.status_pending=false;
    cd.audio_command();clock(m,m.cpu.ticks);
}
void prepare_cut(Machine& m,unsigned cut){
    command(m,0xD8,cut==2?1:0,3);
    if(cut){const auto seek=m.bus.cd.audio.seek_deadline;clock(m,seek);}
    if(cut==2)clock(m,m.cpu.ticks+100*hz/44100+1);
}
void same(const Machine& a,const Machine& b){
    require(pce::encode_checkpoint(a.bus,a.cpu)==pce::encode_checkpoint(b.bus,b.cpu),
        "complete restored leadout state differs");
}
void roundtrip_and_suffix(){
    for(auto timing:{pce::AudioTiming::gear,pce::AudioTiming::legacy})
    for(unsigned output:{0u,1u,2u})for(unsigned cut:{0u,1u,2u})for(unsigned mode:{1u,2u,3u}){
        auto a=std::make_unique<Machine>(),b=std::make_unique<Machine>();setup(*a,timing,output);auto media=setup(*b,timing,output);
        prepare_cut(*a,cut);command(*a,0xD9,mode,4);
        require(a->bus.cd.audio.stop_lba==5,"next-track stop was not clamped to inclusive leadout-1");
        require(a->bus.cd.audio.stop_mode==(mode==1?1u:mode==2?2u:0u),"stop mode differs");
        const auto saved=pce::encode_checkpoint(a->bus,a->cpu);
        require(saved==pce::encode_checkpoint(a->bus,a->cpu),"checkpoint save mutated source");
        pce::restore_checkpoint(b->bus,b->cpu,saved);
        require(!media->reads,"restore reread retained audio source");same(*a,*b);
        require(a->bus.pcm.drain()==b->bus.pcm.drain(),"restored pending PCM differs");
        const auto start=a->cpu.ticks;
        // Preserve real pending seek/resume/sample deadlines, then run beyond
        // the last sector through loop/GOOD completion and digital PCM tails.
        for(std::uint64_t offset=1;offset<=10000001;offset+=1000000){
            clock(*a,start+offset);clock(*b,start+offset);same(*a,*b);
            require(a->bus.cd.audio.current_lba<6,"audio head escaped the disc");
            require(!a->bus.pcm.discarded_frames&&!b->bus.pcm.discarded_frames,"fixture overflowed PCM capture");
            require(a->bus.pcm.drain()==b->bus.pcm.drain(),"restored leadout PCM differs");
        }
        if(mode==1)require(a->bus.cd.audio.state==0,"loop mode stopped at leadout");
        else require(a->bus.cd.audio.state==3&&a->bus.cd.audio.current_lba==5,"leadout stop state differs");
        if(mode==2)require(a->bus.cd.scsi.phase==7&&a->bus.cd.scsi.data==0&&
            (a->bus.cd.interrupt_active&0x20),"IRQ stop omitted GOOD completion");
        require(!a->cpu.native_steps&&!a->cpu.interpreter_steps&&!b->cpu.native_steps&&!b->cpu.interpreter_steps,
            "device fixture fabricated guest execution");
    }
}
std::vector<std::uint8_t> timeline(const pce::CdAudio& a){
    pce::checkpoint::Writer out;
    out(a.state,a.stop_mode,a.start_lba,a.current_lba,a.stop_lba,a.seek_start_lba,
        a.deadline,a.seek_deadline,a.sector_deadline,a.playback_deadline,a.sectors_played,
        a.sector_fraction,a.fader,a.fade_start,a.fade_duration);
    return std::move(out.data);
}
void rejected_start_roundtrips(){
    for(unsigned cut:{0u,1u,2u})for(unsigned mode:{0u,1u}){
        auto a=std::make_unique<Machine>(),b=std::make_unique<Machine>();setup(*a,pce::AudioTiming::gear,1);setup(*b,pce::AudioTiming::gear,1);
        prepare_cut(*a,cut);const auto prior=timeline(a->bus.cd.audio);
        const auto commands=a->bus.cd.audio.commands;const auto head=a->bus.cd.scsi.current_lba;
        command(*a,0xD8,mode,4);
        require(timeline(a->bus.cd.audio)==prior&&a->bus.cd.scsi.current_lba==head,
            "rejected leadout start changed the active audio timeline");
        require(a->bus.cd.audio.commands==commands+1,"rejected start lost existing command accounting");
        require(a->bus.cd.pending_sense.key==5&&a->bus.cd.pending_sense.asc==0x25&&a->bus.cd.scsi.data==2,
            "rejected leadout start lost CHECK CONDITION");
        const auto saved=pce::encode_checkpoint(a->bus,a->cpu);pce::restore_checkpoint(b->bus,b->cpu,saved);same(*a,*b);
        require(a->bus.pcm.drain()==b->bus.pcm.drain(),"range-reject pending PCM differs");
        const auto start=a->cpu.ticks;
        for(std::uint64_t offset=1;offset<=9000001;offset+=1000000){clock(*a,start+offset);clock(*b,start+offset);same(*a,*b);
            require(!a->bus.pcm.discarded_frames&&!b->bus.pcm.discarded_frames,"range-reject fixture overflowed PCM");
            require(a->bus.pcm.drain()==b->bus.pcm.drain(),"range-reject restore changed PCM continuation");}
    }
}
}
int main(){try{roundtrip_and_suffix();rejected_start_roundtrips();
    std::cout<<checks<<" authored CDDA leadout/checkpoint/PCM checks passed; zero guest retirements\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
