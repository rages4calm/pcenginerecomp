// Authored device states/geometry only. No retail data or firmware excerpts.
#include "pce/checkpoint.hpp"
#include "pce/checkpoint_archive.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
unsigned checks=0;
void require(bool value,const char* why) {++checks;if(!value)throw std::runtime_error(why);}
template<class F> void refuses(F operation) {
    bool caught=false;try{operation();}catch(const pce::Fault&){caught=true;}
    require(caught,"invalid provider/address was admitted");
}
struct Media final:pce::SectorProvider {
    pce::CdToc table;
    bool known=true,stored=false;
    unsigned invalid=0;
    mutable unsigned lookups=0;
    unsigned audio_reads=0,data_reads=0;
    Media(bool first_audio=true,bool second_audio=true,bool stored_gap=false):stored(stored_gap) {
        table.track_count=3;table.leadout_lba=18;
        table.tracks[0]={0,std::uint8_t(first_audio?0:4)};table.tracks[1]={6,std::uint8_t(second_audio?0:4)};table.tracks[2]={12,0};
    }
    const pce::CdToc& toc()const override{return table;}
    pce::ProgramTrackLookup program_track(std::uint32_t lba)const override {
        ++lookups;
        if(invalid==1)return {false,0};
        if(invalid==2)return {true,99};
        if(invalid==3)return {true,1};
        if(invalid==4)return {true,0};
        if(!known)return {};
        for(unsigned i=0;i<3;++i)if(lba>=i*6 && lba-i*6<4)return {true,i};
        return {true,{}};
    }
    bool audio_playable(std::uint32_t lba)const override {
        for(unsigned i=0;i<3;++i)if(lba>=i*6 && lba-i*6<4)return table.tracks[i].type==0;
        return stored && lba>=4 && lba<6 && table.tracks[0].type==0 && table.tracks[1].type==0;
    }
    pce::AudioSector read_audio(std::uint32_t lba) override {
        ++audio_reads;pce::AudioSector result{};
        for(unsigned i=0;i<588;++i){result[i*2]=std::int16_t(900+lba*31+i);result[i*2+1]=std::int16_t(-1700-int(lba*17+i));}
        return result;
    }
    pce::Sector read(std::uint32_t lba)override {
        ++data_reads;pce::Sector result{};for(unsigned i=0;i<result.size();++i)result[i]=std::uint8_t(lba*37+i);return result;
    }
};
pce::CdControl configured(const std::shared_ptr<Media>& media) {
    pce::CdControl cd;cd.enabled=cd.scsi.enabled=cd.audio_enabled=true;cd.set_sector_provider(media);return cd;
}
void command(pce::CdControl& cd,unsigned op,unsigned mode=0,unsigned lba=0,bool msf=false) {
    cd.scsi.command.fill(0);cd.scsi.command[0]=std::uint8_t(op);cd.scsi.command[1]=std::uint8_t(mode);
    if(msf) {
        const auto bcd=[](unsigned x){return std::uint8_t((x/10)*16+x%10);};
        const auto at=lba+150;cd.scsi.command[2]=bcd(at/4500);cd.scsi.command[3]=bcd(at/75%60);cd.scsi.command[4]=bcd(at%75);cd.scsi.command[9]=64;
    } else {cd.scsi.command[3]=std::uint8_t(lba>>16);cd.scsi.command[4]=std::uint8_t(lba>>8);cd.scsi.command[5]=std::uint8_t(lba);}
    cd.scsi.phase=3;cd.scsi.signals=0xD0;cd.scsi.event=0;cd.scsi.deadline=0;
    cd.scsi.response_size=cd.scsi.response_index=0;cd.scsi.status_pending=false;
}
std::vector<std::uint8_t> audio_bytes(const pce::CdAudio& a) {
    pce::checkpoint::Writer out;
    out(a.state,a.stop_mode,a.start_lba,a.current_lba,a.stop_lba,a.seek_start_lba,
        a.deadline,a.seek_deadline,a.sector_deadline,a.playback_deadline,a.sectors_played,a.commands,
        a.sector_fraction,a.fader,a.fade_start,a.fade_duration);
    const auto& c=a.source_cursor;
    out(bool(c.source.lock()),c.lba,c.frame,c.last_state,c.commands_seen,c.sectors_seen,c.seek_seen,
        c.active,c.finished,c.tail_pending,c.was_enabled,a.sample_raw,a.sample_held,a.sample_valid,a.sample_right,
        a.sample_latch,a.sample_last_latch,a.sample_frames,a.sample_ticks,a.sample_clock_ticks,a.sample_next_tick,a.sample_remainder);
    return std::move(out.data);
}
void seed(pce::CdControl& cd,unsigned state,bool seeking) {
    cd.scsi.master_ticks=1000000;cd.scsi.current_lba=3;
    auto& a=cd.audio;a.state=state;a.start_lba=2;a.current_lba=3;a.stop_lba=15;a.seek_start_lba=1;
    a.stop_mode=2;a.commands=19;a.sectors_played=7;a.sector_fraction=23;
    a.seek_deadline=seeking?1000200:0;a.sector_deadline=!seeking&&state==0?1000300:0;
    a.playback_deadline=!seeking&&state==2?1000400:0;a.reschedule();
    a.fader=12;a.fade_start=999700;a.fade_duration=53693182;
    auto& c=a.source_cursor;c.source=cd.provider;c.lba=3;c.frame=417;c.last_state=state;c.commands_seen=19;c.sectors_seen=7;c.seek_seen=a.seek_deadline;
    c.active=state!=1;c.finished=false;c.tail_pending=state==3;c.was_enabled=true;
    a.sample_raw={1234,-2345};a.sample_held={117,-291};a.sample_valid=true;a.sample_right=true;
    a.sample_latch=0xA3C7;a.sample_last_latch=999700;a.sample_frames=2053;a.sample_ticks=999913;
    a.sample_clock_ticks=1000000;a.sample_next_tick=1000401;a.sample_remainder=47;
}
void ignored_matrix() {
    // Program/gap admission is independent of PLAY mode and PCM readability.
    // In particular, stored audio INDEX00 samples are playable while excluded
    // from the program track used to admit a new D8 request.
    for(bool stored:{false,true})for(unsigned state=0;state<4;++state)for(bool seeking:{false,true}) {
        if(seeking&&state==1)continue;
        for(unsigned mode=0;mode<256;++mode)for(unsigned lba:{4u,5u,10u,11u,16u,17u})for(bool msf:{false,true}) {
            auto media=std::make_shared<Media>(true,true,stored);auto cd=configured(media);seed(cd,state,seeking);
            const auto before=audio_bytes(cd.audio);const auto head=cd.scsi.current_lba;const auto source=cd.audio.source_cursor.source.lock();
            command(cd,0xD8,mode,lba,msf);cd.audio_command();
            require(audio_bytes(cd.audio)==before,"gap D8 changed audio/source/latch/deadline state");
            require(cd.scsi.current_lba==head&&cd.scsi.master_ticks==1000000,"gap D8 moved head or advanced clock");
            require(cd.audio.source_cursor.source.lock()==source&&media->lookups==1&&!media->audio_reads&&!media->data_reads,"gap admission replaced provider or read media");
            const bool immediate=!mode&&!seeking;
            require(cd.scsi.phase==(immediate?7u:8u)&&cd.scsi.signals==(immediate?0xD8:0x80),"gap controller mode/retained-seek decision differs");
            require(cd.scsi.status_pending==immediate&&cd.scsi.response_size==(immediate?1u:0u)&&!cd.scsi.event&&!cd.scsi.deadline,"gap start invented transport completion/deadline");
            if(immediate)require(cd.scsi.data==0&&cd.scsi.response[0]==0,"gap paused immediate status was not GOOD");
        }
    }
}
void admission_and_metadata() {
    for(bool first_audio:{false,true})for(bool second_audio:{false,true})for(unsigned mode:{0u,1u,255u})for(unsigned lba:{0u,3u,6u,9u,12u,15u}) {
        auto media=std::make_shared<Media>(first_audio,second_audio);auto cd=configured(media);seed(cd,3,false);
        command(cd,0xD8,mode,lba);cd.audio_command();
        require(cd.audio.commands==20&&cd.audio.start_lba==lba&&cd.audio.current_lba==lba&&cd.scsi.current_lba==lba,"program D8 admission changed, including data program");
        require(cd.audio.state==(mode?0u:2u)&&cd.audio.seek_start_lba==3&&cd.audio.stop_lba==17&&cd.audio.stop_mode==0,"program start literal state differs");
        require(cd.audio.seek_deadline==4221590&&cd.audio.deadline==4221590&&cd.scsi.phase==8,"program seek profile changed");
    }
    auto media=std::make_shared<Media>();media->known=false;auto cd=configured(media);
    command(cd,0xD8,1,4);cd.audio_command();require(cd.audio.current_lba==4&&cd.audio.seek_deadline==3221590,"unavailable program metadata fabricated a gap");
    pce::CdControl toc_only;toc_only.enabled=toc_only.scsi.enabled=toc_only.audio_enabled=true;toc_only.set_toc(media->table);
    command(toc_only,0xD8,0,5);toc_only.audio_command();require(toc_only.audio.current_lba==5&&toc_only.audio.state==2,"TOC-only start approximation changed");
    for(unsigned kind=1;kind<=4;++kind) {
        auto bad=std::make_shared<Media>();bad->invalid=kind;auto c=configured(bad);seed(c,0,false);
        const auto before=audio_bytes(c.audio);const auto head=c.scsi.current_lba;
        command(c,0xD8,1,kind==4?6:4);refuses([&]{c.audio_command();});
        require(audio_bytes(c.audio)==before&&c.scsi.current_lba==head,"invalid provider changed audio before refusal");
    }
    auto strict=configured(std::make_shared<Media>());command(strict,0xD8,1,18);strict.audio_command();
    require(strict.scsi.data==2&&strict.pending_sense.asc==0x25,"declared strict leadout failure policy changed");
}
void retained_event_and_recovery() {
    for(unsigned mode:{0u,1u,255u}) {
        auto cd=configured(std::make_shared<Media>());command(cd,0xD8,1,0);cd.audio_command();cd.advance_to(1000000);
        command(cd,0xD8,mode,4);cd.audio_command();require(cd.audio.seek_deadline==3221590&&cd.audio.start_lba==0,"gap replaced original pending seek");
        cd.advance_to(3221589);require(cd.scsi.phase==8&&cd.audio.seek_deadline==3221590,"retained seek completed early");
        cd.advance_to(3221590);require(cd.scsi.phase==7&&cd.scsi.data==0&&!cd.audio.seek_deadline&&cd.audio.sector_deadline==3507953,"original seek did not complete ignored command BUSY");
    }
    auto cd=configured(std::make_shared<Media>());command(cd,0xD8,1,4);cd.audio_command();
    cd.advance_to(4000000);require(cd.scsi.phase==8&&cd.audio.state==1&&!cd.audio.deadline,"eventless gap PLAY BUSY was fabricated as success");
    command(cd,0xDA);cd.audio_command();require(cd.audio.state==2&&cd.scsi.phase==7&&cd.scsi.data==0,"DA recovery from ignored start failed");
    command(cd,0xD9,3,9);cd.audio_command();require(cd.audio.state==0&&cd.audio.current_lba==0&&cd.audio.stop_lba==9&&cd.audio.playback_deadline==8810909,"D9 resume/end did not act on retained position");
    command(cd,0xD8,0,11);cd.audio_command();require(cd.audio.playback_deadline==8810909&&cd.scsi.phase==7,"gap PAUSE request cancelled existing playback delay");
    command(cd,0xD9,0);cd.audio_command();require(cd.audio.state==3&&!cd.audio.playback_deadline&&cd.scsi.phase==7,"D9 STOP recovery failed");
}
struct Machine {pce::Bus bus;pce::Cpu cpu;};
std::shared_ptr<Media> configure(Machine& m,pce::AudioTiming timing) {
    m.bus.enable_adpcm();auto media=std::make_shared<Media>(true,true,true);m.bus.cd.set_sector_provider(media);
    m.bus.enable_audio_output(pce::AudioProfile::filtered,48000,timing);
    m.bus.psg.write(0,0);m.bus.psg.write(1,255);m.bus.psg.write(5,255);m.bus.psg.write(4,0xDF);m.bus.psg.write(6,23);
    m.bus.adpcm.playing=true;m.bus.adpcm.control=32;m.bus.adpcm.sample_rate=15;m.bus.adpcm.length=4000;
    for(unsigned i=0;i<m.bus.adpcm.ram.size();++i)m.bus.adpcm.ram[i]=std::uint8_t(i*11+7);
    return media;
}
void clock(Machine& m,std::uint64_t ticks) {m.cpu.ticks=ticks;m.bus.sync(m.cpu);}
void checkpoint_continuation() {
    for(auto timing:{pce::AudioTiming::gear,pce::AudioTiming::legacy})for(bool seeking:{false,true}) {
        auto a=std::make_unique<Machine>();auto media=configure(*a,timing);
        command(a->bus.cd,0xD8,1,0);a->bus.cd.audio_command();clock(*a,seeking?3200000:3230000);
        const auto saved=pce::encode_checkpoint(a->bus,a->cpu);require(saved==pce::encode_checkpoint(a->bus,a->cpu),"save changed active CD/audio/FIR state");
        auto b=std::make_unique<Machine>(),control=std::make_unique<Machine>();auto fresh=configure(*b,timing);configure(*control,timing);
        pce::restore_checkpoint(b->bus,b->cpu,saved);pce::restore_checkpoint(control->bus,control->cpu,saved);
        require(!fresh->audio_reads&&!fresh->data_reads,"restore read source to rebuild retained cache");
        const auto held=audio_bytes(a->bus.cd.audio);
        for(auto* m:{a.get(),b.get()}){command(m->bus.cd,0xD8,1,4);m->bus.cd.audio_command();require(audio_bytes(m->bus.cd.audio)==held,"ignored gap command changed restored source state");}
        // Give the time-only control the same transport request record, without
        // executing an audio command. Audio and PCM then must stay identical.
        control->bus.cd.scsi=a->bus.cd.scsi;
        require(pce::encode_checkpoint(a->bus,a->cpu)==pce::encode_checkpoint(b->bus,b->cpu),"gap transaction differs after fresh restore");
        require(pce::encode_checkpoint(a->bus,a->cpu)==pce::encode_checkpoint(control->bus,control->cpu),"ignored start differs from time-only control before clocks");
        for(auto tick:{3230001ULL,3230100ULL,3507953ULL,3508000ULL}) {
            for(auto* m:{a.get(),b.get(),control.get()})clock(*m,tick);
            require(pce::encode_checkpoint(a->bus,a->cpu)==pce::encode_checkpoint(b->bus,b->cpu),"checkpoint gap continuation differs at source/DSP boundary");
            require(pce::encode_checkpoint(a->bus,a->cpu)==pce::encode_checkpoint(control->bus,control->cpu),"ignored start changed PCM/source/FIR continuation");
        }
        require(a->bus.pcm.drain()==b->bus.pcm.drain(),"restored pending PCM output differs");
        require(media->data_reads==0&&fresh->data_reads==0,"audio start unexpectedly read data sectors");
    }
}
void bus_observation_order() {
    // The public bus observes admitted commands on every synchronization,
    // including a same-tick synchronization before the next port operation.
    // A low-level supervisor must honor that contract when bypassing the bus.
    for(auto timing:{pce::AudioTiming::gear,pce::AudioTiming::legacy})for(unsigned offset:{0u,1u,10u,100u,200u,400u}) {
        auto control=std::make_unique<Machine>();configure(*control,timing);
        if(offset)clock(*control,offset);
        command(control->bus.cd,0xD8,1,0);control->bus.cd.audio_command();clock(*control,control->bus.cd.audio.seek_deadline);
        command(control->bus.cd,0xD9,3,0);control->bus.cd.audio_command();clock(*control,control->bus.cd.audio.sector_deadline-1);
        require(control->bus.cd.audio.state==0&&control->bus.cd.audio.source_cursor.finished,
                "clock-created terminal cursor window was not reached");
        const auto saved=pce::encode_checkpoint(control->bus,control->cpu);
        auto resumed=std::make_unique<Machine>();configure(*resumed,timing);pce::restore_checkpoint(resumed->bus,resumed->cpu,saved);
        for(auto* m:{control.get(),resumed.get()}) {
            command(m->bus.cd,0xD9,3,3);m->bus.cd.audio_command();
            // A real port access first invokes Bus::sync at unchanged CPU time;
            // source observation does not wait for another 44.1kHz edge.
            m->bus.write(m->cpu,0x1801,0xA7);
            require(!m->bus.cd.audio.source_cursor.finished&&m->bus.cd.audio.source_cursor.commands_seen==3,
                    "bus failed to observe admitted D9 before a later port write");
        }
        const auto before=audio_bytes(resumed->bus.cd.audio);
        command(resumed->bus.cd,0xD8,1,4);resumed->bus.cd.audio_command();resumed->bus.sync(resumed->cpu);
        require(audio_bytes(resumed->bus.cd.audio)==before,"ignored gap affected synchronized pending D9");
        control->bus.cd.scsi=resumed->bus.cd.scsi;
        require(pce::encode_checkpoint(control->bus,control->cpu)==pce::encode_checkpoint(resumed->bus,resumed->cpu),
                "synchronized D9/gap transaction differs from time-only control");
        const auto edge=control->bus.cd.audio.sample_next_tick;
        clock(*control,edge);clock(*resumed,edge);
        require(control->bus.cd.audio.sample_raw==std::array<std::int16_t,2>{931,-1717}&&
                resumed->bus.cd.audio.sample_raw==control->bus.cd.audio.sample_raw,
                "D9 rearmed source did not emit independent next-sector sample after gap request");
        require(pce::encode_checkpoint(control->bus,control->cpu)==pce::encode_checkpoint(resumed->bus,resumed->cpu),
                "D9/gap source-cache/FIR/queue state differs after next source edge");
    }
}
}
int main(){try{ignored_matrix();admission_and_metadata();retained_event_and_recovery();checkpoint_continuation();bus_observation_order();std::cout<<checks<<" authored CDDA gap-start/admission/checkpoint checks passed\n";return 0;}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
