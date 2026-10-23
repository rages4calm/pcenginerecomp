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

}
// Presentation-only cursor storage stays behind the existing pointer so it
// does not enlarge Bus or expose stream bookkeeping to generated modules.
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
    std::weak_ptr<SectorProvider> cd_source_;
    std::uint32_t cd_lba_=0;
    unsigned cd_frame_=0,cd_last_state_=3;
    std::uint64_t cd_commands_seen_=0,cd_sectors_seen_=0,cd_seek_seen_=0;
    bool cd_active_=false,cd_finished_=false,cd_tail_pending_=false,cd_was_enabled_=false;
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
void AudioOutput::observe_cd_audio(const Bus& bus) {
    const auto& audio=bus.cd.audio;
    // RST can leave an already naturally stopped drive's observed command,
    // state and sector counters unchanged. It still cancels the terminal
    // token immediately, including between adjacent output sample edges.
    if(bus.cd.reset&2) {
        cd_cache_->cd_active_=cd_cache_->cd_finished_=cd_cache_->cd_tail_pending_=false;
        cd_cache_->cd_frame_=0;
    }
    const bool same_source=!cd_cache_->cd_source_.owner_before(bus.cd.provider) &&
                           !bus.cd.provider.owner_before(cd_cache_->cd_source_);
    if(same_source && cd_cache_->cd_was_enabled_==bus.cd.audio_enabled &&
       cd_cache_->cd_last_state_==audio.state && cd_cache_->cd_commands_seen_==audio.commands &&
       cd_cache_->cd_sectors_seen_==audio.sectors_played && cd_cache_->cd_seek_seen_==audio.seek_deadline) return;
    const auto reset=[&] {cd_cache_->cd_active_=cd_cache_->cd_finished_=cd_cache_->cd_tail_pending_=false;cd_cache_->cd_frame_=0;};
    if(!same_source || !bus.cd.audio_enabled) reset();
    if(audio.seek_deadline || audio.state==1) reset();
    else if(audio.state==3) {
        // A rounded natural stop may precede the last 44.1 kHz source sample
        // by one output edge. Deliver only that exact terminal frame once.
        // An explicit stop/READ/reset does not acquire this completion token.
        const bool natural=cd_cache_->cd_last_state_==0 && audio.sectors_played>cd_cache_->cd_sectors_seen_ &&
                           (audio.commands==cd_cache_->cd_commands_seen_ || bus.cd.scsi.command[0]==0xdd);
        if(natural) {
            cd_cache_->cd_tail_pending_=cd_cache_->cd_active_ && cd_cache_->cd_lba_==audio.stop_lba && cd_cache_->cd_frame_==587;
            if(!cd_cache_->cd_tail_pending_) reset();
        } else if(cd_cache_->cd_last_state_!=3 ||
                  (audio.commands!=cd_cache_->cd_commands_seen_ && bus.cd.scsi.command[0]!=0xdd)) reset();
    } else if(audio.state==2) {
        // Pause and its resume delay hold the PCM cursor, rather than replaying
        // the beginning of the guest drive's current sector after resumption.
        cd_cache_->cd_tail_pending_=false;
    } else if(audio.state==0 && cd_cache_->cd_finished_ && audio.commands!=cd_cache_->cd_commands_seen_ &&
              bus.cd.scsi.command[0]==0xd9 && bus.cd.scsi.command[1]) reset();
    cd_cache_->cd_source_=bus.cd.provider;cd_cache_->cd_was_enabled_=bus.cd.audio_enabled;
    cd_cache_->cd_last_state_=audio.state;cd_cache_->cd_commands_seen_=audio.commands;
    cd_cache_->cd_sectors_seen_=audio.sectors_played;cd_cache_->cd_seek_seen_=audio.seek_deadline;
}
std::array<std::int16_t,2> AudioOutput::cdda_sample(Bus& bus) {
    observe_cd_audio(bus);
    const auto& audio=bus.cd.audio;
    if(!bus.cd.audio_enabled || (bus.cd.reset&2) || audio.seek_deadline || audio.playback_deadline ||
       (audio.state!=0 && !cd_cache_->cd_tail_pending_)) return {};
    if(audio.state==0 && !audio.sector_deadline) return {};
    if(cd_cache_->cd_finished_) return {};
    if(!bus.cd.provider) throw Fault("CD audio playback requires a sector provider");
    if(!cd_cache_->cd_active_) {cd_cache_->cd_lba_=audio.current_lba;cd_cache_->cd_frame_=0;cd_cache_->cd_active_=true;}
    if(cd_cache_->cd_lba_>audio.stop_lba) {cd_cache_->cd_finished_=true;cd_cache_->cd_active_=false;return {};}
    const auto sample=cd_cache_->cache.sample(bus.cd.provider,cd_cache_->cd_lba_,cd_cache_->cd_frame_);
    if(++cd_cache_->cd_frame_==588) {
        cd_cache_->cd_frame_=0;
        if(cd_cache_->cd_lba_==audio.stop_lba) {
            if(audio.stop_mode==1) cd_cache_->cd_lba_=audio.start_lba;
            else {cd_cache_->cd_active_=false;cd_cache_->cd_finished_=true;}
        } else ++cd_cache_->cd_lba_;
    }
    cd_cache_->cd_tail_pending_=false;
    return sample;
}
void AudioOutput::advance_to(Bus& bus,std::uint64_t ticks) {
    if(!enabled)return;
    if(ticks<master_ticks)throw Fault("CPU/audio output clock regression");
    unsigned budget=0;
    while(next_tick_<=ticks) {
        if(++budget>441000)throw Fault("audio output advance exceeds ten-second work bound");
        devices(bus,next_tick_,true);
        const auto psg=timing()==AudioTiming::gear ? bus.psg.held_pcm():bus.psg.sample_pcm();
        const auto adpcm=bus.adpcm.enabled && bus.adpcm.playing && !(bus.adpcm.control&128) ? bus.adpcm.sample_pcm():0;
        const auto cd=cdda_sample(bus);
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
    devices(bus,ticks);observe_cd_audio(bus);master_ticks=ticks;
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
    if(!psg.enabled)enable_psg();
    if(psg.clock_ticks || adpcm.master_ticks || cd.scsi.master_ticks)throw Fault("enable audio output before guest clocks advance");
    pcm.enable(profile,output_rate,timing);psg.synthesis_enabled=true;
}
} // namespace pce
