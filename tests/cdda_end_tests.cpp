// Authored ramps and control states; no disc excerpts or emulator code.
#include "pce/checkpoint.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
unsigned checks=0;
constexpr std::uint64_t hz=21477273;
void require(bool value,const char* why){++checks;if(!value)throw std::runtime_error(why);}
std::uint64_t edge(std::uint64_t frame){return (frame*hz+44099)/44100;}
class Media final:public pce::SectorProvider {
public:
    pce::CdToc geometry;
    unsigned reads=0;
    Media(){geometry.track_count=1;geometry.leadout_lba=20;geometry.tracks[0]={0,0};}
    pce::Sector read(std::uint32_t)override{throw pce::Fault("unexpected data read");}
    bool audio_playable(std::uint32_t lba)const override{return lba<20;}
    pce::AudioSector read_audio(std::uint32_t lba)override{
        ++reads;pce::AudioSector result{};
        for(unsigned i=0;i<588;++i){const int value=1+lba*588+i;
            result[i*2]=static_cast<std::int16_t>(value*2);
            result[i*2+1]=static_cast<std::int16_t>(-value*2);}
        return result;
    }
    const pce::CdToc& toc()const override{return geometry;}
};
struct Machine {pce::Bus bus;pce::Cpu cpu;};
std::shared_ptr<Media> setup(Machine& m,pce::AudioTiming timing,unsigned output){
    m.bus.enable_cd_transport();m.bus.cd.audio_enabled=true;
    auto source=std::make_shared<Media>();m.bus.cd.set_sector_provider(source);
    if(output)m.bus.enable_audio_output(output==1?pce::AudioProfile::raw:pce::AudioProfile::filtered,
                                        output==3?48000:44100,timing);
    return source;
}
void clock(Machine& m,std::uint64_t ticks){m.cpu.ticks=ticks;m.bus.sync(m.cpu);}
void start(Machine& m,std::uint64_t ticks){
    auto& a=m.bus.cd.audio;a.state=0;a.start_lba=a.current_lba=10;a.stop_lba=19;
    a.sector_deadline=ticks+286363;a.sector_fraction=48;a.reschedule();clock(m,ticks);
}
void command(Machine& m,unsigned opcode,unsigned mode=0,unsigned end=0){
    // These are device-level tests. The independent port/opcode probe covers
    // actual selection/ACK admission; this supervisor observes each command
    // immediately, exactly as the Bus synchronization contract requires.
    auto& cd=m.bus.cd;cd.scsi.command.fill(0);cd.scsi.command[0]=opcode;cd.scsi.command[1]=mode;
    cd.scsi.command[3]=end>>16;cd.scsi.command[4]=end>>8;cd.scsi.command[5]=end;
    cd.scsi.phase=3;cd.scsi.signals=0xd0;cd.scsi.event=0;cd.scsi.deadline=0;
    cd.scsi.response_size=cd.scsi.response_index=0;cd.scsi.status_pending=false;
    cd.audio_command();clock(m,m.cpu.ticks);
}
void source_matrix(){
    for(unsigned offset:{0u,28u})for(unsigned end:{9u,10u,11u})for(unsigned mode:{1u,2u,3u}){
        auto m=std::make_unique<Machine>();setup(*m,pce::AudioTiming::gear,1);
        clock(*m,edge(offset));start(*m,edge(offset));
        clock(*m,edge(offset+100));command(*m,0xd9,mode,end);
        const unsigned length=end<=10?588:1176;
        for(unsigned frame=101;frame<=length+2;++frame){
            clock(*m,edge(offset+frame));
            const int ordinal=mode==1?1+(frame-1)%length:frame<=length?frame:0;
            const int value=ordinal?5880+ordinal:0;
            require(m->bus.cd.audio.sample_raw==std::array<std::int16_t,2>{
                static_cast<std::int16_t>(value*2),static_cast<std::int16_t>(-value*2)},
                "D9 lost, duplicated, or reordered an authored source sample");
        }
        require(m->bus.cd.audio.current_lba==(mode==1?10u:end<=10?11u:12u),"end sector transport head differs");
        require(m->bus.cd.audio.state==(mode==1?0u:3u),"end sector loop/stop state differs");
        if(mode==2)require(m->bus.cd.scsi.phase==7&&m->bus.cd.scsi.data==0,"IRQ mode omitted GOOD completion");
    }
}
void paused_remainder(){
    for(unsigned mode:{1u,2u,3u}){
        auto m=std::make_unique<Machine>();setup(*m,pce::AudioTiming::gear,0);start(*m,0);
        clock(*m,edge(100));command(*m,0xda);clock(*m,edge(125));
        require(m->bus.cd.audio.source_cursor.frame==100,"pause consumed source frames");
        command(*m,0xd9,mode,9);const auto deadline=m->bus.cd.audio.playback_deadline;
        clock(*m,deadline-1);require(m->bus.cd.audio.sample_raw==std::array<std::int16_t,2>{0,0},"resume delay emitted source");
        const auto first=deadline*44100/hz+1;
        for(unsigned i=0;i<490;++i){clock(*m,edge(first+i));
            const unsigned ordinal=mode==1?1+(100+i)%588:i<488?101+i:0;
            const int value=ordinal?5880+ordinal:0;
            require(m->bus.cd.audio.sample_raw==std::array<std::int16_t,2>{
                static_cast<std::int16_t>(value*2),static_cast<std::int16_t>(-value*2)},"paused end change lost remainder");}
    }
}
void checkpoint_matrix(){
    for(auto timing:{pce::AudioTiming::gear,pce::AudioTiming::legacy})for(unsigned output:{0u,1u,2u,3u})
    for(unsigned mode:{1u,2u,3u})for(unsigned frame:{100u,587u})for(bool admitted:{false,true}){
        auto a=std::make_unique<Machine>(),b=std::make_unique<Machine>();setup(*a,timing,output);auto source=setup(*b,timing,output);
        clock(*a,edge(28));start(*a,edge(28));clock(*a,edge(28+frame));
        if(admitted)command(*a,0xd9,mode,9);
        const auto saved=pce::encode_checkpoint(a->bus,a->cpu);pce::restore_checkpoint(b->bus,b->cpu,saved);
        require(!source->reads,"checkpoint restore reread retained source cache");
        require(saved==pce::encode_checkpoint(b->bus,b->cpu),"checkpoint initial full payload differs");
        if(!admitted){command(*a,0xd9,mode,9);command(*b,0xd9,mode,9);}
        for(auto ticks:{edge(28+frame)+1,edge(28)+286363,edge(616),edge(617),edge(1205)}){
            if(ticks<a->cpu.ticks)continue;clock(*a,ticks);clock(*b,ticks);
            require(pce::encode_checkpoint(a->bus,a->cpu)==pce::encode_checkpoint(b->bus,b->cpu),"end change checkpoint source/queue/filter continuation differs");
        }
        require(a->bus.pcm.drain()==b->bus.pcm.drain(),"end change restored output differs");
    }
}
void explicit_stop_cancels_tail(){
    for(unsigned op:{0xd9u,0xd8u}){
        auto m=std::make_unique<Machine>();setup(*m,pce::AudioTiming::gear,1);clock(*m,edge(28));start(*m,edge(28));
        clock(*m,edge(128));command(*m,0xd9,3,9);clock(*m,edge(28)+286363);
        require(m->bus.cd.audio.source_cursor.tail_pending,"shortened end lost rounded final-frame token");
        command(*m,op,0,10);clock(*m,edge(616));
        require(m->bus.cd.audio.sample_raw==std::array<std::int16_t,2>{0,0},"explicit stop/seek retained shortened-end token");
    }
}
}
int main(){try{source_matrix();paused_remainder();checkpoint_matrix();explicit_stop_cancels_tail();
    std::cout<<checks<<" authored CDDA end-change/source/pause/checkpoint checks passed\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
