// Authored stereo literals and independent rational-clock expectations.
// No BIOS, disc excerpts or game-specific addresses are used.
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include <iostream>
#include <limits>
#include <tuple>
#include <vector>

namespace {
unsigned checks=0;
constexpr std::uint64_t hz=21477273;
constexpr std::int16_t literals[]={32767,-32768,-12345,23456,-1,1,30000,-30000};
void require(bool value,const char* why){++checks;if(!value)throw std::runtime_error(why);}
template<class F> void refuses(F operation,const char* why){bool refused=false;
    try{operation();}catch(const pce::Fault&){refused=true;}require(refused,why);}
constexpr std::uint64_t edge(std::uint64_t n){return (n*hz+44099)/44100;}
std::int16_t value(std::uint64_t ordinal,unsigned channel){return literals[(ordinal*2+channel)%8];}
class Source final:public pce::SectorProvider {
public:
    pce::CdToc geometry;unsigned reads=0;bool failed=false,playable=true;int offset=0;
    Source(){geometry.track_count=1;geometry.leadout_lba=4;geometry.tracks[0]={0,0};}
    pce::Sector read(std::uint32_t)override{throw pce::Fault("authored data refusal");}
    const pce::CdToc& toc()const override{return geometry;}
    bool audio_playable(std::uint32_t)const override{return playable;}
    pce::AudioSector read_audio(std::uint32_t lba)override{
        ++reads;if(failed)throw pce::Fault("authored audio refusal");
        pce::AudioSector result{};
        for(unsigned n=0;n<588;++n)for(unsigned c=0;c<2;++c)
            result[n*2+c]=static_cast<std::int16_t>(int(value(lba*588+n,c))+offset);
        return result;
    }
};
void playing(pce::Bus& bus,unsigned last=3){auto& a=bus.cd.audio;
    a.state=0;a.start_lba=a.current_lba=0;a.stop_lba=last;
    a.sector_deadline=286363;a.sector_fraction=48;a.reschedule();}
std::shared_ptr<Source> setup(pce::Bus& bus,unsigned mode){
    bus.enable_cd_transport();bus.cd.audio_enabled=true;
    auto source=std::make_shared<Source>();bus.cd.set_sector_provider(source);
    if(mode)bus.enable_audio_output(mode>=3?pce::AudioProfile::filtered:pce::AudioProfile::raw,
        mode==4?48000:44100,mode==2?pce::AudioTiming::legacy:pce::AudioTiming::gear);
    playing(bus);return source;
}
std::uint16_t latched(pce::Bus& bus,pce::Cpu& cpu){const auto lo=bus.read(cpu,0x1805);
    return static_cast<std::uint16_t>(lo|(unsigned(bus.read(cpu,0x1806))<<8));}
void sync(pce::Bus& bus,pce::Cpu& cpu,std::uint64_t ticks){cpu.ticks=ticks;bus.sync(cpu);}
void control_only(){
    pce::Bus bus;pce::Cpu cpu;bus.enable_cd_control();
    require(latched(bus,cpu)==0 && bus.read(cpu,0x1803)==0x12,"initial latch or side");
    for(const auto tick:{0ULL,1ULL,699ULL}){cpu.ticks=tick;bus.write(cpu,0x1805,255);
        require(!bus.cd.audio.sample_right && !bus.cd.audio.sample_last_latch,"early write accepted");}
    cpu.ticks=700;bus.write(cpu,0x1805,0);
    require(bus.cd.audio.sample_right && bus.cd.audio.sample_last_latch==700 && latched(bus,cpu)==0,
        "control-only latch incorrectly used the disabled transport clock");
    bus.cd.bram_unlocked=true;bus.cd.interrupt_active=0x60;
    require(bus.read(cpu,0x1803)==0x70 && !bus.cd.bram_unlocked,"side status/IRQ merge/BRAM lock");
    for(unsigned i=0;i<12;++i)require(bus.read(cpu,0x1803)==0x70,"status read toggled side");
    cpu.ticks=1399;bus.write(cpu,0x1805,7);
    require(bus.cd.audio.sample_last_latch==700 && bus.cd.audio.sample_right,"rejected write reset cooldown");
    cpu.ticks=1400;bus.write(cpu,0x1806,3);
    require(bus.cd.audio.sample_last_latch==700 && bus.cd.audio.sample_right,"1806 write acquired latch semantics");
    bus.write(cpu,0x1805,127);
    require(!bus.cd.audio.sample_right && bus.cd.audio.sample_last_latch==1400 && bus.read(cpu,0x1803)==0x72,
        "second accepted write did not select left");
    bus.enable_cd_control();require(!bus.cd.audio.sample_right && !bus.cd.audio.sample_latch &&
        !bus.cd.audio.sample_last_latch,"full control reset retained latch");
}
void control_clock_guards(){
    pce::Bus bus;pce::Cpu cpu;bus.enable_cd_control();sync(bus,cpu,700);
    cpu.ticks=699;refuses([&]{bus.sync(cpu);},"control-only source clock regressed");
    require(bus.cd.audio.sample_clock_ticks==700 && bus.cd.audio.sample_frames==1 &&
        bus.cd.audio.sample_ticks==488 && !bus.cd.audio.sample_latch && !bus.cd.audio.sample_right,
        "rejected clock regression changed guest sample state");
    for(bool enabled:{false,true}){pce::Bus late;pce::Cpu c;late.enable_cd_control();
        if(enabled)late.enable_psg();late.psg.main_volume=0x52;late.psg.channels[3].dda=11;
        sync(late,c,700);const auto kinds=late.kind;
        refuses([&]{late.enable_audio_output();},"control-only execution allowed retroactive PCM enable");
        require(late.psg.enabled==enabled && late.psg.main_volume==0x52 && late.psg.channels[3].dda==11 &&
            late.kind==kinds && !late.pcm.enabled && !late.pcm.frames && late.cd.audio.sample_clock_ticks==700,
            "rejected late PCM enable changed PSG, mapping or sample clock");
    }
}
void clock_horizon(){
    // Literal values independently calculated with unbounded integer math:
    // floor(UINT64_MAX*44100/21477273) and its final ceiling-rational edge.
    constexpr auto end=std::numeric_limits<std::uint64_t>::max();
    constexpr std::uint64_t count=37877314017035180ULL,last=18446744073709551281ULL;
    pce::Bus bus;pce::Cpu cpu;bus.enable_cd_transport();
    sync(bus,cpu,last-1);
    require(bus.cd.audio.sample_frames==count-1 && bus.cd.audio.sample_next_tick==last,
        "silent source lost its final representable deadline");
    sync(bus,cpu,last);
    require(bus.cd.audio.sample_frames==count && bus.cd.audio.sample_ticks==last && !bus.cd.audio.sample_next_tick,
        "silent final source edge wrapped its future deadline");
    sync(bus,cpu,end);
    require(bus.cd.scsi.master_ticks==end && bus.cd.audio.sample_clock_ticks==end &&
        bus.cd.audio.sample_frames==count && bus.cd.audio.sample_ticks==last && !bus.cd.audio.sample_next_tick,
        "idle transport could not reach uint64 clock horizon");
    bus.write(cpu,0x1805,255);
    require(latched(bus,cpu)==0 && bus.cd.audio.sample_right && bus.cd.audio.sample_last_latch==end,
        "representable latch at clock horizon was rejected");
    bus.write(cpu,0x1805,0);require(bus.cd.audio.sample_last_latch==end && bus.cd.audio.sample_right,
        "horizon cooldown wrapped and accepted a duplicate write");
    bool transport_overflow=false;
    try{bus.write(cpu,0x1800,0);}catch(const pce::Fault& e){transport_overflow=std::string(e.what())=="CD transport clock overflow";}
    require(transport_overflow && !bus.cd.scsi.event && !bus.cd.scsi.deadline,
        "real transport scheduling overflow was hidden or wrapped");
    // Seed an authored near-horizon source clock, then execute its last real
    // edge. This is a boundary-state fixture, not a claim of executing all
    // preceding 37 quadrillion sample edges.
    pce::Bus active;pce::Cpu c;active.enable_cd_transport();active.cd.audio_enabled=true;
    auto& a=active.cd.audio;a.sample_frames=count-1;a.sample_ticks=18446744073709550794ULL;
    a.sample_clock_ticks=last-1;a.sample_next_tick=last;a.sample_remainder=16139;
    sync(active,c,last-1);require(a.sample_frames==count-1,"active final source edge fired early");
    sync(active,c,last);require(a.sample_frames==count && a.sample_ticks==last && !a.sample_next_tick && a.sample_valid,
        "active source could not complete its final representable edge");
    sync(active,c,end);require(a.sample_frames==count && a.sample_clock_ticks==end && !a.sample_next_tick && !active.pcm.frames,
        "exhausted source wrapped a deadline or synthesized extra samples");
}
void exact_phase_and_legacy_boundary(){
    require(edge(14700)==7159091,"literal rational CDDA clock boundary");
    for(unsigned mode=0;mode<5;++mode){pce::Bus bus;pce::Cpu cpu;auto source=setup(bus,mode);
        bus.cd.audio.stop_lba=0;bus.cd.audio.stop_mode=1;
        for(unsigned n=14698;n<=14702;++n){sync(bus,cpu,edge(n)-1);
            require(bus.cd.audio.sample_frames==n-1,"CDDA source edge rounded early near exact period");
            sync(bus,cpu,edge(n));require(bus.cd.audio.sample_frames==n && bus.cd.audio.sample_ticks==edge(n),
                "CDDA source edge rounded late near exact period");
            require(bus.cd.audio.sample_raw==std::array<std::int16_t,2>{value((n-1)%588,0),value((n-1)%588,1)},
                "exact-period source cursor identity changed");bus.pcm.drain();
        }
        require(source->reads==1,"loop source and legacy compatibility cursor failed to share cache");
        pce::Bus stopped;pce::Cpu c;setup(stopped,mode);c.ticks=487;stopped.write(c,0x1804,2);
        require(!stopped.cd.audio.sample_frames,"legacy output edge leaked into canonical source state");
        sync(stopped,c,488);require(stopped.cd.audio.sample_frames==1 &&
            stopped.cd.audio.sample_held==std::array<std::int16_t,2>{},"between-edge reset depended on PCM timing");
        if(mode)require(stopped.pcm.drain()==(mode==2 ? std::vector<std::int16_t>{10922,-10922}:std::vector<std::int16_t>{0,0}),
            "canonical guest cursor changed legacy floor-edge PCM compatibility");
        c.ticks=700;stopped.write(c,0x1805,0);require(latched(stopped,c)==0 && stopped.cd.audio.sample_right,
            "between-edge reset latched a presentation-only compatibility sample");
    }
}
void profiles_and_bytes(){
    std::vector<std::tuple<std::uint64_t,std::uint16_t,bool>> reference;
    for(unsigned mode=0;mode<5;++mode){pce::Bus bus;pce::Cpu cpu;auto source=setup(bus,mode);
        sync(bus,cpu,487);require(bus.cd.audio.sample_frames==0 && bus.cd.audio.sample_held==std::array<std::int16_t,2>{},"source before first edge");
        sync(bus,cpu,488);require(bus.cd.audio.sample_frames==1 && bus.cd.audio.sample_held==std::array<std::int16_t,2>{32767,-32768},"first signed source edge");
        for(unsigned n=1;n<=150;++n){cpu.ticks=n*700;bus.write(cpu,0x1805,static_cast<std::uint8_t>(n));
            const auto frames=cpu.ticks*44100/hz;
            const auto expected=static_cast<std::uint16_t>(value(frames-1,n&1));
            require(latched(bus,cpu)==expected,"latch not latest signed source/channel");
            require(bus.cd.audio.sample_frames==frames && bus.cd.audio.sample_ticks==edge(frames),"source count/last timestamp");
            const auto status=bus.read(cpu,0x1803);
            require((status&2)==((n&1)?0:2),"status side disagrees with accepted writes");
            const auto actual=std::tuple{frames,expected,bus.cd.audio.sample_right};
            if(!mode)reference.push_back(actual);else require(actual==reference[n-1],"PCM/profile/rate affected guest latch");
            bus.pcm.drain();
        }
        require(source->reads==1,"dual source/presentation cursor reread the same sector");
        if(!mode)require(!bus.pcm.frames && !bus.pcm.enabled,"PCM-off guest samples created presentation frames");
    }
    pce::Bus bus;pce::Cpu cpu;setup(bus,0);cpu.ticks=700;bus.write(cpu,0x1805,0);
    require(bus.read(cpu,0x1805)==0,"negative sample LSB");
    cpu.ticks=1000;require(bus.read(cpu,0x1806)==128 && bus.cd.audio.sample_right,"split-byte read tore the latch or toggled");
    cpu.ticks=1400;bus.write(cpu,0x1806,255);bus.write(cpu,0x1805,0);
    require(latched(bus,cpu)==static_cast<std::uint16_t>(-12345),"left negative two's-complement encoding");
}
void hold_and_fader(){
    for(unsigned operation=0;operation<4;++operation){pce::Bus bus;pce::Cpu cpu;setup(bus,0);
        cpu.ticks=700;bus.write(cpu,0x1805,0);const auto old=bus.cd.audio.sample_held;
        cpu.ticks=710;
        if(operation==0){bus.cd.audio.state=2;bus.cd.audio.sector_deadline=0;bus.cd.audio.reschedule();}
        if(operation==1)bus.cd.audio.stop();
        if(operation==2)bus.write(cpu,0x1804,2);
        if(operation==3){bus.cd.audio.seek_deadline=5000;bus.cd.audio.reschedule();}
        sync(bus,cpu,710);
        require(bus.cd.audio.sample_held==old && latched(bus,cpu)==0x8000 && bus.cd.audio.sample_right,
            "drive transition prematurely cleared held DAC/latch/side");
        sync(bus,cpu,975);
        require(bus.cd.audio.sample_held==std::array<std::int16_t,2>{} && latched(bus,cpu)==0x8000,
            "inactive sample edge failed to zero DAC or cleared latched sample");
        cpu.ticks=1400;bus.write(cpu,0x1805,0);require(latched(bus,cpu)==0,"inactive source did not latch zero");
    }
    for(unsigned mode=0;mode<5;++mode){pce::Bus bus;pce::Cpu cpu;setup(bus,mode);
        // An authored short fade gives exact integer gain 1/2 at the first
        // sample edge and expires just after the second. The register chooses
        // much longer durations; the multiplier/truncation semantics are shared.
        bus.cd.audio.fader=8;bus.cd.audio.fade_duration=976;
        sync(bus,cpu,488);require(bus.cd.audio.sample_raw==std::array<std::int16_t,2>{32767,-32768} &&
            bus.cd.audio.sample_held==std::array<std::int16_t,2>{16383,-16384},"post-fader signed truncation");
        cpu.ticks=700;bus.write(cpu,0x1805,0);require(latched(bus,cpu)==0xc000,"latch bypassed held post-fader sample");
        sync(bus,cpu,976);require(bus.cd.audio.sample_held==std::array<std::int16_t,2>{-12,24},"fade sampled at edge rather than current read time");
        cpu.ticks=1400;bus.write(cpu,0x1805,0);require(latched(bus,cpu)==static_cast<std::uint16_t>(-12),"fader write/read recomputed held sample");
    }
}
void media_and_partition(){
    pce::Bus a,b;pce::Cpu ca,cb;auto sa=setup(a,0);auto sb=setup(b,0);
    sync(a,ca,edge(1764));for(std::uint64_t t=1;t<edge(1764);t+=3179)sync(b,cb,t);
    sync(b,cb,edge(1764));
    require(a.cd.audio.sample_raw==b.cd.audio.sample_raw && a.cd.audio.sample_frames==1764 &&
        a.cd.audio.source_cursor.lba==b.cd.audio.source_cursor.lba && a.cd.audio.source_cursor.frame==b.cd.audio.source_cursor.frame,
        "PCM-off partition changed source cursor");
    require(sa->reads==3 && sb->reads==3,"PCM-off source cache read count");
    pce::Bus missing;pce::Cpu cpu;missing.enable_cd_transport();missing.cd.audio_enabled=true;playing(missing);
    sync(missing,cpu,700);require(!missing.cd.audio.sample_valid,"provider-less active DAC was called valid silence");
    refuses([&]{missing.write(cpu,0x1805,0);},"unavailable sample silently latched");
    require(!missing.cd.audio.sample_right && !missing.cd.audio.sample_last_latch,"failed latch committed side/cooldown");
    auto replacement=std::make_shared<Source>();missing.cd.provider=replacement;
    sync(missing,cpu,975);require(missing.cd.audio.sample_valid && replacement->reads==1,"new source did not recover unavailable DAC");
    cpu.ticks=1400;missing.write(cpu,0x1805,0);require(latched(missing,cpu)==0x8000,"new source retained invalid cursor");
    pce::Bus bad;pce::Cpu badcpu;auto failing=setup(bad,0);failing->failed=true;
    refuses([&]{sync(bad,badcpu,488);},"provider read error became silence");
    pce::Bus gap;pce::Cpu gapcpu;auto data=setup(gap,0);data->playable=false;gapcpu.ticks=700;gap.write(gapcpu,0x1805,0);
    require(latched(gap,gapcpu)==0 && gap.cd.audio.sample_valid && !data->reads,"nonplayable audio geometry was read as PCM");
}
}
int main(){try{control_only();control_clock_guards();clock_horizon();exact_phase_and_legacy_boundary();profiles_and_bytes();hold_and_fader();media_and_partition();
    std::cout<<checks<<" authored CDDA latch/source/phase/provider/profile checks passed\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
