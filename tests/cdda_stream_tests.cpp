// Authored per-frame CDDA ramps expose duplication/skips that constant sectors
// cannot. The cursor policy is digital presentation, not analog phase proof.
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
unsigned checks=0;
pce::AudioTiming timing=pce::AudioTiming::legacy;
constexpr std::uint64_t clock_hz=21477273;
void require(bool okay,const char* why){++checks;if(!okay)throw std::runtime_error(why);}
std::uint64_t tick(std::uint64_t frame){return (frame*clock_hz+(timing==pce::AudioTiming::gear ? 44099:0))/44100;}
class Ramp final:public pce::SectorProvider {
public:
    pce::CdToc geometry;unsigned reads=0,base=0;
    explicit Ramp(unsigned offset=0):base(offset){geometry.track_count=1;geometry.leadout_lba=6;geometry.tracks[0]={0,0};}
    pce::Sector read(std::uint32_t) override{throw pce::Fault("unexpected data read");}
    bool audio_playable(std::uint32_t lba) const override{return lba<6;}
    pce::AudioSector read_audio(std::uint32_t lba) override {
        ++reads;pce::AudioSector result{};
        for(unsigned frame=0;frame<588;++frame){const auto ordinal=base+1+lba*588+frame;
            result[frame*2]=static_cast<std::int16_t>(ordinal*3);
            result[frame*2+1]=static_cast<std::int16_t>(-int(ordinal)*6);}
        return result;
    }
    const pce::CdToc& toc() const override{return geometry;}
};
std::shared_ptr<Ramp> attach(pce::Bus& bus){bus.enable_cd_transport();bus.cd.audio_enabled=true;
    auto source=std::make_shared<Ramp>();bus.cd.set_sector_provider(source);bus.enable_audio_output(pce::AudioProfile::raw,44100,timing);return source;}
void playing(pce::Bus& bus,unsigned last=5,std::uint64_t start=0,unsigned first=0){
    auto& a=bus.cd.audio;a.state=0;a.start_lba=a.current_lba=first;a.stop_lba=last;
    a.sector_deadline=start+286363;a.sector_fraction=48;a.reschedule();}
void command(pce::Bus& bus,unsigned opcode,unsigned mode=0,unsigned lba=0){
    auto& cd=bus.cd;cd.scsi.command.fill(0);cd.scsi.command[0]=opcode;cd.scsi.command[1]=mode;
    cd.scsi.command[3]=lba>>16;cd.scsi.command[4]=lba>>8;cd.scsi.command[5]=lba;
    cd.scsi.phase=3;cd.scsi.signals=0xd0;cd.scsi.event=0;cd.scsi.deadline=0;
    cd.scsi.response_size=cd.scsi.response_index=0;cd.audio_command();
    // Register changes can happen between output edges. An ordinary bus sync
    // must still observe explicit stop/pause/seek even with no new PCM sample.
    bus.pcm.advance_to(bus,bus.pcm.master_ticks);
}
void ramp(const std::vector<std::int16_t>& pcm,unsigned start,unsigned frames){
    require(pcm.size()==frames*2,"unexpected ramp frame count");
    for(unsigned i=0;i<frames;++i)require(pcm[i*2]==int(start+i) && pcm[i*2+1]==-2*int(start+i),
                                          "CDDA source frame repeated, skipped, or changed stereo identity");
}
void continuous_and_finite(){
    for(unsigned sectors:{1u,2u,3u}){
        pce::Bus bus;auto source=attach(bus);playing(bus,sectors-1);
        bus.pcm.advance_to(bus,tick(sectors*588));
        ramp(bus.pcm.drain(),1,sectors*588);
        require(source->reads==sectors && bus.pcm.cdda_nonzero==sectors*588,"per-sector cache or terminal frame count");
        require(bus.cd.audio.state==3 && bus.cd.audio.sectors_played==sectors,"PCM changed finite drive timeline");
        bus.pcm.advance_to(bus,tick(sectors*588+1));
        require(bus.pcm.drain()==std::vector<std::int16_t>{0,0},"natural terminal frame leaked twice");
    }
    // Playback begins between global output edges. Its source frames remain
    // consecutive across rounded 75 Hz sector boundaries.
    pce::Bus offset;auto source=attach(offset);offset.pcm.advance_to(offset,1000);offset.pcm.drain();
    playing(offset,2,1000);offset.pcm.advance_to(offset,1000);
    offset.pcm.advance_to(offset,tick(1766));ramp(offset.pcm.drain(),1,1764);
    require(source->reads==3,"nonaligned CDDA cache sequence");
    offset.pcm.advance_to(offset,tick(1767));
    require(offset.pcm.drain()==std::vector<std::int16_t>{0,0},"finite cursor exceeded inclusive end bound");
}
void status_during_natural_tail(){
    pce::Bus bus;attach(bus);bus.pcm.advance_to(bus,tick(28));bus.pcm.drain();
    playing(bus,0,tick(28));bus.pcm.advance_to(bus,tick(28));
    // Start at global sample28: rounded drive end istick(28)+286363, while the final
    // source sample is due at output edgetick(616). DD is a status read, not stop.
    bus.pcm.advance_to(bus,tick(28)+286363);ramp(bus.pcm.drain(),1,587);
    require(bus.cd.audio.state==3,"natural completion did not precede terminal sample");
    command(bus,0xdd);bus.pcm.advance_to(bus,tick(616));ramp(bus.pcm.drain(),588,1);
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));
    require(bus.pcm.drain()==std::vector<std::int16_t>{0,0},"DD retained terminal token twice");
}
void reset_during_natural_tail(){
    pce::Bus bus;attach(bus);bus.pcm.advance_to(bus,tick(28));bus.pcm.drain();
    playing(bus,0,tick(28));bus.pcm.advance_to(bus,tick(28));
    bus.pcm.advance_to(bus,tick(28)+286363);ramp(bus.pcm.drain(),1,587);
    bus.cd.transport_write(4,2);bus.pcm.advance_to(bus,tick(28)+286363);
    bus.pcm.advance_to(bus,tick(616));
    require(bus.pcm.drain()==std::vector<std::int16_t>{0,0},"bus reset failed to cancel natural terminal token");
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+3));auto held=bus.pcm.drain();
    require(held==std::vector<std::int16_t>(6),"held bus reset emitted stale CDDA");
    bus.cd.transport_write(4,0);command(bus,0xd8,1,0);
    const auto seek=bus.cd.audio.seek_deadline;bus.pcm.advance_to(bus,seek-1);held=bus.pcm.drain();
    require(std::all_of(held.begin(),held.end(),[](auto v){return !v;}),"reset/reseek delay emitted old cursor");
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));ramp(bus.pcm.drain(),1,1);
}
void looping(){
    pce::Bus bus;auto source=attach(bus);playing(bus,0);bus.cd.audio.stop_mode=1;
    bus.pcm.advance_to(bus,tick(1764));const auto output=bus.pcm.drain();
    require(output.size()==3528,"loop output frame count");
    for(unsigned i=0;i<1764;++i){const int expected=1+i%588;
        require(output[2*i]==expected && output[2*i+1]==-2*expected,"loop skipped terminal or initial frame");}
    require(source->reads==1 && bus.cd.audio.current_lba==0 && bus.cd.audio.sectors_played==3,
            "loop changed cache reuse or guest drive counters");
}
void pause_resume_and_stop(){
    pce::Bus bus;attach(bus);playing(bus);bus.pcm.advance_to(bus,tick(100));ramp(bus.pcm.drain(),1,100);
    command(bus,0xda);bus.pcm.advance_to(bus,tick(120));
    auto paused=bus.pcm.drain();require(paused.size()==40 && std::all_of(paused.begin(),paused.end(),[](auto v){return !v;}),
                                      "paused CDDA cursor emitted samples");
    command(bus,0xd9,3,5);const auto resume=bus.cd.audio.playback_deadline;
    bus.pcm.advance_to(bus,resume-1);paused=bus.pcm.drain();
    require(std::all_of(paused.begin(),paused.end(),[](auto v){return !v;}),"resume delay emitted CDDA");
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));ramp(bus.pcm.drain(),101,1);
    // Stop and restart happen without an intervening sample edge: the old
    // cursor must be invalidated by the between-edge state observer.
    command(bus,0xd9,0);command(bus,0xd9,3,5);
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));ramp(bus.pcm.drain(),1,1);
}
void seek_reset_and_provider(){
    pce::Bus bus;attach(bus);playing(bus);bus.pcm.advance_to(bus,tick(5));bus.pcm.drain();
    command(bus,0xd8,1,2);const auto seek=bus.cd.audio.seek_deadline;
    bus.pcm.advance_to(bus,seek-1);auto silent=bus.pcm.drain();
    require(std::all_of(silent.begin(),silent.end(),[](auto v){return !v;}),"seek leaked old cursor");
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));ramp(bus.pcm.drain(),1177,1);
    bus.cd.audio.stop(true);bus.pcm.advance_to(bus,bus.pcm.master_ticks);
    playing(bus,5,bus.pcm.master_ticks,1);bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));ramp(bus.pcm.drain(),589,1);
    auto replacement=std::make_shared<Ramp>(1000);bus.cd.provider=replacement;
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));ramp(bus.pcm.drain(),1589,1);
    bus.cd.audio.stop();bus.pcm.advance_to(bus,bus.pcm.master_ticks);
    bus.pcm.advance_to(bus,tick(bus.pcm.frames+1));
    require(bus.pcm.drain()==std::vector<std::int16_t>{0,0},"reset/explicit stop emitted stale source");
}
void partition(){
    pce::Bus a,b;attach(a);attach(b);playing(a,2);playing(b,2);
    a.pcm.advance_to(a,tick(1764));
    for(std::uint64_t t=1;t<tick(1764);t+=3179)b.pcm.advance_to(b,t);
    b.pcm.advance_to(b,tick(1764));
    require(a.pcm.drain()==b.pcm.drain() && a.pcm.pcm_hash==b.pcm.pcm_hash &&
            a.cd.audio.current_lba==b.cd.audio.current_lba && a.cd.audio.sector_fraction==b.cd.audio.sector_fraction &&
            a.cd.audio.sectors_played==b.cd.audio.sectors_played,"CDDA chunking changed source order or drive timeline");
}
}
int main(){try{for(const auto mode:{pce::AudioTiming::legacy,pce::AudioTiming::gear}){timing=mode;continuous_and_finite();status_during_natural_tail();reset_during_natural_tail();looping();pause_resume_and_stop();seek_reset_and_provider();partition();}
    std::cout<<checks<<" authored continuous CDDA cursor/ramp/terminal/loop/pause/seek/reset checks passed\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
