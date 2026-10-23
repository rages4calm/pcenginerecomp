// Authored digital PSG vectors. These are not retail recordings or copied
// emulator fixtures; no analog filter/resampler/hardware-output qualification.
#include "pce/audio.hpp"
#include <array>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <tuple>

static unsigned checks=0;
static void require(bool okay,const char* why) {++checks;if(!okay)throw std::runtime_error(why);}
static pce::Psg tone(unsigned index=0,unsigned frequency=4) {
    pce::Psg p;p.enabled=true;p.synthesis_enabled=true;p.main_volume=0xff;
    auto& c=p.channels[index];c.frequency=frequency;c.control=0x9f;c.balance=0xff;
    for(unsigned i=0;i<32;++i)c.waveform[i]=i;
    return p;
}
static auto phase(const pce::Psg::Channel& c) {
    return std::tuple{c.wave_index,c.wave_remaining,c.noise_remaining,c.noise_lfsr};
}
static void clock_vectors() {
    auto p=tone();
    require(p.sample_pcm()==std::array<std::int16_t,2>{-5285,-5285},"initial centered DAC vector");
    p.advance_to(0);require(p.channels[0].wave_index==0,"zero advance acquired initial edge");
    p.advance_to(5);require(p.channels[0].wave_index==0 && p.master_remainder==5,"PSG master divider");
    p.advance_to(6);require(p.channels[0].wave_index==1 && p.channels[0].wave_remaining==3,"Gear initial zero-counter phase");
    require(p.sample_pcm()==std::array<std::int16_t,2>{-4944,-4944},"waveform sample one");
    p.advance_to(23);require(p.channels[0].wave_index==1,"wave edge occurred early");
    p.advance_to(24);require(p.channels[0].wave_index==2 && p.channels[0].wave_remaining==4,"wave edge exact expiry");
    require(p.sample_pcm()==std::array<std::int16_t,2>{-4603,-4603},"waveform sample two");
    auto zero=tone(0,0);zero.advance_to(6);require(zero.channels[0].wave_index==1,"zero frequency initial edge");
    zero.advance_to(24575);require(zero.channels[0].wave_index==1,"zero period must be 4096 PSG clocks");
    zero.advance_to(24576);require(zero.channels[0].wave_index==2,"zero period exact boundary");
    auto fastest=tone(0,1);fastest.advance_to(6);require(fastest.channels[0].wave_index==2,"period-one initial phase");
    fastest.advance_to(186);require(fastest.channels[0].wave_index==0,"32-entry waveform wrap");
    const auto before=phase(fastest.channels[0]);bool refused=false;
    try{fastest.advance_to(185);}catch(const std::invalid_argument&){refused=true;}
    require(refused && fastest.clock_ticks==186 && phase(fastest.channels[0])==before,"backwards PSG clock mutation");
}
static void pcm_vectors() {
    auto p=tone();auto& c=p.channels[0];c.control=0xdf;c.dda=31;
    require(p.sample_pcm()==std::array<std::int16_t,2>{5285,5285},"maximum DDA vector");
    c.dda=0;require(p.sample_pcm()[0]==-5285,"minimum centered DDA vector");
    c.dda=31;c.balance=0xf0;require(p.sample_pcm()==std::array<std::int16_t,2>{5285,0},"right pan mute");
    c.balance=0x0f;require(p.sample_pcm()==std::array<std::int16_t,2>{0,5285},"left pan mute");
    c.balance=0xff;p.main_volume=0xf0;require(p.sample_pcm()==std::array<std::int16_t,2>{5285,0},"master right mute");
    p.main_volume=0x0f;require(p.sample_pcm()==std::array<std::int16_t,2>{0,5285},"master left mute");
    p.main_volume=0xff;c.control=0xde;require(p.sample_pcm()[0]==4448,"one 1.5dB attenuation step");
    c.control=0xdd;require(p.sample_pcm()[0]==3735,"two attenuation steps");
    c.control=0xdf;c.balance=0x88;require(p.sample_pcm()[0]==387,"balance central step eight");
    c.balance=0x77;require(p.sample_pcm()[0]==325,"balance central step seven");
    c.balance=0x11;require(p.sample_pcm()[0]==31,"balance low step");
    c.balance=0xff;c.control=0xc0;require(p.sample_pcm()[0]==0,"amplitude zero mutes");
    c.control=0xdf;p.centered_dac=false;require(p.sample_pcm()[0]==10571,"original unipolar DAC vector");
    for(auto& channel:p.channels){channel.control=0xdf;channel.balance=0xff;channel.dda=31;}
    require(p.sample_pcm()[0]==32767,"unipolar mix saturates rather than wraps");
    p.centered_dac=true;require(p.sample_pcm()[0]==31713,"six-channel centered headroom");
    const auto count=p.writes;const auto sample=p.sample_pcm();
    require(sample==p.sample_pcm() && p.writes==count,"sample_pcm must be observational");
    p.enabled=false;require(p.sample_pcm()==std::array<std::int16_t,2>{0,0},"disabled device output");
}
static void mode_and_legacy_vectors() {
    auto p=tone();p.write(0,0);p.write(4,0xdf);p.write(6,23);
    p.advance_to(1000);require(p.channels[0].wave_index==0 && p.channels[0].dda==23,"DDA must hold wave phase");
    p.write(4,0x9f);require(p.channels[0].wave_index==0 && p.channels[0].wave_remaining==4,"DDA falling reload");
    p.advance_to(1023);require(p.channels[0].wave_index==1,"DDA reload edge and retained master fraction");
    auto old=tone();old.synthesis_enabled=false;
    const auto original=old.channels;old.advance_to(1000000000000ULL);
    for(unsigned i=0;i<6;++i)require(phase(old.channels[i])==phase(original[i]),"functional-only clock changed legacy channel");
    require(old.sample_pcm()==std::array<std::int16_t,2>{0,0},"functional-only mode emitted PCM");
    auto off=tone();off.channels[0].control=31;off.advance_to(1000);
    require(off.channels[0].wave_index==0,"disabled channel advanced waveform");
    require(off.channels[4].noise_lfsr!=1,"disabled channels must still advance noise");
    auto reset=pce::Psg{};
    require(!reset.synthesis_enabled && reset.clock_ticks==0 && reset.master_remainder==0 &&
        reset.channels[4].noise_lfsr==1 && reset.channels[4].noise_remaining==0 &&
        reset.channels[0].wave_remaining==0,"default/reset digital phase");
}
static void noise_vectors() {
    // Literal 18-bit sequence from the documented polynomial and reset seed.
    constexpr std::array<std::uint32_t,24> sequence{
        131072,196608,229376,245760,253952,258048,129024,64512,
        32256,16128,8064,4032,133088,197616,229880,246012,
        254078,127039,194591,228367,245255,253699,257921,260032};
    auto p=tone(4);p.channels[4].noise=0x9f;
    for(unsigned i=0;i<sequence.size();++i) {
        p.advance_to(i==0 ? 6:std::uint64_t(i)*192);
        require(p.channels[4].noise_lfsr==sequence[i],"18-bit noise literal sequence");
        require(p.sample_pcm()[0]==((sequence[i]&1)?5285:-5285),"noise sample polarity");
    }
    auto slow=tone(5);slow.channels[5].noise=0x9e;slow.advance_to(6);
    require(slow.channels[5].noise_remaining==63,"noise code30 period64");
    slow.advance_to(384);require(slow.channels[5].noise_lfsr==196608,"noise code30 boundary");
    const auto state=slow.channels[5].noise_lfsr;slow.write(0,5);slow.write(7,0);
    slow.write(4,0);slow.write(4,0x9f);
    require(slow.channels[5].noise_lfsr==state,"noise enable and channel control must not reseed LFSR");
    auto dda=tone(4);dda.channels[4].control=0xdf;dda.channels[4].dda=0;dda.channels[4].noise=0x9f;
    require(dda.sample_pcm()[0]==5285,"noise precedence over DDA");
}
static void lfo_vectors() {
    auto p=tone();p.channels[0].frequency=20;p.channels[0].wave_remaining=1;
    p.channels[1].control=0x9f;p.channels[1].frequency=2;p.channels[1].waveform.fill(16);
    p.channels[1].waveform[1]=17;p.channels[1].waveform[2]=15;
    p.channels[1].wave_remaining=1;p.lfo_frequency=3;p.lfo_control=1;
    p.advance_to(6);
    require(p.channels[0].wave_index==1 && p.channels[0].wave_remaining==21 &&
            p.channels[1].wave_index==1 && p.channels[1].wave_remaining==6,"LFO coincident source-first reload");
    p.advance_to(42);
    require(p.channels[1].wave_index==2 && p.channels[1].wave_remaining==6 &&
            p.channels[0].wave_remaining==15,"LFO source divided period");
    for(unsigned depth=1;depth<=3;++depth) {
        auto d=tone();d.channels[0].frequency=20;d.channels[0].wave_remaining=1;
        d.channels[1].control=0xdf;d.channels[1].waveform[0]=17;d.lfo_control=depth;
        d.advance_to(6);
        const std::array<unsigned,3> expected{21,24,36};
        require(d.channels[0].wave_remaining==expected[depth-1],"LFO depths one/four/sixteen");
    }
    auto zero=tone();zero.channels[1].control=0x9f;zero.channels[1].frequency=2;
    zero.channels[1].waveform.fill(16);zero.lfo_control=1;
    zero.advance_to(6);require(zero.channels[1].wave_remaining==511,"LFO zero divider means256");
    zero.write(9,0x81);require(zero.channels[1].wave_index==0 && zero.channels[1].wave_remaining==512,"LFO trigger reload");
    zero.advance_to(100000);require(zero.channels[1].wave_index==0,"LFO trigger holds source phase");
    auto wrap=tone();wrap.channels[0].frequency=1;wrap.channels[0].wave_remaining=1;
    wrap.channels[1].control=0xdf;wrap.channels[1].waveform[0]=0;wrap.lfo_control=3;
    wrap.advance_to(6);require(wrap.channels[0].wave_remaining==3841,"LFO signed modulation wraps12bits");
}
static void partition_vectors() {
    for(unsigned scenario=0;scenario<6;++scenario) {
        auto whole=tone(scenario,scenario*7);whole.channels[4].noise=0x9f;
        if(scenario&1) {whole.channels[0].control=0x9f;whole.channels[1].control=0x9f;
            whole.channels[1].frequency=3;whole.lfo_control=(scenario%3)+1;
            whole.lfo_frequency=2;for(unsigned i=0;i<32;++i)whole.channels[1].waveform[i]=(i*7)&31;}
        auto split=whole;whole.advance_to(100003);
        for(std::uint64_t tick=1;tick<100003;tick+=113) split.advance_to(tick);
        split.advance_to(100003);
        require(whole.clock_ticks==split.clock_ticks && whole.master_remainder==split.master_remainder &&
                whole.sample_pcm()==split.sample_pcm(),"clock partition changed PCM");
        for(unsigned i=0;i<6;++i) require(phase(whole.channels[i])==phase(split.channels[i]),"clock partition changed oscillator state");
    }
    auto whole=tone();auto split=whole;
    whole.advance_to(std::numeric_limits<std::uint64_t>::max());
    split.advance_to(std::numeric_limits<std::uint64_t>::max()/2);
    split.advance_to(std::numeric_limits<std::uint64_t>::max());
    for(unsigned i=0;i<6;++i)require(phase(whole.channels[i])==phase(split.channels[i]),"huge bounded jump partition");
    require(whole.master_remainder==split.master_remainder,"huge clock remainder overflow");
}
int main() {try {
    clock_vectors();pcm_vectors();mode_and_legacy_vectors();noise_vectors();lfo_vectors();partition_vectors();
    std::cout<<checks<<" authored PSG PCM/clock/phase/noise/LFO/partition checks passed; digital profile only\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
