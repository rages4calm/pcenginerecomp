#include "pce/runtime.hpp"
#include "pce/cdda_pcm.hpp"
#include "pce/audio_dsp.hpp"
#include <algorithm>
#include <limits>

namespace pce {
namespace {
constexpr std::uint64_t master_clock=21477273;
void validate_profile(AudioProfile profile,unsigned rate) {
    if((profile!=AudioProfile::raw && profile!=AudioProfile::filtered) ||
       (rate!=44100 && rate!=48000) || (profile==AudioProfile::raw && rate!=44100))
        throw Fault("unsupported audio profile or output rate");
}
void devices(Bus& bus,std::uint64_t ticks,bool psg=false) {
    if(bus.adpcm.enabled)bus.adpcm.advance_to(ticks,&bus.cd);
    else bus.cd.advance_to(ticks);
    if(psg)bus.psg.advance_to(ticks);
}
void silent_source_to(CdAudio& audio,std::uint64_t ticks) {
    // Advance the global rational phase without polling disabled hardware.
    // Division before multiplication also keeps the full uint64 tick range
    // representable; the remainder products are bounded by the clock rate.
    const auto count=(ticks/master_clock)*44100+(ticks%master_clock)*44100/master_clock;
    const auto edge=[](std::uint64_t frame) {
        const auto whole=(frame/44100)*master_clock;
        const auto part=((frame%44100)*master_clock+44099)/44100;
        // A disabled source need not schedule an event outside the guest
        // timestamp domain. Its final representable edge/count remain exact.
        if(whole>std::numeric_limits<std::uint64_t>::max()-part)return std::uint64_t{0};
        return whole+part;
    };
    if(count!=audio.sample_frames) {audio.sample_raw={};audio.sample_held={};audio.sample_valid=true;}
    audio.sample_frames=count;audio.sample_ticks=edge(count);
    audio.sample_next_tick=edge(count+1);
    audio.sample_remainder=static_cast<unsigned>(((count+1)%44100*(master_clock%44100)+44099)%44100);
    audio.sample_clock_ticks=ticks;
}

}
// Media caching and legacy presentation compatibility stay opaque. The
// canonical guest cursor and readable DAC are value state in CdAudio.
class CddaStreamState {
public:
    explicit CddaStreamState(AudioProfile profile,unsigned rate,AudioTiming timing):profile(profile),timing(timing),resampler(rate) {}
    AudioProfile profile;
    AudioTiming timing;
    AudioProcessingStats processing;
    PsgPresentationFilter psg_filter;
    AdpcmPresentationFilter adpcm_filter;
    StereoResampler resampler;
    CddaPcmCache cache;
    CdAudio::Cursor legacy_cursor;
};
AudioOutput::AudioOutput()=default;
AudioOutput::~AudioOutput()=default;
AudioOutput::AudioOutput(AudioOutput&&) noexcept=default;
AudioOutput& AudioOutput::operator=(AudioOutput&&) noexcept=default;
void AudioOutput::enable(AudioProfile profile,unsigned output_rate,AudioTiming timing) {
    if(enabled || master_ticks || frames)throw Fault("audio output must be enabled before guest execution");
    validate_profile(profile,output_rate);
    if(timing!=AudioTiming::gear && timing!=AudioTiming::legacy)throw Fault("unsupported audio timing");
    cd_cache_=std::make_unique<CddaStreamState>(profile,output_rate,timing);enabled=true;
    // ceil(n*M/R) is floor((n*M+R-1)/R). The phase must retain
    // that R-1 offset, including exact rational-period boundaries.
    if(timing==AudioTiming::gear) {next_tick_=488;remainder_=572;}
    cd_cache_->processing.latency_source_frames=cd_cache_->resampler.latency();
}
AudioProfile AudioOutput::profile() const {return cd_cache_ ? cd_cache_->profile:AudioProfile::raw;}
AudioTiming AudioOutput::timing() const {return cd_cache_ ? cd_cache_->timing:AudioTiming::gear;}
unsigned AudioOutput::output_rate() const {return cd_cache_ ? cd_cache_->resampler.output_rate():44100;}
AudioProcessingStats AudioOutput::processing_stats() const {return cd_cache_ ? cd_cache_->processing:AudioProcessingStats{};}
void AudioOutput::reset_adpcm_filter() {if(cd_cache_)cd_cache_->adpcm_filter.reset();}
void AudioOutput::append(std::array<std::int16_t,2> sample) {
    if(count_==capacity){begin_=(begin_+1)%capacity;--count_;++discarded_frames;}
    queue_[(begin_+count_)%capacity]=sample;++count_;
    for(auto value:sample) {
        const auto u=static_cast<std::uint16_t>(value);
        for(unsigned shift:{0u,8u}){pcm_hash^=(u>>shift)&255;pcm_hash*=1099511628211ULL;}
        peak=std::max(peak,static_cast<unsigned>(value<0 ? -int(value):int(value)));
    }
    if(sample[0] || sample[1])++mixed_nonzero;
    ++frames;
}
void CdAudio::Cursor::observe(const CdControl& cd) {
    const auto& audio=cd.audio;
    // RST can leave an already naturally stopped drive's observed command,
    // state and sector counters unchanged. It still cancels the terminal
    // token immediately, including between adjacent output sample edges.
    if(cd.reset&2) {
        active=finished=tail_pending=false;
        frame=0;
    }
    const bool same_source=!source.owner_before(cd.provider) && !cd.provider.owner_before(source);
    if(same_source && was_enabled==cd.audio_enabled &&
       last_state==audio.state && commands_seen==audio.commands &&
       sectors_seen==audio.sectors_played && seek_seen==audio.seek_deadline) return;
    const auto reset=[&] {active=finished=tail_pending=false;frame=0;};
    if(!same_source || !cd.audio_enabled) reset();
    if(audio.seek_deadline || audio.state==1) reset();
    else if(audio.state==3) {
        // A rounded natural stop may precede the last 44.1 kHz source sample
        // by one output edge. Deliver only that exact terminal frame once.
        // An explicit stop/READ/reset does not acquire this completion token.
        const bool natural=last_state==0 && audio.sectors_played>sectors_seen &&
                           (audio.commands==commands_seen || cd.scsi.command[0]==0xdd);
        if(natural) {
            tail_pending=active && lba==audio.stop_lba && frame==587;
            if(!tail_pending) reset();
        } else if(last_state!=3 || (audio.commands!=commands_seen && cd.scsi.command[0]!=0xdd)) reset();
    } else if(audio.state==2) {
        // Pause and its resume delay hold the PCM cursor, rather than replaying
        // the beginning of the guest drive's current sector after resumption.
        tail_pending=false;
    } else if(audio.state==0 && finished && audio.commands!=commands_seen &&
              cd.scsi.command[0]==0xd9 && cd.scsi.command[1]) reset();
    source=cd.provider;was_enabled=cd.audio_enabled;
    last_state=audio.state;commands_seen=audio.commands;
    sectors_seen=audio.sectors_played;seek_seen=audio.seek_deadline;
}
std::array<std::int16_t,2> CdAudio::Cursor::sample(CdControl& cd,CddaPcmCache& cache,bool& valid) {
    observe(cd);valid=true;
    const auto& audio=cd.audio;
    if(!cd.audio_enabled || (cd.reset&2) || audio.seek_deadline || audio.playback_deadline ||
       (audio.state!=0 && !tail_pending)) return {};
    if(audio.state==0 && !audio.sector_deadline) return {};
    if(finished) return {};
    if(!active) {lba=audio.current_lba;frame=0;active=true;}
    if(lba>audio.stop_lba) {finished=true;active=false;return {};}
    // A control-only transport can model seeks without media. Its source DAC
    // is explicitly unavailable until a provider is attached; observing that
    // value via the latch or enabled PCM is an error, never invented silence.
    std::array<std::int16_t,2> result{};
    if(cd.provider) result=cache.sample(cd.provider,lba,frame);
    else valid=false;
    if(++frame==588) {
        frame=0;
        if(lba==audio.stop_lba) {
            if(audio.stop_mode==1) lba=audio.start_lba;
            else {active=false;finished=true;}
        } else ++lba;
    }
    tail_pending=false;
    return result;
}
void AudioOutput::advance_to(Bus& bus,std::uint64_t ticks) {
    auto& audio=bus.cd.audio;
    if(ticks<audio.sample_clock_ticks)throw Fault("CPU/CD sample clock regression");
    if(!enabled && !bus.cd.audio_enabled) {
        devices(bus,ticks);
        if(bus.cd.enabled)silent_source_to(audio,ticks);
        return;
    }
    if(enabled && ticks<master_ticks)throw Fault("CPU/audio output clock regression");
    if(!cd_cache_)cd_cache_=std::make_unique<CddaStreamState>(AudioProfile::raw,44100,AudioTiming::gear);
    unsigned source_budget=0,output_budget=0;
    for(;;) {
        const auto source_tick=bus.cd.audio_enabled && audio.sample_next_tick ? audio.sample_next_tick:
            std::numeric_limits<std::uint64_t>::max();
        const auto output_tick=enabled ? next_tick_:std::numeric_limits<std::uint64_t>::max();
        const auto next=std::min(source_tick,output_tick);
        if(next>ticks || next==std::numeric_limits<std::uint64_t>::max())break;
        const bool source_edge=next==source_tick,output_edge=next==output_tick;
        if((source_edge && ++source_budget>441000) || (output_edge && ++output_budget>441000))
            throw Fault("audio source/output advance exceeds ten-second work bound");
        devices(bus,next,output_edge);
        if(source_edge) {
            audio.sample_raw=audio.source_cursor.sample(bus.cd,cd_cache_->cache,audio.sample_valid);
            const auto gain=bus.cd.fader_gain(false);
            for(unsigned channel=0;channel<2;++channel)
                audio.sample_held[channel]=static_cast<std::int16_t>(audio.sample_raw[channel]*gain);
            audio.sample_ticks=next;++audio.sample_frames;
            auto delta=master_clock/rate;
            audio.sample_remainder+=master_clock%rate;
            if(audio.sample_remainder>=rate){audio.sample_remainder-=rate;++delta;}
            audio.sample_next_tick=audio.sample_next_tick>std::numeric_limits<std::uint64_t>::max()-delta ?
                0:audio.sample_next_tick+delta;
        }
        if(!output_edge)continue;
        const auto psg=timing()==AudioTiming::gear ? bus.psg.held_pcm():bus.psg.sample_pcm();
        const auto adpcm=bus.adpcm.enabled && bus.adpcm.playing && !(bus.adpcm.control&128) ? bus.adpcm.sample_pcm():0;
        bool cd_valid=true;
        const auto cd=timing()==AudioTiming::legacy ? cd_cache_->legacy_cursor.sample(bus.cd,cd_cache_->cache,cd_valid):
            (bus.cd.audio_enabled ? audio.sample_raw:std::array<std::int16_t,2>{});
        if(!cd_valid || (timing()==AudioTiming::gear && bus.cd.audio_enabled && !audio.sample_valid))
            throw Fault("CD audio playback requires a sector provider");
        if(psg[0] || psg[1])++psg_nonzero;
        if(adpcm)++adpcm_nonzero;
        if(cd[0] || cd[1])++cdda_nonzero;
        const auto adpcm_gain=bus.cd.fader_gain(true),cd_gain=bus.cd.fader_gain(false);
        std::array<std::int16_t,2> mixed{};
        for(unsigned channel=0;channel<2;++channel) {
            // Fixed equal source gains supply headroom. Gain is presentation
            // policy, not a claim about the console's analog output circuit.
            const auto sum=static_cast<std::int32_t>(psg[channel])+static_cast<std::int32_t>(adpcm*adpcm_gain)
                +static_cast<std::int32_t>(cd[channel]*cd_gain);
            mixed[channel]=static_cast<std::int16_t>(std::clamp(sum/3,-32768,32767));
        }
        if(cd_cache_->profile==AudioProfile::raw)append(mixed);
        else {
            auto& state=*cd_cache_;
            auto& raw=state.processing;
            ++raw.source_frames;
            if(mixed[0] || mixed[1])++raw.raw_mixed_nonzero;
            for(const auto value:mixed) {
                const auto u=static_cast<std::uint16_t>(value);
                for(unsigned shift:{0u,8u}) {raw.raw_pcm_hash^=(u>>shift)&255;raw.raw_pcm_hash*=1099511628211ULL;}
                raw.raw_peak=std::max(raw.raw_peak,static_cast<unsigned>(value<0 ? -int(value):int(value)));
            }
            // Preserve the guest source clocks and the raw reference above.
            // Filters consume the unclipped PSG half-sum and held ADPCM DAC;
            // stopping playback retains its analog-style filter tail.
            const auto filtered_psg=state.psg_filter.process(timing()==AudioTiming::gear ? bus.psg.held_sum():bus.psg.sample_sum());
            if(bus.adpcm.control&128)state.adpcm_filter.reset();
            const auto filtered_adpcm=bus.adpcm.enabled ? state.adpcm_filter.process(
                bus.adpcm.decoder_output,static_cast<float>(adpcm_gain)):0;
            for(unsigned channel=0;channel<2;++channel) {
                const auto sum=static_cast<std::int32_t>(filtered_psg[channel])+filtered_adpcm+
                    static_cast<std::int32_t>(cd[channel]*cd_gain);
                mixed[channel]=static_cast<std::int16_t>(std::clamp(sum/3,-32768,32767));
            }
            const auto output=state.resampler.push(mixed);
            for(unsigned i=0;i<output.count;++i)append(output.samples[i]);
        }
        auto delta=master_clock/rate;
        remainder_+=master_clock%rate;
        if(remainder_>=rate){remainder_-=rate;++delta;}
        if(next_tick_>std::numeric_limits<std::uint64_t>::max()-delta)throw Fault("audio output clock overflow");
        next_tick_+=delta;
    }
    devices(bus,ticks);
    if(!bus.cd.audio_enabled)silent_source_to(audio,ticks);
    audio.source_cursor.observe(bus.cd);
    if(enabled && timing()==AudioTiming::legacy)cd_cache_->legacy_cursor.observe(bus.cd);
    audio.sample_clock_ticks=ticks;
    if(enabled)master_ticks=ticks;
}
std::vector<std::int16_t> AudioOutput::drain() {
    std::vector<std::int16_t> samples; samples.reserve(count_*2);
    while(count_) {
        const auto value=queue_[begin_];samples.push_back(value[0]);samples.push_back(value[1]);
        begin_=(begin_+1)%capacity;--count_;
    }
    return samples;
}
void Bus::enable_audio_output(AudioProfile profile,unsigned output_rate,AudioTiming timing) {
    validate_profile(profile,output_rate);
    if(timing!=AudioTiming::gear && timing!=AudioTiming::legacy)throw Fault("unsupported audio timing");
    if(psg.clock_ticks || adpcm.master_ticks || cd.scsi.master_ticks || cd.audio.sample_clock_ticks)
        throw Fault("enable audio output before guest clocks advance");
    if(!psg.enabled)enable_psg();
    pcm.enable(profile,output_rate,timing);psg.synthesis_enabled=true;
}
} // namespace pce
