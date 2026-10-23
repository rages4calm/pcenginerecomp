// Authored digital PSG vectors. These are not retail recordings or copied
// emulator fixtures; no analog filter/resampler/hardware-output qualification.
#include "pce/audio.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <tuple>
#include <utility>

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
    require(p.sample_pcm()==std::array<std::int16_t,2>{0,0},"initial ultrasonic ramp mean");
    p.advance_to(0);require(p.channels[0].wave_index==0,"zero advance acquired initial edge");
    p.advance_to(5);require(p.channels[0].wave_index==0 && p.master_remainder==5,"PSG master divider");
    p.advance_to(6);require(p.channels[0].wave_index==1 && p.channels[0].wave_remaining==3,"Gear initial zero-counter phase");
    require(p.sample_pcm()==std::array<std::int16_t,2>{0,0},"ultrasonic mean at phase one");
    p.advance_to(23);require(p.channels[0].wave_index==1,"wave edge occurred early");
    p.advance_to(24);require(p.channels[0].wave_index==2 && p.channels[0].wave_remaining==4,"wave edge exact expiry");
    require(p.sample_pcm()==std::array<std::int16_t,2>{0,0},"ultrasonic mean at phase two");
    auto zero=tone(0,0);zero.advance_to(6);require(zero.channels[0].wave_index==1,"zero frequency initial edge");
    zero.advance_to(24575);require(zero.channels[0].wave_index==1,"zero period must be 4096 PSG clocks");
    zero.advance_to(24576);require(zero.channels[0].wave_index==2,"zero period exact boundary");
    auto fastest=tone(0,1);fastest.advance_to(6);require(fastest.channels[0].wave_index==2,"period-one initial phase");
    fastest.advance_to(186);require(fastest.channels[0].wave_index==0,"32-entry waveform wrap");
    const auto before=phase(fastest.channels[0]);bool refused=false;
    try{fastest.advance_to(185);}catch(const std::invalid_argument&){refused=true;}
    require(refused && fastest.clock_ticks==186 && phase(fastest.channels[0])==before,"backwards PSG clock mutation");
}
static void ultrasonic_vectors() {
    // Authored impulse: sum=31, centered numerator=-930. At full gain the
    // per-channel rounded mean is -9910, then the mixer halves to -4955.
    for(unsigned frequency=1;frequency<=5;++frequency) {
        auto p=tone(0,frequency);auto& c=p.channels[0];
        c.waveform.fill(0);c.waveform[0]=31;
        for(unsigned index=0;index<32;++index) {
            c.wave_index=index;const auto before=phase(c);
            require(p.sample_pcm()==std::array<std::int16_t,2>{-4955,-4955},"ultrasonic full-cycle mean at every phase/period");
            require(phase(c)==before,"ultrasonic observation changed oscillator state");
            p.centered_dac=false;
            require(p.sample_pcm()==std::array<std::int16_t,2>{330,330},"unipolar ultrasonic full-cycle mean");
            p.centered_dac=true;
        }
    }
    for(unsigned frequency:{0u,6u}) {
        auto p=tone(0,frequency);auto& c=p.channels[0];
        c.waveform.fill(0);c.waveform[0]=31;
        for(unsigned index=0;index<32;++index) {
            c.wave_index=index;
            require(p.sample_pcm()[0]==(index==0 ? 5285:-5285),"period zero/6 must retain instantaneous waveform output");
        }
    }
    auto p=tone();auto& c=p.channels[0];c.waveform.fill(0);c.waveform[0]=31;
    c.balance=0xf0;require(p.sample_pcm()==std::array<std::int16_t,2>{-4955,0},"ultrasonic right pan mute");
    c.balance=0x0f;require(p.sample_pcm()==std::array<std::int16_t,2>{0,-4955},"ultrasonic left pan mute");
    c.balance=0xff;p.main_volume=0xf0;
    require(p.sample_pcm()==std::array<std::int16_t,2>{-4955,0},"ultrasonic master side gain");
    p.main_volume=0xff;c.control=0x9e;
    require(p.sample_pcm()[0]==-4170,"ultrasonic attenuated mean rounds before mix");
    c.control=0x80;require(p.sample_pcm()[0]==0,"ultrasonic zero amplitude");
    c.control=0x1f;require(p.sample_pcm()[0]==0,"ultrasonic disabled channel");
    c.control=0x9f;c.wave_index=0;
    p.write(0,0);p.write(6,0);
    require(p.sample_pcm()[0]==-5285 && c.wave_index==0,"playing waveform write immediately changes mean without phase advance");
    p.write(4,0);p.write(6,31);
    require(c.wave_index==1,"disabled waveform write advances phase");
    p.write(4,0x9f);require(p.sample_pcm()[0]==-4955,"disabled waveform write appears in mean after reenable");
    c.control=0xdf;c.dda=31;
    require(p.sample_pcm()[0]==5285,"ultrasonic DDA bypasses waveform mean");
    for(unsigned index:{4u,5u}) {
        auto n=tone(index,1);n.channels[index].noise=0x9f;
        n.channels[index].noise_lfsr=1;
        require(n.sample_pcm()[0]==5285,"ultrasonic noise bypasses waveform mean");
        n.channels[index].noise_lfsr=2;
        require(n.sample_pcm()[0]==-5285,"ultrasonic noise negative polarity");
    }
    // Two equal channels expose rounding before summation/halving, including
    // signed half-way cases that would disappear in a lone-channel half-scale.
    for(const auto [sum,expected]:std::array<std::pair<unsigned,int>,4>{{{488,-171},{503,149},{504,171},{505,192}}}) {
        auto r=tone();r.channels[1]=r.channels[0];
        for(unsigned ch=0;ch<2;++ch) {
            r.channels[ch].waveform.fill(0);unsigned remaining=sum;
            for(auto& sample:r.channels[ch].waveform) {sample=std::min(remaining,31u);remaining-=sample;}
        }
        require(r.sample_pcm()[0]==expected,"centered mean signed nearest/ties-away channel rounding");
    }
    auto r=tone();r.centered_dac=false;r.channels[1]=r.channels[0];
    for(unsigned ch=0;ch<2;++ch) {r.channels[ch].waveform.fill(0);r.channels[ch].waveform[0]=8;}
    require(r.sample_pcm()[0]==171,"unipolar mean half-way rounding");
}
static void ultrasonic_lfo_exclusions() {
    for(unsigned depth=1;depth<=3;++depth) {
        auto p=tone();p.channels[0].waveform.fill(0);p.channels[0].waveform[0]=31;
        p.channels[1]=p.channels[0];p.channels[1].balance=0;
        p.lfo_control=depth;
        require(p.sample_pcm()[0]==5285,"active LFO destination bypasses ultrasonic mean");
        p.channels[0].balance=0;p.channels[1].balance=0xff;
        require(p.sample_pcm()[0]==5285,"active LFO source bypasses ultrasonic mean");
        p.channels[0].control=0;
        require(p.sample_pcm()[0]==-4955,"unconfigured LFO channel1 retains ordinary waveform mean");
        p.channels[1].control=0;p.channels[0].control=0x9f;p.channels[0].balance=0xff;
        require(p.sample_pcm()[0]==-4955,"unconfigured LFO destination retains ordinary waveform mean");
    }
    auto held=tone(1);held.channels[1].waveform.fill(0);held.channels[1].waveform[0]=31;
    held.lfo_control=0x80;
    require(held.sample_pcm()[0]==5285,"channel1 trigger hold bypasses mean without modulation");
    held.lfo_control=0;
    require(held.sample_pcm()[0]==-4955,"clearing trigger hold restores mean");
    auto third=tone(2);third.channels[2].waveform.fill(0);third.channels[2].waveform[0]=31;
    third.channels[0].control=third.channels[1].control=0x9f;third.lfo_control=1;
    require(third.sample_pcm()[0]==-4955,"configured LFO does not exclude unrelated channels");
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
static void held_dac_vectors() {
    // Literal full-gain centered DAC values: (2*data-31)*341 per channel,
    // followed by the observation's half-scale truncation toward zero.
    auto p=tone(0,32);p.channels[0].control=0xdf;p.channels[0].dda=31;
    require(p.held_sum()==std::array<std::int32_t,2>{0,0},"timed DAC must initialize silent");
    require(p.sample_pcm()[0]==5285,"analytical getter retains immediate reference");
    p.advance_to(486);
    require(p.held_sum()==std::array<std::int32_t,2>{10571,10571},"positive clock initializes timed DDA");
    p.write(6,0);
    require(p.held_pcm()[0]==5285 && p.sample_pcm()[0]==-5285,"DDA data write holds previous timed output");
    p.advance_to(488);
    require(p.held_pcm()[0]==5285,"sample edge without positive PSG clock must retain DDA");
    p.advance_to(492);
    require(p.held_pcm()[0]==-5285,"next positive PSG clock exposes DDA write");
    for(unsigned offset=1;offset<6;++offset) {
        auto q=tone();q.channels[0].control=0xdf;q.channels[0].dda=31;
        q.advance_to(6);q.write(1,0);q.advance_to(6+offset);
        require(q.held_pcm()[0]==5285 && q.sample_pcm()[0]==0,"master gain write must wait for PSG clock");
        q.advance_to(12);require(q.held_pcm()[0]==0,"master gain applies on positive PSG clock");
    }
    auto gain=tone();gain.channels[0].control=0xdf;gain.channels[0].dda=31;
    gain.advance_to(6);gain.write(5,0xf0);
    require(gain.held_pcm()==std::array<std::int16_t,2>{5285,5285},"balance write leaves both timed sides held");
    gain.advance_to(12);
    require(gain.held_pcm()==std::array<std::int16_t,2>{5285,0},"balance becomes visible on clock");
    gain.write(4,0x5f);
    require(gain.held_pcm()[0]==5285 && gain.sample_pcm()[0]==0,"channel disable does not immediately clear timed DAC");
    gain.advance_to(18);require(gain.held_pcm()[0]==0,"disabled channel clears timed DAC on clock");
    gain.write(4,0xdf);require(gain.held_pcm()[0]==0,"channel enable also waits for clock");
    gain.advance_to(24);require(gain.held_pcm()[0]==5285,"reenabled DDA applies on clock");

    auto wave=tone(0,3);wave.channels[0].waveform.fill(0);
    wave.advance_to(6);wave.write(6,31);
    require(wave.held_pcm()[0]==5285 && wave.sample_pcm()[0]==-4955,
            "playing waveform write immediately uses point DAC, not ultrasonic mean");
    wave.advance_to(11);require(wave.held_pcm()[0]==5285,"point waveform write persists through subclock gap");
    wave.advance_to(12);require(wave.held_pcm()[0]==-4955,"positive clock restores ultrasonic mean");
    wave.channels[0].waveform[0]=31;wave.write(4,0xdf);wave.write(6,0);
    wave.advance_to(18);require(wave.held_pcm()[0]==-5285,"DDA clock before falling transition");
    wave.write(4,0x9f);
    require(wave.held_pcm()[0]==5285,"DDA falling immediately outputs waveform zero");
    wave.write(4,0xdf);wave.advance_to(24);wave.write(4,0x1f);
    require(wave.held_pcm()[0]==-5285,"DDA falling into disabled mode retains previous DAC");
    wave.advance_to(30);require(wave.held_pcm()[0]==0,"disabled falling output clears on next clock");

    auto noise=tone(4,3);noise.selected=4;noise.channels[4].noise=0x9f;
    noise.advance_to(6);const auto held_noise=noise.held_sum();noise.write(6,31);
    require(noise.held_sum()==held_noise,"noise suppresses immediate waveform output update");
    noise.write(4,0xdf);noise.write(4,0x9f);
    require(noise.held_sum()==held_noise,"noise suppresses immediate DDA-falling waveform output");
    auto multi=tone();multi.channels[0].control=0xdf;multi.channels[0].dda=31;
    multi.channels[1]=multi.channels[0];multi.channels[1].dda=0;
    multi.channels[1].waveform.fill(0);multi.channels[1].waveform[0]=31;multi.advance_to(6);
    require(multi.held_sum()[0]==0,"opposite DDA channels cancel without half-scale loss");
    multi.write(4,0x5f);multi.write(0,1);multi.write(4,0x9f);
    require(multi.held_sum()[0]==21142,
            "single immediate waveform update must preserve another disabled channel's held DAC");
    multi.advance_to(12);require(multi.held_sum()[0]==-9910,"positive clock refreshes all channel DACs together");
    auto reset=pce::Psg{};reset.enabled=true;reset.synthesis_enabled=true;
    require(reset.held_pcm()==std::array<std::int16_t,2>{0,0},"reset restores held silence");
    p.enabled=false;require(p.held_sum()==std::array<std::int32_t,2>{0,0},"disabled PSG masks timed output");
    p.enabled=true;p.synthesis_enabled=false;
    require(p.held_pcm()==std::array<std::int16_t,2>{0,0},"synthesis-disabled PSG masks timed output");
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
        require(whole.held_sum()==split.held_sum(),"clock partition changed held DAC output");
        for(unsigned i=0;i<6;++i) require(phase(whole.channels[i])==phase(split.channels[i]),"clock partition changed oscillator state");
    }
    auto whole=tone();auto split=whole;
    whole.advance_to(std::numeric_limits<std::uint64_t>::max());
    split.advance_to(std::numeric_limits<std::uint64_t>::max()/2);
    split.advance_to(std::numeric_limits<std::uint64_t>::max());
    for(unsigned i=0;i<6;++i)require(phase(whole.channels[i])==phase(split.channels[i]),"huge bounded jump partition");
    require(whole.master_remainder==split.master_remainder,"huge clock remainder overflow");
    require(whole.held_sum()==split.held_sum(),"huge bounded jump changed held output");
}
int main() {try {
    clock_vectors();pcm_vectors();ultrasonic_vectors();ultrasonic_lfo_exclusions();
    mode_and_legacy_vectors();held_dac_vectors();noise_vectors();lfo_vectors();partition_vectors();
    std::cout<<checks<<" authored PSG PCM/clock/phase/noise/LFO/partition checks passed; digital profile only\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
