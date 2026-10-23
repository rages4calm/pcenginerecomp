#include "pce/audio.hpp"
#include <algorithm>
#include <stdexcept>

namespace pce {
namespace {
std::array<std::int16_t,2> point_output(const Psg&,unsigned,unsigned);
std::array<std::int16_t,2> analytical_output(const Psg&,unsigned);
void update_wave_write(Psg& p,unsigned index,unsigned data) {
    auto& channel=p.channels[index];
    if(channel.playing() && !(index>=4 && (channel.noise&128)))
        channel.held_output=point_output(p,index,data);
}
}
void Psg::write(unsigned port, std::uint8_t value) {
    ++writes;
    const unsigned reg=port&15;
    if(reg==0) { selected=value&7;return; }
    if(reg==1) { main_volume=value;return; }
    if(reg==8) { lfo_frequency=value;return; }
    if(reg==9) {
        if(value&128) {
            if(synthesis_enabled) {
                const auto frequency=channels[1].frequency ? channels[1].frequency:4096u;
                channels[1].wave_remaining=frequency*((lfo_control&3) ? (lfo_frequency ? lfo_frequency:256u):1u);
            }
            channels[1].wave_index=0;
            channels[1].dda=channels[1].waveform[0];
        }
        lfo_control=value;return;
    }
    if(selected>=channels.size()) return;
    auto& channel=channels[selected];
    switch(reg) {
    case 2: channel.frequency=static_cast<std::uint16_t>((channel.frequency&0xF00)|value);break;
    case 3: channel.frequency=static_cast<std::uint16_t>((channel.frequency&255)|((value&15)<<8));break;
    case 4: {
        // Gear-reference write semantics: DDA holds the waveform address
        // reset, including the transition back to waveform mode.
        if(channel.dda_mode() || (value&64)) channel.wave_index=0;
        const bool falling=channel.dda_mode() && !(value&64);
        if(synthesis_enabled && falling)
            channel.wave_remaining=channel.frequency ? channel.frequency:4096;
        channel.control=value;
        if(falling)update_wave_write(*this,selected,channel.waveform[0]);
        break;
    }
    case 5: channel.balance=value;break;
    case 6:
        channel.wave=value&31;
        if(channel.dda_mode()) channel.dda=channel.wave;
        else {
            channel.waveform[channel.wave_index]=channel.wave;
            if(!channel.playing()) channel.wave_index=(channel.wave_index+1)&31;
            update_wave_write(*this,selected,channel.wave);
        }
        break;
    case 7: if(selected>=4) channel.noise=value;break;
    default: break; // Unused PSG register numbers have no register storage.
    }
}
namespace {
// Mathematical shift-register recurrence from hardware noise research; this
// implementation composes linear maps to bound even very large clock jumps.
std::uint32_t noise_next(std::uint32_t value) {
    const auto feedback=(value^(value>>1)^(value>>11)^(value>>12)^(value>>17))&1;
    return (value>>1)|(feedback<<17);
}
std::uint32_t noise_jump(std::uint32_t value, std::uint64_t steps) {
    if(steps<32) {
        while(steps--) value=noise_next(value);
        return value;
    }
    using Map=std::array<std::uint32_t,18>;
    const auto apply=[](const Map& map, std::uint32_t input) {
        std::uint32_t output=0;
        for(unsigned bit=0;bit<18;++bit) if(input&(1u<<bit)) output^=map[bit];
        return output;
    };
    static const auto powers=[&] {
        std::array<Map,64> result{};
        for(unsigned bit=0;bit<18;++bit) result[0][bit]=noise_next(1u<<bit);
        for(unsigned power=1;power<64;++power)
            for(unsigned bit=0;bit<18;++bit)
                result[power][bit]=apply(result[power-1],result[power-1][bit]);
        return result;
    }();
    for(unsigned bit=0;steps;++bit,steps>>=1) if(steps&1) value=apply(powers[bit],value);
    return value;
}
// The initial zero counter has an initial edge on the first positive advance.
// Subsequent edges are inclusive at exact expiry, independently of call sizes.
std::uint64_t elapsed_edges(std::uint64_t clocks, std::uint32_t& remaining, std::uint32_t period) {
    if(!clocks || clocks<remaining) {
        remaining-=static_cast<std::uint32_t>(clocks);
        return 0;
    }
    const auto after=clocks-remaining;
    remaining=period-static_cast<std::uint32_t>(after%period);
    return 1+after/period;
}
unsigned plain_period(const Psg::Channel& channel) { return channel.frequency ? channel.frequency:4096; }
unsigned balance_level(unsigned value) {
    // Hardware 4-bit-to-5-bit amplitude scale, including its central step.
    return value==0 ? 0:value==8 ? 16:value*2+1;
}
unsigned channel_gain(const Psg& p,unsigned index,unsigned side) {
    // floor((65535/(6*32))*10^(-1.5*dB_step/20)), fixed for reproducible PCM.
    static constexpr std::array<unsigned,32> gain{
        341,287,241,203,171,143,121,101,85,72,60,51,42,36,30,25,
        21,18,15,12,10,9,7,6,5,4,3,3,2,2,1,0};
    const auto& channel=p.channels[index];
    const auto shift=side==0 ? 4:0;
    const unsigned loss=(31-balance_level((p.main_volume>>shift)&15))+
        (31-balance_level((channel.balance>>shift)&15))+(31-(channel.control&31));
    return gain[std::min(loss,31u)];
}
std::array<std::int16_t,2> point_output(const Psg& p,unsigned index,unsigned data) {
    const int level=int(data)*2-(p.centered_dac ? 31:0);
    return {static_cast<std::int16_t>(level*int(channel_gain(p,index,0))),
            static_cast<std::int16_t>(level*int(channel_gain(p,index,1)))};
}
std::array<std::int16_t,2> analytical_output(const Psg& p,unsigned index) {
    const auto& channel=p.channels[index];
    if(!channel.playing())return {};
    const bool noise=index>=4 && (channel.noise&128);
    const bool lfo=(p.lfo_control&3) && p.channels[0].playing() && p.channels[1].playing();
    const bool averaged=!noise && !channel.dda_mode() && plain_period(channel)<=5 &&
        !(lfo && index<2) && !(index==1 && (p.lfo_control&128));
    if(!averaged) {
        const unsigned data=noise ? ((channel.noise_lfsr&1) ? 31:0):
            channel.dda_mode() ? channel.dda:channel.waveform[channel.wave_index];
        return point_output(p,index,data);
    }
    int numerator=0;
    for(const auto sample:channel.waveform)numerator+=int(sample)*2;
    if(p.centered_dac)numerator-=31*32;
    std::array<std::int16_t,2> result{};
    for(unsigned side=0;side<2;++side) {
        const int scaled=numerator*int(channel_gain(p,index,side));
        result[side]=static_cast<std::int16_t>((scaled+(scaled<0 ? -16:16))/32);
    }
    return result;
}
}

void Psg::advance_to(std::uint64_t ticks) {
    if(ticks<clock_ticks) throw std::invalid_argument("PSG clock cannot move backwards");
    const auto delta=ticks-clock_ticks;
    clock_ticks=ticks;
    if(!synthesis_enabled) { master_remainder=0; return; }
    auto clocks=delta/6;
    const auto tail=static_cast<unsigned>(delta%6)+master_remainder;
    clocks+=tail/6; master_remainder=tail%6;
    if(!clocks) return;
    for(unsigned index=4;index<6;++index) {
        auto& channel=channels[index];
        const auto steps=elapsed_edges(clocks,channel.noise_remaining,channel.noise_period());
        channel.noise_lfsr=noise_jump(channel.noise_lfsr,steps);
    }
    const bool configured=(lfo_control&3) && channels[0].playing() && channels[1].playing();
    const bool source_running=configured && !(lfo_control&128) && !channels[1].dda_mode();
    const bool dest_running=configured && !channels[0].dda_mode();
    const auto lfo_period=[&] { return plain_period(channels[1])*(lfo_frequency ? lfo_frequency:256u); };
    const auto dest_period=[&] {
        const int depth=1<<(((lfo_control&3)-1)*2);
        const int modulation=(int(channels[1].waveform[channels[1].wave_index])-16)*depth;
        const unsigned period=(plain_period(channels[0])+modulation)&4095;
        return period ? period:4096u;
    };
    if(configured) {
        // Visit only oscillator edges. Source edges precede simultaneous
        // destination reloads so the new sample controls the next period.
        auto left=clocks;
        while(left && (source_running || dest_running)) {
            const auto source=source_running ? channels[1].wave_remaining:UINT32_MAX;
            const auto dest=dest_running ? channels[0].wave_remaining:UINT32_MAX;
            const auto step=std::min<std::uint64_t>(left,std::min(source,dest));
            if(source_running) channels[1].wave_remaining-=static_cast<std::uint32_t>(step);
            if(dest_running) channels[0].wave_remaining-=static_cast<std::uint32_t>(step);
            left-=step;
            if(source_running && !channels[1].wave_remaining) {
                channels[1].wave_index=(channels[1].wave_index+1)&31;
                channels[1].wave_remaining=lfo_period();
            }
            if(dest_running && !channels[0].wave_remaining) {
                channels[0].wave_index=(channels[0].wave_index+1)&31;
                channels[0].wave_remaining=dest_period();
            }
        }
    }
    for(unsigned index=0;index<6;++index) {
        auto& channel=channels[index];
        if(!channel.playing() || channel.dda_mode() || (configured && index<2) ||
           (index==1 && (lfo_control&128))) continue;
        const auto steps=elapsed_edges(clocks,channel.wave_remaining,plain_period(channel));
        channel.wave_index=(channel.wave_index+(steps&31))&31;
    }
    for(unsigned index=0;index<6;++index)
        channels[index].held_output=analytical_output(*this,index);
}

std::array<std::int32_t,2> Psg::sample_sum() const {
    if(!synthesis_enabled || !enabled) return {};
    std::array<int,2> mixed{};
    for(unsigned index=0;index<6;++index) {
        const auto sample=analytical_output(*this,index);
        for(unsigned side=0;side<2;++side)mixed[side]+=sample[side];
    }
    return {mixed[0],mixed[1]};
}
std::array<std::int16_t,2> Psg::sample_pcm() const {
    const auto mixed=sample_sum();
    return {static_cast<std::int16_t>(std::clamp(mixed[0]/2,-32768,32767)),
            static_cast<std::int16_t>(std::clamp(mixed[1]/2,-32768,32767))};
}
std::array<std::int32_t,2> Psg::held_sum() const {
    if(!synthesis_enabled || !enabled)return {};
    std::array<std::int32_t,2> sum{};
    for(const auto& channel:channels)
        for(unsigned side=0;side<2;++side)sum[side]+=channel.held_output[side];
    return sum;
}
std::array<std::int16_t,2> Psg::held_pcm() const {
    const auto sum=held_sum();
    return {static_cast<std::int16_t>(std::clamp(sum[0]/2,-32768,32767)),
            static_cast<std::int16_t>(std::clamp(sum[1]/2,-32768,32767))};
}
} // namespace pce
