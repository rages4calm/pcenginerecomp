// Authored digital mixer expectations. No retail samples or reference audio.
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <tuple>

namespace {
unsigned checks=0;
constexpr std::uint64_t clock_hz=21477273;
void require(bool okay,const char* why) {++checks;if(!okay)throw std::runtime_error(why);}
template<class F> void fault(F&& fn,const char* why) {
    bool refused=false;try{fn();}catch(const pce::Fault&){refused=true;}require(refused,why);
}
std::uint64_t sample_tick(unsigned frame) {return frame*clock_hz/44100;}
std::uint64_t hash_pcm(const std::vector<std::int16_t>& samples) {
    std::uint64_t hash=14695981039346656037ULL;
    for(auto value:samples) {
        const unsigned bits=static_cast<std::uint16_t>(value);
        hash=(hash^(bits%256))*1099511628211ULL;
        hash=(hash^(bits/256))*1099511628211ULL;
    }
    return hash;
}
auto cpu_state(const pce::Cpu& s) {
    return std::tuple{s.a,s.x,s.y,s.sp,s.p,s.pc,s.mpr,s.mpr_latch,s.ticks,s.cycles,
        s.native_steps,s.interpreter_steps,s.guard_misses,s.native_block_steps,
        s.interpreter_block_steps,s.block_bytes,s.clock_divisor,s.irq_sampled,
        s.irq_vector,s.irq_entries,s.rti_steps};
}
auto output_state(const pce::AudioOutput& a) {
    return std::tuple{a.enabled,a.master_ticks,a.frames,a.discarded_frames,a.psg_nonzero,
        a.adpcm_nonzero,a.cdda_nonzero,a.mixed_nonzero,a.pcm_hash,a.peak,a.queued_frames()};
}
void silent_clock_queue() {
    pce::Bus whole,parts;whole.enable_audio_output();parts.enable_audio_output();
    whole.pcm.advance_to(whole,486);require(whole.pcm.frames==0,"PCM edge occurred before floor-rational boundary");
    for(unsigned frame=1;frame<=64;++frame) {
        whole.pcm.advance_to(whole,sample_tick(frame));
        require(whole.pcm.frames==frame,"PCM rational frame edge count");
    }
    whole.pcm.advance_to(whole,clock_hz);
    for(unsigned t=1;t<clock_hz;t+=7919)parts.pcm.advance_to(parts,t);
    parts.pcm.advance_to(parts,clock_hz);
    require(whole.pcm.frames==44100 && whole.pcm.queued_frames()==8192 &&
            whole.pcm.discarded_frames==35908,"one-second count or bounded oldest-frame discard");
    require(output_state(whole.pcm)==output_state(parts.pcm),"PCM advance partition changes output diagnostics");
    require(whole.pcm.pcm_hash==hash_pcm(std::vector<std::int16_t>(88200)),"one-second silent PCM hash");
    require(!whole.pcm.mixed_nonzero && !whole.pcm.peak,"silent source produced nonzero PCM");
    const auto hash=whole.pcm.pcm_hash,frames=whole.pcm.frames;
    const auto output=whole.pcm.drain();
    require(output.size()==16384 && std::all_of(output.begin(),output.end(),[](auto v){return v==0;}),
            "bounded drain size or silent samples");
    require(whole.pcm.drain().empty() && whole.pcm.frames==frames && whole.pcm.pcm_hash==hash,
            "drain changed generated stream identity or retained stale samples");
    whole.pcm.advance_to(whole,sample_tick(44101));
    require(whole.pcm.drain()==std::vector<std::int16_t>({0,0}) && whole.pcm.discarded_frames==35908,
            "queue did not restart after drain");
    const auto before=output_state(whole.pcm);
    fault([&]{whole.pcm.advance_to(whole,0);},"audio output accepted clock regression");
    require(output_state(whole.pcm)==before,"clock regression mutated output state");
    fault([&]{whole.enable_audio_output();},"audio output enabled twice");
    pce::Bus late;late.enable_psg();late.psg.clock_ticks=1;
    fault([&]{late.enable_audio_output();},"audio output accepted already-clocked PSG");
}
void dda(pce::Bus& bus,pce::Cpu& cpu,unsigned value=31) {
    for(auto [port,data]:{std::pair{0,0},std::pair{1,255},std::pair{4,223},
                         std::pair{5,240},std::pair{6,static_cast<int>(value)}})
        bus.write(cpu,static_cast<std::uint16_t>(0x800+port),static_cast<std::uint8_t>(data));
}
void dda_and_observation() {
    pce::Bus bus;bus.enable_audio_output();pce::Cpu cpu;dda(bus,cpu);
    cpu.ticks=487;bus.sync(cpu);
    require(bus.pcm.psg_nonzero==1 && bus.pcm.mixed_nonzero==1 && bus.pcm.peak==1761,
            "PSG DDA source activity or fixed mixer gain");
    const auto original=cpu_state(cpu);
    const auto guest=std::tuple{bus.psg.writes,bus.cd.reads,bus.cd.writes,bus.adpcm.samples,
        bus.vdc.reads,bus.vdc.writes,bus.irq.entries,bus.psg.clock_ticks,bus.cd.scsi.master_ticks};
    require(bus.pcm.drain()==std::vector<std::int16_t>({1761,0}),"literal DDA left-only mixer vector");
    require(cpu_state(cpu)==original && guest==std::tuple{bus.psg.writes,bus.cd.reads,bus.cd.writes,
        bus.adpcm.samples,bus.vdc.reads,bus.vdc.writes,bus.irq.entries,bus.psg.clock_ticks,bus.cd.scsi.master_ticks},
        "drain advanced CPU or devices");
    bus.write(cpu,0x806,0);cpu.ticks=974;bus.sync(cpu);
    require(bus.pcm.drain()==std::vector<std::int16_t>({-1761,0}),"literal negative DDA mixer vector");
    require(bus.pcm.pcm_hash==hash_pcm({1761,0,-1761,0}),"signed little-endian stream hash");
    pce::Bus disabled;const auto state=output_state(disabled.pcm);
    disabled.pcm.advance_to(disabled,clock_hz);
    require(output_state(disabled.pcm)==state && !disabled.psg.enabled && !disabled.psg.clock_ticks &&
            !disabled.cd.scsi.master_ticks,"opt-out PCM call advanced devices or enabled synthesis");
}
void ultrasonic_mixer() {
    for(bool impulse:{false,true}) {
        pce::Bus whole,parts;whole.enable_audio_output();parts.enable_audio_output();
        for(auto* bus:{&whole,&parts}) {
            auto& psg=bus->psg;
            psg.write(0,0);psg.write(1,255);psg.write(5,240);
            psg.write(2,4);psg.write(3,0);
            for(unsigned index=0;index<32;++index)
                psg.write(6,static_cast<std::uint8_t>(impulse ? (index==0 ? 31:0):index));
            psg.write(4,159);
        }
        whole.pcm.advance_to(whole,sample_tick(64));
        for(unsigned frame=1;frame<=64;++frame)parts.pcm.advance_to(parts,sample_tick(frame));
        const auto output=whole.pcm.drain();
        require(output==parts.pcm.drain() && output_state(whole.pcm)==output_state(parts.pcm),
                "ultrasonic averaging depends on audio clock partition");
        // Centered ramp mean is zero. One 31 among 31 zeros has signed
        // PSG output -4955, then the fixed one-third source gain gives -1651.
        const std::int16_t expected=impulse ? -1651:0;
        require(output.size()==128,"ultrasonic mixer frame count");
        for(unsigned frame=0;frame<64;++frame)
            require(output[frame*2]==expected && output[frame*2+1]==0,
                    "ultrasonic waveform mean or stereo mixer gain");
        require(whole.pcm.psg_nonzero==(impulse ? 64u:0u) &&
                whole.pcm.mixed_nonzero==whole.pcm.psg_nonzero && !whole.pcm.discarded_frames,
                "ultrasonic source activity or loss counters");
        require(whole.psg.channels[0].wave_index==parts.psg.channels[0].wave_index &&
                whole.psg.channels[0].wave_remaining==parts.psg.channels[0].wave_remaining,
                "ultrasonic presentation changed oscillator phase");
    }
}
void adpcm_fader() {
    for(bool fade_adpcm:{false,true}) {
        pce::Bus bus;bus.enable_adpcm();bus.enable_audio_output();
        bus.adpcm.playing=true;bus.adpcm.control=32;bus.adpcm.sample_rate=0;
        bus.adpcm.length=10;bus.adpcm.decoder_output=3072;
        // A short authored fader duration isolates its exact half/full gain
        // arithmetic. Normal command durations are qualified in cdda_tests.
        bus.cd.write_fader(fade_adpcm?0x0e:0x0c);bus.cd.audio.fade_duration=974;
        bus.pcm.advance_to(bus,974);
        const auto output=bus.pcm.drain();
        require(output==(fade_adpcm ? std::vector<std::int16_t>{2730,2730,0,0}:
                                     std::vector<std::int16_t>{5461,5461,5461,5461}),
                "held ADPCM PCM, fader target, or half/full gain");
        require(bus.adpcm.samples==0 && bus.adpcm.decoder_output==3072 && bus.pcm.adpcm_nonzero==2,
                "mixer consumed ADPCM ahead of nibble clock or counted post-fader source activity");
        bus.adpcm.playing=false;bus.pcm.advance_to(bus,1461);
        require(bus.pcm.drain()==std::vector<std::int16_t>({0,0}),"stopped held ADPCM leaked into mixer");
    }
}

class Samples final:public pce::SectorProvider {
public:
    pce::CdToc geometry;
    unsigned reads=0,classifications=0;
    bool fail_read=false,fail_classification=false;
    Samples() {
        geometry.track_count=3;geometry.leadout_lba=6;
        geometry.tracks[0]={0,0};geometry.tracks[1]={2,4};geometry.tracks[2]={4,0};
    }
    pce::Sector read(std::uint32_t) override {throw pce::Fault("unexpected data-sector request");}
    bool audio_playable(std::uint32_t lba) const override {
        ++const_cast<Samples*>(this)->classifications;
        if(fail_classification)throw pce::Fault("authored classification failure");
        return lba<6 && lba!=1 && (lba<2 || lba>=4); // Stored audio, gap, data, audio.
    }
    pce::AudioSector read_audio(std::uint32_t lba) override {
        ++reads;if(fail_read)throw pce::Fault("authored audio read failure");
        pce::AudioSector result{};const auto level=static_cast<std::int16_t>(3000+lba*300);
        for(unsigned frame=0;frame<588;++frame){result[2*frame]=level;result[2*frame+1]=-2*level;}
        return result;
    }
    const pce::CdToc& toc() const override {return geometry;}
};
std::shared_ptr<Samples> attach(pce::Bus& bus) {
    bus.enable_cd_transport();bus.cd.audio_enabled=true;
    auto source=std::make_shared<Samples>();bus.cd.set_sector_provider(source);bus.enable_audio_output();return source;
}
void playing(pce::Bus& bus,unsigned lba=0) {
    auto& audio=bus.cd.audio;audio.state=0;audio.start_lba=audio.current_lba=lba;
    audio.stop_lba=5;audio.sector_deadline=286363;audio.sector_fraction=48;audio.reschedule();
}
void command(pce::CdControl& cd,unsigned opcode,unsigned mode=0,unsigned lba=0) {
    cd.scsi.command.fill(0);cd.scsi.command[0]=opcode;cd.scsi.command[1]=mode;
    cd.scsi.command[3]=lba>>16;cd.scsi.command[4]=lba>>8;cd.scsi.command[5]=lba;
    cd.scsi.phase=3;cd.scsi.signals=0xd0;cd.scsi.event=0;cd.scsi.deadline=0;
    cd.scsi.response_index=cd.scsi.response_size=0;cd.audio_command();
}
void cd_audio_geometry_and_edges() {
    pce::Bus bus;auto source=attach(bus);playing(bus);
    bus.pcm.advance_to(bus,286362);auto output=bus.pcm.drain();
    require(output.size()==1174 && source->reads==1,"first CDDA sector frame count/cache bound");
    for(unsigned i=0;i<output.size();i+=2)
        require(output[i]==1000 && output[i+1]==-2000,"authored CDDA stereo/mixer vector");
    bus.pcm.advance_to(bus,286363);
    require(bus.cd.audio.current_lba==1 && bus.pcm.drain()==std::vector<std::int16_t>({1000,-2000}) && source->reads==1,
            "CDDA sector boundary must retain the terminal source frame");
    bus.pcm.advance_to(bus,859090);output=bus.pcm.drain();
    require(bus.cd.audio.current_lba==3 && source->reads==1 &&
            std::all_of(output.begin(),output.end(),[](auto v){return !v;}),"data-track PCM was synthesized or read as audio");
    bus.pcm.advance_to(bus,1145454);output=bus.pcm.drain();
    require(bus.cd.audio.current_lba==4 && output.size()==1176 &&
            std::all_of(output.begin(),output.end(),[](auto v){return !v;}) && source->reads==1,"CDDA data-sector terminal frame identity");
    bus.pcm.advance_to(bus,1145941);output=bus.pcm.drain();
    require(output==std::vector<std::int16_t>({1400,-2800}) && source->reads==2,"CDDA next-sector first source frame identity");
    pce::Bus loop;auto looping=attach(loop);playing(loop);loop.cd.audio.stop_lba=0;loop.cd.audio.stop_mode=1;
    loop.pcm.advance_to(loop,572727);
    require(loop.cd.audio.current_lba==0 && loop.cd.audio.sectors_played==2 && loop.cd.audio.state==0 &&
            looping->reads==1 && loop.pcm.cdda_nonzero==1176,"CDDA loop edge or same-sector cache");

    pce::Bus seek;auto seeking=attach(seek);command(seek.cd,0xd8,1,0);
    seek.pcm.advance_to(seek,3221589);
    require(!seek.pcm.cdda_nonzero && seeking->reads==0,"seeking drive emitted CDDA prematurely");
    seek.pcm.drain();seek.pcm.advance_to(seek,3222077);
    require(seeking->reads==1 && seek.pcm.cdda_nonzero>0,"seek completion did not expose audio");
    command(seek.cd,0xda);seek.pcm.drain();const auto count=seek.pcm.cdda_nonzero;
    seek.pcm.advance_to(seek,seek.pcm.master_ticks+10000);output=seek.pcm.drain();
    require(seek.pcm.cdda_nonzero==count && std::all_of(output.begin(),output.end(),[](auto v){return !v;}),
            "paused drive emitted CDDA");
    command(seek.cd,0xd9,3,5);const auto resume=seek.cd.audio.playback_deadline;
    seek.pcm.advance_to(seek,resume-1);require(seek.pcm.cdda_nonzero==count,"resume delay emitted CDDA");
    seek.pcm.advance_to(seek,resume+1000);require(seek.pcm.cdda_nonzero>count,"resume edge did not restore audio");
}
void cd_fader_failures() {
    pce::Bus faded;attach(faded);playing(faded);faded.cd.write_fader(0x0c);faded.cd.audio.fade_duration=974;
    faded.pcm.advance_to(faded,974);
    require(faded.pcm.drain()==std::vector<std::int16_t>({500,-1000,0,0}),"CDDA fader half/full gain");
    for(bool classification:{false,true}) {
        pce::Bus bus;auto source=attach(bus);playing(bus);
        source->fail_read=!classification;source->fail_classification=classification;
        fault([&]{bus.pcm.advance_to(bus,487);},"CDDA source fault silently muted");
    }
    pce::Bus missing;missing.enable_cd_transport();missing.cd.audio_enabled=true;
    missing.enable_audio_output();playing(missing);
    fault([&]{missing.pcm.advance_to(missing,487);},"missing CDDA provider silently succeeded");
}
void cpu_conservation() {
    pce::Bus off,on;off.kind[0x80]=on.kind[0x80]=pce::BankKind::ram;
    off.kind[0xf8]=on.kind[0xf8]=pce::BankKind::ram;
    // LDA, TAX, INX, store/increment work RAM, and branch back to INX.
    constexpr std::uint8_t program[]={0xa9,0x23,0xaa,0xe8,0x8e,0x00,0x20,0xee,0x00,0x20,0x80,0xf7};
    off.load(0x100000,program,sizeof(program));on.load(0x100000,program,sizeof(program));on.enable_audio_output();
    pce::Cpu a,b;a.pc=b.pc=0x4000;
    for(unsigned i=0;i<20000;++i) {
        require(pce::interpret_step(off,a,std::numeric_limits<std::uint64_t>::max())==pce::Exit::executed &&
                pce::interpret_step(on,b,std::numeric_limits<std::uint64_t>::max())==pce::Exit::executed,
                "authored CPU conservation program did not execute");
    }
    require(cpu_state(a)==cpu_state(b) && *off.bytes==*on.bytes && off.generation==on.generation &&
            off.irq.master_ticks==on.irq.master_ticks && off.cd.scsi.master_ticks==on.cd.scsi.master_ticks,
            "audio output changed CPU/RAM/retirement/device timeline");
    const auto original=cpu_state(b);on.pcm.drain();require(cpu_state(b)==original,"drain advanced interpreted CPU");
}
}
int main() {
    try {
        silent_clock_queue();dda_and_observation();ultrasonic_mixer();adpcm_fader();cd_audio_geometry_and_edges();
        cd_fader_failures();cpu_conservation();
        std::cout<<"Guest-clock PCM output: "<<checks<<" independent expectations passed\n";
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
